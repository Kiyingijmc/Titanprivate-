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


FIB_LO, FIB_HI = 0.5, 0.705  # a-priori discount/premium band (NOT swept)


def confirmed_entry(bar, leg, bias, lo=FIB_LO, hi=FIB_HI):
    """A just-closed 5m bar triggers entry if it tagged the fib zone AND closed back in the
    trend direction (a resumption candle). Never a passive limit at the level (limits get
    wicked / expire -- the OTE failure mode)."""
    leg_low, leg_high = leg
    rng = leg_high - leg_low
    if rng <= 0:
        return False
    if bias == "BULLISH":
        z_hi = leg_high - lo * rng    # shallow (0.5) retrace
        z_lo = leg_high - hi * rng    # deep (0.705) retrace
        tagged = bar["low"] <= z_hi
        held = bar["close"] >= z_lo
        resume = bar["close"] > bar["open"]
        return tagged and held and resume
    if bias == "BEARISH":
        z_lo = leg_low + lo * rng
        z_hi = leg_low + hi * rng
        tagged = bar["high"] >= z_lo
        held = bar["close"] <= z_hi
        resume = bar["close"] < bar["open"]
        return tagged and held and resume
    return False


def build_signals(m5_df, bias_list, atr1h, lk=5, rr=2.5):
    """Scan 5m bars; on a confirmed pullback entry in the trend direction, emit a signal:
    entry at the NEXT bar open, structural stop = 1.0xATR(1H), fixed target = rr*risk.
    Carries 'risk' and 'atr' for the partial/trail exit. One signal per qualifying bar;
    concurrency (one-open-per-symbol) is enforced by the exit simulators."""
    highs = list(m5_df["high"].values)
    lows = list(m5_df["low"].values)
    recs = m5_df[["open", "high", "low", "close"]].to_dict("records")
    n = len(recs)
    sigs = []
    for i in range(lk + 1, n - 1):
        bias = bias_list[i]
        if bias == "NEUTRAL":
            continue
        a = atr1h[i]
        if not (a > 0):
            continue
        leg = impulse_leg(highs, lows, i, lk, bias)
        if leg is None:
            continue
        if not confirmed_entry(recs[i], leg, bias):
            continue
        entry = recs[i + 1]["open"]
        risk = 1.0 * a
        if bias == "BULLISH":
            sl, tp, d = entry - risk, entry + rr * risk, "BUY"
        else:
            sl, tp, d = entry + risk, entry - rr * risk, "SELL"
        sigs.append({"bar_idx": i + 1, "dir": d, "cmd": "MARKET", "entry": entry,
                     "sl": sl, "tp": tp, "risk": risk, "atr": a, "ttl_bars": 1})
    return sigs


def simulate_partial_trail(sigs, bars, trail_mult=2.0):
    """Exit model (b): book HALF at +1R and move the stop to break-even, then TRAIL the
    remaining half by trail_mult*ATR(1H) off the running extreme; exit when the stop is hit.
    One open position per symbol (later signals during a live trade are skipped). Same-bar
    stop+target -> stop wins (conservative). Returns trade dicts with blended R + outcome."""
    trades = []
    busy_until = -1
    n = len(bars)
    for sig in sigs:
        b0 = sig["bar_idx"]
        if b0 <= busy_until or b0 >= n:
            continue
        is_long = sig["dir"] == "BUY"
        E, S, risk = sig["entry"], sig["sl"], sig["risk"]
        trail_dist = trail_mult * sig["atr"]
        one_r = E + risk if is_long else E - risk
        partialed = False
        stop = S
        extreme = bars[b0]["high"] if is_long else bars[b0]["low"]
        r_total, exit_idx = None, b0
        for j in range(b0, n):
            bar = bars[j]
            extreme = max(extreme, bar["high"]) if is_long else min(extreme, bar["low"])
            hit = (bar["low"] <= stop) if is_long else (bar["high"] >= stop)
            if hit:
                exit_r = (stop - E) / risk if is_long else (E - stop) / risk
                r_total = (0.5 * 1.0 + 0.5 * exit_r) if partialed else exit_r
                exit_idx = j
                break
            if not partialed:
                reached = (bar["high"] >= one_r) if is_long else (bar["low"] <= one_r)
                if reached:
                    partialed = True
                    stop = E  # break-even on the remainder
            if partialed:
                t_stop = (extreme - trail_dist) if is_long else (extreme + trail_dist)
                stop = max(stop, t_stop) if is_long else min(stop, t_stop)
        if r_total is None:  # never resolved -> mark out at last close
            px = bars[n - 1]["close"]
            exit_r = (px - E) / risk if is_long else (E - px) / risk
            r_total = (0.5 * 1.0 + 0.5 * exit_r) if partialed else exit_r
            exit_idx = n - 1
        trades.append({**sig, "r": r_total, "entry_idx": b0, "exit_idx": exit_idx,
                       "outcome": "TP" if r_total > 0 else "SL"})
        busy_until = exit_idx
    return trades
