#!/usr/bin/env python3
"""Diagnostic 2, horizon sweep -- one pass, several horizons.

Fixes two things about the first attempt:
  * a single arbitrary horizon truncated 27.5% of OTE trades, understating reach
  * it also asks whether the screen is independent of Diagnostic 1 at all

Reports P(MFE >= RR + cost) against breakeven 1/(1+RR), per horizon, plus the
realized fixed-exit win rate for comparison.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

COST = 0.11


def mfe_series(h, l, fill, entry, risk, is_long, horizons):
    """MFE in R at each horizon, no stop, no target, exits never consulted."""
    out = []
    n = len(h)
    for hz in horizons:
        end = min(fill + hz, n - 1) if hz else n - 1
        if end < fill:
            out.append(0.0); continue
        m = (h[fill:end + 1].max() - entry) if is_long else (entry - l[fill:end + 1].min())
        out.append(m / risk)
    return out


def run_ote(horizons):
    df = pd.read_csv("data/history/ote_canonical_trades.csv")
    df = df[df.sym != "XBRUSD"]
    rows = []
    for sym, d in df.groupby("sym"):
        m5 = pd.read_csv(f"data/history/{sym}_M5.csv")
        h, l = m5["high"].values, m5["low"].values
        for _, t in d.iterrows():
            rows.append(mfe_series(h, l, int(t.fill_idx), t.entry, t.risk,
                                   t.dir == "BUY", horizons))
    return np.array(rows), 2.5, 100.0 * (df.r > 0).mean()


def run_sb(horizons):
    from scripts.poc_sb_stops import collect_signals, resolve
    rows, wins, n = [], 0, 0
    for sym in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
                "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]:
        sigs, bars = collect_signals(sym, tf="H1")
        if sigs is None:
            continue
        h, l = bars["high"], bars["low"]
        for t in resolve(sigs, bars, "ATR10"):
            rows.append(mfe_series(h, l, int(t["fill_idx"]), t["entry"],
                                   t["risk"], t["dir"] == "BUY", horizons))
            wins += 1 if t["r"] > 0 else 0
            n += 1
    return np.array(rows), 2.0, 100.0 * wins / n


def report(name, mfe, rr, winpct, horizons, unit):
    need, be = rr + COST, 100.0 / (1.0 + rr)
    print(f"\n{name}   n={len(mfe)}   RR {rr}   need {need:.2f}R   "
          f"breakeven {be:.1f}%   realized win {winpct:.1f}%")
    print(f"  {'horizon':>12} {'median MFE':>11} {'reach%':>8} {'vs BE':>8}  verdict")
    for i, hz in enumerate(horizons):
        col = mfe[:, i]
        reach = 100.0 * (col >= need).mean()
        lbl = f"{hz} {unit}" if hz else "unbounded"
        print(f"  {lbl:>12} {np.median(col):>10.2f}R {reach:>7.1f}% "
              f"{reach - be:>+7.1f}  {'PASS' if reach >= be else 'FAIL'}")
    col = mfe[:, -1]
    reach = 100.0 * (col >= need).mean()
    print(f"  stop-out drag (unbounded reach - realized win) = "
          f"{reach - winpct:+.1f}pp")


if __name__ == "__main__":
    H_M5 = [144, 288, 576, None]
    H_H1 = [12, 24, 48, None]
    print("=" * 78)
    print("DIAGNOSTIC 2 -- REACH SCREEN, HORIZON SWEEP")
    print("=" * 78)
    m, rr, w = run_ote(H_M5)
    report("OTE canonical (NO-GO, -0.158R)", m, rr, w, H_M5, "M5")
    m, rr, w = run_sb(H_H1)
    report("SilverBullet H1/ATR10 (LIVE, +0.109R)", m, rr, w, H_H1, "H1")
