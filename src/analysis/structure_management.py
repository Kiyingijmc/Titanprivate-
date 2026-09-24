"""Causal M15 context and a pure, bounded partial/structure-trail policy.

Only complete M15 bars assembled from three closed M5 bars are consumed.
Two bars on each side confirm a swing: a pivot is observable 30 minutes
after its own close, never at its timestamp. This module sends no orders.
"""
from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StructurePolicy:
    first_progress: float = .50
    second_progress: float = .75
    second_spacing_atr: float = .75
    buffer_atr: float = .15
    buffer_spreads: float = 1.5
    normal_partial: float = .35
    trend_partial: float = .25
    defensive_partial: float = .50
    second_partial: float = .25
    volatility_trigger: float = 1.5
    trend_efficiency: float = .55

    def __post_init__(self):
        values = asdict(self)
        if not all(math.isfinite(v) and v > 0 for v in values.values()):
            raise ValueError('structure settings must be finite and positive')
        if not 0 < self.first_progress < self.second_progress < 1:
            raise ValueError('partial progress must satisfy 0 < first < second < 1')
        if not (0 < self.trend_partial <= self.normal_partial <= self.defensive_partial < 1
                and 0 < self.second_partial < 1 and self.trend_efficiency <= 1):
            raise ValueError('invalid partial fractions or efficiency threshold')


def m15_context(m5, as_of):
    """Return observable context or None; timestamps are naive UTC opens."""
    if m5 is None or len(m5) < 60:
        return None
    x = m5[['time', 'open', 'high', 'low', 'close']].copy()
    x['time'] = pd.to_datetime(x.time, utc=True).dt.tz_localize(None)
    now = pd.Timestamp(as_of)
    if now.tzinfo is not None:
        now = now.tz_convert('UTC').tz_localize(None)
    x = x[x.time + pd.Timedelta(minutes=5) <= now]
    # Warmup history can overlap the first streamed candle; newest wins.
    x = x.drop_duplicates('time', keep='last').sort_values('time')
    if x.empty or (x.time.to_numpy(dtype='datetime64[ns]').astype('int64') % (5*60*10**9)).any():
        return None
    nums = x[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
    if not np.isfinite(nums).all() or (nums <= 0).any():
        return None
    if ((x.high < x[['open', 'close']].max(axis=1)).any()
            or (x.low > x[['open', 'close']].min(axis=1)).any()):
        return None
    g = x.set_index('time').resample('15min', closed='left', label='left')
    f = g.agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    f = f[(g.close.count() == 3) & (f.index + pd.Timedelta(minutes=15) <= now)]
    if len(f) < 35 or now - (f.index[-1] + pd.Timedelta(minutes=15)) > pd.Timedelta(minutes=30):
        return None
    previous = f.close.shift()
    tr = pd.concat([f.high-f.low, (f.high-previous).abs(), (f.low-previous).abs()], axis=1).max(axis=1)
    atrs = tr.rolling(14, min_periods=14).mean()
    atr, baseline = float(atrs.iloc[-1]), float(atrs.iloc[-21:-1].median())
    if not all(math.isfinite(v) and v > 0 for v in (atr, baseline)):
        return None
    returns = f.close.iloc[-7:].diff().dropna()
    efficiency = float(returns.sum()/returns.abs().sum()) if returns.abs().sum() else 0.
    context = {'atr': atr, 'volatility_ratio': atr/baseline, 'efficiency': efficiency,
               'closed_at': str(f.index[-1] + pd.Timedelta(minutes=15)),
               'swing_low': None, 'swing_high': None}
    for column, key, low in [('low', 'swing_low', True), ('high', 'swing_high', False)]:
        points = []
        prices = f[column].to_numpy()
        for i in range(2, len(f)-2):
            if f.index[i+2]-f.index[i-2] != pd.Timedelta(minutes=60):
                continue
            value = float(prices[i])
            others = np.delete(prices[i-2:i+3], 2)
            is_pivot = value < others.min() if low else value > others.max()
            if is_pivot:
                points.append({'price': value, 'time': str(f.index[i]),
                               'confirmed_at': str(f.index[i+2] + pd.Timedelta(minutes=15))})
        if len(points) >= 2:
            last, previous = points[-1], points[-2]
            last['continuation'] = (last['price'] > previous['price'] if low
                                    else last['price'] < previous['price'])
            context[key] = last
    return context


def management_plan(*, context, policy, entry, original_tp, current_sl, current_tp,
                    price, is_long, spread, tick_size, since, level):
    """Desired action; caller persists volume target before sending commands.

    First partial: halfway to target. Its fraction is frozen by the caller's
    durable intent. Second partial is spaced by volatility and occurs once.
    No arbitrary ATR fallback trail: without an eligible new swing keep SL/TP.
    """
    values = (entry, original_tp, current_sl, price, spread, tick_size)
    if context is None or not all(math.isfinite(v) for v in values):
        return None
    if min(entry, original_tp, current_sl, price, tick_size) <= 0 or spread < 0:
        return None
    direction = 1 if is_long else -1
    distance = direction*(original_tp-entry)
    if distance <= 0:
        return None
    progress = direction*(price-entry)
    first = policy.first_progress*distance
    second = max(policy.second_progress*distance, first+policy.second_spacing_atr*context['atr'])
    next_level, fraction = level, 0.
    tolerance = tick_size * 1e-6  # absorb float subtraction noise, not a tradable tick
    if level < 2 and progress + tolerance >= first:
        efficiency = direction*context['efficiency']
        if context['volatility_ratio'] >= policy.volatility_trigger or efficiency <= 0:
            fraction = policy.defensive_partial
        elif efficiency >= policy.trend_efficiency:
            fraction = policy.trend_partial
        else:
            fraction = policy.normal_partial
        next_level = 2
    elif level == 2 and progress + tolerance >= second:
        next_level, fraction = 3, policy.second_partial

    stop, target = current_sl, current_tp
    pivot = context['swing_low' if is_long else 'swing_high']
    # Arm after the first stage is broker-confirmed. BID swing highs need ASK
    # conversion for short stops; add current spread before the noise buffer.
    if level >= 2 and pivot and pivot['continuation'] and pd.Timestamp(pivot['time']) >= pd.Timestamp(since):
        buffer = max(policy.buffer_atr*context['atr'], policy.buffer_spreads*spread, 2*tick_size)
        candidate = pivot['price']-buffer if is_long else pivot['price']+spread+buffer
        if (direction*(candidate-entry) >= tick_size and direction*(price-candidate) > tick_size
                and direction*(candidate-current_sl) > tick_size):
            stop = candidate
        # Release TP only once a structural stop is actually proposed/protective.
        if stop != current_sl:
            target = 0.
    if next_level == level and stop == current_sl and target == current_tp:
        return None
    return {'level': next_level, 'sl': stop, 'tp': target, 'fraction': fraction,
            'label': 'M15 structure', 'volatility_ratio': context['volatility_ratio'],
            'efficiency': direction*context['efficiency']}
