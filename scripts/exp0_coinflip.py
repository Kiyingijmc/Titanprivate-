#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/exp0_coinflip.py
# EXP-0 "Coin Flip" — the v14.4 ratchet on random entries (placebo study).
#
# Pre-registered: docs/research/2026-07-31-exp0-coinflip-preregistration.md
# Hypothesis under test: "the edge is the exit engine, not the entry"
# (audit 05-STRATEGY-ARSENAL §2). Placebo entries are matched per symbol to
# SilverBullet's marginals:
#   - candidate count (one placebo per real signal)
#   - hour-of-day, broker time (sampled from bars in the same hour)
#   - direction balance (the real signals' directions, shuffled)
#   - in-bar limit placement (the real signal's entry fraction of its bar range)
#   - stop geometry (the same stop_price() models on the placebo bar's ATR /
#     structure extreme)
# Fill mechanics (limit + TTL), exits (replay_managed) and costs (cost_r) are
# the SilverBullet stop study's own code: only the entry bar is random.
#
#   .venv/bin/python scripts/exp0_coinflip.py                    # full H1 run
#   .venv/bin/python scripts/exp0_coinflip.py --sym EURUSD --quick --reps 5
# ==============================================================================
import argparse
import json
import os
import sys
import time as _t

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.poc_sb_stops import (                              # noqa: E402
    SYMS, STOP_MODELS, collect_signals, resolve, replay_managed,
    cost_r, metrics,
)

MIN_BAR = 50                    # mirror collect_signals' sig_mask[:50] = False


# ---------------------------------------------------------------- generator
def _eligible_by_hour(bars):
    """Bar indices usable as placebo entry bars, bucketed by broker hour."""
    atr = np.asarray(bars["atr"], dtype=float)
    n = len(atr)
    ok = np.zeros(n, dtype=bool)
    ok[MIN_BAR:n - 1] = True
    ok &= np.nan_to_num(atr) > 0
    hours = pd.to_datetime(bars["times"]).hour.values
    by_hour = {h: np.where(ok & (hours == h))[0] for h in range(24)}
    by_hour = {h: idx for h, idx in by_hour.items() if len(idx)}
    return by_hour, np.where(ok)[0]


def gen_placebo_signals(signals, bars, seed):
    """One placebo per real signal, marginals matched, schema-identical."""
    rng = np.random.default_rng(seed)
    by_hour, all_ok = _eligible_by_hour(bars)
    if len(all_ok) == 0:
        return []
    highs = np.asarray(bars["high"], dtype=float)
    lows = np.asarray(bars["low"], dtype=float)
    atr = np.asarray(bars["atr"], dtype=float)
    times = pd.to_datetime(bars["times"])

    dirs = [signals[k]["dir"] for k in rng.permutation(len(signals))]
    placebo = []
    for i, sig in enumerate(signals):
        pool = by_hour.get(sig["hour"], all_ok)
        j = int(pool[rng.integers(len(pool))])
        span = sig["sig_high"] - sig["sig_low"]
        frac = 0.5 if span <= 0 else min(1.0, max(0.0, (sig["entry"] - sig["sig_low"]) / span))
        entry = float(lows[j] + frac * (highs[j] - lows[j]))
        d = dirs[i]
        t = pd.Timestamp(times[j])
        placebo.append({
            "bar_idx": j, "time": t, "dir": d, "entry": entry,
            "far_extreme": float(highs[j - 2] if d == "SELL" else lows[j - 2]),
            "sig_high": float(highs[j]), "sig_low": float(lows[j]),
            "atr": float(atr[j]), "body_atr": float(sig["body_atr"]),
            "bias": "NEUTRAL", "liq_status": "",
            "hour": int(t.hour), "year": int(t.year),
        })
    placebo.sort(key=lambda p: p["bar_idx"])
    return placebo


# ---------------------------------------------------------------- experiment
ARMS = ["FIXED 2R", "RATCHET", "RATCHET+RUNNER"]


def arm_nets(trades, bars_by_sym, specs, spread_mult=1.0):
    """Per-arm net-R lists for resolved trades, time-ordered (study convention)."""
    ts = sorted(trades, key=lambda t: t["time"])
    out = {}
    costs = [cost_r(t, t["sym"], specs, spread_mult) for t in ts]
    out["FIXED 2R"] = [t["r"] - c for t, c in zip(ts, costs)]
    out["RATCHET"] = [replay_managed(t, bars_by_sym[t["sym"]]) - c
                      for t, c in zip(ts, costs)]
    out["RATCHET+RUNNER"] = [replay_managed(t, bars_by_sym[t["sym"]], runner=True) - c
                             for t, c in zip(ts, costs)]
    return out


def run_rep(signals_by_sym, bars_by_sym, specs, model, seed):
    trades = []
    for sym, signals in signals_by_sym.items():
        placebo = gen_placebo_signals(signals, bars_by_sym[sym], seed)
        for t in resolve(placebo, bars_by_sym[sym], model):
            t["sym"] = sym
            trades.append(t)
    return arm_nets(trades, bars_by_sym, specs)


def fmt(m):
    return (f"n={m['n']:5d} exp={m['exp']:+.3f}R totR={m['totR']:+7.1f} "
            f"PF={m['pf']:4.2f} DD={m['dd']:.0f}R win={m['winpct']:.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--tf", default="H1", choices=["M5", "M15", "H1"])
    ap.add_argument("--model", default="ATR10", choices=STOP_MODELS)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    syms = [a.sym] if a.sym else SYMS
    if a.out is None:
        a.out = f"data/results/exp0_coinflip/reps_{a.tf}_{a.model}.csv"
    print(f"### EXP-0 Coin Flip — tf={a.tf} model={a.model} "
          f"reps={a.reps} seed={a.seed} ###\n", flush=True)

    with open("data/specs.json") as f:
        specs = json.load(f)

    signals_by_sym, bars_by_sym = {}, {}
    for sym in syms:
        t0 = _t.time()
        signals, bars = collect_signals(sym, quick=a.quick, tf=a.tf)
        if signals is None:
            print(f"[SKIP] {sym}: no data file")
            continue
        signals_by_sym[sym] = signals
        bars_by_sym[sym] = bars
        print(f"[{sym}] {len(signals)} real signals  ({_t.time()-t0:.0f}s)",
              flush=True)
    if not signals_by_sym:
        print("No data.")
        return

    # ---- real SilverBullet arms (the two known cells of the 2x2)
    real_trades = []
    for sym, signals in signals_by_sym.items():
        for t in resolve(signals, bars_by_sym[sym], a.model):
            t["sym"] = sym
            real_trades.append(t)
    real = {arm: metrics(nets)
            for arm, nets in arm_nets(real_trades, bars_by_sym, specs).items()}
    print("\n" + "=" * 78)
    print(f"REAL SILVERBULLET (model={a.model}, NET 1x)")
    print("=" * 78)
    for arm in ARMS:
        print(f"  {arm:16} {fmt(real[arm])}")

    # ---- placebo replications
    rep_rows = []
    for rep in range(a.reps):
        nets = run_rep(signals_by_sym, bars_by_sym, specs, a.model, a.seed + rep)
        for arm in ARMS:
            m = metrics(nets[arm])
            rep_rows.append({"rep": rep, "seed": a.seed + rep, "arm": arm, **m})
        print(f"[rep {rep:2d}] " + "  ".join(
            f"{arm.split()[0]}:{metrics(nets[arm])['exp']:+.3f}R" for arm in ARMS),
            flush=True)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    df = pd.DataFrame(rep_rows)
    df.to_csv(a.out, index=False)
    print(f"\n[CSV] {len(df)} rep-arm rows -> {a.out}")

    print("\n" + "=" * 78)
    print(f"PLACEBO DISTRIBUTION over {a.reps} reps (pooled net exp per rep)")
    print("=" * 78)
    for arm in ARMS:
        e = df[df["arm"] == arm]["exp"].values
        share_pos = float((e > 0).mean())
        share_ge_real = float((e >= real[arm]["exp"]).mean())
        print(f"  {arm:16} mean={e.mean():+.3f}R sd={e.std():.3f} "
              f"p5={np.percentile(e, 5):+.3f} p95={np.percentile(e, 95):+.3f} "
              f"reps>0: {share_pos:.0%}  reps>=real: {share_ge_real:.0%}")

    # ---- pre-registered interpretation (runner arm)
    e = df[df["arm"] == "RATCHET+RUNNER"]["exp"].values
    mu, p5 = float(e.mean()), float(np.percentile(e, 5))
    print("\n" + "=" * 78)
    print("PRE-REGISTERED INTERPRETATION (RATCHET+RUNNER placebo arm)")
    print("=" * 78)
    if mu <= -0.05:
        verdict = ("OUTCOME 1: random+ratchet is clearly negative. The ratchet is a "
                   "skew transform that needs a real signal; the SB entry does "
                   "genuine work. Proceed with the arsenal as designed.")
    elif mu < 0.05:
        verdict = ("OUTCOME 2: random+ratchet ~ 0. The ratchet neutralises cost "
                   "drag but adds no alpha alone; the entry carries the edge. "
                   "Healthy result.")
    elif p5 > 0:
        verdict = ("OUTCOME 3: random+ratchet is positive and robust across reps. "
                   "ENTRIES ARE DECORATION — pivot the research programme to "
                   "exit-engine parameterisation (arsenal §2, third row).")
    else:
        verdict = ("INCONCLUSIVE: positive mean but p5 <= 0 — not robust across "
                   "reps. Increase --reps and inspect per-year slices before "
                   "claiming outcome 3.")
    print(verdict)
    print("\n[DONE]")


if __name__ == "__main__":
    main()
