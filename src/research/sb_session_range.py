"""Causal first-sweep reversal of a completed New York overnight range."""
import math
import numpy as np
import pandas as pd
from src.research.sb_sessions import utc_from_broker


def collect_session_range(frame, *, spread, commission):
    if not all(math.isfinite(v) and v>=0 for v in (spread,commission)):
        raise ValueError('invalid costs')
    t=frame.time.to_numpy(dtype='datetime64[ns]')
    if len(t) and (np.isnat(t).any() or (np.diff(t)<=np.timedelta64(0,'m')).any()):
        raise ValueError('unordered or invalid times')
    for key in ('open','high','low','close'):
        if not np.isfinite(frame[key]).all() or (frame[key]<=0).any():
            raise ValueError('invalid prices')
    if ((frame.high<frame[['open','close']].max(axis=1)).any() or (frame.low>frame[['open','close']].min(axis=1)).any()):
        raise ValueError('invalid OHLC')
    local=utc_from_broker(pd.DatetimeIndex(t),'seasonal_eet').tz_convert('America/New_York')
    minute=local.hour*60+local.minute
    dates=local.date
    o,h,l,c,a=(frame[k].to_numpy() for k in ('open','high','low','close','atr'))
    signals, diagnostics=[],[]
    for day in sorted(set(dates[local.notna()])):
        indices=np.flatnonzero((dates==day)&local.notna())
        reference=indices[(minute[indices]>=0)&(minute[indices]<570)]
        active=indices[(minute[indices]>=570)&(minute[indices]<645)]
        if not len(active): continue
        record=dict(ny_date=str(day),complete_range=0,event=0,ambiguous=0,invalidated=0,
                    cost_rejected=0,eligible=0)
        diagnostics.append(record)
        if (len(reference)!=38 or not np.array_equal(minute[reference],np.arange(0,570,15))
                or not (np.diff(t[reference])==np.timedelta64(15,'m')).all()):
            continue
        # Range indices all precede the first possible sweep; immutable thereafter.
        upper,lower=float(max(h[reference])),float(min(l[reference]))
        record.update(complete_range=1,range_high=upper,range_low=lower)
        event=None
        side=0
        for i in active:
            if i<1 or t[i]-t[i-1]!=np.timedelta64(15,'m'):
                break
            if h[i]>upper and l[i]<lower:
                record['ambiguous']=1
                break
            if event is None:
                if minute[i]+15>630: break
                side=1 if l[i]<lower and c[i]>lower else (-1 if h[i]>upper and c[i]<upper else 0)
                if side:
                    event=i
                    record.update(event=1,event_time=str(t[i]),direction='BUY' if side==1 else 'SELL')
                continue
            if (c[i]<lower if side==1 else c[i]>upper):
                record['invalidated']=1
                break
            if t[i]-t[event]>np.timedelta64(60,'m'): break
            if i<50 or i-event<2: continue
            if t[i]-t[event]!=np.timedelta64((i-event)*15,'m'): break
            if not (math.isfinite(a[i]) and a[i]>0 and math.isfinite(a[i-1]) and a[i-1]>0): continue
            gap=l[i]>h[i-2] if side==1 else h[i]<l[i-2]
            if not gap or side*(c[i-1]-o[i-1])<a[i-1]: continue
            entry=float((l[i]+h[i-2])/2 if side==1 else (h[i]+l[i-2])/2)
            extreme=float(min(l[event:i+1]) if side==1 else max(h[event:i+1]))
            risk=float(max(a[i],side*(entry-extreme)+.1*a[i]))
            if not all(math.isfinite(v) and v>0 for v in (entry,risk,entry-side*risk,entry+side*2*risk)): continue
            if (spread+commission)/risk>.25:
                record['cost_rejected']+=1
                continue
            signals.append(dict(time=str(t[i]),dir='BUY' if side==1 else 'SELL',entry=entry,risk=risk,
                                atr=float(a[i]),event_time=str(t[event]),range_high=upper,range_low=lower,
                                range_date=str(day),cost_r=(spread+commission)/risk))
            record['eligible']=1
            break
    return signals,diagnostics
