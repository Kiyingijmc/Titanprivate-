"""Closed-bar adapters for the two unchanged research detectors."""
import hashlib
import json
import math
import numpy as np
import pandas as pd
from src.research.sb_entries import candidates
from src.research.sb_session_range import collect_session_range
from src.research.sb_sessions import utc_from_broker
from src.research.sb_variants import resample_complete
from src.research.sb_execution import validate_bars
from src.research.costs import spread_price
from .store import CANDIDATES


def market_epoch(raw):
    """Bridge UTC labels encode broker wall time in this frozen cohort."""
    stamp=pd.Timestamp(raw)
    if stamp.tzinfo is not None: stamp=stamp.tz_convert('UTC').tz_localize(None)
    converted=utc_from_broker([stamp],'seasonal_eet')[0]
    if pd.isna(converted): raise ValueError('ambiguous broker clock')
    return converted.timestamp()


def prepare_bars(candles,now):
    frame=pd.DataFrame([dict(time=c.time,open=c.open,high=c.high,low=c.low,close=c.close) for c in candles])
    if frame.empty: raise ValueError('empty history')
    frame['time']=pd.to_datetime(frame.time,utc=True).dt.tz_localize(None)
    ends=utc_from_broker(pd.DatetimeIndex(frame.time)+pd.Timedelta(minutes=5),'seasonal_eet')
    keep=ends.notna()&(ends<=pd.Timestamp(now,unit='s',tz='UTC'))
    frame=frame[keep].sort_values('time').reset_index(drop=True)
    validate_bars({k:frame[k].to_numpy() for k in ('time','open','high','low','close')})
    if (frame[['open','high','low','close']]<=0).any().any(): raise ValueError('nonpositive bars')
    return frame


def rolling_reason(frame,signals,spread,commission):
    if len(frame)<=50: return 'WARMUP'
    i=len(frame)-1
    h,l,c,o,a=(frame[k].to_numpy() for k in ('high','low','close','open','atr'))
    side=1 if l[i]>h[i-2] else (-1 if h[i]<l[i-2] else 0)
    if not side: return 'NO_FVG'
    if not math.isfinite(a[i-1]) or side*(c[i-1]-o[i-1])<a[i-1]: return 'NO_DISPLACEMENT'
    low=min(l[i-14:i-2]); high=max(h[i-14:i-2])
    swept=l[i-2]<low and c[i-2]>low if side==1 else h[i-2]>high and c[i-2]<high
    if not swept: return 'NO_SWEEP_RECLAIM'
    entry=(l[i]+h[i-2])/2 if side==1 else (h[i]+l[i-2])/2
    extreme=min(l[i-2:i+1]) if side==1 else max(h[i-2:i+1])
    risk=max(a[i],side*(entry-extreme)+.1*a[i])
    if not math.isfinite(risk) or min(risk,entry-risk,entry-2*risk)<=0: return 'INVALID_GEOMETRY'
    if (spread+commission)/risk>.25: return 'MODEL_COST'
    return 'DAILY_CAP' if signals else 'NO_PARENT_AT_CLOSE'


def observe_bars(store,symbol,candles,spec,now):
    frame=prepare_bars(candles,now)
    if not store.record_bars(symbol,frame,now):
        return 'BAR_REVISION'
    gaps=np.flatnonzero(frame.time.diff().ne(pd.Timedelta(minutes=5)).to_numpy())
    part=frame.iloc[gaps[-1]:].reset_index(drop=True)
    m15=resample_complete(part,15)
    if m15.empty:
        with store.db:
            store.event(now,'NO_COMPLETE_M15',dict(symbol=symbol))
        return 'NO_COMPLETE_M15'
    last=pd.Timestamp(m15.time.iloc[-1])
    closed=market_epoch(last+pd.Timedelta(minutes=15))
    ny=pd.Timestamp(closed,unit='s',tz='UTC').tz_convert('America/New_York')
    spread=spread_price(symbol,spec['tick_size'])
    commission=7*spec['tick_size']/spec['tick_value']
    context=dict(first=str(part.time.iloc[0]),last=str(part.time.iloc[-1]),bars=len(part),
        sha256=hashlib.sha256(part.to_csv(index=False).encode()).hexdigest(),
        clock='seasonal_eet',funnel_scope='available contiguous segment')
    if now-closed>900:
        with store.db: store.event(now,'STALE_BARS',dict(symbol=symbol,closed=closed))
    for candidate in CANDIDATES:
        details=dict(context=context)
        signal=None
        selected=[]
        if len(m15)<=50:
            reason='WARMUP'
        elif not 570<=ny.hour*60+ny.minute<660:
            reason='OUTSIDE_WINDOW'
        elif candidate=='wider_midpoint':
            selected,funnel=candidates(m15,'open_window',spread=spread,commission=commission)
            details['funnel']=funnel
            signal=next((s for s in selected if pd.Timestamp(s['time'])==last),None)
            reason='SIGNAL' if signal else rolling_reason(m15,selected,spread,commission)
        else:
            selected,days=collect_session_range(m15,spread=spread,commission=commission)
            signal=next((s for s in selected if pd.Timestamp(s['time'])==last),None)
            day=next((d for d in reversed(days) if d['ny_date']==str(ny.date())),{})
            details['day']=day
            reason=('SIGNAL' if signal else 'INCOMPLETE_RANGE' if not day.get('complete_range') else
                    'AMBIGUOUS_SWEEP' if day.get('ambiguous') else 'EVENT_INVALIDATED' if day.get('invalidated') else
                    'DAILY_CAP' if day.get('eligible') else 'NO_SESSION_SWEEP' if not day.get('event') else
                    'NO_DISPLACEMENT_OR_FVG')
        # Preserve today's first parent even if it predates this process or a
        # later history gap removes it from the next fetched context.
        for previous in selected:
            previous_close=market_epoch(pd.Timestamp(previous['time'])+pd.Timedelta(minutes=15))
            previous_day=pd.Timestamp(previous_close,unit='s',tz='UTC').tz_convert('America/New_York').date()
            if previous_day==ny.date() and previous_close<closed:
                store.decision(symbol,candidate,previous_close,now,'CONTEXT_PARENT',
                    dict(context=context,signal=previous,context_only=True),signal=previous,commission=commission)
        if signal: details['signal']=signal
        store.decision(symbol,candidate,closed,now,reason,details,signal=signal,commission=commission)
    with store.db:
        store.set('last_bars:'+symbol,now)
        store.set('last_bar_close:'+symbol,closed)
    return 'RECORDED'
