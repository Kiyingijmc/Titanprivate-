"""Submit a fresh midpoint LIMIT only after a completed M5 confirmation."""
import math
import numpy as np
from src.research.sb_execution import PATHS, replay_order, validate_bars


def retest_order(signal, bars, *, path, spread, commission):
    """Replay one parent on uninterrupted M5 bars with full lifecycle coverage.

    Pending expiry remains anchored to the parent close. Post-submission gaps
    are handled by the unchanged LIMIT engine, including adverse stop gaps.
    """
    validate_bars(bars)
    if path not in PATHS or signal['dir'] not in ('BUY', 'SELL'):
        raise ValueError('invalid direction/path')
    side = 1 if signal['dir']=='BUY' else -1
    entry, risk = float(signal['entry']), float(signal['risk'])
    if not all(math.isfinite(x) for x in (entry,risk,spread,commission)) or min(entry,risk)<=0 or min(spread,commission)<0:
        raise ValueError('invalid geometry or costs')
    stop = entry-side*risk
    if stop<=0 or entry+side*2*risk<=0:
        raise ValueError('nonpositive stop or target')
    created = np.datetime64(signal['time'],'ns')+np.timedelta64(15,'m')
    if np.isnat(created):
        raise ValueError('invalid timestamp')
    expiry = created+np.timedelta64(45,'m')
    times = bars['time']
    start = int(np.searchsorted(times,created))
    end = int(np.searchsorted(times,created+np.timedelta64(225,'m')))
    if (start<1 or end>=len(times) or times[start]!=created
            or times[end]!=created+np.timedelta64(225,'m')
            or not (np.diff(times[start-1:end+1])==np.timedelta64(5,'m')).all()):
        raise ValueError('complete uninterrupted parent lifecycle required')

    def rejected(outcome,release,confirmation=None):
        return dict(time=str(signal['time']),dir=signal['dir'],entry=entry,risk=risk,
                    parent_risk=risk,created=str(created),release=str(release),
                    fill_idx=None,exit_idx=None,outcome=outcome,gross_r=None,net_r=None,
                    rejected_be=0,confirmation_close=confirmation,risk_ratio=None,
                    fill_time=None,exit_time=None)

    touched = False
    for k in range(start,end+1):
        if times[k]>=expiry:
            return rejected('NO_CONFIRMATION',expiry)
        o,h,l,c = (float(bars[key][k]) for key in ('open','high','low','close'))
        if (l<=stop if side==1 else h+spread>=stop):
            return rejected('INVALIDATED',times[k]+np.timedelta64(5,'m'))
        touched |= l+spread<=entry if side==1 else h>=entry
        broken = c>bars['high'][k-1] if side==1 else c<bars['low'][k-1]
        if not (touched and side*(c-o)>0 and side*(c-entry)>0 and broken):
            continue
        available = times[k]+np.timedelta64(5,'m')
        if available>=expiry:
            return rejected('NO_CONFIRMATION',expiry)
        if (spread+commission)/risk>.25:
            return rejected('ENTRY_COST',available,str(available))
        remaining = int((expiry-available)/np.timedelta64(1,'m'))
        resting = dict(signal,time=str(times[k]))
        row = replay_order(resting,bars,arm='fixed',path=path,spread=spread,
                           commission=commission,signal_minutes=5,ttl_minutes=remaining,
                           max_hold_minutes=180)
        row.update(time=str(signal['time']),created=str(created),parent_risk=risk,
                   confirmation_close=str(available),risk_ratio=1. if row['fill_idx'] is not None else None,
                   fill_time=str(times[row['fill_idx']]) if row['fill_idx'] is not None else None,
                   exit_time=str(times[row['exit_idx']]) if row['exit_idx'] is not None else None)
        return row
    raise AssertionError('expiry must be covered')
