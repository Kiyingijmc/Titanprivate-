#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/poc_ict_revival.py
# Canonical Unicorn + CRT revival gates (3-year, 11 instruments, net of costs).
# Pre-registration: docs/research/2026-08-01-ict-revival-gate.md (frozen rule
# sets + the OTE-cycle gate criteria verbatim). Rig lineage: resumed from
# scripts/poc_ote_canonical.py (deleted 6de8edb, recovered structure lib at
# src/analysis/ict_structure.py); managed replay + cost model imported from
# scripts/poc_sb_stops.py (the validated engine).
#
#   .venv/bin/python scripts/poc_ict_revival.py --model unicorn          # gate
#   .venv/bin/python scripts/poc_ict_revival.py --model crt              # gate
#   .venv/bin/python scripts/poc_ict_revival.py --model crt --sym XAUUSD \
#       --golden --start 2026-03-02 --end 2026-03-27   # hand-check event log
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
from src.analysis.ict_structure import (                           # noqa: E402
    structure_bias, confirmed_swings, precompute_last_swings, impulse_leg,
    zone_invalidation, mss_confirm, stop_anchor, advance_setup,
    AWAIT_ZONE, IN_ZONE, CONFIRMED, DEAD,
)
from src.analysis.ict_zones import (                               # noqa: E402
    opposing_candle_before, bull_fvg_in_leg, bear_fvg_in_leg, zone_overlap,
)
from scripts.poc_sb_stops import (                                 # noqa: E402
    replay_managed, cost_r, metrics, wilson,
)

# Frozen parameters (pre-registration; the one-pass rule forbids tuning).
STOP_FLOOR_ATR = 0.5
TTL_H1_BARS = 12            # Unicorn setup TTL
RR_UNICORN = 2.5
CRT_MIN_RR = 1.0
BRK_LOOKBACK = 3
LK_HTF = 3
LK_M5 = 2
COST_SCREEN_R = 0.25

ASSET_CLASSES = {
    "FX-majors": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
    "FX-crosses": ["GBPCAD", "GBPJPY"],
    "metals": ["XAUUSD"],
    "index": ["US30"],
    "crypto": ["BTCUSD"],
    "energy": ["XBRUSD"],
}
SYMS = [s for syms in ASSET_CLASSES.values() for s in syms]


def bootstrap_expectancy_ci(rs, n_boot=2000, alpha=0.05, seed=0):
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


def _fixed_resolve(m5_h, m5_l, i, is_long, sl, tp, risk):
    """Same-bar SL-first fixed resolution from bar i+1. Returns
    (outcome, r, exit_k)."""
    n = len(m5_h)
    for k in range(i + 1, n):
        sl_hit = (m5_l[k] <= sl) if is_long else (m5_h[k] >= sl)
        tp_hit = (m5_h[k] >= tp) if is_long else (m5_l[k] <= tp)
        if sl_hit:
            return "SL", -1.0, k
        if tp_hit:
            return "TP", (abs(tp - (sl + risk if is_long else sl - risk)) / risk), k
    return "OPEN", 0.0, n - 1


# ------------------------------------------------------------------ Unicorn
def scan_unicorn(m5df, quick=False, verbose=False):
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
    h1_o = list(h1["open"].values.astype(float))
    h1_h = list(h1["high"].values.astype(float))
    h1_l = list(h1["low"].values.astype(float))
    h1_c = list(h1["close"].values.astype(float))
    h1_bias = structure_bias(h1_h, h1_l, LK_HTF)
    h4_bias = structure_bias(list(h4["high"].values.astype(float)),
                             list(h4["low"].values.astype(float)), LK_HTF)
    atr_h1 = SMCAnalyzer(h1.copy()).process()["ATR"].values
    swh_h1, swl_h1 = confirmed_swings(h1_h, h1_l, LK_HTF)
    last_swh, last_swl = precompute_last_swings(list(m5_h), list(m5_l), LK_M5)
    cont_h1 = np.searchsorted(h1_t, m5_t, side="right") - 1

    trades = []
    funnel = {"legs": 0, "breakers": 0, "fvgs": 0, "setups": 0,
              "zone_touch": 0, "mss": 0, "entries": 0}
    setup = None
    busy_until = -1
    prev_cont = int(cont_h1[0])

    def _say(msg, i):
        if verbose:
            print(f"  [{pd.Timestamp(m5_t[i])}] {msg}")

    for i in range(n):
        cont = int(cont_h1[i])
        if cont != prev_cont:
            upto = cont - 1
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
                    if leg is not None and a > 0:
                        funnel["legs"] += 1
                        is_long = bias == "BULLISH"
                        origin = leg[2] if is_long else leg[3]
                        end = leg[3] if is_long else leg[2]
                        brk = opposing_candle_before(
                            h1_o, h1_c, origin, bearish=is_long,
                            lookback=BRK_LOOKBACK)
                        zone = None
                        if brk is not None:
                            funnel["breakers"] += 1
                            brk_zone = (h1_l[brk], h1_h[brk])
                            fvg = (bull_fvg_in_leg(h1_h, h1_l, origin, end)
                                   if is_long else
                                   bear_fvg_in_leg(h1_h, h1_l, origin, end))
                            if fvg is not None:
                                funnel["fvgs"] += 1
                                zone = zone_overlap(brk_zone, fvg)
                        key = (leg[2], leg[3])
                        if zone is not None and (setup is None
                                                 or setup["key"] != key
                                                 or setup["is_long"] != is_long):
                            inval_side = h1_l[brk] if is_long else h1_h[brk]
                            ext = end
                            pb_start = (int(np.searchsorted(m5_t, h1_t[ext + 1]))
                                        if ext + 1 < len(h1_t) else i)
                            setup = {"key": key, "is_long": is_long,
                                     "bias": bias, "leg_lo": leg[0],
                                     "leg_hi": leg[1], "z_lo": zone[0],
                                     "z_hi": zone[1], "atr": a,
                                     "created": upto, "state": AWAIT_ZONE,
                                     "pb_start": pb_start,
                                     "origin_level": inval_side}
                            funnel["setups"] += 1
                            _say(f"SETUP {bias} breaker@H1[{brk}] "
                                 f"zone=({zone[0]:.5f},{zone[1]:.5f}) "
                                 f"atr={a:.5f}", i)
                if setup is not None and upto - setup["created"] >= TTL_H1_BARS:
                    _say("SETUP expired: TTL", i)
                    setup = None

        if i <= busy_until or setup is None:
            continue

        s = setup
        mss_ok = mss_confirm(m5_h, m5_l, m5_c, i, s["bias"], last_swh, last_swl)
        prev_state = s["state"]
        st = advance_setup(prev_state, s["is_long"], s["z_lo"], s["z_hi"],
                           s["origin_level"], m5_h[i], m5_l[i], m5_c[i], mss_ok)
        if st == IN_ZONE and prev_state == AWAIT_ZONE:
            funnel["zone_touch"] += 1
            _say("ZONE touched", i)
        s["state"] = st
        if st == DEAD:
            _say("SETUP dead: breaker breached", i)
            setup = None
            continue
        if st != CONFIRMED:
            continue

        funnel["mss"] += 1
        _say("MSS confirmed", i)
        setup = None
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
        tp = entry + RR_UNICORN * risk if is_long else entry - RR_UNICORN * risk
        outcome, r, exit_k = "OPEN", 0.0, n - 1
        for k in range(i + 1, n):
            sl_hit = (m5_l[k] <= sl) if is_long else (m5_h[k] >= sl)
            tp_hit = (m5_h[k] >= tp) if is_long else (m5_l[k] <= tp)
            if sl_hit:
                outcome, r, exit_k = "SL", -1.0, k
                break
            if tp_hit:
                outcome, r, exit_k = "TP", RR_UNICORN, k
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
                       "z_lo": s["z_lo"], "z_hi": s["z_hi"],
                       "atr_h1": s["atr"], "bias": s["bias"]})

    bars = {"high": m5_h, "low": m5_l}
    return trades, bars, funnel


# ------------------------------------------------------------------ CRT
def scan_crt(m5df, quick=False, verbose=False):
    df = m5df.copy()
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    times = pd.to_datetime(df["time"])
    m5_t = times.values
    day_id = times.dt.normalize().values
    m5_o = df["open"].values.astype(float)
    m5_h = df["high"].values.astype(float)
    m5_l = df["low"].values.astype(float)
    m5_c = df["close"].values.astype(float)
    n = len(df)

    h1 = _resample(df, "1h")
    h1_t = pd.to_datetime(h1["time"]).values
    atr_h1 = SMCAnalyzer(h1.copy()).process()["ATR"].values
    cont_h1 = np.searchsorted(h1_t, m5_t, side="right") - 1
    last_swh, last_swl = precompute_last_swings(list(m5_h), list(m5_l), LK_M5)

    def _say(msg, i):
        if verbose:
            print(f"  [{pd.Timestamp(m5_t[i])}] {msg}")

    trades = []
    funnel = {"raids": 0, "armed": 0, "retest": 0, "mss": 0,
              "entries": 0, "skipped_lowrr": 0}
    prev_hi = prev_lo = None
    cur_hi = cur_lo = None
    cur_day = None
    # per-side state: None | dict(state=RAIDING|ARMED|IN_ZONE, raid_ext, armed_i)
    bull = bear = None
    bull_done = bear_done = False       # one setup per day per side
    busy_until = -1

    for i in range(n):
        d = day_id[i]
        if d != cur_day:
            if cur_day is not None and cur_hi is not None:
                prev_hi, prev_lo = cur_hi, cur_lo
            cur_day = d
            cur_hi = m5_h[i]
            cur_lo = m5_l[i]
            bull = bear = None
            bull_done = bear_done = False
        else:
            cur_hi = max(cur_hi, m5_h[i])
            cur_lo = min(cur_lo, m5_l[i])

        if prev_hi is None:
            continue
        cont = int(cont_h1[i])
        a = float(atr_h1[cont - 1]) if cont >= 1 and \
            not np.isnan(atr_h1[cont - 1]) else 0.0

        # ---- bull side (raid of the prior-day LOW) ----
        if not bull_done and i > busy_until:
            if bull is None:
                if m5_l[i] < prev_lo:
                    funnel["raids"] += 1
                    bull = {"state": "RAIDING", "raid_ext": m5_l[i]}
                    _say(f"BULL raid: low {m5_l[i]:.5f} < prevLo {prev_lo:.5f}", i)
                    if m5_c[i] > prev_lo:
                        bull["state"] = "ARMED"
                        bull["armed_i"] = i
                        funnel["armed"] += 1
                        _say("BULL armed (closed back inside)", i)
            else:
                if bull["state"] == "RAIDING":
                    bull["raid_ext"] = min(bull["raid_ext"], m5_l[i])
                    if m5_c[i] > prev_lo:
                        bull["state"] = "ARMED"
                        bull["armed_i"] = i
                        funnel["armed"] += 1
                        _say("BULL armed (closed back inside)", i)
                elif bull["state"] in ("ARMED", "IN_ZONE") and i > bull["armed_i"]:
                    if m5_l[i] < bull["raid_ext"]:
                        _say("BULL dead: raid extreme breached", i)
                        bull = None
                        bull_done = True
                    else:
                        if bull["state"] == "ARMED" and m5_l[i] <= prev_lo:
                            bull["state"] = "IN_ZONE"
                            funnel["retest"] += 1
                            _say("BULL retest into raid band", i)
                        if bull is not None and bull["state"] == "IN_ZONE" and \
                                mss_confirm(m5_h, m5_l, m5_c, i, "BULLISH",
                                            last_swh, last_swl):
                            funnel["mss"] += 1
                            _say("BULL MSS confirmed", i)
                            if i + 1 < n and a > 0:
                                entry = float(m5_o[i + 1])
                                sl = min(bull["raid_ext"] - 0.1 * a,
                                         entry - STOP_FLOOR_ATR * a)
                                risk = entry - sl
                                tp = prev_hi
                                if risk > 0 and (tp - entry) >= CRT_MIN_RR * risk:
                                    rr = (tp - entry) / risk
                                    outcome, r, exit_k = "OPEN", 0.0, n - 1
                                    for k in range(i + 1, n):
                                        if m5_l[k] <= sl:
                                            outcome, r, exit_k = "SL", -1.0, k
                                            break
                                        if m5_h[k] >= tp:
                                            outcome, r, exit_k = "TP", rr, k
                                            break
                                    busy_until = exit_k
                                    if outcome != "OPEN":
                                        funnel["entries"] += 1
                                        ts = pd.Timestamp(m5_t[i + 1])
                                        _say(f"ENTRY BUY @{entry:.5f} "
                                             f"sl={sl:.5f} tp={tp:.5f} "
                                             f"rr={rr:.2f} -> {outcome}", i)
                                        trades.append({
                                            "dir": "BUY", "time": ts,
                                            "year": int(ts.year),
                                            "entry": entry, "sl": sl, "tp": tp,
                                            "risk": risk, "fill_idx": i + 1,
                                            "exit_idx": exit_k,
                                            "outcome": outcome, "r": float(r),
                                            "atr_h1": a, "bias": "BULLISH"})
                                else:
                                    funnel["skipped_lowrr"] += 1
                                    _say("BULL skipped: target < min RR", i)
                            bull = None
                            bull_done = True

        # ---- bear side (raid of the prior-day HIGH) ----
        if not bear_done and i > busy_until:
            if bear is None:
                if m5_h[i] > prev_hi:
                    funnel["raids"] += 1
                    bear = {"state": "RAIDING", "raid_ext": m5_h[i]}
                    _say(f"BEAR raid: high {m5_h[i]:.5f} > prevHi {prev_hi:.5f}", i)
                    if m5_c[i] < prev_hi:
                        bear["state"] = "ARMED"
                        bear["armed_i"] = i
                        funnel["armed"] += 1
                        _say("BEAR armed (closed back inside)", i)
            else:
                if bear["state"] == "RAIDING":
                    bear["raid_ext"] = max(bear["raid_ext"], m5_h[i])
                    if m5_c[i] < prev_hi:
                        bear["state"] = "ARMED"
                        bear["armed_i"] = i
                        funnel["armed"] += 1
                        _say("BEAR armed (closed back inside)", i)
                elif bear["state"] in ("ARMED", "IN_ZONE") and i > bear["armed_i"]:
                    if m5_h[i] > bear["raid_ext"]:
                        _say("BEAR dead: raid extreme breached", i)
                        bear = None
                        bear_done = True
                    else:
                        if bear["state"] == "ARMED" and m5_h[i] >= prev_hi:
                            bear["state"] = "IN_ZONE"
                            funnel["retest"] += 1
                            _say("BEAR retest into raid band", i)
                        if bear is not None and bear["state"] == "IN_ZONE" and \
                                mss_confirm(m5_h, m5_l, m5_c, i, "BEARISH",
                                            last_swh, last_swl):
                            funnel["mss"] += 1
                            _say("BEAR MSS confirmed", i)
                            if i + 1 < n and a > 0:
                                entry = float(m5_o[i + 1])
                                sl = max(bear["raid_ext"] + 0.1 * a,
                                         entry + STOP_FLOOR_ATR * a)
                                risk = sl - entry
                                tp = prev_lo
                                if risk > 0 and (entry - tp) >= CRT_MIN_RR * risk:
                                    rr = (entry - tp) / risk
                                    outcome, r, exit_k = "OPEN", 0.0, n - 1
                                    for k in range(i + 1, n):
                                        if m5_h[k] >= sl:
                                            outcome, r, exit_k = "SL", -1.0, k
                                            break
                                        if m5_l[k] <= tp:
                                            outcome, r, exit_k = "TP", rr, k
                                            break
                                    busy_until = exit_k
                                    if outcome != "OPEN":
                                        funnel["entries"] += 1
                                        ts = pd.Timestamp(m5_t[i + 1])
                                        _say(f"ENTRY SELL @{entry:.5f} "
                                             f"sl={sl:.5f} tp={tp:.5f} "
                                             f"rr={rr:.2f} -> {outcome}", i)
                                        trades.append({
                                            "dir": "SELL", "time": ts,
                                            "year": int(ts.year),
                                            "entry": entry, "sl": sl, "tp": tp,
                                            "risk": risk, "fill_idx": i + 1,
                                            "exit_idx": exit_k,
                                            "outcome": outcome, "r": float(r),
                                            "atr_h1": a, "bias": "BEARISH"})
                                else:
                                    funnel["skipped_lowrr"] += 1
                                    _say("BEAR skipped: target < min RR", i)
                            bear = None
                            bear_done = True

    bars = {"high": m5_h, "low": m5_l}
    return trades, bars, funnel


# ------------------------------------------------------------------ gate
def _gate_class(rows, key_net, label):
    rows = sorted(rows, key=lambda t: t["time"])
    cut = int(len(rows) * 0.7)
    tr_rs = [t[key_net] for t in rows[:cut]]
    te_rs = [t[key_net] for t in rows[cut:]]
    tr_exp = sum(tr_rs) / len(tr_rs) if tr_rs else 0.0
    te_exp = sum(te_rs) / len(te_rs) if te_rs else 0.0
    lo, hi = bootstrap_expectancy_ci(te_rs)
    wins = sum(1 for r in te_rs if r > 0)
    _, w_lo, w_hi = wilson(wins, len(te_rs))
    passed = (tr_exp > 0 and te_exp > 0 and len(te_rs) >= 30
              and (lo > 0 or lo > -0.02))
    print(f"    {label:10} train={tr_exp:+.3f} test={te_exp:+.3f} "
          f"(n_te={len(te_rs)}) bootCI[{lo:+.3f},{hi:+.3f}] "
          f"winCI[{w_lo*100:.0f}-{w_hi*100:.0f}%] "
          f"{'PASS' if passed else 'fail'}")
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["unicorn", "crt"], required=True)
    ap.add_argument("--sym", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--golden", action="store_true")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    scan = scan_unicorn if a.model == "unicorn" else scan_crt
    out = a.out or f"data/history/{a.model}_canonical_trades.csv"
    syms = [a.sym] if a.sym else SYMS

    with open("data/specs.json") as f:
        specs = json.load(f)

    print(f"### Canonical {a.model.upper()} revival gate "
          f"(docs/research/2026-08-01-ict-revival-gate.md) ###\n", flush=True)

    all_trades = []
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
        trades, bars, funnel = scan(df, quick=a.quick, verbose=a.golden)
        for t in trades:
            t["sym"] = sym
            t["r_mgd"] = replay_managed(t, bars, runner=True)
            for mult, key in ((1.0, "c1"), (1.5, "c15"), (2.0, "c2")):
                t[key] = cost_r(t, sym, specs, mult)
        all_trades += trades
        print(f"[{sym}] funnel={funnel}  ({_t.time()-t0:.0f}s)", flush=True)

    if not all_trades:
        print("No trades.")
        return
    pd.DataFrame(all_trades).to_csv(out, index=False)
    print(f"\n[CSV] {len(all_trades)} trades -> {out}\n")

    for t in all_trades:
        t["net_fix_1"] = t["r"] - t["c1"]
        t["net_fix_15"] = t["r"] - t["c15"]
        t["net_mgd_1"] = t["r_mgd"] - t["c1"]
        t["net_mgd_15"] = t["r_mgd"] - t["c15"]

    print("=" * 88)
    print(f"1. COST SCREEN — median RT cost at realized stops "
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

    print("\n" + "=" * 88)
    print("3. GATE — per asset class (pre-registered criteria, OTE-cycle)")
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

    print("\n" + "=" * 88)
    gos = [c for c, v in verdicts.items() if v]
    print(f"FINAL {a.model.upper()}: "
          f"{'GO for ' + ', '.join(gos) if gos else 'NO-GO everywhere'}"
          f"  (one-pass rule: no in-place re-tuning)")
    print("=" * 88)


if __name__ == "__main__":
    main()
