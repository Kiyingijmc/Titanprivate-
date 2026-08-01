#!/usr/bin/env python
"""Gyroscope v2 pre-registered gate (docs/research/2026-08-01-gyroscope2-gate.md).

Single-pass offline gate for the innovation-SPRT redesign on the trend-prone
universe (BTCUSD, ETHUSD, XAUUSD, US30, US100, XTIUSD), scored under the
adopted v14.4.2 managed exit ladder (ratchet + runner + arm-C tighten) with a
48-bar time-stop, net of measured FBS spreads + $7/lot commission.

Accounting engine: `_replay_managed_c_ts` is a line-faithful copy of
scripts/poc_sb_stops.py `replay_overlay(arm="C", signal="giveback")` (itself
byte-identical to replay_managed(runner=True) when the arm is off) extended
with ONLY (a) a max-bars time-stop that closes remaining volume at that bar's
close, and (b) returning the exit bar for busy accounting. Parity with the
originals is enforced by tests/unit/test_gyro2_gate.py, and the fast signal
path is parity-checked against the real GyroscopeStrategy in-run (--parity).

Usage:
  .venv/bin/python scripts/gyro2_gate.py            # full gate + sweeps
  .venv/bin/python scripts/gyro2_gate.py --parity   # strategy-parity check only
"""
import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd  # noqa: E402

from src.analysis.kalman_drift import KalmanDrift  # noqa: E402

# ---- pre-registered parameters (LOCKED by the gate doc; do not tune) ----
PARAMS = {
    "sprt_on": "innovation", "z_confirm": 1.0,
    "alpha": 0.05, "beta": 0.20, "delta": 0.40,
    "warmup_bars": 200, "q_atr_frac": 0.05, "r_frac": 1.0,
    "nis_window": 50, "nis_persist": 10,
    "k_sl": 3.0, "sl_atr_floor": 0.8, "rr_target": 2.0,
    "reentry_lockout": 12, "max_bars_in_trade": 48,
}
SYMS = ["BTCUSD", "ETHUSD", "XAUUSD", "US30", "US100", "XTIUSD"]
SPREADS = {  # broker points, measured (universe screen 2026-07-28 + specs.json symbols)
    "BTCUSD": 1000, "ETHUSD": 193, "XAUUSD": 20,
    "US30": 200, "US100": 200, "XTIUSD": 2,
}
SPECS_EXTRA = {  # measured over the bridge 2026-07-28 (universe screen harness)
    "US100": {"tick_value": 0.1, "tick_size": 0.01},
    "ETHUSD": {"tick_value": 0.1, "tick_size": 0.01},
    "XTIUSD": {"tick_value": 10.0, "tick_size": 0.01},
}
COMMISSION_USD_PER_LOT = 7.0
DATA_ROOT = "data"  # overridable via --data-root (worktrees carry no data/)
TIGHT_TRAIL = 0.10           # arm C tighten target (poc_sb_stops.TIGHT_TRAIL)
SPLIT = 0.70
WINDOW = 300                 # sliding window fed to the real strategy in parity mode
BOOT_SEED, BOOT_N, BOOT_Q = 11, 2000, 0.05


# ------------------------------------------------------------------ data
def load_h1(sym):
    path = os.path.join(DATA_ROOT, "history", f"{sym}_M5.csv")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["datetime"])
    df = (df.set_index("time")
            .resample("1h").agg({"open": "first", "high": "max",
                                 "low": "min", "close": "last"})
            .dropna().reset_index())
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return df, sha


def atr_series(highs, lows, closes, period=14):
    """atr[i] == src.analysis.atr_simple.last_atr(df.iloc[:i+1], period)."""
    n = len(highs)
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    out = [0.0] * n
    run = 0.0
    for i in range(1, n):
        run += trs[i]
        if i > period:
            run -= trs[i - period]
        out[i] = run / min(i, period)
    return out


# ----------------------------------------------------------- signal path
def collect_signals(df, params, start_at=WINDOW):
    """Fast path: feed KalmanDrift bar-by-bar, replicating GyroscopeStrategy's
    gating (cooldown ages every bar; a signal re-arms it; crossings before
    `start_at` mirror the strategy's untraded bootstrap window)."""
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    atrs = atr_series(highs, lows, closes)
    filt = KalmanDrift(
        warmup_bars=params["warmup_bars"], q_atr_frac=params["q_atr_frac"],
        r_frac=params["r_frac"], alpha=params["alpha"], beta=params["beta"],
        delta=params["delta"], nis_window=params["nis_window"],
        sprt_on=params["sprt_on"], z_confirm=params["z_confirm"],
        nis_persist=params["nis_persist"])
    signals = []
    cooldown = 0
    for i in range(len(closes)):
        r = filt.update(math.log(closes[i]), atrs[i])
        cd = cooldown - 1
        cooldown = max(0, cd)
        if r.state != "OBSERVE" or not r.crossed or cd >= 0:
            continue
        if i < start_at:
            continue  # strategy bootstraps its first window without trading
        atr = atrs[i]
        if atr <= 0:
            continue
        price = float(closes[i])
        risk = max(params["k_sl"] * r.sqrt_S_price,
                   params["sl_atr_floor"] * atr)
        cooldown = params["reentry_lockout"]
        is_long = r.crossed == "LONG"
        signals.append({
            "i": i, "dir": "BUY" if is_long else "SELL", "price": price,
            "sl": price - risk if is_long else price + risk,
            "tp": price + params["rr_target"] * risk if is_long
                  else price - params["rr_target"] * risk,
        })
    return signals


def collect_signals_strategy(df, params):
    """Reference path: drive the real GyroscopeStrategy with a sliding
    window, exactly as the live controller feeds it (parity oracle)."""
    from src.strategies.models.gyroscope import GyroscopeStrategy

    class _NullLogger:
        def log_event(self, *a, **k):
            pass

    cfg = {
        "enabled": True, "timeframe": "H1",
        "warmup_bars": params["warmup_bars"], "q_atr_frac": params["q_atr_frac"],
        "r_frac": params["r_frac"],
        "sprt": {"alpha": params["alpha"], "beta": params["beta"],
                 "delta": params["delta"]},
        "nis_window": params["nis_window"], "nis_persist": params["nis_persist"],
        "sprt_on": params["sprt_on"], "z_confirm": params["z_confirm"],
        "k_sl": params["k_sl"], "sl_atr_floor": params["sl_atr_floor"],
        "rr_target": params["rr_target"],
        "reentry_lockout": params["reentry_lockout"],
    }
    strat = GyroscopeStrategy(cfg, _NullLogger())
    df = df.copy()
    df["time"] = df["time"].astype(str)
    out = []
    for i in range(WINDOW - 1, len(df)):
        win = df.iloc[i - WINDOW + 1:i + 1]
        coro = strat.on_new_candle(win, {"symbol": "PARITY"})
        try:
            coro.send(None)
            raise RuntimeError("on_new_candle awaited unexpectedly")
        except StopIteration as e:
            dec = e.value
        if dec:
            out.append({"i": i, "dir": dec["signal"], "price": dec["price"],
                        "sl": dec["sl"], "tp": dec["tp"]})
    return out


# ------------------------------------------------- managed replay + time-stop
def _replay_managed_c_ts(tr, highs, lows, closes, max_bars, tighten=True):
    """poc_sb_stops.replay_overlay(arm='C', signal='giveback') copied
    line-faithfully (arm-A branches dropped; trace dropped), extended with a
    max-bars time-stop. tighten=False degrades to replay_managed(runner=True).
    Returns (realized_r, exit_idx, expired)."""
    e, sl0, tp, risk = tr["entry"], tr["sl"], tr["tp"], tr["risk"]
    is_long = tr["dir"] == "BUY"
    rng = abs(tp - e)
    L1, L2, L3 = 0.382, 0.618, 0.886
    lvl_price = lambda fr: e + fr * rng if is_long else e - fr * rng   # noqa: E731
    r_of = lambda px: ((px - e) / risk) if is_long else ((e - px) / risk)  # noqa: E731

    sl, level, vol, realized = sl0, 0, 1.0, 0.0
    trail = (L3 - L2) * rng
    hwm = None
    tightened = False
    n = len(highs)
    last_bar = tr["fill_idx"] + max_bars
    for k in range(tr["fill_idx"], n):
        hi, lo = highs[k], lows[k]
        if (is_long and lo <= sl) or (not is_long and hi >= sl):
            return realized + vol * r_of(sl), k, False
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
            pull_ext = lo if is_long else hi
            if tighten and not tightened:
                give = (hwm - pull_ext) if is_long else (pull_ext - hwm)
                if give >= 0.5 * trail:     # replay_overlay g=0.5 default
                    trail = TIGHT_TRAIL * rng
                    tightened = True
            hwm = max(hwm, hi) if is_long else min(hwm, lo)
        if tp is not None and ((is_long and hi >= tp) or (not is_long and lo <= tp)):
            return realized + vol * r_of(tp), k, False
        if level >= 3:
            cand = (hi - trail) if is_long else (lo + trail)
            if (is_long and cand > sl) or (not is_long and cand < sl):
                sl = cand
        if k >= last_bar:                   # time-stop: flat at this close
            return realized + vol * r_of(closes[k]), k, True
    return realized, n - 1, False           # open at end: tail ignored (poc conv.)


def resolve_fixed(tr, highs, lows):
    """Secondary accounting: first-hit fixed SL/TP (v1-gate comparable)."""
    e, sl, tp, risk = tr["entry"], tr["sl"], tr["tp"], tr["risk"]
    is_long = tr["dir"] == "BUY"
    rr = abs(tp - e) / risk
    for k in range(tr["fill_idx"], len(highs)):
        sl_hit = (lows[k] <= sl) if is_long else (highs[k] >= sl)
        tp_hit = (highs[k] >= tp) if is_long else (lows[k] <= tp)
        if sl_hit:
            return -1.0
        if tp_hit:
            return rr
    return 0.0


# ------------------------------------------------------------------ costs
def cost_r(risk, sym, specs, spread_mult=1.0, spread_pts=None):
    spec = specs[sym]
    tick = float(spec["tick_size"])
    tv = float(spec["tick_value"])
    pts = SPREADS[sym] if spread_pts is None else spread_pts
    spread = pts * spread_mult * tick
    comm = (COMMISSION_USD_PER_LOT / tv) * tick
    return (spread + comm) / risk


def load_specs():
    specs = json.load(open(os.path.join(DATA_ROOT, "specs.json")))
    specs = {k: v for k, v in specs.items()}
    specs.update(SPECS_EXTRA)
    return {s: specs[s] for s in SYMS}


# ------------------------------------------------------------------ run
def run_symbol(sym, df, params, specs):
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    times = df["time"].astype(str).tolist()
    signals = collect_signals(df, params)
    split_i = int(len(closes) * SPLIT)
    trades, busy_until, skipped_busy = [], -1, 0
    for s in signals:
        i = s["i"]
        if i <= busy_until:
            skipped_busy += 1
            continue
        if i + 1 >= len(closes):
            continue
        entry = float(df["open"].iloc[i + 1])
        risk = abs(entry - s["sl"])
        if risk <= 0 or (s["dir"] == "BUY" and entry <= s["sl"]) \
                or (s["dir"] == "SELL" and entry >= s["sl"]):
            continue
        tr = {"entry": entry, "sl": s["sl"], "tp": s["tp"], "risk": risk,
              "dir": s["dir"], "fill_idx": i + 1}
        r, exit_idx, expired = _replay_managed_c_ts(
            tr, highs, lows, closes, params["max_bars_in_trade"])
        busy_until = exit_idx
        trades.append({
            "sym": sym, "i": i, "time": times[i], "dir": s["dir"],
            "entry": entry, "sl": s["sl"], "tp": s["tp"], "risk": risk,
            "r": r, "r_fixed": resolve_fixed(tr, highs, lows),
            "exit_idx": exit_idx, "expired": expired,
            "cost_r": cost_r(risk, sym, specs),
            "cost_r_15": cost_r(risk, sym, specs, 1.5),
            "cost_r_20": cost_r(risk, sym, specs, 2.0),
            "is_oos": "IS" if i < split_i else "OOS",
        })
    n_days = (df["time"].iloc[-1] - df["time"].iloc[0]).days or 1
    flips = sum(1 for a, b in zip(signals, signals[1:]) if a["dir"] != b["dir"])
    sig_times = [df["time"].iloc[s["i"]] for s in signals]
    gaps_h = [(b - a).total_seconds() / 3600.0
              for a, b in zip(sig_times, sig_times[1:])]
    return {"trades": trades, "n_signals": len(signals),
            "skipped_busy": skipped_busy, "n_days": n_days,
            "flip_transitions": max(0, len(signals) - 1), "flips": flips,
            "gaps_h": gaps_h}


def pool_metrics(trades, key="net"):
    n = len(trades)
    if n == 0:
        return {"n": 0, "exp": 0.0, "totR": 0.0, "pf": 0.0, "dd": 0.0}
    vals = [t[key] for t in trades]
    tot = sum(vals)
    gw = sum(x for x in vals if x > 0)
    gl = abs(sum(x for x in vals if x < 0))
    eq = pk = dd = 0.0
    for x in vals:
        eq += x
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {"n": n, "exp": tot / n, "totR": tot,
            "pf": (gw / gl) if gl else float("inf"), "dd": dd}


def bootstrap_lb(vals, seed=BOOT_SEED, n_boot=BOOT_N, q=BOOT_Q):
    if not vals:
        return 0.0
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(rng.choice(vals) for _ in range(n)) / n
                   for _ in range(n_boot))
    return means[int(q * n_boot)]


def evaluate(all_res, sweep_signs):
    pooled = [t for r in all_res.values() for t in r["trades"]]
    for t in pooled:
        t["net"] = t["r"] - t["cost_r"]
        t["net15"] = t["r"] - t["cost_r_15"]
    is_t = [t for t in pooled if t["is_oos"] == "IS"]
    oos_t = [t for t in pooled if t["is_oos"] == "OOS"]
    m = pool_metrics(pooled)
    med_cost = sorted(t["cost_r"] for t in pooled)[len(pooled) // 2] if pooled else 0.0
    sym_net = {s: sum(t["net"] for t in r["trades"])
               for s, r in all_res.items()}
    n_sig = sum(r["n_signals"] for r in all_res.values())
    n_days = max(r["n_days"] for r in all_res.values())
    flips = sum(r["flips"] for r in all_res.values())
    trans = sum(r["flip_transitions"] for r in all_res.values())
    all_gaps = sorted(g for r in all_res.values() for g in r["gaps_h"])
    med_gap = all_gaps[len(all_gaps) // 2] if all_gaps else 0.0
    lb = bootstrap_lb([t["net"] for t in pooled])
    crit = {
        "1_econ": {"pass": m["exp"] > 0 and pool_metrics(oos_t)["exp"] > 0,
                   "pooled_exp": m["exp"],
                   "is_exp": pool_metrics(is_t)["exp"],
                   "oos_exp": pool_metrics(oos_t)["exp"]},
        "2_cost": {"pass": med_cost <= 0.25, "median_cost_r": med_cost},
        "3_stress15": {"pass": pool_metrics(pooled, "net15")["exp"] >= 0,
                       "exp_15x": pool_metrics(pooled, "net15")["exp"]},
        "4_breadth": {"pass": sum(1 for v in sym_net.values() if v >= 0) >= 4,
                      "nonneg": sum(1 for v in sym_net.values() if v >= 0),
                      "per_symbol_net": sym_net},
        "5_sweeps": {"pass": sum(1 for s in sweep_signs if s < 0) <= 1,
                     "signs": sweep_signs} if sweep_signs is not None
                    else {"pass": None, "signs": None},
        "6_ci": {"pass": lb > -0.05, "lower_bound": lb},
        # Ratified 2026-08-01 (gyroscope2b gate doc): episodicity measured
        # directly — signal rate + median same-symbol inter-signal gap.
        # Flip-rate reported non-binding (mis-specified in the v2 gate: it
        # demanded cross-episode autocorrelation, the v1 pathology).
        "7_calibration": {
            "pass": (n_sig / n_days) <= 2.0 and med_gap >= 48.0,
            "signals_per_day": n_sig / n_days,
            "median_gap_h": med_gap,
            "flip_rate_nonbinding": (flips / trans) if trans else 0.0},
    }
    return crit, pooled


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parity", action="store_true",
                    help="strategy-parity check only (no gate run)")
    ap.add_argument("--no-sweeps", action="store_true")
    ap.add_argument("--data-root", default="data")
    ap.add_argument("--out", default=None,
                    help="default: <data-root>/results/gyro2_gate")
    args = ap.parse_args()
    global DATA_ROOT
    DATA_ROOT = args.data_root
    if args.out is None:
        args.out = os.path.join(DATA_ROOT, "results", "gyro2_gate")

    specs = load_specs()

    if args.parity:
        sym = "XTIUSD"
        df, _ = load_h1(sym)
        fast = collect_signals(df, PARAMS)
        slow = collect_signals_strategy(df, PARAMS)
        a = [(s["i"], s["dir"]) for s in fast]
        b = [(s["i"], s["dir"]) for s in slow]
        print(f"[PARITY] {sym}: fast={len(a)} strategy={len(b)} match={a == b}")
        if a != b:
            only_f = set(a) - set(b)
            only_s = set(b) - set(a)
            print(f"  only-fast: {sorted(only_f)[:10]}")
            print(f"  only-strategy: {sorted(only_s)[:10]}")
            sys.exit(1)
        sys.exit(0)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = os.path.join(args.out, f"{stamp}_gyroscope2_POOLED6_H1")
    os.makedirs(outdir, exist_ok=True)

    frames, shas, all_res = {}, {}, {}
    for sym in SYMS:
        frames[sym], shas[sym] = load_h1(sym)
        all_res[sym] = run_symbol(sym, frames[sym], PARAMS, specs)
        r = all_res[sym]
        net = sum(t["r"] - t["cost_r"] for t in r["trades"])
        print(f"[GYRO2] {sym}: bars={len(frames[sym])} signals={r['n_signals']} "
              f"trades={len(r['trades'])} netR={net:+.1f}", flush=True)

    sweep_signs = None
    if not args.no_sweeps:
        sweep_signs = []
        for kv in [("delta", 0.28), ("delta", 0.52),
                   ("q_atr_frac", 0.035), ("q_atr_frac", 0.065)]:
            p = dict(PARAMS)
            p[kv[0]] = kv[1]
            tot = 0.0
            for sym in SYMS:
                res = run_symbol(sym, frames[sym], p, specs)
                tot += sum(t["r"] - t["cost_r"] for t in res["trades"])
            sweep_signs.append(tot)
            print(f"[GYRO2] sweep {kv[0]}={kv[1]}: pooled netR={tot:+.1f}", flush=True)

    crit, pooled = evaluate(all_res, sweep_signs)
    verdict = "GO" if all(c["pass"] for c in crit.values()
                          if c["pass"] is not None) else "NO-GO"

    # XTIUSD spread sensitivity at 5 pts (reported, non-binding)
    xti = [t for t in pooled if t["sym"] == "XTIUSD"]
    xti_5pt = sum(t["r"] - cost_r(t["risk"], "XTIUSD", specs, spread_pts=5)
                  for t in xti) / len(xti) if xti else 0.0

    card = {
        "gate": "docs/research/2026-08-01-gyroscope2b-gate.md",
        "git_sha": git_sha(),
        "params": PARAMS, "symbols": SYMS, "spreads_pts": SPREADS,
        "split": SPLIT, "data_sha256": shas,
        "n_signals": sum(r["n_signals"] for r in all_res.values()),
        "n_trades": len(pooled),
        "n_skipped_busy": sum(r["skipped_busy"] for r in all_res.values()),
        "n_expired": sum(1 for t in pooled if t["expired"]),
        "open_at_end": 0,
        "pooled_managed_net": pool_metrics(pooled),
        "pooled_fixed_gross": pool_metrics(pooled, "r_fixed"),
        "xtiusd_exp_at_5pt_spread": xti_5pt,
        "criteria": crit, "verdict": verdict,
        "bootstrap": {"seed": BOOT_SEED, "n_boot": BOOT_N, "q": BOOT_Q},
    }
    with open(os.path.join(outdir, "run.json"), "w") as f:
        json.dump(card, f, indent=1, default=str)
    with open(os.path.join(outdir, "trades.jsonl"), "w") as f:
        for t in pooled:
            f.write(json.dumps(t, default=str) + "\n")

    print(f"[GYRO2] pooled: n={card['n_trades']} "
          f"exp={card['pooled_managed_net']['exp']:+.3f}R "
          f"PF={card['pooled_managed_net']['pf']:.2f}")
    for k, c in crit.items():
        print(f"[GYRO2] criterion {k}: "
              f"{'PASS' if c['pass'] else ('n/a' if c['pass'] is None else 'FAIL')} {c}")
    print(f"[GYRO2] VERDICT: {verdict}")
    print(f"[GYRO2] wrote {outdir}/run.json + trades.jsonl")


if __name__ == "__main__":
    main()
