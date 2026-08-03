#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/exp1_mss_ablation.py
# EXP-1 "MSS ablation": does M5 MSS confirmation subtract value from an entry
# stream that already clears costs?
#
# Pre-registration: docs/research/2026-08-03-exp1-mss-ablation-preregistration.md
# (frozen arms, two anchoring variants, dual-exit gate, power floor). The
# one-pass rule forbids tuning anything below after the first gate run.
#
# Arm A (control) = the adopted v14.4.2 SilverBullet config, unmodified, via
# scripts/poc_sb_stops.py. Arm B (treated) = the same signals, but entry waits
# for an M5 MSS after the zone touch and then takes MARKET at the next M5 open,
# using the identical mss_confirm/LK_M5=2 definition the OTE, Unicorn and CRT
# gates used (src/analysis/ict_structure.py).
#
#   .venv/bin/python scripts/exp1_mss_ablation.py --fidelity     # arm-A precondition
#   .venv/bin/python scripts/exp1_mss_ablation.py --golden --sym XAUUSD \
#       --start 2026-03-01 --end 2026-03-31                      # hand-check log
#   .venv/bin/python scripts/exp1_mss_ablation.py                # the gate run
# ==============================================================================
import argparse
import json
import os
import sys
import time as _t

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.analysis.ict_structure import (                          # noqa: E402
    precompute_last_swings, mss_confirm,
)
from scripts.poc_sb_stops import (                                # noqa: E402
    SYMS, RR, TTL_BARS, collect_signals, resolve, stop_price,
    replay_managed, cost_r, metrics,
)

# ---- Frozen parameters (pre-registration; do not tune) ----------------------
TF = "H1"
MODEL = "ATR10"
LK_M5 = 2                   # identical to poc_ict_revival.py:47
BOOT_N = 10000
BOOT_SEED = 11
VARIANTS = ("B1", "B2")     # B1 stop-anchored, B2 R-anchored
EXITS = ("FIXED", "RUNNER")

# Registered arm-A fidelity targets (EXP-0 reproduced these to 3 decimals).
FIDELITY = {"n": 2217, "FIXED": -0.122, "RATCHET": 0.087, "RUNNER": 0.109}

# Registered power floor.
N_CONFIRMATORY = 500
N_DIRECTIONAL = 300

SKIP_REASONS = ("NO_TOUCH", "NO_MSS", "NO_ENTRY_BAR", "B1_STOP_CROSSED",
                "ZERO_RISK", "UNRESOLVED")


# ---------------------------------------------------------------- M5 loading
def load_m5(sym, quick=False):
    """The same M5 frame collect_signals() resampled from — same truncation."""
    path = f"data/history/{sym}_M5.csv"
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    return df.rename(columns={"datetime": "time"})


def m5_subrange(h1_times, m5_times, j):
    """[lo, hi) M5 index range belonging to H1 bar j. The next H1 bar's open
    time is the exclusive bound; data gaps contain no M5 bars by construction."""
    lo = int(np.searchsorted(m5_times, h1_times[j], side="left"))
    if j + 1 < len(h1_times):
        hi = int(np.searchsorted(m5_times, h1_times[j + 1], side="left"))
    else:
        hi = len(m5_times)
    return lo, hi


# ---------------------------------------------------------------- arm-B parts
def find_touch(m5_l, m5_h, lo, hi, entry):
    """First M5 bar in [lo, hi) whose range contains `entry`. None if the H1
    bar's extremes bracket the entry but no single M5 bar spans it (gap)."""
    for k in range(lo, hi):
        if m5_l[k] <= entry <= m5_h[k]:
            return k
    return None


def find_mss(m5_h, m5_l, m5_c, k0, k_end, bias, last_swh, last_swl):
    """First M5 bar in [k0, k_end) confirming a structure shift toward `bias`."""
    for k in range(k0, min(k_end, len(m5_c))):
        if mss_confirm(m5_h, m5_l, m5_c, k, bias, last_swh, last_swl):
            return k
    return None


def build_variant(variant, sig, tr_a, entry_b):
    """Arm-B geometry under one registered anchoring. None => pair is dropped.

    B1 (stop-anchored): SL price frozen at arm A's; risk and TP float.
    B2 (R-anchored):    risk frozen at 1.0*ATR(H1); SL and TP float.
    """
    is_long = sig["dir"] == "BUY"
    if variant == "B1":
        sl = tr_a["sl"]
        # A confirmation that only prints after price has already run through
        # the control's stop has no coherent stop-anchored counterfactual.
        if (is_long and entry_b <= sl) or (not is_long and entry_b >= sl):
            return None, "B1_STOP_CROSSED"
        risk = abs(entry_b - sl)
    else:
        risk = 1.0 * float(sig["atr"])
        sl = (entry_b - risk) if is_long else (entry_b + risk)
    if risk <= 0:
        return None, "ZERO_RISK"
    tp = entry_b + RR * risk if is_long else entry_b - RR * risk
    return {"entry": entry_b, "sl": sl, "tp": tp, "risk": risk,
            "dir": sig["dir"]}, None


def resolve_from(bars, j, entry, sl, tp, is_long):
    """Arm A's exact bar-path convention (same-bar SL-first, pessimistic),
    started at the H1 bar that contains arm B's market entry. Arm A starts at
    its own fill bar the same way, so neither arm is advantaged."""
    highs, lows = bars["high"], bars["low"]
    for k in range(j, len(highs)):
        sl_hit = (lows[k] <= sl) if is_long else (highs[k] >= sl)
        tp_hit = (highs[k] >= tp) if is_long else (lows[k] <= tp)
        if sl_hit:
            return "SL", -1.0, k
        if tp_hit:
            return "TP", RR, k
    return "OPEN", 0.0, len(highs) - 1


# ---------------------------------------------------------------- pairing
def counterfactual(sig, tr_a, bars, m5, last_swh, last_swl):
    """One arm-A trade -> its arm-B counterfactual under both anchorings.

    Returns (pair_dict, None) or (None, reason). A pair is kept only when BOTH
    variants resolve, so all four gate cells are read on an identical set.
    """
    h1_times = bars["times"]
    m5_times = m5["_t"]
    lo, hi = m5_subrange(h1_times, m5_times, tr_a["fill_idx"])
    k_touch = find_touch(m5["low"], m5["high"], lo, hi, tr_a["entry"])
    if k_touch is None:
        return None, "NO_TOUCH"

    j_end = min(sig["bar_idx"] + TTL_BARS, len(h1_times) - 1)
    _, k_end = m5_subrange(h1_times, m5_times, j_end)
    bias = "BULLISH" if sig["dir"] == "BUY" else "BEARISH"
    k_mss = find_mss(m5["high"], m5["low"], m5["close"],
                     k_touch, k_end, bias, last_swh, last_swl)
    if k_mss is None:
        return None, "NO_MSS"

    k_entry = k_mss + 1
    if k_entry >= len(m5_times):
        return None, "NO_ENTRY_BAR"
    entry_b = float(m5["open"][k_entry])
    j_b = int(np.searchsorted(h1_times, m5_times[k_entry], side="right")) - 1
    if j_b < 0:
        return None, "NO_ENTRY_BAR"

    is_long = sig["dir"] == "BUY"
    legs = {}
    for v in VARIANTS:
        geom, reason = build_variant(v, sig, tr_a, entry_b)
        if geom is None:
            return None, reason
        outcome, r, exit_k = resolve_from(bars, j_b, geom["entry"],
                                          geom["sl"], geom["tp"], is_long)
        if outcome == "OPEN":
            return None, "UNRESOLVED"
        legs[v] = {**geom, "fill_idx": j_b, "outcome": outcome, "r": r,
                   "exit_idx": exit_k}

    return {
        "sym": sig["sym"], "time": sig["time"], "dir": sig["dir"],
        "year": sig["year"], "hour": sig["hour"],
        "k_touch": k_touch, "k_mss": k_mss, "k_entry": k_entry,
        "bars_to_mss": k_mss - k_touch,
        "entry_a": tr_a["entry"], "entry_b": entry_b,
        # The mechanism in H1(a), SIGNED: how much of the leg confirmation
        # surrenders, priced in arm-A R. Positive = arm B entered at a WORSE
        # price (leg given up, the hypothesised cost); negative = confirmation
        # bought the dip / sold the rally and got a BETTER price. An unsigned
        # magnitude would score both as "cost" and could not measure H1(a).
        "first_leg_r": ((entry_b - tr_a["entry"]) if is_long
                        else (tr_a["entry"] - entry_b)) / tr_a["risk"],
        "a": tr_a, "b": legs,
    }, None


# ---------------------------------------------------------------- arm metrics
def net_r(tr, sym, specs, exit_model, bars, spread_mult=1.0):
    gross = tr["r"] if exit_model == "FIXED" else replay_managed(
        tr, bars, runner=(exit_model == "RUNNER"))
    return gross - cost_r(tr, sym, specs, spread_mult)


def paired_bootstrap(deltas, n=BOOT_N, seed=BOOT_SEED):
    """Percentile CI on the mean paired difference. Resamples pairs, not arms."""
    if not deltas:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    arr = np.asarray(deltas, dtype=float)
    idx = rng.integers(0, len(arr), size=(n, len(arr)))
    means = arr[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def verdict(cells, n_paired):
    """The registered gate. All four cells must agree; anything else is
    INCONCLUSIVE by construction."""
    if n_paired < N_DIRECTIONAL:
        return "INCONCLUSIVE (n < 300 — registered stop; do not re-tune)"
    bands = set()
    for c in cells.values():
        d, (loq, hiq) = c["delta"], c["ci"]
        if d <= -0.05 and hiq < 0:
            bands.add("A")
        elif d >= 0.05 and loq > 0:
            bands.add("C")
        elif abs(d) < 0.05 or (loq <= 0 <= hiq):
            bands.add("B")
        else:
            bands.add("?")
    if len(bands) != 1 or "?" in bands:
        return "INCONCLUSIVE (cells disagree — MTF-PB v2 lesson; no claim)"
    band = bands.pop()
    label = {"A": "OUTCOME A — component confirmed costly",
             "B": "OUTCOME B — component neutral (H1 is dead)",
             "C": "OUTCOME C — component adds value (hypothesis inverted)"}[band]
    if n_paired < N_CONFIRMATORY:
        return f"{label} [DIRECTIONAL ONLY — n < 500, no permanent verdict]"
    return label


# ---------------------------------------------------------------- run
def build_symbol(sym, quick=False):
    """Arm A + the M5 scaffolding arm B needs. None if the symbol has no data."""
    got = collect_signals(sym, quick=quick, tf=TF)
    if got[0] is None:
        return None
    signals, bars = got
    for s in signals:
        s["sym"] = sym
    trades = resolve(signals, bars, MODEL)
    for t in trades:
        t["sym"] = sym
    by_bar = {s["bar_idx"]: s for s in signals}

    df5 = load_m5(sym, quick=quick)
    m5 = {"open": df5["open"].values, "high": df5["high"].values,
          "low": df5["low"].values, "close": df5["close"].values,
          "_t": pd.to_datetime(df5["time"]).values}
    last_swh, last_swl = precompute_last_swings(
        list(m5["high"]), list(m5["low"]), LK_M5)
    return {"signals": by_bar, "bars": bars, "trades": trades, "m5": m5,
            "swh": last_swh, "swl": last_swl}


def run_fidelity(syms, specs, quick):
    """Registered precondition: arm A must reproduce the stop study exactly."""
    rows = {"FIXED": [], "RATCHET": [], "RUNNER": []}
    for sym in syms:
        ctx = build_symbol(sym, quick)
        if ctx is None:
            print(f"[SKIP] {sym}: no data file")
            continue
        for t in ctx["trades"]:
            for em in rows:
                rows[em].append(net_r(t, sym, specs, em, ctx["bars"]))
        print(f"[{sym}] {len(ctx['trades'])} arm-A trades", flush=True)

    n = len(rows["FIXED"])
    print("\n" + "=" * 72)
    print("ARM-A FIDELITY CHECK (registered precondition)")
    print(f"  {'metric':<10} {'observed':>10} {'registered':>12}  {'':>4}")
    ok = (n == FIDELITY["n"])
    print(f"  {'n':<10} {n:>10} {FIDELITY['n']:>12}  {'OK' if ok else 'FAIL'}")
    for em in ("FIXED", "RATCHET", "RUNNER"):
        exp = sum(rows[em]) / len(rows[em]) if rows[em] else float("nan")
        hit = abs(round(exp, 3) - FIDELITY[em]) < 5e-4
        ok = ok and hit
        print(f"  {em:<10} {exp:>10.3f} {FIDELITY[em]:>12.3f}  "
              f"{'OK' if hit else 'FAIL'}")
    print("=" * 72)
    print("PRECONDITION MET — the gate run is authorised." if ok else
          "PRECONDITION FAILED — run is void; no verdict may be issued.")
    return ok


def run_golden(sym, start, end, specs, quick):
    """Per-pair event log for hand-verification against raw M5 data."""
    ctx = build_symbol(sym, quick)
    if ctx is None:
        print(f"no data for {sym}")
        return
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    shown = 0
    for tr in ctx["trades"]:
        ts = pd.Timestamp(tr["time"])
        if not (t0 <= ts <= t1):
            continue
        sig = ctx["signals"][tr["bar_idx"]]
        pair, reason = counterfactual(sig, tr, ctx["bars"], ctx["m5"],
                                      ctx["swh"], ctx["swl"])
        print("-" * 72)
        print(f"SIGNAL {ts} {tr['dir']}  H1 bar_idx={tr['bar_idx']} "
              f"atr={sig['atr']:.6f}")
        print(f"  ARM A  entry={tr['entry']:.6f} sl={tr['sl']:.6f} "
              f"tp={tr['tp']:.6f} risk={tr['risk']:.6f}")
        print(f"         fill H1 bar {tr['fill_idx']} "
              f"({pd.Timestamp(ctx['bars']['times'][tr['fill_idx']])}) "
              f"-> {tr['outcome']} r={tr['r']:+.2f}")
        if pair is None:
            print(f"  ARM B  dropped: {reason}")
            shown += 1
            continue
        m5t = ctx["m5"]["_t"]
        print(f"  touch  M5 bar {pair['k_touch']} ({pd.Timestamp(m5t[pair['k_touch']])})"
              f"  L={ctx['m5']['low'][pair['k_touch']]:.6f} "
              f"H={ctx['m5']['high'][pair['k_touch']]:.6f}")
        swi = (ctx["swh"] if tr["dir"] == "BUY" else ctx["swl"])[pair["k_mss"]]
        brk = (ctx["m5"]["high"] if tr["dir"] == "BUY" else ctx["m5"]["low"])[swi]
        print(f"  MSS    M5 bar {pair['k_mss']} ({pd.Timestamp(m5t[pair['k_mss']])})"
              f"  close={ctx['m5']['close'][pair['k_mss']]:.6f} breaks "
              f"swing@{swi} ({pd.Timestamp(m5t[swi])}) level={brk:.6f}")
        print(f"  entry  M5 bar {pair['k_entry']} "
              f"({pd.Timestamp(m5t[pair['k_entry']])}) open={pair['entry_b']:.6f}"
              f"  first_leg={pair['first_leg_r']:.3f}R")
        for v in VARIANTS:
            b = pair["b"][v]
            print(f"  ARM B {v}  entry={b['entry']:.6f} sl={b['sl']:.6f} "
                  f"tp={b['tp']:.6f} risk={b['risk']:.6f} -> {b['outcome']} "
                  f"r={b['r']:+.2f} (H1 fill bar {b['fill_idx']})")
        shown += 1
    print("-" * 72)
    print(f"{shown} arm-A trades in window.")


def run_gate(syms, specs, quick, out_dir):
    pairs, skips = [], {r: 0 for r in SKIP_REASONS}
    no_mss = []          # (sym, arm-A trade) — the ITT-eligible set
    n_arm_a = 0
    ctxs = {}
    for sym in syms:
        t0 = _t.time()
        ctx = build_symbol(sym, quick)
        if ctx is None:
            print(f"[SKIP] {sym}: no data file")
            continue
        ctxs[sym] = ctx
        kept = 0
        for tr in ctx["trades"]:
            n_arm_a += 1
            sig = ctx["signals"][tr["bar_idx"]]
            pair, reason = counterfactual(sig, tr, ctx["bars"], ctx["m5"],
                                          ctx["swh"], ctx["swl"])
            if pair is None:
                skips[reason] += 1
                if reason == "NO_MSS":
                    no_mss.append((sym, tr))
                continue
            pairs.append(pair)
            kept += 1
        print(f"[{sym}] arm-A {len(ctx['trades'])} -> {kept} paired "
              f"({_t.time() - t0:.0f}s)", flush=True)

    n = len(pairs)
    print("\n" + "=" * 78)
    print(f"FUNNEL  arm-A trades {n_arm_a}  ->  paired {n}")
    for r in SKIP_REASONS:
        if skips[r]:
            print(f"  dropped {r:<18} {skips[r]:>6}")

    if n == 0:
        print("No pairs — nothing to report.")
        return

    # ---- the four registered cells ----------------------------------------
    cells = {}
    for em in EXITS:
        for v in VARIANTS:
            deltas, a_net, b_net = [], [], []
            for p in pairs:
                bars = ctxs[p["sym"]]["bars"]
                na = net_r(p["a"], p["sym"], specs, em, bars)
                nb = net_r(p["b"][v], p["sym"], specs, em, bars)
                a_net.append(na); b_net.append(nb); deltas.append(nb - na)
            cells[(em, v)] = {
                "delta": float(np.mean(deltas)),
                "sd": float(np.std(deltas, ddof=1)) if n > 1 else float("nan"),
                "ci": paired_bootstrap(deltas),
                "a_exp": float(np.mean(a_net)), "b_exp": float(np.mean(b_net)),
                "deltas": deltas,
            }

    print("=" * 78)
    print("PRIMARY — paired difference  D = arm B - arm A  (net 1x, per trade)")
    print(f"  {'cell':<16} {'armA':>8} {'armB':>8} {'D':>9} "
          f"{'CI95':>20} {'sd(D)':>8}")
    for em in EXITS:
        for v in VARIANTS:
            c = cells[(em, v)]
            lo, hi = c["ci"]
            print(f"  {em + '/' + v:<16} {c['a_exp']:>8.3f} {c['b_exp']:>8.3f} "
                  f"{c['delta']:>+9.3f} {f'[{lo:+.3f}, {hi:+.3f}]':>20} "
                  f"{c['sd']:>8.3f}")

    print(f"\n  n_paired = {n}   "
          f"(registered: >={N_CONFIRMATORY} confirmatory, "
          f">={N_DIRECTIONAL} directional, else stop)")
    print(f"  VERDICT: {verdict(cells, n)}")

    # ---- reported, not gated ----------------------------------------------
    print("\n" + "=" * 78)
    print("REPORTED, NOT GATED")
    fired = n + skips["NO_MSS"]
    print(f"  MSS fire-rate           {100.0 * n / fired:.1f}%  "
          f"({n} of {fired} arm-A trades with a resolvable touch)")
    print(f"  bars touch->MSS         median {np.median([p['bars_to_mss'] for p in pairs]):.0f}"
          f"  mean {np.mean([p['bars_to_mss'] for p in pairs]):.1f}")
    fl = [p["first_leg_r"] for p in pairs]
    print(f"  first-leg (signed, +=worse entry)  median {np.median(fl):+.3f}R"
          f"  mean {np.mean(fl):+.3f}R"
          f"  adverse {100.0 * sum(1 for x in fl if x > 0) / n:.1f}%")
    wa = 100.0 * sum(1 for p in pairs if p["a"]["outcome"] == "TP") / n
    print(f"  win% (fixed-TP basis)   armA {wa:.1f}%", end="")
    for v in VARIANTS:
        wb = 100.0 * sum(1 for p in pairs if p["b"][v]["outcome"] == "TP") / n
        print(f"   armB/{v} {wb:.1f}%", end="")
    print()

    # ITT secondary (no-MSS pairs contribute 0R at no cost to arm B).
    print("\n  ITT secondary (no-MSS -> armB 0R; reported, cannot carry a verdict)")
    for em in EXITS:
        # A skipped trade forgoes exactly arm A's realized net on that trade.
        forgone = [-net_r(tr, sym, specs, em, ctxs[sym]["bars"])
                   for sym, tr in no_mss]
        for v in VARIANTS:
            c = cells[(em, v)]
            denom = n + len(no_mss)
            itt = (sum(c["deltas"]) + sum(forgone)) / denom if denom else 0.0
            print(f"    {em + '/' + v:<14} D_itt = {itt:+.3f}  (n={denom})")

    # x1.5 spread stress
    print("\n  x1.5 spread stress (D only)")
    for em in EXITS:
        for v in VARIANTS:
            ds = [net_r(p["b"][v], p["sym"], specs, em, ctxs[p["sym"]]["bars"], 1.5)
                  - net_r(p["a"], p["sym"], specs, em, ctxs[p["sym"]]["bars"], 1.5)
                  for p in pairs]
            print(f"    {em + '/' + v:<14} D = {np.mean(ds):+.3f}")

    # per-year / per-symbol on the primary cell
    prim = cells[("RUNNER", "B2")]
    print("\n  per-year D (RUNNER/B2)")
    for y in sorted({p["year"] for p in pairs}):
        d = [prim["deltas"][i] for i, p in enumerate(pairs) if p["year"] == y]
        print(f"    {y}  n={len(d):>5}  D={np.mean(d):+.3f}")
    print("\n  per-symbol D (RUNNER/B2)")
    for s in sorted({p["sym"] for p in pairs}):
        d = [prim["deltas"][i] for i, p in enumerate(pairs) if p["sym"] == s]
        print(f"    {s:<8} n={len(d):>5}  D={np.mean(d):+.3f}")

    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for i, p in enumerate(pairs):
        row = {k: p[k] for k in ("sym", "time", "dir", "year", "bars_to_mss",
                                 "entry_a", "entry_b", "first_leg_r")}
        row["a_outcome"] = p["a"]["outcome"]
        row["a_risk"] = p["a"]["risk"]
        for v in VARIANTS:
            row[f"{v}_outcome"] = p["b"][v]["outcome"]
            row[f"{v}_risk"] = p["b"][v]["risk"]
        for em in EXITS:
            for v in VARIANTS:
                row[f"d_{em}_{v}"] = cells[(em, v)]["deltas"][i]
        rows.append(row)
    out = os.path.join(out_dir, "pairs.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n[CSV] {len(rows)} pairs -> {out}")


def main():
    ap = argparse.ArgumentParser(description="EXP-1 MSS ablation")
    ap.add_argument("--fidelity", action="store_true",
                    help="arm-A reproduction check only (registered precondition)")
    ap.add_argument("--golden", action="store_true", help="per-pair event log")
    ap.add_argument("--sym", default=None)
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-03-31")
    ap.add_argument("--quick", action="store_true", help="tail 30k M5 bars (dev)")
    ap.add_argument("--out", default="data/results/exp1_mss_ablation")
    a = ap.parse_args()

    with open("data/specs.json") as f:
        specs = json.load(f)
    syms = [a.sym] if a.sym else SYMS

    if a.golden:
        run_golden(a.sym or "XAUUSD", a.start, a.end, specs, a.quick)
    elif a.fidelity:
        sys.exit(0 if run_fidelity(syms, specs, a.quick) else 1)
    else:
        run_gate(syms, specs, a.quick, a.out)


if __name__ == "__main__":
    main()
