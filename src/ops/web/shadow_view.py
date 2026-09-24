"""Read-only localhost dashboard for the isolated prospective shadow cohort."""
import csv
import io
import json
from pathlib import Path
import sqlite3
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from src.research.shadow.store import CANDIDATES, SCENARIOS, POLICY


def connect(path):
    path=Path(path).resolve()
    if not path.is_file(): raise HTTPException(503,'Shadow recorder has not created its database')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def snapshot(path,now=None):
    now=time.time() if now is None else now
    db=connect(path)
    try:
        db.execute('BEGIN')
        meta=dict(db.execute('SELECT key,value FROM meta').fetchall())
        result=dict(started=float(meta['started']),status=meta.get('status'),
            heartbeat_age=now-float(meta.get('heartbeat',meta['started'])),
            manifest=json.loads(meta['manifest']),candidates=[],symbols=[])
        for candidate in CANDIDATES:
            scenarios=[]
            for scenario in SCENARIOS:
                rows=db.execute('SELECT * FROM trades WHERE candidate=? AND scenario=?',(candidate,scenario)).fetchall()
                closed=[r for r in rows if r['status']=='CLOSED']
                by_symbol={}
                for row in closed: by_symbol.setdefault(row['symbol'],[]).append(row['net_r'])
                breadth=[sum(v)/len(v) for v in by_symbol.values() if len(v)>=POLICY['breadth_fills']]
                mean=sum(r['net_r'] for r in closed)/len(closed) if closed else None
                counts={state:sum(r['status']==state for r in rows) for state in ('PENDING','OPEN','CLOSED','EXPIRED','REJECTED','CENSORED')}
                enough=len(closed)>=POLICY['minimum_fills'] and len(breadth)>=POLICY['breadth_symbols']
                positive=bool(mean is not None and mean>0 and sum(v>0 for v in breadth)>len(breadth)/2)
                scenarios.append(dict(scenario=scenario,counts=counts,mean_net_r=mean,
                    total_net_r=sum(r['net_r'] for r in closed),eligible_symbols=len(breadth),
                    positive_eligible_symbols=sum(v>0 for v in breadth),sample_ready=enough,
                    review_ready=enough and positive,filled=sum(r['fill_time'] is not None for r in rows)))
            result['candidates'].append(dict(name=candidate,scenarios=scenarios,
                gate='REVIEW_READY' if all(s['review_ready'] for s in scenarios) else
                     'CRITERIA_NOT_MET' if all(s['sample_ready'] for s in scenarios) else 'COLLECTING'))
        for symbol in result['manifest']['symbols']:
            latest=json.loads(meta.get('latest:'+symbol,'null'))
            recent=db.execute('SELECT reason,observed FROM quotes WHERE symbol=? ORDER BY id DESC LIMIT 1',(symbol,)).fetchone()
            result['symbols'].append(dict(symbol=symbol,last_valid_age=now-latest['observed'] if latest else None,
                bid=latest['bid'] if latest else None,ask=latest['ask'] if latest else None,
                spread=latest['ask']-latest['bid'] if latest else None,
                last_reason=recent['reason'] if recent else 'WAITING',
                latest_bar_age=now-float(meta['last_bar_close:'+symbol]) if 'last_bar_close:'+symbol in meta else None,
                last_bar_fetch_age=now-float(meta['last_bars:'+symbol]) if 'last_bars:'+symbol in meta else None))
        result['feed_status']='HEALTHY' if all(s['last_valid_age'] is not None and s['last_valid_age']<=POLICY['max_quote_age']
            and s['last_reason']=='VALID' and s['latest_bar_age'] is not None and s['latest_bar_age']<=900
            for s in result['symbols']) else 'DEGRADED'
        result['reasons']=[dict(r) for r in db.execute('SELECT candidate,reason,count(*) AS count FROM decisions GROUP BY candidate,reason ORDER BY candidate,count DESC')]
        result['quote_quality']=[dict(r) for r in db.execute('SELECT reason,count(*) AS count FROM quotes GROUP BY reason')]
        result['recent_trades']=[dict(r) for r in db.execute('SELECT * FROM trades ORDER BY admitted DESC,id LIMIT 40')]
        result['recent_events']=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 20')]
        return result
    finally:
        db.close()


def create_app(path):
    app=FastAPI(title='SilverBullet prospective shadow',docs_url=None,redoc_url=None)

    @app.get('/',response_class=HTMLResponse)
    def index():
        return Path(__file__).with_name('shadow_dashboard.html').read_text()

    @app.get('/api/state')
    def state():
        return snapshot(path)

    @app.get('/api/export/{name}.csv')
    def export(name:str):
        if name not in ('trades','decisions','quotes','bars','events'):
            raise HTTPException(404,'Unknown export')
        # Stream bounded chunks: long-running quote archives can be large.
        from fastapi.responses import StreamingResponse
        def chunks():
            db=connect(path)
            try:
                cursor=db.execute('SELECT * FROM '+name)
                output=io.StringIO()
                writer=csv.writer(output)
                writer.writerow([c[0] for c in cursor.description])
                yield output.getvalue()
                while rows:=cursor.fetchmany(1000):
                    output.seek(0); output.truncate(0)
                    writer.writerows(rows)
                    yield output.getvalue()
            finally:
                db.close()
        return StreamingResponse(chunks(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="shadow-{name}.csv"'})

    return app
