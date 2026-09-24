#!/usr/bin/env python3
"""Read-only bridge comparison against immutable shadow observations."""
import argparse,asyncio,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from src.research.shadow.feed import Feed
from src.research.shadow.signals import market_epoch,prepare_bars

async def run(args):
    load_dotenv(ROOT/'.env',override=False)
    db=sqlite3.connect(args.directory.resolve().joinpath('shadow.sqlite3').as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    report=dict(captured=time.time(),symbols=[])
    async with Feed() as feed:
        for symbol in ('EURUSD','GBPJPY','BTCUSD'):
            item=dict(symbol=symbol)
            try:
                tick=await feed.quote(symbol)
                item['quote_age_seconds']=time.time()-market_epoch(tick.time)
                item['raw_quote_time']=tick.time.isoformat()
                frame=prepare_bars(await feed.candles(symbol),time.time())
                differences=[]
                overlap=0
                for r in frame.itertuples(index=False):
                    old=db.execute('SELECT * FROM bars WHERE symbol=? AND time=?',(symbol,str(r.time))).fetchone()
                    if old is None: continue
                    overlap+=1
                    cols=('open','high','low','close')
                    new=[float(getattr(r,k)) for k in cols]
                    previous=[old[k] for k in cols]
                    if new!=previous:
                        differences.append(dict(time=str(r.time),first_observed=old['first_observed'],old=previous,new=new,
                                                max_abs_change=max(abs(a-b) for a,b in zip(new,previous))))
                item.update(overlap=overlap,conflicts=len(differences),examples=differences[:5],last_conflicts=differences[-3:])
            except Exception as exc:
                item['error']=type(exc).__name__
            report['symbols'].append(item)
    db.close()
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--directory',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    asyncio.run(run(ap.parse_args()))
