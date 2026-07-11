#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/poc_sb_stops.py
# SilverBullet stop-model study (3-year, 11 instruments, net of costs).
#
# Prior finding (2026-05-30): SB's frictionless +0.33R London-open edge is a
# cost artifact — the live stop is a fixed 0.2xATR buffer beyond the FVG edge
# (risk ~ sub-pip), so spread crossing costs ~1R+. This study keeps the entry
# frozen (limit at the FVG edge, displacement-gated) and tests STOP MODELS:
#
#   LIVE   sl = entry -/+ 0.2*ATR                (current live logic, baseline)
#   ATR05  sl = entry -/+ 0.5*ATR
#   ATR10  sl = entry -/+ 1.0*ATR
#   STRUCT sl beyond the displacement structure (far bar extreme) + 0.2*ATR
#
# TP = entry +/- RR * risk (RR 2.0, as live). One open trade per symbol,
# limit TTL 12 bars (as the validation harness). Costs are charged in R:
# cost_R = (spread_ticks + commission_ticks) * tick / risk_distance.
#
#   .venv/bin/python scripts/poc_sb_stops.py            # full run (background it)
#   .venv/bin/python scripts/poc_sb_stops.py --sym EURUSD --quick
# ==============================================================================
import argparse
import json
import math
import os
import sys
import time as _t

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.analysis.smc_analyzer import SMCAnalyzer            # noqa: E402
from src.analysis.bias_engine import BiasEngine               # noqa: E402

SYMS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
        "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]
RR = 2.0
TTL_BARS = 12
BODY_MIN_ATR = 0.8          # SilverBullet's momentum gate
NY_SHIFT = -7               # broker(GMT+3ish) -> NY approx; +/-1h DST wobble accepted
SPREADS = {                 # indicative FBS spread in ticks (same table as harness)
    "EURUSD": 8, "GBPUSD": 12, "USDJPY": 10, "AUDUSD": 10, "USDCAD": 12,
    "GBPCAD": 30, "GBPJPY": 25, "XAUUSD": 20, "US30": 200, "BTCUSD": 1000, "XBRUSD": 30,
}
COMMISSION_USD_PER_LOT = 7.0

STOP_MODELS = ["LIVE", "ATR05", "ATR10", "STRUCT"]
TIGHT_TRAIL = 0.10          # arm C: trail distance as fraction of range after signal


# ---------------------------------------------------------------- collection
def collect_signals(sym, quick=False, tf="M5"):
    """One pass over the (optionally resampled) M5 file -> signal dicts."""
    path = f"data/history/{sym}_M5.csv"
    if not os.path.exists(path):
        return None, None
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    df = df.rename(columns={"datetime": "time"})
    df_m5 = df.copy()
    if tf != "M5":
        rule = {"M15": "15min", "H1": "1h"}[tf]
        df = (df.set_index("time")
                .resample(rule).agg({"open": "first", "high": "max",
                                     "low": "min", "close": "last"})
                .dropna().reset_index())
    enr = SMCAnalyzer(df.copy()).process()

    highs = enr["high"].values; lows = enr["low"].values
    opens = enr["open"].values; closes = enr["close"].values
    atr = enr["ATR"].values
    bear = enr["is_fvg_bear"].values; bull = enr["is_fvg_bull"].values
    ftop = enr["fvg_top"].values; fbot = enr["fvg_bottom"].values
    times = pd.to_datetime(enr["time"]).values

    # H1 context for bias/liquidity (broker time, same as live warmup data)
    h1 = (df.set_index("time")
            .resample("1h").agg({"open": "first", "high": "max",
                                 "low": "min", "close": "last"})
            .dropna().reset_index())
    h1_times = h1["time"].values

    body = np.abs(closes - opens)
    sig_mask = (bear | bull) & (atr > 0) & (body >= BODY_MIN_ATR * atr)
    sig_mask[:50] = False
    idxs = np.where(sig_mask)[0]

    bias_cache = {}
    signals = []
    for i in idxs:
        t = times[i]
        h1_n = int(np.searchsorted(h1_times, t))     # H1 bars closed before t
        if h1_n not in bias_cache:
            if h1_n > 20:
                ctx = h1.iloc[max(0, h1_n - 100):h1_n]
                bias_cache[h1_n] = BiasEngine(ctx).get_bias_context()
            else:
                bias_cache[h1_n] = ("NEUTRAL", {})
        bias, liq = bias_cache[h1_n]
        is_bear = bool(bear[i])
        signals.append({
            "bar_idx": int(i), "time": pd.Timestamp(t),
            "dir": "SELL" if is_bear else "BUY",
            "entry": float(fbot[i] if is_bear else ftop[i]),   # live entry (near gap edge)
            "far_extreme": float(highs[i - 2] if is_bear else lows[i - 2]),
            "sig_high": float(highs[i]), "sig_low": float(lows[i]),
            "atr": float(atr[i]), "body_atr": float(body[i] / atr[i]),
            "bias": bias, "liq_status": (liq or {}).get("STATUS", ""),
            "hour": int(pd.Timestamp(t).hour),
            "year": int(pd.Timestamp(t).year),
        })
    disp15 = _disp15_by_bar(df_m5, times, tf)
    bars = {"high": highs, "low": lows,
            "disp_bull": disp15["bull"], "disp_bear": disp15["bear"]}
    return signals, bars


def _disp15_by_bar(df, tf_times, tf):
    """For each trade-TF bar, True if any M15 sub-bar of that bar is an FVG
    displacement (bull/bear). Returns {'bull': bool[], 'bear': bool[]} aligned
    to tf_times. All-False when tf is M5/M15 (no coarser sub-M15 grouping)."""
    n = len(tf_times)
    empty = {"bull": np.zeros(n, dtype=bool), "bear": np.zeros(n, dtype=bool)}
    if tf not in ("H1",):
        return empty
    m15 = (df.set_index("time")
             .resample("15min").agg({"open": "first", "high": "max",
                                     "low": "min", "close": "last"})
             .dropna().reset_index())
    if len(m15) < 60:
        return empty
    enr15 = SMCAnalyzer(m15.copy()).process()
    b_bull = enr15["is_fvg_bull"].values
    b_bear = enr15["is_fvg_bear"].values
    m15_times = pd.to_datetime(enr15["time"]).values
    # map each M15 bar to the trade-TF bar it falls in (last tf bar <= m15 time)
    out = {"bull": np.zeros(n, dtype=bool), "bear": np.zeros(n, dtype=bool)}
    tf_sorted = np.asarray(tf_times)
    for j in range(len(m15_times)):
        idx = int(np.searchsorted(tf_sorted, m15_times[j], side="right")) - 1
        if 0 <= idx < n:
            if b_bull[j]:
                out["bull"][idx] = True
            if b_bear[j]:
                out["bear"][idx] = True
    return out


# ---------------------------------------------------------------- resolution
def stop_price(sig, model):
    e, a = sig["entry"], sig["atr"]
    if model == "LIVE":
        d = 0.2 * a
    elif model == "ATR05":
        d = 0.5 * a
    elif model == "ATR10":
        d = 1.0 * a
    elif model == "STRUCT":
        d = abs(e - sig["far_extreme"]) + 0.2 * a
    else:
        raise ValueError(model)
    return (e + d) if sig["dir"] == "SELL" else (e - d)


def resolve(signals, bars, model):
    """Fixed-TP resolution, one open per symbol, limit fill within TTL."""
    highs, lows = bars["high"], bars["low"]
    n = len(highs)
    trades = []
    busy_until = -1
    for sig in signals:
        i = sig["bar_idx"]
        if i <= busy_until:
            continue
        entry = sig["entry"]; sl = stop_price(sig, model)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        is_long = sig["dir"] == "BUY"
        tp = entry + RR * risk if is_long else entry - RR * risk

        # limit fill: bar range touches entry within TTL (bars after signal bar)
        fill = None
        for k in range(i + 1, min(i + 1 + TTL_BARS, n)):
            if lows[k] <= entry <= highs[k]:
                fill = k
                break
        if fill is None:
            busy_until = min(i + TTL_BARS, n - 1)
            continue

        outcome, r, exit_k = "OPEN", 0.0, n - 1
        for k in range(fill, n):
            sl_hit = (lows[k] <= sl) if is_long else (highs[k] >= sl)
            tp_hit = (highs[k] >= tp) if is_long else (lows[k] <= tp)
            if sl_hit:                        # same-bar both -> SL (pessimistic)
                outcome, r, exit_k = "SL", -1.0, k
                break
            if tp_hit:
                outcome, r, exit_k = "TP", RR, k
                break
        busy_until = exit_k
        if outcome in ("SL", "TP"):
            trades.append({**sig, "model": model, "sl": sl, "tp": tp,
                           "risk": risk, "outcome": outcome, "r": r,
                           "fill_idx": fill, "exit_idx": exit_k})
    return trades


# ------------------------------------------------------- management replay
def replay_managed(tr, bars, runner=False):
    """Replay the v14.4 ratchet on a resolved-entry trade; returns realized R.

    Levels on the entry->TP range: 0.382 BE(sl->entry), 0.618 bank 30% + sl->L1,
    0.886 bank 50% of remainder + sl->L2 (runner: drop TP, trail by 0.268*range).
    Partials assumed filled AT the fib level (optimistic on partials, pessimistic
    same-bar SL-first as elsewhere). R measured on initial risk, volume-weighted.
    """
    highs, lows = bars["high"], bars["low"]
    e, sl0, tp, risk = tr["entry"], tr["sl"], tr["tp"], tr["risk"]
    is_long = tr["dir"] == "BUY"
    rng = abs(tp - e)
    L1, L2, L3 = 0.382, 0.618, 0.886
    lvl_price = lambda f: e + f * rng if is_long else e - f * rng
    r_of = lambda px: ((px - e) / risk) if is_long else ((e - px) / risk)

    sl, level, vol, realized = sl0, 0, 1.0, 0.0
    trail = (L3 - L2) * rng
    n = len(highs)
    for k in range(tr["fill_idx"], n):
        hi, lo = highs[k], lows[k]
        # 1. stop first (pessimistic within the bar)
        if (is_long and lo <= sl) or (not is_long and hi >= sl):
            return realized + vol * r_of(sl)
        up = hi if is_long else None
        # progress high-water this bar
        reach = (hi - e) / rng if is_long else (e - lo) / rng
        if level < 1 and reach >= L1:
            sl, level = e, 1                      # BE (buffer ignored: ~0 R)
        if level < 2 and reach >= L2:
            realized += 0.30 * vol * r_of(lvl_price(L2))
            vol *= 0.70
            sl, level = lvl_price(L1), 2
        if level < 3 and reach >= L3:
            realized += 0.50 * vol * r_of(lvl_price(L3))
            vol *= 0.50
            sl, level = lvl_price(L2), 3
            if runner:
                tp = None
        # 2. TP / trail
        if tp is not None and ((is_long and hi >= tp) or (not is_long and lo <= tp)):
            return realized + vol * r_of(tp)
        if runner and level >= 3:
            cand = (hi - trail) if is_long else (lo + trail)
            if (is_long and cand > sl) or (not is_long and cand < sl):
                sl = cand
    return realized + vol * 0.0                   # open at end: ignore tail


def replay_overlay(tr, bars, *, arm="off", signal="giveback",
                   f=0.5, g=0.5, max_cycles=2, disp15=None, trace=None):
    """Runner-phase Pullback Monetizer overlay on top of the v14.4 ratchet.

    arm="off" -> byte-identical to replay_managed(tr, bars, runner=True) (Control).
    arm="A"   -> bank fraction f of the runner tail on a pullback signal, re-add
                 the banked volume on the next new high-water mark (resumption);
                 at most max_cycles bank/re-add cycles.
    arm="C"   -> same bank signal, but tighten the trail to TIGHT_TRAIL*range once
                 (no extra trades) instead of banking.

    Returns (realized_r, extra_rt_units). realized_r is volume-weighted R on
    initial risk (same convention as replay_managed). extra_rt_units is the total
    tail volume that did an extra bank+re-add round trip; the caller charges it as
    cost_r(t)*extra_rt_units. Bank signal selects only WHEN to bank; re-add is
    always the next-new-HWM event (spec: resumption proven).
    """
    highs, lows = bars["high"], bars["low"]
    e, sl0, tp, risk = tr["entry"], tr["sl"], tr["tp"], tr["risk"]
    is_long = tr["dir"] == "BUY"
    rng = abs(tp - e)
    L1, L2, L3 = 0.382, 0.618, 0.886
    lvl_price = lambda fr: e + fr * rng if is_long else e - fr * rng
    r_of = lambda px: ((px - e) / risk) if is_long else ((e - px) / risk)

    sl, level, vol, realized = sl0, 0, 1.0, 0.0
    trail = (L3 - L2) * rng
    hwm = None
    ov_state = "ARMED"          # ARMED -> BANKED -> (re-add) ARMED ... / DONE
    banked_vol = 0.0
    cycles = 0
    extra_rt_units = 0.0
    n = len(highs)
    for k in range(tr["fill_idx"], n):
        hi, lo = highs[k], lows[k]
        if (is_long and lo <= sl) or (not is_long and hi >= sl):
            return realized + vol * r_of(sl), extra_rt_units
        reach = (hi - e) / rng if is_long else (e - lo) / rng
        if level < 1 and reach >= L1:
            sl, level = e, 1
        if level < 2 and reach >= L2:
            realized += 0.30 * vol * r_of(lvl_price(L2))
            vol *= 0.70
            sl, level = lvl_price(L1), 2
        if level < 3 and reach >= L3:
            realized += 0.50 * vol * r_of(lvl_price(L3))
            vol *= 0.50
            sl, level = lvl_price(L2), 3
            tp = None                       # runner: drop TP
            hwm = hi if is_long else lo
        if level >= 3:
            cur_ext = hi if is_long else lo
            pull_ext = lo if is_long else hi
            if arm != "off" and cycles < max_cycles and ov_state == "ARMED":
                if _overlay_bank_signal(signal, is_long, hwm, pull_ext, g,
                                        trail, disp15, k):
                    if arm == "A":
                        bank_px = (hwm - g * trail) if is_long else (hwm + g * trail)
                        realized += f * vol * r_of(bank_px)
                        banked_vol = f * vol
                        vol *= (1 - f)
                        ov_state = "BANKED"
                        if trace is not None:
                            trace.append(("bank", k, bank_px))
                    elif arm == "C":
                        trail = TIGHT_TRAIL * rng
                        ov_state = "DONE"
                        if trace is not None:
                            trace.append(("tighten", k, trail))
            if arm == "A" and ov_state == "BANKED":
                new_hwm = (cur_ext > hwm) if is_long else (cur_ext < hwm)
                if new_hwm:
                    realized -= banked_vol * r_of(cur_ext)   # re-add basis = cur_ext
                    vol += banked_vol
                    extra_rt_units += banked_vol
                    banked_vol = 0.0
                    cycles += 1
                    ov_state = "ARMED"
                    if trace is not None:
                        trace.append(("readd", k, cur_ext))
            hwm = max(hwm, hi) if is_long else min(hwm, lo)
        if tp is not None and ((is_long and hi >= tp) or (not is_long and lo <= tp)):
            return realized + vol * r_of(tp), extra_rt_units
        if level >= 3:
            cand = (hi - trail) if is_long else (lo + trail)
            if (is_long and cand > sl) or (not is_long and cand < sl):
                sl = cand
    return realized + vol * 0.0, extra_rt_units


def _overlay_bank_signal(signal, is_long, hwm, pull_ext, g, trail, disp15, k):
    """Return True if a bank should fire on bar k. giveback: retrace >= g*trail
    from HWM. m15disp: an opposing (counter-core) M15 displacement in bar k."""
    if signal == "giveback":
        give = (hwm - pull_ext) if is_long else (pull_ext - hwm)
        return give >= g * trail
    if signal == "m15disp":
        if disp15 is None:
            return False
        return bool(disp15["bear"][k] if is_long else disp15["bull"][k])
    return False


# ---------------------------------------------------------------- analytics
def wilson(w, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = w / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den
    return p, max(0.0, c - m), min(1.0, c + m)


def cost_r(tr, sym, specs, spread_mult=1.0):
    """Round-trip cost in R for this trade (spread + commission vs risk size)."""
    spec = specs.get(sym, {})
    tick = float(spec.get("tick_size") or 0) or 1e-5
    tv = float(spec.get("tick_value") or 0) or 1.0
    spread = SPREADS.get(sym, 20) * spread_mult * tick        # price units
    # commission in price units for 1 lot: $7 / tick_value = ticks -> price
    comm = (COMMISSION_USD_PER_LOT / tv) * tick
    return (spread + comm) / tr["risk"]


def block(rows, label):
    n = len(rows)
    if n == 0:
        print(f"  {label:22} n=0")
        return
    wins = sum(1 for t in rows if t["_net_r"] > 0)
    tot = sum(t["_net_r"] for t in rows)
    exp = tot / n
    gw = sum(t["_net_r"] for t in rows if t["_net_r"] > 0)
    gl = abs(sum(t["_net_r"] for t in rows if t["_net_r"] < 0))
    pf = gw / gl if gl else float("inf")
    p, lo, hi = wilson(wins, n)
    eq = pk = dd = 0.0
    for t in rows:
        eq += t["_net_r"]; pk = max(pk, eq); dd = max(dd, pk - eq)
    print(f"  {label:22} n={n:5d} win={p*100:4.1f}% CI[{lo*100:.0f}-{hi*100:.0f}] "
          f"exp={exp:+.3f}R totR={tot:+7.1f} PF={pf:4.2f} DD={dd:.0f}R"
          f"{'  [n<30]' if n < 30 else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--tf", default="M5", choices=["M5", "M15", "H1"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    syms = [a.sym] if a.sym else SYMS
    if a.out is None:
        a.out = f"data/history/sb_stops_trades_{a.tf}.csv"
    print(f"### SilverBullet stop-model study — timeframe {a.tf} ###\n", flush=True)

    with open("data/specs.json") as f:
        specs = json.load(f)

    all_trades = []
    bars_by_sym = {}
    for sym in syms:
        t0 = _t.time()
        got = collect_signals(sym, quick=a.quick, tf=a.tf)
        if got[0] is None:
            print(f"[SKIP] {sym}: no data file")
            continue
        signals, bars = got
        bars_by_sym[sym] = bars
        line = [f"[{sym}] {len(signals)} signals"]
        for model in STOP_MODELS:
            trades = resolve(signals, bars, model)
            for t in trades:
                t["sym"] = sym
            all_trades += trades
            line.append(f"{model}:{len(trades)}")
        print("  ".join(line) + f"  ({_t.time()-t0:.0f}s)", flush=True)

    df = pd.DataFrame(all_trades)
    if df.empty:
        print("No trades.")
        return
    df.to_csv(a.out, index=False)
    print(f"\n[CSV] {len(df)} trade records -> {a.out}\n")

    trades_by = {m: [t for t in all_trades if t["model"] == m] for m in STOP_MODELS}

    # ---- 1. Stop-model table: gross and net (1x spreads), pooled all-hours
    print("=" * 88)
    print("1. STOP MODELS — pooled, all hours, 3yr, one-open-per-symbol (net = 1x spreads+comm)")
    print("=" * 88)
    for m in STOP_MODELS:
        ts = trades_by[m]
        med_risk_atr = float(np.median([t["risk"] / t["atr"] for t in ts])) if ts else 0
        for t in ts:
            t["_net_r"] = t["r"]                       # gross
        print(f"model={m}  (median risk = {med_risk_atr:.2f} ATR)")
        block(ts, "GROSS")
        for t in ts:
            t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs)
        block(ts, "NET 1.0x spread")
        for t in ts:
            t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs, 1.5)
        block(ts, "NET 1.5x spread")
        for t in ts:
            t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs, 2.0)
        block(ts, "NET 2.0x spread")
        print()

    # ---- 2. Timing windows on the best-net model (decide from table 1 output)
    print("=" * 88)
    print("2. BROKER-HOUR WINDOWS per model (NET 1x), incl. prior H05-07 / H04-08 candidates")
    print("=" * 88)
    windows = [("H05-07", 5, 7), ("H04-08", 4, 8), ("H10-12", 10, 12),
               ("H13-17", 13, 17), ("H16-18", 16, 18), ("all", 0, 24)]
    for m in STOP_MODELS:
        ts = trades_by[m]
        for t in ts:
            t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs)
        print(f"model={m}")
        for name, s, e in windows:
            block([t for t in ts if s <= t["hour"] < e], name)
        print()

    # ---- 3. OOS split + per-year for each model in the best window family
    print("=" * 88)
    print("3. TRAIN/TEST (70/30 chronological) + YEARLY — NET 1x, window H04-08 and all-hours")
    print("=" * 88)
    for m in STOP_MODELS:
        for wname, s, e in [("H04-08", 4, 8), ("all", 0, 24)]:
            ts = sorted([t for t in trades_by[m] if s <= t["hour"] < e],
                        key=lambda t: t["time"])
            for t in ts:
                t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs)
            k = int(len(ts) * 0.7)
            print(f"model={m} window={wname}")
            block(ts[:k], "TRAIN")
            block(ts[k:], "TEST (OOS)")
            for y in sorted({t["year"] for t in ts}):
                block([t for t in ts if t["year"] == y], f"year {y}")
            print()

    # ---- 4. Management replay (ratchet vs fixed vs runner) on each model, all hours NET
    print("=" * 88)
    print("4. EXIT MODELS — fixed 2R vs v14.4 ratchet vs ratchet+runner (NET 1x, all hours)")
    print("=" * 88)
    for m in STOP_MODELS:
        ts = trades_by[m]
        print(f"model={m}")
        for t in ts:
            t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs)
        block(ts, "FIXED 2R")
        for t in ts:
            t["_net_r"] = replay_managed(t, bars_by_sym[t["sym"]]) - cost_r(t, t["sym"], specs)
        block(ts, "RATCHET")
        for t in ts:
            t["_net_r"] = replay_managed(t, bars_by_sym[t["sym"]], runner=True) - cost_r(t, t["sym"], specs)
        block(ts, "RATCHET+RUNNER")
        print()

    # ---- 5. Grading gate impact (offline scoring mirror of SignalGrader), NET 1x
    print("=" * 88)
    print("5. GRADING GATE — NET 1x, all hours, per stop model")
    print("=" * 88)
    KZ = [(2, 5), (7, 11), (13, 16)]
    def grade(t):
        s = 0
        if (t["bias"] == "BULLISH" and t["dir"] == "BUY") or \
           (t["bias"] == "BEARISH" and t["dir"] == "SELL"):
            s += 30
        elif t["bias"] == "NEUTRAL":
            s += 10
        s += 15                                        # RR 2.0 fixed
        ba = t["body_atr"]
        s += 20 if ba >= 1.5 else (15 if ba >= 1.0 else (10 if ba >= 0.8 else 0))
        st = t["liq_status"]
        if (t["dir"] == "BUY" and st == "DISCOUNT") or (t["dir"] == "SELL" and st == "PREMIUM"):
            s += 15
        elif st in ("", "EQ", None):
            s += 5
        ny = (t["hour"] + NY_SHIFT) % 24
        if any(a_ <= ny < b_ for a_, b_ in KZ):
            s += 15
        return "A++" if s >= 90 else "A+" if s >= 80 else "A" if s >= 70 else "B" if s >= 55 else "C"
    for m in STOP_MODELS:
        ts = trades_by[m]
        for t in ts:
            t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs)
            t["_grade"] = grade(t)
        print(f"model={m}")
        block(ts, "no gate")
        order = {"C": 0, "B": 1, "A": 2, "A+": 3, "A++": 4}
        for floor in ["B", "A", "A+"]:
            block([t for t in ts if order[t["_grade"]] >= order[floor]], f">= {floor}")
        print()

    print("[DONE]")


if __name__ == "__main__":
    main()
