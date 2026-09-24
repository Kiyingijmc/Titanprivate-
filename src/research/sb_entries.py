"""Frozen, one-change-at-a-time M15 frequency/entry research arms."""
import math

import numpy as np
import pandas as pd

from src.research.sb_sessions import utc_from_broker
from src.research.sb_variants import collect

ARMS = ('baseline', 'two_setups', 'open_window', 'quarter_retest',
        'edge_retest', 'recent_sweep', 'h1_aligned')


def h1_alignment(h1, signal_times, directions):
    """Use only completed H1 bars; no neutral or stale context admission."""
    ends = h1.time.to_numpy(dtype='datetime64[ns]') + np.timedelta64(60, 'm')
    ema = h1.close.ewm(span=20, adjust=False, min_periods=20).mean().to_numpy()
    prices = h1.close.to_numpy()
    answer = []
    for stamp, direction in zip(signal_times, directions):
        available = np.datetime64(stamp, 'ns')+np.timedelta64(15, 'm')
        j = int(np.searchsorted(ends, available, side='right'))-1
        if j < 1 or available-ends[j] > np.timedelta64(60,'m') or not np.isfinite(ema[j-1]):
            answer.append(False)
            continue
        side = 1 if direction=='BUY' else -1
        answer.append(side*(prices[j]-ema[j]) > 0 and side*(ema[j]-ema[j-1]) > 0)
    return answer


def candidates(frame, arm, *, spread, commission, h1=None):
    if arm not in ARMS:
        raise ValueError('unknown research arm')
    if not all(math.isfinite(x) and x>=0 for x in (spread, commission)):
        raise ValueError('invalid costs')
    variant = 'middle_retest' if arm=='recent_sweep' else 'sweep_reclaim'
    # Collect geometry before cost filtering: entry changes need their own
    # cost eligibility, and a rejected candidate must not consume the cap.
    raw, _ = collect(frame,15,variant,'all_hours',spread=0.,commission=0.)
    index = {pd.Timestamp(t):i for i,t in enumerate(frame.time)}
    t = frame.time.to_numpy(dtype='datetime64[ns]')
    high,low,close = (frame[k].to_numpy() for k in ('high','low','close'))
    prior_low = frame.low.shift(1).rolling(12).min().to_numpy()
    prior_high = frame.high.shift(1).rolling(12).max().to_numpy()
    prepared = []
    for original in raw:
        s = dict(original)
        i = index[pd.Timestamp(s['time'])]
        side = 1 if s['dir']=='BUY' else -1
        if arm=='recent_sweep':
            sweep = None
            for j in range(i-2,i-6,-1):
                if j < 12 or t[i]-t[j-12] != np.timedelta64((i-j+12)*15,'m'):
                    continue
                qualifies = (low[j]<prior_low[j] and close[j]>prior_low[j] if side==1
                             else high[j]>prior_high[j] and close[j]<prior_high[j])
                if qualifies:
                    sweep = j
                    break
            if sweep is None:
                continue
            extreme = min(low[sweep:i+1]) if side==1 else max(high[sweep:i+1])
            s['risk'] = max(s['atr'],side*(s['entry']-extreme)+.1*s['atr'])
        elif arm in ('quarter_retest','edge_retest'):
            stop = s['entry']-side*s['risk']
            near,far = (low[i],high[i-2]) if side==1 else (high[i],low[i-2])
            depth = .25 if arm=='quarter_retest' else 0.
            s['entry'] = float(near+depth*(far-near))
            s['risk'] = float(side*(s['entry']-stop))
        s['cost_r'] = (spread+commission)/s['risk']
        prepared.append(s)
    aligned = [True]*len(prepared)
    if arm=='h1_aligned':
        if h1 is None:
            raise ValueError('completed H1 data required')
        aligned = h1_alignment(h1,[s['time'] for s in prepared],[s['dir'] for s in prepared])
    ny = utc_from_broker(pd.DatetimeIndex([s['time'] for s in prepared])+pd.Timedelta(minutes=15),
                         'seasonal_eet').tz_convert('America/New_York')
    counts = dict(pattern=len(prepared), in_window=0, cost_rejected=0,
                  alignment_rejected=0, cap_rejected=0, eligible=0)
    selected, dates = [], {}
    for s, stamp, allow in zip(prepared,ny,aligned):
        if pd.isna(stamp):
            continue
        minute = stamp.hour*60+stamp.minute
        if not (570 if arm=='open_window' else 600) <= minute < 660:
            continue
        counts['in_window'] += 1
        if s['cost_r']>.25:
            counts['cost_rejected'] += 1
            continue
        if not allow:
            counts['alignment_rejected'] += 1
            continue
        previous = dates.setdefault(stamp.date(),[])
        cap = 2 if arm=='two_setups' else 1
        if len(previous)>=cap or (previous and stamp-previous[-1]<pd.Timedelta(minutes=30)):
            counts['cap_rejected'] += 1
            continue
        previous.append(stamp)
        selected.append(s)
    counts['eligible'] = len(selected)
    return selected,counts
