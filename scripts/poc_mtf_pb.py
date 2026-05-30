#!/usr/bin/env python3
# scripts/poc_mtf_pb.py
# MTF trend-pullback proof-of-concept. 4H+1H 50-EMA bias -> 5m fib(0.5-0.705) pullback
# + confirmation-close entry -> 1.0xATR(1H) structural stop -> two exit models
# (fixed-2.5R, partial-at-1R+ATR-trail). Screens net-of-cost, OOS edge across asset
# classes. NOT a live strategy. See docs/superpowers/specs/2026-05-30-mtf-trend-pullback-poc-design.md
import bisect
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
                                "tests", "backtest"))
import backtest_engine as bt          # noqa: E402
from scripts import poc_trend_h4 as tp # noqa: E402


def resample_tf(m5_df, rule):
    """Resample M5 OHLC to a higher timeframe ('4h','1h','15min'). Returns a df with a
    'time' column (bar-open timestamp) + open/high/low/close. Bars are label='left'
    (pandas default): a 4h bar stamped 00:00 spans 00:00-03:59 and CLOSES at 04:00."""
    df = m5_df.copy()
    tcol = "time" if "time" in df.columns else "datetime"
    df["time"] = pd.to_datetime(df[tcol])
    df = df.set_index("time")
    r = df.resample(rule).agg({"open": "first", "high": "max",
                               "low": "min", "close": "last"}).dropna()
    return r.reset_index()


def ma_bias(htf_df, ma_len=50):
    """Per-closed-bar trend by price vs a single EMA. BULLISH if close>EMA, BEARISH if
    close<EMA, NEUTRAL within the warmup (< ma_len bars) or on an exact touch."""
    closes = htf_df["close"].reset_index(drop=True)
    e = closes.ewm(span=ma_len, adjust=False).mean()
    out = []
    for i in range(len(closes)):
        if i < ma_len:
            out.append("NEUTRAL")
        elif closes[i] > e[i]:
            out.append("BULLISH")
        elif closes[i] < e[i]:
            out.append("BEARISH")
        else:
            out.append("NEUTRAL")
    return out


def last_closed_indexer(m5_times, htf_times, tf_hours):
    """For each m5 timestamp, the index of the most recently CLOSED htf bar (or -1).
    An htf bar stamped T closes at T + tf_hours; it may only be used from then on.
    No look-ahead: a bar in progress is never visible to an earlier m5 bar."""
    close_times = [t + pd.Timedelta(hours=tf_hours) for t in htf_times]  # ascending
    out = []
    for t in m5_times:
        out.append(bisect.bisect_right(close_times, t) - 1)
    return out


def combine_bias_lists(bias4, bias1, idx4, idx1):
    """Combine per-bar 4H/1H bias for each 5m bar given the closed-bar indices.
    BULLISH only if both agree bullish, BEARISH only if both agree bearish, else NEUTRAL.
    A negative index (no closed HTF bar yet) -> NEUTRAL."""
    out = []
    for k in range(len(idx4)):
        a = bias4[idx4[k]] if idx4[k] >= 0 else "NEUTRAL"
        b = bias1[idx1[k]] if idx1[k] >= 0 else "NEUTRAL"
        if a == "BULLISH" and b == "BULLISH":
            out.append("BULLISH")
        elif a == "BEARISH" and b == "BEARISH":
            out.append("BEARISH")
        else:
            out.append("NEUTRAL")
    return out


def combined_bias(m5_df, h4, h1, ma_len=50):
    """Per-5m-bar combined 4H+1H bias, using only closed HTF bars (no look-ahead)."""
    m5t = list(pd.to_datetime(m5_df["time" if "time" in m5_df.columns else "datetime"]))
    idx4 = last_closed_indexer(m5t, list(pd.to_datetime(h4["time"])), 4)
    idx1 = last_closed_indexer(m5t, list(pd.to_datetime(h1["time"])), 1)
    return combine_bias_lists(ma_bias(h4, ma_len), ma_bias(h1, ma_len), idx4, idx1)


def attach_atr1h(m5_df, h1, period=14):
    """ATR(1H) value of the last CLOSED H1 bar, aligned to each 5m bar (0.0 if none yet).
    Reuses poc_trend_h4.atr_series for the ATR computation."""
    atr = tp.atr_series(h1, period).fillna(0.0).values
    m5t = list(pd.to_datetime(m5_df["time" if "time" in m5_df.columns else "datetime"]))
    idx = last_closed_indexer(m5t, list(pd.to_datetime(h1["time"])), 1)
    return [float(atr[j]) if j >= 0 else 0.0 for j in idx]


def _is_swing_high(highs, j, lk):
    """True when highs[j] is strictly greater than all lk neighbours on each side."""
    window = highs[j - lk:j + lk + 1]
    return highs[j] > max(window[:lk] + window[lk + 1:])


def _is_swing_low(lows, j, lk):
    """True when lows[j] is strictly less than all lk neighbours on each side."""
    window = lows[j - lk:j + lk + 1]
    return lows[j] < min(window[:lk] + window[lk + 1:])


def recent_swing(highs, lows, i, lk):
    """Indices of the most recent CONFIRMED swing high and swing low strictly before bar i.
    A swing at j needs lk bars either side; confirmation requires j+lk < i (no look-ahead).
    Returns (lo_idx, hi_idx), either may be None."""
    hi_idx = lo_idx = None
    j = i - lk - 1
    while j >= lk:
        if hi_idx is None and _is_swing_high(highs, j, lk):
            hi_idx = j
        if lo_idx is None and _is_swing_low(lows, j, lk):
            lo_idx = j
        if hi_idx is not None and lo_idx is not None:
            break
        j -= 1
    return lo_idx, hi_idx


def impulse_leg(highs, lows, i, lk, bias):
    """The most recent impulse leg matching the bias: an up-leg (swing low BEFORE swing
    high) for BULLISH, a down-leg (swing high before swing low) for BEARISH. Returns
    (leg_low, leg_high) prices, or None if no leg in the trend direction is found."""
    lo_idx, hi_idx = recent_swing(highs, lows, i, lk)
    if lo_idx is None or hi_idx is None:
        return None
    if bias == "BULLISH" and hi_idx > lo_idx:
        return (lows[lo_idx], highs[hi_idx])
    if bias == "BEARISH" and lo_idx > hi_idx:
        return (lows[lo_idx], highs[hi_idx])
    return None
