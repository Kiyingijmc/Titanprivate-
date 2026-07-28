#!/usr/bin/env python3
"""Candidate-universe screen for SilverBullet v14.4.2.

Reuses scripts/poc_sb_stops.py (the 2026-07-11 stop-study harness) unchanged:
same signal collection, ATR10 stop model, ratchet+runner replay, cost model.
Applies the study's a-priori economic screen (median round-trip cost <= 0.25R)
plus net expectancy at 1x/1.5x/2x spread stress and a 70/30 chronological OOS
split per symbol.

Spreads below were measured live over the HTTP bridge on 2026-07-28 (median of
6 samples, evening session) in ticks/points — same units as the study table.
"""
import json
import os
import sys

import numpy as np

REPO = "/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.chdir(REPO)

import poc_sb_stops as poc  # noqa: E402

# candidate -> measured spread in ticks (spread_points, 2026-07-28 sampling)
CAND_SPREADS = {
    "USDCHF": 9, "NZDUSD": 12, "EURJPY": 13, "EURGBP": 10,
    "XAGUSD": 33, "US100": 200, "ETHUSD": 193, "XTIUSD": 2,
}
CAND_SPECS = {
    "USDCHF": {"tick_value": 1.2215, "tick_size": 1e-05},
    "NZDUSD": {"tick_value": 1.0,    "tick_size": 1e-05},
    "EURJPY": {"tick_value": 0.6104, "tick_size": 0.001},
    "EURGBP": {"tick_value": 1.3292, "tick_size": 1e-05},
    "XAGUSD": {"tick_value": 5.0,    "tick_size": 0.001},
    "US100":  {"tick_value": 0.1,    "tick_size": 0.01},
    "ETHUSD": {"tick_value": 0.1,    "tick_size": 0.01},
    "XTIUSD": {"tick_value": 10.0,   "tick_size": 0.01},
}
SCREEN_MAX_COST_R = 0.25
MODEL = "ATR10"
TF = "H1"

poc.SPREADS.update(CAND_SPREADS)

with open("data/specs.json") as f:
    specs = json.load(f)
specs.update(CAND_SPECS)


def screen(sym):
    signals, bars = poc.collect_signals(sym, tf=TF)
    if signals is None:
        return {"sym": sym, "error": "no data file"}
    trades = poc.resolve(signals, bars, MODEL)
    for t in trades:
        t["sym"] = sym
    if not trades:
        return {"sym": sym, "error": "no resolved trades"}

    costs = [poc.cost_r(t, sym, specs) for t in trades]
    med_cost = float(np.median(costs))

    # managed replay: v14.4.2 ratchet + runner (arm off == replay_managed runner)
    for t in trades:
        t["_managed_r"], _ = poc.replay_overlay(t, bars, arm="off")

    row = {"sym": sym, "n": len(trades), "med_cost_r": med_cost,
           "screen_pass": med_cost <= SCREEN_MAX_COST_R}
    for mult, key in [(1.0, "net1x"), (1.5, "net15x"), (2.0, "net2x")]:
        nets = [t["_managed_r"] - poc.cost_r(t, sym, specs, mult) for t in trades]
        m = poc.metrics(nets)
        row[key] = {"exp": m["exp"], "pf": m["pf"], "totR": m["totR"]}
    # 70/30 chronological OOS on net 1x managed
    ts = sorted(trades, key=lambda t: t["time"])
    nets = [t["_managed_r"] - poc.cost_r(t, sym, specs) for t in ts]
    k = int(len(nets) * 0.7)
    row["train"] = poc.metrics(nets[:k])
    row["test"] = poc.metrics(nets[k:])
    yrs = sorted({t["year"] for t in ts})
    row["yearly"] = {
        y: poc.metrics([t["_managed_r"] - poc.cost_r(t, sym, specs)
                        for t in ts if t["year"] == y]) for y in yrs}
    return row


def main():
    syms = sys.argv[1:] or list(CAND_SPREADS)
    rows = []
    for s in syms:
        print(f"[screen] {s} ...", flush=True)
        rows.append(screen(s))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "candidate_screen.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    print(f"[screen] wrote {out}\n", flush=True)

    hdr = (f"{'sym':8}{'n':>6}{'medCost':>9}{'screen':>8}"
           f"{'exp1x':>8}{'exp1.5x':>9}{'exp2x':>8}{'PF1x':>7}"
           f"{'OOSn':>6}{'OOSexp':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if "error" in r:
            print(f"{r['sym']:8}  ERROR: {r['error']}")
            continue
        print(f"{r['sym']:8}{r['n']:>6}{r['med_cost_r']:>9.3f}"
              f"{('PASS' if r['screen_pass'] else 'FAIL'):>8}"
              f"{r['net1x']['exp']:>+8.3f}{r['net15x']['exp']:>+9.3f}"
              f"{r['net2x']['exp']:>+8.3f}{r['net1x']['pf']:>7.2f}"
              f"{r['test']['n']:>6}{r['test']['exp']:>+8.3f}")


if __name__ == "__main__":
    main()
