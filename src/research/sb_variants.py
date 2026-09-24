"""Causal, research-only SilverBullet detectors. No live registry side effects."""
import math

import numpy as np
import pandas as pd

TIMEFRAMES = {'M5': 5, 'M15': 15, 'M30': 30, 'H1': 60, 'H2': 120}
VARIANTS = ('edge_control', 'middle_retest', 'sweep_reclaim')
WINDOWS = ('all_hours', 'ny_am')


def resample_complete(frame, minutes):
    """Keep only complete, aligned source buckets; fail on invalid M5 data."""
    from src.research.sb_execution import validate_bars
    if minutes not in TIMEFRAMES.values():
        raise ValueError('unsupported timeframe')
    x = frame.copy()
    x['time'] = pd.to_datetime(x['time'])
    validate_bars({k: x[k].to_numpy() for k in ('time', 'open', 'high', 'low', 'close')})
    if (x['time'].to_numpy(dtype='datetime64[ns]').astype('int64') % (5 * 60 * 10**9)).any():
        raise ValueError('source timestamps must align to M5 opens')
    if (x[['open', 'high', 'low', 'close']] <= 0).any().any():
        raise ValueError('source prices must be positive')
    x = x.set_index('time')
    grouped = x.resample(f'{minutes}min', closed='left', label='left', origin='start_day')
    out = grouped.agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    out = out[grouped['close'].count() == minutes // 5].copy()
    prev = out['close'].shift()
    tr = pd.concat([out.high-out.low, (out.high-prev).abs(), (out.low-prev).abs()], axis=1).max(axis=1)
    out['atr'] = tr.rolling(14, min_periods=14).mean()
    return out.reset_index()


def collect(frame, minutes, variant, window, *, spread, commission, broker_offset=2):
    """Return cost-eligible signals and funnel counts from completed TF bars.

    frame is resample_complete output. Prefix evaluation produces the same
    signals as the corresponding prefix of a longer history.
    """
    if variant not in VARIANTS or window not in WINDOWS or minutes not in TIMEFRAMES.values():
        raise ValueError('unknown variant/window/timeframe')
    if not all(math.isfinite(v) and v >= 0 for v in (spread, commission)):
        raise ValueError('invalid costs')
    t = frame.time.to_numpy(dtype='datetime64[ns]')
    o, h, l, c, atr = (frame[k].to_numpy(dtype=float) for k in ('open', 'high', 'low', 'close', 'atr'))
    body = c-o
    look_low = frame.low.shift(3).rolling(12).min().to_numpy()
    look_high = frame.high.shift(3).rolling(12).max().to_numpy()
    delta = np.timedelta64(minutes, 'm')
    # Only closed signal times are converted. Broker offset is an explicit
    # assumption, never guessed from the machine's timezone or wall clock.
    ny = (pd.DatetimeIndex(t + delta).tz_localize('UTC')
          - pd.Timedelta(hours=broker_offset)).tz_convert('America/New_York')
    signals, dates = [], set()
    counts = dict(pattern=0, session=0, cost_rejected=0, duplicate_session=0, eligible=0)
    for i in range(50, len(frame)):
        if t[i]-t[i-2] != 2*delta:
            continue
        side = 1 if l[i] > h[i-2] else (-1 if h[i] < l[i-2] else 0)
        if not side or not math.isfinite(atr[i]) or atr[i] <= 0:
            continue
        j = i if variant == 'edge_control' else i-1
        if side*body[j] < atr[j]:
            continue
        if variant == 'sweep_reclaim':
            if t[i]-t[i-14] != 14*delta:
                continue
            reclaim = (l[i-2] < look_low[i] and c[i-2] > look_low[i] if side == 1
                       else h[i-2] > look_high[i] and c[i-2] < look_high[i])
            if not reclaim:
                continue
        counts['pattern'] += 1
        if window == 'ny_am' and ny[i].hour != 10:
            continue
        counts['session'] += 1
        if variant == 'edge_control':
            entry = l[i] if side == 1 else h[i]
            risk = atr[i]
        else:
            entry = (l[i]+h[i-2])/2 if side == 1 else (h[i]+l[i-2])/2
            extreme = min(l[i-2:i+1]) if side == 1 else max(h[i-2:i+1])
            risk = max(atr[i], side*(entry-extreme) + .1*atr[i])
        if not (math.isfinite(risk) and risk > 0 and entry-risk > 0 and entry-2*risk > 0):
            continue
        cost_r = (spread+commission)/risk
        if cost_r > .25:
            counts['cost_rejected'] += 1
            continue
        date = ny[i].date()
        if window == 'ny_am' and date in dates:
            counts['duplicate_session'] += 1
            continue
        dates.add(date)
        signals.append(dict(time=str(t[i]), dir='BUY' if side == 1 else 'SELL',
                            entry=float(entry), risk=float(risk), atr=float(atr[i]),
                            cost_r=float(cost_r)))
    counts['eligible'] = len(signals)
    return signals, counts
