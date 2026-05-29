#!/usr/bin/env python3
# H4 trend-following proof-of-concept (Donchian breakout, structural 2xATR stop).
# Screens net-of-cost, out-of-sample edge across instruments. NOT a live strategy.
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "tests", "backtest"))
import backtest_engine as bt  # noqa: E402


def resample_h4(m5_df):
    df = m5_df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    h4 = df.resample("4h").agg({"open": "first", "high": "max",
                                "low": "min", "close": "last"}).dropna()
    return h4.reset_index()


def atr_series(h4, period=14):
    h, l, c = h4["high"], h4["low"], h4["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def donchian_signals(h4, n=20):
    highs = h4["high"].values
    lows = h4["low"].values
    closes = h4["close"].values
    out = []
    for i in range(n, len(h4)):
        upper = highs[i - n:i].max()
        lower = lows[i - n:i].min()
        if closes[i] > upper:
            out.append((i, "LONG"))
        elif closes[i] < lower:
            out.append((i, "SHORT"))
    return out


def simulate_flip(signals, bars, atrs, stop_mult=2.0):
    """Signal-flip trend sim: enter at next-bar open on a breakout; exit at -1R if the
    structural stop is hit, else at the bar where the opposite signal fires. One position
    at a time. Returns trade dicts with entry/sl/r/outcome/entry_idx/exit_idx."""
    sig_at = dict(signals)
    trades = []
    pos = None
    n = len(bars)
    for i in range(n):
        b = bars[i]
        if pos:
            if pos["dir"] == "LONG" and b["low"] <= pos["sl"]:
                trades.append({**pos, "exit_idx": i, "r": -1.0, "outcome": "SL"}); pos = None
            elif pos["dir"] == "SHORT" and b["high"] >= pos["sl"]:
                trades.append({**pos, "exit_idx": i, "r": -1.0, "outcome": "SL"}); pos = None
        s = sig_at.get(i)
        if s:
            if pos and s != pos["dir"]:
                px = b["close"]
                r = ((px - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - px)) / pos["risk"]
                trades.append({**pos, "exit_idx": i, "r": r, "outcome": "FLIP"}); pos = None
            if pos is None and i + 1 < n:
                entry = bars[i + 1]["open"]
                risk = stop_mult * atrs[i]
                if risk > 0:
                    sl = entry - risk if s == "LONG" else entry + risk
                    pos = {"dir": s, "entry": entry, "sl": sl, "risk": risk, "entry_idx": i + 1}
    return trades


def net_r_after_costs(r, entry, sl, spread_price, tick_size, tick_value, comm_rt=14.0):
    """R net of cost: 2x spread crossing (fraction of the stop) + round-turn commission in R."""
    stop = abs(entry - sl)
    if stop <= 0:
        return r
    money_per_lot = (stop / tick_size) * tick_value
    cost = 2 * spread_price / stop + (comm_rt / money_per_lot if money_per_lot > 0 else 0.0)
    return r - cost
