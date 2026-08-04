#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/poc_gambit.py
# Gambit playbook — offline signal collection + resolution (spec 2026-08-02).
# Imports the LIVE detector functions (gambit_setups) so research and live
# logic cannot drift. Session windows/ranges mirror config/config.yaml gambit.
# NY conversion: fixed NY_SHIFT like poc_sb_stops (+/-1h DST wobble accepted,
# same as the 2026-07-11 study).
#
#   .venv/bin/python scripts/poc_gambit.py                     # gate universe
#   .venv/bin/python scripts/poc_gambit.py --quick --syms US30
#   .venv/bin/python scripts/poc_gambit.py --override body_min_atr=1.04
# ==============================================================================
import argparse
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.analysis.smc_analyzer import SMCAnalyzer                 # noqa: E402
from src.analysis.bias_engine import BiasEngine                    # noqa: E402
from src.strategies.models.gambit_setups import (                  # noqa: E402
    compute_presession_range, detect_judas, detect_reprise)
from scripts.poc_sb_stops import SPREADS, COMMISSION_USD_PER_LOT   # noqa: E402,F401

GATE_SYMS = ["US30", "US100", "XAUUSD", "BTCUSD"]
ARM_SYMS = ["ETHUSD", "XTIUSD"]
NY_SHIFT = -7                    # broker -> NY approx (poc_sb_stops convention)
RR = 2.0
TTL_BARS = 12                    # limit fill TTL (bars after signal bar)
TAIL = 320                       # bars handed to the detectors (chassis _TAIL)
BASE_CFG = {"sweep_ttl_bars": 12, "body_min_atr": 0.8,
            "stop_buffer_atr": 0.2, "rr": RR}

SESSIONS = {                     # minutes-since-midnight NY; mirror config.yaml
    "london": {"window": (120, 300), "range": (1080, 120)},
    "ny_am": {"window": (510, 660), "range": (120, 510)},
}
SYMBOL_SESSIONS = {
    "US30": ["ny_am"], "US100": ["ny_am"],
    "XAUUSD": ["london", "ny_am"], "BTCUSD": ["london", "ny_am"],
    "ETHUSD": ["london", "ny_am"], "XTIUSD": ["ny_am"],
}
# v14.4 ratchet levels (trade_manager.py)
L1, L2, L3 = 0.382, 0.618, 0.886
RUNNER_TRAIL = 0.268


def load_enriched(sym, quick):
    path = f"data/history/{sym}_M5.csv"
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    df = df.rename(columns={"datetime": "time"})
    enr = SMCAnalyzer(df.copy()).process()
    enr["time"] = pd.to_datetime(enr["time"])
    return enr


def make_bias_fn(enr):
    """H1-resampled BiasEngine, cached per closed-H1 count (poc pattern)."""
    h1 = (enr.set_index("time")
             .resample("1h").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"})
             .dropna().reset_index())
    h1_times = h1["time"].values
    cache = {}

    def bias_at(t):
        n = int(np.searchsorted(h1_times, np.datetime64(t)))
        if n not in cache:
            cache[n] = (BiasEngine(h1.iloc[max(0, n - 100):n])
                        .get_bias_context()[0] if n > 20 else "NEUTRAL")
        return cache[n]
    return bias_at


def collect(sym, cfg, quick=False):
    """Walk every M5 bar through the live detector path. Returns signal list
    + bar arrays for resolution."""
    enr = load_enriched(sym, quick)
    if enr is None:
        return None, None
    ny = enr["time"] + timedelta(hours=NY_SHIFT)
    ny_min = (ny.dt.hour * 60 + ny.dt.minute).values
    ny_date = ny.dt.date.values
    ny_py = list(ny.dt.to_pydatetime())          # naive; fine for the pure fns
    cols = {c: enr[c].values for c in
            ("open", "high", "low", "close", "ATR",
             "is_fvg_bull", "is_fvg_bear", "fvg_top", "fvg_bottom")}
    n = len(enr)
    signals = []
    fired = set()          # (session, date) -> one intent per symbol/session/day
                            # across BOTH setups, matching gambit.py._fired
    bias_at = make_bias_fn(enr)

    # Candidate mask: displacement body + FVG (cheap prefilter — the ONLY
    # bars either detector can fire on; everything else returns None).
    body = np.abs(cols["close"] - cols["open"])
    cand = ((cols["is_fvg_bull"] | cols["is_fvg_bear"])
            & (cols["ATR"] > 0)
            & (body >= cfg["body_min_atr"] * cols["ATR"]))
    cand[:TAIL] = False

    for i in np.where(cand)[0]:
        sname = None
        for name in SYMBOL_SESSIONS[sym]:
            w = SESSIONS[name]["window"]
            if w[0] <= ny_min[i] < w[1]:
                sname = name
                break
        if sname is None:
            continue
        key = (sname, ny_date[i])
        if key in fired:                # one intent per symbol/session/day
            continue                     # across BOTH setups (chassis parity)
        lo = i - TAIL + 1
        tail_times = ny_py[lo:i + 1]
        bars = {("atr" if k == "ATR" else k): v[lo:i + 1]
                for k, v in cols.items()}
        bias = bias_at(enr["time"].iloc[i])
        sess = SESSIONS[sname]

        for setup in ("judas", "reprise"):        # same-bar precedence
            if setup == "judas":
                rng = compute_presession_range(
                    tail_times, bars["high"], bars["low"],
                    sess["range"][0], sess["range"][1])
                intent = (detect_judas(bars, tail_times, (rng[0], rng[1]),
                                       sess["window"][0], bias, cfg)
                          if rng is not None else None)
            else:
                intent = detect_reprise(bars, bias, cfg)
            if intent is None:
                continue
            end_min = sess["window"][1]
            # Flat-by-close cap: the exit bar is the LAST bar strictly before
            # the flat boundary (11:00 / 05:00 == window end == flat_at_ny).
            j = i + 1
            while j < n:
                if ny_date[j] != ny_date[i] or ny_min[j] >= end_min:
                    break
                j += 1
            end_idx = max(i, j - 1)
            signals.append({"sym": sym, "setup": intent["setup"],
                            "session": sname, "bar_idx": int(i),
                            "time": str(enr["time"].iloc[i]),
                            "dir": intent["signal"], "entry": intent["price"],
                            "sl": intent["sl"], "tp": intent["tp"],
                            "risk": abs(intent["sl"] - intent["price"]),
                            "end_idx": int(end_idx)})
            fired.add(key)
            break                                  # one intent per bar
    bars_out = {"high": cols["high"], "low": cols["low"],
                "close": cols["close"]}
    return signals, bars_out


def resolve_fixed(sig, bars):
    """Limit fill within TTL, then SL/TP scan capped at session end
    (flat at close of end_idx bar). Same-bar SL+TP -> SL (pessimistic,
    poc convention). Returns (outcome, gross_r, fill_idx, exit_idx) or None."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    i, end = sig["bar_idx"], sig["end_idx"]
    entry, sl, tp = sig["entry"], sig["sl"], sig["tp"]
    risk = sig["risk"]
    is_long = sig["dir"] == "BUY"
    fill = None
    for k in range(i + 1, min(i + 1 + TTL_BARS, end + 1)):
        if lows[k] <= entry <= highs[k]:
            fill = k
            break
    if fill is None:
        return None
    for k in range(fill, end + 1):
        sl_hit = (lows[k] <= sl) if is_long else (highs[k] >= sl)
        tp_hit = (highs[k] >= tp) if is_long else (lows[k] <= tp)
        if sl_hit:
            return "SL", -1.0, fill, k
        if tp_hit:
            return "TP", RR, fill, k
    px = closes[end]
    r = ((px - entry) if is_long else (entry - px)) / risk
    return "FLAT", float(r), fill, end


def replay_managed_capped(sig, bars, fill):
    """v14.4 ratchet + runner, capped at session end. Mirrors trade_manager:
    L1 0.382 -> BE; L2 0.618 -> bank 30%, SL to L1; L3 0.886 -> bank 50% of
    remainder, SL to L2, drop TP, trail 0.268*range (arm-C tighten omitted:
    session-capped trades rarely reach deep runner territory; noted in the
    results doc). Bar path approx: SL checked before TP (pessimistic)."""
    highs, lows = bars["high"], bars["low"]
    entry, risk = sig["entry"], sig["risk"]
    is_long = sig["dir"] == "BUY"
    rng = RR * risk                                  # entry->TP distance
    lv = [entry + s * rng * (1 if is_long else -1) for s in (L1, L2, L3)]
    tp = sig["tp"]
    sl = sig["sl"]
    vol = 1.0
    banked = 0.0
    stage = 0
    hwm = entry
    for k in range(fill, sig["end_idx"] + 1):
        hi, lo = highs[k], lows[k]
        adverse = lo if is_long else hi
        favor = hi if is_long else lo
        hwm = max(hwm, favor) if is_long else min(hwm, favor)
        sl_hit = (adverse <= sl) if is_long else (adverse >= sl)
        if sl_hit:
            r_sl = ((sl - entry) if is_long else (entry - sl)) / risk
            return banked + vol * r_sl
        if stage >= 3:
            trail = RUNNER_TRAIL * rng
            new_sl = (hwm - trail) if is_long else (hwm + trail)
            sl = max(sl, new_sl) if is_long else min(sl, new_sl)
        else:
            if stage < 1 and ((favor >= lv[0]) if is_long else (favor <= lv[0])):
                sl, stage = entry, 1
            if stage < 2 and stage >= 1 and (
                    (favor >= lv[1]) if is_long else (favor <= lv[1])):
                r_here = ((lv[1] - entry) if is_long else (entry - lv[1])) / risk
                banked += 0.30 * vol * r_here
                vol *= 0.70
                sl, stage = lv[0], 2
            if stage == 2 and ((favor >= lv[2]) if is_long else (favor <= lv[2])):
                r_here = ((lv[2] - entry) if is_long else (entry - lv[2])) / risk
                banked += 0.50 * vol * r_here
                vol *= 0.50
                sl, stage = lv[1], 3
                tp = None
            if tp is not None and ((favor >= tp) if is_long else (favor <= tp)):
                return banked + vol * RR
    px = bars["close"][sig["end_idx"]]
    r = ((px - entry) if is_long else (entry - px)) / risk
    return banked + vol * r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", default=",".join(GATE_SYMS))
    ap.add_argument("--arms", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--override", action="append", default=[])
    ap.add_argument("--out-dir", default="data/results/gambit")
    a = ap.parse_args()
    cfg = dict(BASE_CFG)
    for ov in a.override:
        k, v = ov.split("=")
        cfg[k] = type(BASE_CFG[k])(float(v))
    syms = a.syms.split(",") + (ARM_SYMS if a.arms else [])
    os.makedirs(a.out_dir, exist_ok=True)
    rows = []
    for sym in syms:
        sigs, bars = collect(sym, cfg, quick=a.quick)
        if sigs is None:
            print(f"  {sym}: no data")
            continue
        opened = 0
        for s in sigs:
            res = resolve_fixed(s, bars)
            if res is None:
                continue
            outcome, gross, fill, exit_k = res
            managed = replay_managed_capped(s, bars, fill)
            rows.append({**{k: s[k] for k in
                            ("sym", "setup", "session", "time", "dir",
                             "entry", "sl", "tp", "risk")},
                         "outcome": outcome, "gross_r": gross,
                         "managed_r": managed, "fill_idx": fill,
                         "exit_idx": exit_k})
            opened += 1
        print(f"  {sym}: {len(sigs)} intents, {opened} filled")
    df = pd.DataFrame(rows)
    tag = "_".join(f"{k}{cfg[k]}" for k in sorted(cfg) if cfg[k] != BASE_CFG[k])
    for setup in ("judas", "reprise"):
        sub = df[df["setup"] == setup] if len(df) else df
        out = os.path.join(a.out_dir,
                           f"trades_{setup}{('_' + tag) if tag else ''}.csv")
        sub.to_csv(out, index=False)
        print(f"{setup}: n={len(sub)} -> {out}")


if __name__ == "__main__":
    main()
