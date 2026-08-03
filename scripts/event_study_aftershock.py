"""Aftershock kill-screen — IS-only event study (registered protocol).

Registered: docs/research/2026-08-01-wave2-gate-triage.md (committed
before this script existed). Reads ONLY the first 70% of each symbol's
frozen H1 lake. Never touches the OOS remainder, data/db, or the bridge.

Usage: .venv/bin/python scripts/event_study_aftershock.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.event_study_stats import (  # noqa: E402
    bootstrap_diff_ci, bootstrap_mean_ci, ols_signal_coef)
from src.analysis.hawkes_intensity import eligible_signals  # noqa: E402

SEED = 20260801
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
           "GBPJPY", "XAUUSD", "US30", "BTCUSD"]
SPREADS = {                 # verbatim from scripts/poc_sb_stops.py:43
    "EURUSD": 8, "GBPUSD": 12, "USDJPY": 10, "AUDUSD": 10, "USDCAD": 12,
    "GBPCAD": 30, "GBPJPY": 25, "XAUUSD": 20, "US30": 200, "BTCUSD": 1000, "XBRUSD": 30,
}
LAKE = "data/lake/frozen/fbs"
OUT_DIR = "data/results/aftershock_screen"
HORIZONS = (1, 4, 8, 24)
PRIMARY_H = 8
Q_GRID = (2.0, 2.5, 3.0)
HL_GRID = (12, 24, 48)
PRIMARY = (2.5, 24)
WINDOW = 200
S_LO_PCTILE = 20.0
IS_FRAC = 0.70
MIN_POOLED_N = 150
COST_MULT = 8.0

# Module-level cache for IS frames to avoid redundant parquet reads
_CACHE_IS = {}


def load_is(sym: str) -> pd.DataFrame:
    """Load IS frame for symbol, with memoization to avoid redundant parquet reads."""
    if sym in _CACHE_IS:
        return _CACHE_IS[sym]
    files = sorted(glob.glob(f"{LAKE}/{sym}/H1/*.parquet"))
    if not files:
        raise SystemExit(f"FATAL: no frozen lake files for {sym}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    cutoff = int(len(df) * IS_FRAC)
    result = df.iloc[:cutoff].reset_index(drop=True)  # OOS never leaves this function
    _CACHE_IS[sym] = result
    return result


def forward_returns(df, sig, horizon):
    """Signed forward log return from the confirm-bar close; drops rows leaving IS."""
    close = df["close"].to_numpy()
    logc = np.log(close)
    s_idx = sig["signal_idx"].to_numpy()
    keep = s_idx + horizon < len(df)
    s_idx, d = s_idx[keep], sig["direction"].to_numpy()[keep]
    y = d * (logc[s_idx + horizon] - logc[s_idx])
    return y, keep


def control_rows(df, horizon, window=WINDOW, exclude=()):
    """All-bar naive continuation cell: dir-signed forward return per bar."""
    close, opn = df["close"].to_numpy(), df["open"].to_numpy()
    logc = np.log(close)
    d = np.sign(close - opn)
    idx = np.arange(window, len(df) - 1 - horizon)
    idx = idx[d[idx] != 0]
    idx = idx[~np.isin(idx, np.asarray(exclude, dtype=int))]
    y = d[idx] * (logc[idx + 1 + horizon] - logc[idx + 1])
    hours = pd.to_datetime(df["time"]).dt.hour.to_numpy()[idx]
    return y, hours


def run_cell(q, hl, per_symbol_out=None):
    """One (q, half_life) parameter cell; returns pooled arrays + per-symbol stats."""
    rng = np.random.default_rng(SEED)
    pooled_y, pooled_sig_hours = [], []
    ctl_y, ctl_hours = [], []
    per_sym = {}
    for sym in SYMBOLS:
        df = load_is(sym)
        sig = eligible_signals(df, q=q, window=WINDOW, half_life=hl,
                               s_lo_pctile=S_LO_PCTILE)
        y8, keep = forward_returns(df, sig, PRIMARY_H)
        spread = SPREADS[sym] * SPECS[sym]["tick_size"]
        med_range = float(np.median(sig["event_range"])) if len(sig) else 0.0
        cost_alive = med_range >= COST_MULT * spread and len(sig) > 0
        stats = {
            "n_events": int(len(sig)), "n_used": int(keep.sum()),
            "mean_signed_fwd_8": float(y8.mean()) if len(y8) else float("nan"),
            "median_event_range": med_range, "spread": spread,
            "cost_alive": bool(cost_alive),
            "positive": bool(cost_alive and len(y8) and y8.mean() > 0),
        }
        if per_symbol_out is not None:
            for h in HORIZONS:
                yh, _ = forward_returns(df, sig, h)
                stats[f"mean_h{h}"] = float(yh.mean()) if len(yh) else float("nan")
            per_symbol_out[sym] = stats
        per_sym[sym] = stats
        if cost_alive:
            pooled_y.append(y8)
            pooled_sig_hours.append(sig["hour"].to_numpy()[keep])
            cy, ch = control_rows(df, PRIMARY_H,
                                  exclude=sig["event_idx"].to_numpy())
            ctl_y.append(cy)
            ctl_hours.append(ch)
    cat = (lambda parts: np.concatenate(parts) if parts else np.array([]))
    return (cat(pooled_y), cat(pooled_sig_hours), cat(ctl_y), cat(ctl_hours),
            per_sym, rng)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    global SPECS
    with open("data/specs.json") as f:
        SPECS = json.load(f)

    per_symbol = {}
    y, sig_hours, cy, chours, per_sym, rng = run_cell(*PRIMARY, per_symbol)

    n_pooled = len(y)
    pos_syms = sum(1 for s in per_sym.values() if s["positive"])
    cost_dead_symbols = sorted([sym for sym in per_sym if not per_sym[sym]["cost_alive"]])

    c5 = n_pooled >= MIN_POOLED_N
    if c5:
        m, lo, hi = bootstrap_mean_ci(y, rng)
        c1 = m > 0 and lo > 0
        dm, dlo, dhi = bootstrap_diff_ci(y, cy, rng)
        c2 = dm > 0 and dlo > 0
        ally = np.concatenate([cy, y])
        allsig = np.concatenate([np.zeros(len(cy)), np.ones(len(y))])
        allh = np.concatenate([chours, sig_hours])
        b, blo, bhi = ols_signal_coef(ally, allsig, allh, rng)
        c3 = b > 0 and blo > 0
    else:
        m = lo = hi = dm = dlo = dhi = b = blo = bhi = float("nan")
        c1 = c2 = c3 = False
    c4 = pos_syms >= 6

    criteria = {"c1_pooled_ci": bool(c1), "c2_separation": bool(c2),
                "c3_session_control": bool(c3), "c4_consistency": bool(c4),
                "c5_sample_floor": bool(c5),
                "c6_cost_dead_symbols": cost_dead_symbols}
    if not c5:
        verdict = "INSUFFICIENT-N"
    elif all([c1, c2, c3, c4]):
        verdict = "PASS"
    else:
        verdict = "NO-GO"

    robustness = []
    for q in Q_GRID:
        for hl in HL_GRID:
            ry, _, _, _, rps, rrng = run_cell(q, hl)
            if len(ry) >= 2:
                rm, rlo, rhi = bootstrap_mean_ci(ry, rrng)
            else:
                rm = rlo = rhi = float("nan")
            robustness.append({"q": q, "half_life": hl, "n": int(len(ry)),
                               "mean_h8": rm, "lo95": rlo, "hi95": rhi,
                               "primary": (q, hl) == PRIMARY})

    card = {
        "study": "aftershock_kill_screen",
        "registered": "docs/research/2026-08-01-wave2-gate-triage.md",
        "provenance": "data/lake/frozen/PROVENANCE.md",
        "params": {"q": PRIMARY[0], "half_life": PRIMARY[1], "window": WINDOW,
                   "s_lo_pctile": S_LO_PCTILE, "is_frac": IS_FRAC,
                   "primary_horizon": PRIMARY_H, "seed": SEED,
                   "cost_mult": COST_MULT, "min_pooled_n": MIN_POOLED_N},
        "pooled": {"n": n_pooled, "mean_h8": m, "lo95": lo, "hi95": hi,
                   "diff_mean": dm, "diff_lo95": dlo, "diff_hi95": dhi,
                   "ols_beta": b, "ols_lo95": blo, "ols_hi95": bhi,
                   "positive_symbols": pos_syms},
        "criteria": criteria,
        "verdict": verdict,
        "per_symbol": per_symbol,
        "robustness": robustness,
    }
    with open(f"{OUT_DIR}/run_card.json", "w") as f:
        json.dump(card, f, indent=2)
    pd.DataFrame(per_symbol).T.to_csv(f"{OUT_DIR}/per_symbol.csv")
    pd.DataFrame(robustness).to_csv(f"{OUT_DIR}/cells.csv", index=False)

    print("=" * 64)
    print(f"AFTERSHOCK KILL-SCREEN VERDICT: {verdict}")
    print(f"pooled N={n_pooled}  mean+8={m:.6f}  CI[{lo:.6f},{hi:.6f}]")
    print(f"separation diff={dm:.6f}  CI[{dlo:.6f},{dhi:.6f}]")
    print(f"session-controlled beta={b:.6f}  CI[{blo:.6f},{bhi:.6f}]")
    print(f"positive symbols: {pos_syms}/9   criteria: {criteria}")
    print("=" * 64)


if __name__ == "__main__":
    main()
