#!/usr/bin/env python3
"""Diagnostic 2 -- reach screen, run as a CALIBRATION test.

The proposal: measure max favourable excursion (MFE) from the signal and compare
its median against what the trade structure needs. A screen is only useful if it
separates a known-dead model from a known-good one, so this runs BOTH:

  OTE canonical  -- gated NO-GO, -0.158R net managed  (should FAIL the screen)
  SilverBullet   -- the live survivor, +0.109R        (should PASS)

MFE is measured from the ENTRY in units of R (risk = |entry - sl|), so the
required reach to hit a fixed-RR target is exactly RR, not (1+RR). See notes.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


HORIZON_H1 = 12          # the TTL both models use
HORIZON_M5 = 12 * 12     # same wall-clock on OTE's M5 index


def mfe_r(bars_h, bars_l, fill, exit_k, entry, risk, is_long, horizon=None):
    """Max favourable excursion in R from entry.

    horizon=None reproduces the exit-bounded version (which collapses to the
    win rate). An integer horizon is the TRUE screen: a fixed bar count,
    no stop, no target, exit logic never consulted.
    """
    end = exit_k if horizon is None else min(fill + horizon, len(bars_h) - 1)
    if end < fill:
        return 0.0
    if is_long:
        return (bars_h[fill:end + 1].max() - entry) / risk
    return (entry - bars_l[fill:end + 1].min()) / risk


def screen_ote():
    df = pd.read_csv("data/history/ote_canonical_trades.csv")
    df = df[df.sym != "XBRUSD"]                     # cost screen
    rows = []
    for sym, d in df.groupby("sym"):
        m5 = pd.read_csv(f"data/history/{sym}_M5.csv")
        h, l = m5["high"].values, m5["low"].values
        for _, t in d.iterrows():
            rows.append(mfe_r(h, l, int(t.fill_idx), int(t.exit_idx),
                              t.entry, t.risk, t.dir == "BUY", HORIZON_M5))
    return np.array(rows), 2.5


def screen_sb():
    """SilverBullet H1/ATR10 -- rebuilt with the study's own rig."""
    from scripts.poc_sb_stops import collect_signals, resolve
    out = []
    for sym in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
                "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]:
        sigs, bars = collect_signals(sym, tf="H1")
        if sigs is None:
            continue
        h, l = bars["high"], bars["low"]
        for t in resolve(sigs, bars, "ATR10"):
            out.append(mfe_r(h, l, int(t["fill_idx"]), int(t["exit_idx"]),
                             t["entry"], t["risk"], t["dir"] == "BUY", HORIZON_H1))
    return np.array(out), 2.0


def report(name, mfe, rr, cost_r=0.11):
    need = rr + cost_r            # reach required from entry, in R
    q = np.percentile(mfe, [25, 50, 75, 90])
    print(f"\n{name}  n={len(mfe)}")
    print(f"  MFE from entry (R):  p25 {q[0]:.2f}  median {q[1]:.2f}  "
          f"p75 {q[2]:.2f}  p90 {q[3]:.2f}")
    print(f"  required reach = RR {rr} + cost {cost_r} = {need:.2f}R")
    print(f"  median / required   = {q[1] / need:.2f}   "
          f"({'PASS' if q[1] >= need else 'FAIL'})")
    reach = 100.0 * (mfe >= need).mean()
    be = 100.0 / (1.0 + rr)
    print(f"  share reaching target: {reach:.1f}%   breakeven win {be:.1f}%   "
          f"-> {'PASS' if reach >= be else 'FAIL'} on exceedance")


if __name__ == "__main__":
    print("=" * 70)
    print("DIAGNOSTIC 2 -- REACH SCREEN (calibration: dead model vs live model)")
    print("=" * 70)
    m, rr = screen_ote()
    report("OTE canonical (NO-GO, -0.158R)", m, rr)
    m, rr = screen_sb()
    report("SilverBullet H1/ATR10 (LIVE, +0.109R)", m, rr)
