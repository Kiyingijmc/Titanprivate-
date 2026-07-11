#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/poc_ote_canonical.py
# Canonical OTE MTF study (3-year, 11 instruments, net of costs).
# Spec + pre-registered gate: docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md
#
# Model (frozen a-priori, spec section 1): H4+H1 structural BOS bias agree ->
# most recent H1 impulse leg (>=2.0xATR(H1)) -> OTE zone 0.62-0.79 -> price
# trades into zone -> M5 MSS in trend direction -> MARKET at next M5 open.
# Stop: H1-anchored (pullback extreme / zone invalidation / 0.5xATR floor).
# Exits: fixed 2.5R AND v14.4 ratchet+runner (dual-model gate).
#
#   .venv/bin/python scripts/poc_ote_canonical.py                    # full run
#   .venv/bin/python scripts/poc_ote_canonical.py --sym EURUSD --quick
#   .venv/bin/python scripts/poc_ote_canonical.py --sym EURUSD --golden \
#       --start 2026-03-02 --end 2026-03-20      # event log for manual check
# ==============================================================================
import argparse
import json
import os
import random as _random
import sys
import time as _t

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.analysis.smc_analyzer import SMCAnalyzer                  # noqa: E402
from src.analysis.signal_grader import SignalGrader                # noqa: E402
from src.analysis.ote_structure import (                           # noqa: E402
    structure_bias, confirmed_swings, precompute_last_swings, impulse_leg,
    ote_zone, zone_invalidation, mss_confirm, stop_anchor, advance_setup,
    AWAIT_ZONE, IN_ZONE, CONFIRMED, DEAD,
)
from scripts.poc_sb_stops import (                                 # noqa: E402
    replay_managed, cost_r, metrics, wilson, SPREADS,
)

# Frozen parameters (spec section 1) — the one-pass rule forbids tuning these.
ZONE_LO, ZONE_HI = 0.62, 0.79
MIN_SWING_ATR = 2.0
STOP_FLOOR_ATR = 0.5
TTL_H1_BARS = 12
RR = 2.5
LK_HTF = 3
LK_M5 = 2
COST_SCREEN_R = 0.25        # a-priori economic viability screen (spec section 2)
NY_SHIFT = -7               # broker->NY approx, as in poc_sb_stops

# Copied from scripts/poc_mtf_pb2.py (import avoided: that module drags in the
# whole backtest-engine chain at import time; these 8 lines are stable).
ASSET_CLASSES = {
    "FX-majors": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
    "FX-crosses": ["GBPCAD", "GBPJPY"],
    "metals": ["XAUUSD"],
    "index": ["US30"],
    "crypto": ["BTCUSD"],
    "energy": ["XBRUSD"],
}
SYMS = [s for syms in ASSET_CLASSES.values() for s in syms]


def asset_class_of(sym):
    for cls, syms in ASSET_CLASSES.items():
        if sym in syms:
            return cls
    return "other"


def bootstrap_expectancy_ci(rs, n_boot=2000, alpha=0.05, seed=0):
    """Percentile bootstrap CI for mean R (copied from poc_mtf_pb2, same reason)."""
    if not rs:
        return (0.0, 0.0)
    rng = _random.Random(seed)
    n = len(rs)
    means = sorted(sum(rs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(n_boot))
    return (means[int((alpha / 2) * n_boot)],
            means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))])


def _resample(df, rule):
    return (df.set_index("time")
              .resample(rule).agg({"open": "first", "high": "max",
                                   "low": "min", "close": "last"})
              .dropna().reset_index())


def scan_symbol(m5df, quick=False, verbose=False):
    """One pass over an M5 frame -> (trades, bars, funnel). Trades carry the
    FIXED-2.5R outcome (which also fixes the one-open-per-symbol sequencing);
    the managed exit is replayed by the caller on the same entries."""
    df = m5df.copy()
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    m5_t = pd.to_datetime(df["time"]).values
    m5_o = df["open"].values.astype(float)
    m5_h = df["high"].values.astype(float)
    m5_l = df["low"].values.astype(float)
    m5_c = df["close"].values.astype(float)
    n = len(df)

    h1 = _resample(df, "1h")
    h4 = _resample(df, "4h")
    h1_t = pd.to_datetime(h1["time"]).values
    h4_t = pd.to_datetime(h4["time"]).values
    h1_h = list(h1["high"].values.astype(float))
    h1_l = list(h1["low"].values.astype(float))
    h1_bias = structure_bias(h1_h, h1_l, LK_HTF)
    h4_bias = structure_bias(list(h4["high"].values.astype(float)),
                             list(h4["low"].values.astype(float)), LK_HTF)
    atr_h1 = SMCAnalyzer(h1.copy()).process()["ATR"].values   # live ATR source
    swh_h1, swl_h1 = confirmed_swings(h1_h, h1_l, LK_HTF)
    last_swh, last_swl = precompute_last_swings(list(m5_h), list(m5_l), LK_M5)

    # containing H1/H4 index per M5 bar; H1 bar (cont-1) is closed once we are
    # inside bar `cont` (bias/legs use only CLOSED HTF bars — no look-ahead)
    cont_h1 = np.searchsorted(h1_t, m5_t, side="right") - 1

    trades = []
    funnel = {"legs": 0, "setups": 0, "zone_touch": 0, "mss": 0, "entries": 0}
    setup = None
    busy_until = -1
    prev_cont = int(cont_h1[0])

    def _say(msg, i):
        if verbose:
            print(f"  [{pd.Timestamp(m5_t[i])}] {msg}")

    for i in range(n):
        cont = int(cont_h1[i])
        if cont != prev_cont:                       # a new H1 bar started ->
            upto = cont - 1                         # bar `upto` just closed
            prev_cont = cont
            if upto >= 1:
                h4c = int(np.searchsorted(h4_t, m5_t[i], side="right")) - 2
                b1 = h1_bias[upto]
                b4 = h4_bias[h4c] if h4c >= 0 else "NEUTRAL"
                bias = b1 if (b1 == b4 and b1 != "NEUTRAL") else None
                if bias is None:
                    if setup is not None:
                        _say("SETUP dropped: bias lost", i)
                    setup = None
                else:
                    leg = impulse_leg(h1_h, h1_l, upto, LK_HTF, bias,
                                      swh_h1, swl_h1)
                    a = float(atr_h1[upto]) if not np.isnan(atr_h1[upto]) else 0.0
                    if leg is not None and a > 0 and \
                            (leg[1] - leg[0]) >= MIN_SWING_ATR * a:
                        funnel["legs"] += 1
                        key = (leg[2], leg[3])
                        is_long = bias == "BULLISH"
                        if setup is None or setup["key"] != key \
                                or setup["is_long"] != is_long:
                            z_lo, z_hi = ote_zone(leg[0], leg[1], bias,
                                                  ZONE_LO, ZONE_HI)
                            ext = leg[3] if is_long else leg[2]
                            pb_start = (int(np.searchsorted(m5_t, h1_t[ext + 1]))
                                        if ext + 1 < len(h1_t) else i)
                            setup = {"key": key, "is_long": is_long,
                                     "bias": bias, "leg_lo": leg[0],
                                     "leg_hi": leg[1], "z_lo": z_lo,
                                     "z_hi": z_hi, "atr": a, "created": upto,
                                     "state": AWAIT_ZONE, "pb_start": pb_start}
                            funnel["setups"] += 1
                            _say(f"SETUP {bias} leg=({leg[0]:.5f},{leg[1]:.5f}) "
                                 f"zone=({z_lo:.5f},{z_hi:.5f}) atr={a:.5f}", i)
                # TTL expiry (checked on every H1 close)
                if setup is not None and upto - setup["created"] >= TTL_H1_BARS:
                    _say("SETUP expired: TTL", i)
                    setup = None

        if i <= busy_until or setup is None:
            continue

        s = setup
        mss_ok = mss_confirm(m5_h, m5_l, m5_c, i, s["bias"], last_swh, last_swl)
        leg_origin = s["leg_lo"] if s["is_long"] else s["leg_hi"]
        prev_state = s["state"]
        st = advance_setup(prev_state, s["is_long"], s["z_lo"], s["z_hi"],
                           leg_origin, m5_h[i], m5_l[i], m5_c[i], mss_ok)
        if st == IN_ZONE and prev_state == AWAIT_ZONE:
            funnel["zone_touch"] += 1
            _say("ZONE touched", i)
        s["state"] = st
        if st == DEAD:
            _say("SETUP dead: leg origin breached", i)
            setup = None
            continue
        if st != CONFIRMED:
            continue

        funnel["mss"] += 1
        _say("MSS confirmed", i)
        setup = None                                # one shot per setup
        if i + 1 >= n:
            continue
        is_long = s["is_long"]
        entry = float(m5_o[i + 1])
        pb_ext = (float(np.min(m5_l[s["pb_start"]:i + 1])) if is_long
                  else float(np.max(m5_h[s["pb_start"]:i + 1])))
        inval = zone_invalidation(s["z_lo"], s["z_hi"], s["atr"], is_long)
        sl = stop_anchor(entry, pb_ext, inval, s["atr"], is_long, STOP_FLOOR_ATR)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + RR * risk if is_long else entry - RR * risk

        # fixed-RR resolution, same-bar SL first (pessimistic); fixes sequencing
        outcome, r, exit_k = "OPEN", 0.0, n - 1
        for k in range(i + 1, n):
            sl_hit = (m5_l[k] <= sl) if is_long else (m5_h[k] >= sl)
            tp_hit = (m5_h[k] >= tp) if is_long else (m5_l[k] <= tp)
            if sl_hit:
                outcome, r, exit_k = "SL", -1.0, k
                break
            if tp_hit:
                outcome, r, exit_k = "TP", RR, k
                break
        busy_until = exit_k
        if outcome == "OPEN":
            continue
        funnel["entries"] += 1
        ts = pd.Timestamp(m5_t[i + 1])
        _say(f"ENTRY {'BUY' if is_long else 'SELL'} @{entry:.5f} sl={sl:.5f} "
             f"tp={tp:.5f} -> {outcome}", i)
        trades.append({"dir": "BUY" if is_long else "SELL", "time": ts,
                       "year": int(ts.year), "entry": entry, "sl": sl,
                       "tp": tp, "risk": risk, "fill_idx": i + 1,
                       "exit_idx": exit_k, "outcome": outcome, "r": float(r),
                       "leg_low": s["leg_lo"], "leg_high": s["leg_hi"],
                       "atr_h1": s["atr"], "z_lo": s["z_lo"],
                       "z_hi": s["z_hi"], "pullback_ext": pb_ext,
                       "bias": s["bias"]})

    bars = {"high": m5_h, "low": m5_l}
    return trades, bars, funnel


def _grade_mirror(t, grader):
    """Offline SignalGrader mirror (reported, not gated — spec section 3).
    candle=None: the displacement factor is unavailable offline; noted in output."""
    decision = {"signal": t["dir"], "price": t["entry"], "sl": t["sl"],
                "tp": t["tp"]}
    ny_hour = (int(t["time"].hour) + NY_SHIFT) % 24
    ctx = {"bias": t["bias"], "liquidity": {}, "ny_time": f"{ny_hour:02d}:00"}
    return grader.grade(decision, ctx, candle=None)["grade"]


def _gate_class(rows, key_net, label):
    """70/30 chronological OOS gate for one asset class + one exit model.
    Returns (train_exp, test_exp, n_test, ci_lo, ci_hi, passed)."""
    rows = sorted(rows, key=lambda t: t["time"])
    cut = int(len(rows) * 0.7)
    tr_rs = [t[key_net] for t in rows[:cut]]
    te_rs = [t[key_net] for t in rows[cut:]]
    tr_exp = sum(tr_rs) / len(tr_rs) if tr_rs else 0.0
    te_exp = sum(te_rs) / len(te_rs) if te_rs else 0.0
    lo, hi = bootstrap_expectancy_ci(te_rs)
    wins = sum(1 for r in te_rs if r > 0)
    _, w_lo, w_hi = wilson(wins, len(te_rs))     # win-rate CI (reported, spec s3)
    passed = (tr_exp > 0 and te_exp > 0 and len(te_rs) >= 30
              and (lo > 0 or lo > -0.02))
    print(f"    {label:10} train={tr_exp:+.3f} test={te_exp:+.3f} "
          f"(n_te={len(te_rs)}) bootCI[{lo:+.3f},{hi:+.3f}] "
          f"winCI[{w_lo*100:.0f}-{w_hi*100:.0f}%] "
          f"{'PASS' if passed else 'fail'}")
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--golden", action="store_true",
                    help="verbose per-event log for manual verification")
    ap.add_argument("--start", default=None, help="date filter (golden mode)")
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default="data/history/ote_canonical_trades.csv")
    a = ap.parse_args()
    syms = [a.sym] if a.sym else SYMS

    with open("data/specs.json") as f:
        specs = json.load(f)

    print("### Canonical OTE MTF study — H4+H1 BOS -> H1 leg -> 0.62-0.79 zone "
          "-> M5 MSS (spec 2026-07-11) ###\n", flush=True)

    all_trades = []
    funnels = {}
    for sym in syms:
        path = f"data/history/{sym}_M5.csv"
        if not os.path.exists(path):
            print(f"[SKIP] {sym}: no data file")
            continue
        t0 = _t.time()
        df = pd.read_csv(path).rename(columns={"datetime": "time"})
        df["time"] = pd.to_datetime(df["time"])
        if a.start:
            df = df[df["time"] >= pd.Timestamp(a.start)].reset_index(drop=True)
        if a.end:
            df = df[df["time"] <= pd.Timestamp(a.end)].reset_index(drop=True)
        trades, bars, funnel = scan_symbol(df, quick=a.quick, verbose=a.golden)
        funnels[sym] = funnel
        for t in trades:
            t["sym"] = sym
            t["r_mgd"] = replay_managed(t, bars, runner=True)   # v14.4 engine
            for mult, key in ((1.0, "c1"), (1.5, "c15"), (2.0, "c2")):
                t[key] = cost_r(t, sym, specs, mult)
        all_trades += trades
        print(f"[{sym}] funnel={funnel}  ({_t.time()-t0:.0f}s)", flush=True)

    if not all_trades:
        print("No trades.")
        return
    pd.DataFrame(all_trades).to_csv(a.out, index=False)
    print(f"\n[CSV] {len(all_trades)} trades -> {a.out}\n")

    # net columns: gross r minus cost, per exit model / spread stress
    for t in all_trades:
        t["net_fix_1"] = t["r"] - t["c1"]
        t["net_fix_15"] = t["r"] - t["c15"]
        t["net_mgd_1"] = t["r_mgd"] - t["c1"]
        t["net_mgd_15"] = t["r_mgd"] - t["c15"]

    # ---- Section 1: a-priori cost screen (median RT cost at realized stops)
    print("=" * 88)
    print(f"1. COST SCREEN — median round-trip cost at realized stops "
          f"(exclude > {COST_SCREEN_R}R)")
    print("=" * 88)
    included = []
    for sym in sorted({t["sym"] for t in all_trades}):
        cs = [t["c1"] for t in all_trades if t["sym"] == sym]
        med = float(np.median(cs))
        ok = med <= COST_SCREEN_R
        if ok:
            included.append(sym)
        print(f"  {sym:8} median={med:.3f}R n={len(cs):5d} "
              f"{'INCLUDED' if ok else 'EXCLUDED (economic screen)'}")
    inc_trades = [t for t in all_trades if t["sym"] in included]

    # ---- Section 2: per-symbol table (net 1x)
    print("\n" + "=" * 88)
    print("2. PER-SYMBOL (net 1x costs)")
    print("=" * 88)
    for sym in sorted({t["sym"] for t in all_trades}):
        rows = [t for t in all_trades if t["sym"] == sym]
        mf = metrics([t["net_fix_1"] for t in rows])
        mm = metrics([t["net_mgd_1"] for t in rows])
        print(f"  {sym:8} n={mf['n']:5d} FIXED exp={mf['exp']:+.3f}R "
              f"PF={mf['pf']:4.2f} | MANAGED exp={mm['exp']:+.3f}R "
              f"PF={mm['pf']:4.2f}")

    # ---- Section 3: pre-registered gate per asset class
    print("\n" + "=" * 88)
    print("3. GATE — per asset class: net>0 train AND test, BOTH exit models, "
          "n_te>=30, 1.5x sign holds, bootCI (spec section 3)")
    print("=" * 88)
    verdicts = {}
    for cls, cls_syms in ASSET_CLASSES.items():
        rows = [t for t in inc_trades if t["sym"] in cls_syms]
        if not rows:
            print(f"\n  [{cls}] no trades (or all symbols cost-excluded)")
            verdicts[cls] = False
            continue
        print(f"\n  [{cls}] n={len(rows)}")
        p_fix = _gate_class(rows, "net_fix_1", "FIXED")
        p_mgd = _gate_class(rows, "net_mgd_1", "MANAGED")
        s15_f = sum(t["net_fix_15"] for t in rows)
        s15_m = sum(t["net_mgd_15"] for t in rows)
        stress = s15_f > 0 and s15_m > 0
        print(f"    1.5x spread pooled: FIXED {s15_f:+.1f}R "
              f"MANAGED {s15_m:+.1f}R {'holds' if stress else 'SIGN FLIP'}")
        verdicts[cls] = p_fix and p_mgd and stress
        print(f"    VERDICT: {'GO' if verdicts[cls] else 'NO-GO'}")

    # ---- Section 4: pooled portfolio, chronological (correct equity-curve DD)
    print("\n" + "=" * 88)
    print("4. POOLED PORTFOLIO — included symbols, chronological")
    print("=" * 88)
    pooled = sorted(inc_trades, key=lambda t: t["time"])
    for key, label in (("net_fix_1", "FIXED net1x"),
                       ("net_mgd_1", "MANAGED net1x"),
                       ("net_mgd_15", "MANAGED net1.5x")):
        m = metrics([t[key] for t in pooled])
        print(f"  {label:16} n={m['n']:5d} exp={m['exp']:+.3f}R "
              f"totR={m['totR']:+7.1f} PF={m['pf']:4.2f} DD={m['dd']:.0f}R "
              f"win={m['winpct']:.1f}%")
    print("  per-year (MANAGED net1x):")
    for yr in sorted({t["year"] for t in pooled}):
        rs = [t["net_mgd_1"] for t in pooled if t["year"] == yr]
        print(f"    {yr}: n={len(rs):4d} exp={sum(rs)/len(rs):+.3f}R")

    # ---- Section 5: grader mirror (reported, not gated)
    print("\n" + "=" * 88)
    print("5. SIGNAL-GRADER MIRROR (candle=None: displacement factor absent — "
          "approximation, reported only)")
    print("=" * 88)
    grader = SignalGrader({"signal_grading": {"enabled": True, "min_grade": "B"}})
    for t in pooled:
        t["grade"] = _grade_mirror(t, grader)
    for g in ("A++", "A+", "A", "B", "C"):
        rs = [t["net_mgd_1"] for t in pooled if t["grade"] == g]
        if rs:
            print(f"  grade {g:3} n={len(rs):5d} exp={sum(rs)/len(rs):+.3f}R")
    gated = [t["net_mgd_1"] for t in pooled if grader.passes(t["grade"])]
    if gated:
        print(f"  >=B floor: n={len(gated)} exp={sum(gated)/len(gated):+.3f}R "
              f"(vs ungated {sum(t['net_mgd_1'] for t in pooled)/len(pooled):+.3f}R)")

    # ---- Final verdict
    print("\n" + "=" * 88)
    gos = [c for c, v in verdicts.items() if v]
    print(f"FINAL: {'GO for ' + ', '.join(gos) if gos else 'NO-GO everywhere'}"
          f"  (one-pass rule: no in-place re-tuning — spec section 3)")
    print("=" * 88)


if __name__ == "__main__":
    main()
