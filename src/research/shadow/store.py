"""Durable quote-sampled shadow execution, isolated from live trade state."""
import json
import math
from pathlib import Path
import sqlite3
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

CANDIDATES=('wider_midpoint','session_range')
SCENARIOS={'observed':1.,'stress_1_5':1.5}
POLICY=dict(version=1,pending_seconds=2700,holding_seconds=10800,max_quote_age=15.,
            max_observation_gap=15.,max_discovery_delay=90.,cost_ceiling=.25,
            minimum_fills=100,breadth_symbols=3,breadth_fills=20)


class Store:
    def __init__(self,path,manifest,now):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY,symbol TEXT NOT NULL,
          observed REAL NOT NULL,market REAL,raw_time TEXT,bid REAL,ask REAL,reason TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS quote_symbol_time ON quotes(symbol,observed);
        CREATE TABLE IF NOT EXISTS bars(symbol TEXT,time TEXT,open REAL,high REAL,low REAL,close REAL,
          first_observed REAL,PRIMARY KEY(symbol,time));
        CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,symbol TEXT,candidate TEXT,
          closed REAL,observed REAL,reason TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS parent_days(symbol TEXT,candidate TEXT,ny_date TEXT,
          decision_id TEXT,PRIMARY KEY(symbol,candidate,ny_date));
        CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY,symbol TEXT,candidate TEXT,scenario TEXT,
          signal REAL,admitted REAL,direction INTEGER,entry REAL,risk REAL,stop REAL,target REAL,
          commission REAL,expires REAL,status TEXT,fill_time REAL,exit_time REAL,exit_price REAL,
          net_r REAL,reason TEXT,fill_quote INTEGER,exit_quote INTEGER);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,observed REAL,kind TEXT,details TEXT);
        CREATE INDEX IF NOT EXISTS active_trade_symbol ON trades(symbol,status);
        COMMIT;
        ''')
        frozen=json.dumps(manifest,sort_keys=True,allow_nan=False)
        prior=self.get('manifest')
        if prior is not None and prior!=frozen:
            self.db.close()
            raise ValueError('frozen cohort differs; use a new directory, never retune this cohort')
        with self.db:
            if prior is None:
                self.set('manifest',frozen)
                self.set('started',str(now))
            self.set('status','STARTING')
        self.started=float(self.get('started'))

    def close(self):
        self.db.close()

    def get(self,key):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return row[0] if row else None

    def set(self,key,value):
        self.db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))

    def event(self,now,kind,details):
        self.db.execute('INSERT INTO events(observed,kind,details) VALUES(?,?,?)',
                        (now,kind,json.dumps(details,allow_nan=False)))

    def censor_gaps(self,symbol,now):
        last=float(self.get('last_quote:'+symbol) or 0)
        for row in self.db.execute("SELECT * FROM trades WHERE symbol=? AND status IN ('PENDING','OPEN')",(symbol,)).fetchall():
            if now-max(last,row['admitted'])>POLICY['max_observation_gap']:
                self.db.execute("UPDATE trades SET status='CENSORED',exit_time=?,reason='OBSERVATION_GAP' WHERE id=?",(now,row['id']))

    def quote(self,symbol,now,market=None,bid=None,ask=None,raw_time=None,error=None):
        reason=error
        if reason is None:
            if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (market,bid,ask)) or bid<=0 or ask<bid:
                reason='INVALID_QUOTE'
            elif market>now+2:
                reason='FUTURE_OR_WRONG_CLOCK'
            elif now-market>POLICY['max_quote_age']:
                reason='STALE_QUOTE'
            elif market<float(self.get('last_market:'+symbol) or 0):
                reason='OUT_OF_ORDER_QUOTE'
        with self.db:
            self.censor_gaps(symbol,now)
            cursor=self.db.execute('INSERT INTO quotes(symbol,observed,market,raw_time,bid,ask,reason) VALUES(?,?,?,?,?,?,?)',
                (symbol,now,market,raw_time,bid if bid is None or math.isfinite(bid) else None,
                 ask if ask is None or math.isfinite(ask) else None,reason or 'VALID'))
            quote_id=cursor.lastrowid
            self.set('heartbeat',now)
            if reason:
                return reason
            self.set('last_quote:'+symbol,now)
            self.set('last_market:'+symbol,market)
            self.set('latest:'+symbol,json.dumps(dict(observed=now,market=market,bid=bid,ask=ask)))
            for row in self.db.execute("SELECT * FROM trades WHERE symbol=? AND status IN ('PENDING','OPEN')",(symbol,)).fetchall():
                r=dict(row)
                # A quote predating admission cannot fill the newly created order.
                if market<r['admitted']:
                    continue
                mult=SCENARIOS[r['scenario']]
                executable_ask=bid+(ask-bid)*mult
                if r['status']=='PENDING':
                    if now>=r['expires']:
                        self.db.execute("UPDATE trades SET status='EXPIRED',exit_time=?,reason='TTL' WHERE id=?",(now,r['id']))
                        continue
                    touched=executable_ask<=r['entry'] if r['direction']==1 else bid>=r['entry']
                    if not touched:
                        continue
                    # Requested limit price: deliberately no favorable improvement.
                    self.db.execute("UPDATE trades SET status='OPEN',fill_time=?,fill_quote=? WHERE id=?",(now,quote_id,r['id']))
                    r['fill_time']=now
                liquidation=bid if r['direction']==1 else executable_ask
                oriented=r['direction']*(liquidation-r['entry'])
                outcome=None
                if oriented<=-r['risk']:
                    outcome='STOP'
                    price=liquidation
                elif oriented>=2*r['risk']:
                    outcome='TP'
                    price=r['target']
                elif now>=r['fill_time']+POLICY['holding_seconds']:
                    outcome='TIME_EXIT'
                    price=liquidation
                if outcome:
                    net=(r['direction']*(price-r['entry'])-r['commission'])/r['risk']
                    self.db.execute("UPDATE trades SET status='CLOSED',exit_time=?,exit_price=?,net_r=?,reason=?,exit_quote=? WHERE id=?",(now,price,net,outcome,quote_id,r['id']))
        return 'VALID'

    def record_bars(self,symbol,frame,now):
        """Immutable completed bars: corrections are reported, never overwritten."""
        conflict=False
        with self.db:
            for row in frame.itertuples(index=False):
                key=str(row.time)
                values=tuple(float(getattr(row,k)) for k in ('open','high','low','close'))
                old=self.db.execute('SELECT open,high,low,close FROM bars WHERE symbol=? AND time=?',(symbol,key)).fetchone()
                if old and tuple(old)!=values:
                    conflict=True
                elif not old:
                    self.db.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?)',(symbol,key,*values,now))
            if conflict:
                self.event(now,'BAR_REVISION',dict(symbol=symbol))
        return not conflict

    def decision(self,symbol,candidate,closed,now,reason,details,signal=None,commission=0.):
        if candidate not in CANDIDATES:
            raise ValueError('unknown frozen candidate')
        identifier=f'{candidate}:{symbol}:{closed:.0f}'
        with self.db:
            if self.db.execute('SELECT 1 FROM decisions WHERE id=?',(identifier,)).fetchone():
                if signal is not None:
                    day=str(datetime.fromtimestamp(closed,timezone.utc).astimezone(ZoneInfo('America/New_York')).date())
                    self.db.execute('INSERT OR IGNORE INTO parent_days VALUES(?,?,?,?)',(symbol,candidate,day,identifier))
                return 'DUPLICATE'
            if signal is not None:
                day=str(datetime.fromtimestamp(closed,timezone.utc).astimezone(ZoneInfo('America/New_York')).date())
                if self.db.execute('SELECT 1 FROM parent_days WHERE symbol=? AND candidate=? AND ny_date=?',(symbol,candidate,day)).fetchone():
                    signal=None
                    reason='DAILY_CAP'
                else:
                    self.db.execute('INSERT INTO parent_days VALUES(?,?,?,?)',(symbol,candidate,day,identifier))
            if signal is not None:
                if closed<self.started:
                    reason='BEFORE_COHORT'
                elif now<closed or now-closed>POLICY['max_discovery_delay']:
                    reason='LATE_DISCOVERY'
                else:
                    quote=json.loads(self.get('latest:'+symbol) or 'null')
                    if not quote or now-quote['observed']>POLICY['max_quote_age'] or now-quote['market']>POLICY['max_quote_age']:
                        reason='NO_FRESH_QUOTE'
                    elif self.db.execute("SELECT 1 FROM trades WHERE symbol=? AND candidate=? AND status IN ('PENDING','OPEN')",(symbol,candidate)).fetchone():
                        reason='BUSY'
                    else:
                        entry,risk=float(signal['entry']),float(signal['risk'])
                        if signal['dir'] not in ('BUY','SELL') or not all(math.isfinite(v) and v>0 for v in (entry,risk)) or not math.isfinite(commission) or commission<0:
                            raise ValueError('invalid hypothetical order')
                        direction=1 if signal['dir']=='BUY' else -1
                        stop,target=entry-direction*risk,entry+direction*2*risk
                        if min(stop,target)<=0: raise ValueError('invalid stop/target')
                        reason='SIGNAL'
                        for scenario,mult in SCENARIOS.items():
                            cost=(quote['ask']-quote['bid']+commission)*mult/risk
                            state='PENDING' if cost<=POLICY['cost_ceiling'] else 'REJECTED'
                            self.db.execute('''INSERT INTO trades(id,symbol,candidate,scenario,signal,admitted,direction,entry,risk,stop,target,commission,expires,status,reason)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (identifier+':'+scenario,symbol,candidate,scenario,closed,now,direction,entry,risk,stop,target,
                                 commission*mult,closed+POLICY['pending_seconds'],state,'AWAITING_QUOTE' if state=='PENDING' else 'OBSERVED_COST'))
            self.db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?)',
                (identifier,symbol,candidate,closed,now,reason,json.dumps(details,sort_keys=True,allow_nan=False)))
        return reason

    def stop(self,now):
        with self.db:
            self.db.execute("UPDATE trades SET status='CENSORED',exit_time=?,reason='RECORDER_STOPPED' WHERE status IN ('PENDING','OPEN')",(now,))
            self.set('status','STOPPED')
            self.set('heartbeat',now)
