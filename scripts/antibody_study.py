#!/usr/bin/env python3
# scripts/antibody_study.py
# Antibody v1 / Task 2: walk-forward counterfactual study. Fits the Antibody
# self-model on a trailing window, rolls quarterly (no lookahead), overlays SB
# trades from ONE pooled research_run, and reports inside-alert vs
# outside-alert expectancy against the pre-registered adoption criteria.
#
#   .venv/bin/python scripts/antibody_study.py \
#       --run-dir data/results/<TS>_silver_bullet_POOLED9_H1 \
#       --out data/results
#
# Study-only: reads frozen H1 (data/lake/frozen) + a run-card; writes a
# study-card JSON + a printed report. No src/core or src/execution imports.
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.analysis.antibody import AntibodyScorer, compute_features  # noqa: E402
from src.data.lake import Lake  # noqa: E402

DEFAULT_FIT_BARS = 6000    # ~1 year of H1
DEFAULT_STEP_BARS = 1500   # ~1 quarter of H1

# Pre-registered adoption criteria (echoed into the study-card; the doc is the
# source of truth -- docs/research/2026-07-14-antibody-study.md).
CRITERIA = {
    "max_pooled_alert_rate": 0.02,
    "min_inside_trades": 30,
    "inside_must_be_negative": True,
    "min_expectancy_gap_r": 0.15,
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:  # noqa: BLE001 - provenance best-effort
        return "unknown"


def window_bounds(n_bars, fit_bars, step_bars):
    """Tile [fit_bars, n_bars) into NON-overlapping score regions, each with a
    trailing fit window of fit_bars ending where the score region begins. A tail
    shorter than step_bars stays a short final region (NOT back-pinned to a full
    step) so score regions tile [fit_bars, n_bars) exactly -- every bar is scored
    once, none twice. Back-pinning the last window would overlap the previous
    one and double-score / double-feed the tail bars into the rolling state
    machine (~337 bars/symbol at fit=6000/step=1500 on the study data)."""
    wins = []
    score_lo = fit_bars
    while score_lo < n_bars:
        score_hi = min(score_lo + step_bars, n_bars)
        wins.append((score_lo - fit_bars, score_lo, score_lo, score_hi))
        score_lo = score_hi
    return wins


def walk_forward_states(df, fit_bars=DEFAULT_FIT_BARS, step_bars=DEFAULT_STEP_BARS):
    """Roll the self-model quarterly; score every valid bar in order with ONE
    scorer (state carried across refits). Lookahead-safe: each window's fit uses
    only bars strictly before its score region."""
    feats = compute_features(df)
    times = df["time"].tolist()
    bounds = window_bounds(len(df), fit_bars, step_bars)
    states = []
    scorer = None
    for fit_lo, fit_hi, score_lo, score_hi in bounds:
        fit_feats = [f for f in feats[fit_lo:fit_hi] if f is not None]
        if len(fit_feats) < 5:
            continue  # not enough valid history yet (very early data only)
        if scorer is None:
            scorer = AntibodyScorer(fit_feats)
        else:
            scorer.refit(fit_feats)
        for k in range(score_lo, score_hi):
            f = feats[k]
            if f is None:
                continue
            r = scorer.score(f)
            states.append({"i": k, "time": times[k], "score": r.score,
                           "threshold": r.threshold, "state": r.state, "alert": r.alert})
    return states


def alert_windows(states):
    """Contiguous runs where state == 'ALERT'."""
    wins, run = [], []
    for s in states:
        if s["state"] == "ALERT":
            run.append(s)
        elif run:
            wins.append(_window_from_run(run))
            run = []
    if run:
        wins.append(_window_from_run(run))
    return wins


def _window_from_run(run):
    return {
        "start_time": run[0]["time"], "end_time": run[-1]["time"],
        "start_i": run[0]["i"], "end_i": run[-1]["i"],
        "duration": len(run), "peak_score": max(s["score"] for s in run),
    }


def classify_trades(trades, windows_by_symbol):
    out = []
    for t in trades:
        ttime = pd.to_datetime(t["time"])
        wins = windows_by_symbol.get(t["symbol"], [])
        inside = any(w["start_time"] <= ttime <= w["end_time"] for w in wins)
        out.append({**t, "inside_alert": inside})
    return out


def bucket_metrics(trades):
    resolved = [t for t in trades if t.get("outcome") in ("TP", "SL")]
    if not resolved:
        return {"n": 0, "expectancy": 0.0, "profit_factor": 0.0}
    rs = [float(t["r"]) for t in resolved]
    wins = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    pf = (wins / losses) if losses > 0 else float("inf")
    return {"n": len(resolved), "expectancy": sum(rs) / len(rs), "profit_factor": pf}


def fit_diagnostics(fit_features):
    """Degeneracy diagnostic for one fit window (carry-forward from the Task-1
    review, disclosure-C): the smallest per-feature variance and the condition
    number of the SAME eps=1e-9-ridged covariance the scorer inverts. A tiny
    min_variance / huge cov_condition means a near-constant feature dimension
    that the fixed ridge would let dominate the Mahalanobis distance and distort
    q99. Recorded per-symbol so Task 4 can verify real data is well-conditioned;
    does not change the spec-locked ridge. Mirrors the scorer's loud failure."""
    if len(fit_features) < 5:
        raise ValueError(f"antibody: need >= 5 fit samples, got {len(fit_features)}")
    x = np.asarray(fit_features, dtype=float)
    cov = np.atleast_2d(np.cov(x, rowvar=False, ddof=1)) + 1e-9 * np.eye(x.shape[1])
    return {"min_variance": float(np.var(x, axis=0, ddof=1).min()),
            "cov_condition": float(np.linalg.cond(cov))}


def _worst_fit_diag(df, feats, fit_bars, step_bars):
    """Worst-across-windows diagnostic for a symbol: min of min_variance, max of
    cov_condition over the same fit windows walk_forward_states uses."""
    worst = {"min_variance": float("inf"), "cov_condition": 0.0}
    for fit_lo, fit_hi, _score_lo, _score_hi in window_bounds(len(df), fit_bars, step_bars):
        ff = [f for f in feats[fit_lo:fit_hi] if f is not None]
        if len(ff) < 5:
            continue
        d = fit_diagnostics(ff)
        worst["min_variance"] = min(worst["min_variance"], d["min_variance"])
        worst["cov_condition"] = max(worst["cov_condition"], d["cov_condition"])
    if worst["min_variance"] == float("inf"):
        worst["min_variance"] = 0.0  # no valid window (symbol too short)
    return worst


def _load_trades(run_dir):
    """Filled SB trades from a run-card's signals.jsonl (entered the market)."""
    path = Path(run_dir) / "signals.jsonl"
    trades = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("filled"):
                trades.append(rec)
    return trades


def build_study_card(run_dir, run_card, symbols, per_symbol, pooled, top_episodes,
                     fit_bars, step_bars):
    return {
        "git_sha": _git_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "run_git_sha": run_card.get("git_sha", "unknown"),
        "fit_params": {"fit_bars": fit_bars, "step_bars": step_bars,
                       "quantile": 0.99, "atr_period": 14},
        "symbols": symbols,
        "per_symbol": per_symbol,
        "pooled": pooled,
        "top_episodes": top_episodes,
        "criteria": CRITERIA,
    }


def _build_parser():
    p = argparse.ArgumentParser(description="Antibody v1 walk-forward counterfactual study.")
    p.add_argument("--run-dir", required=True,
                   help="pooled SB research_run output dir (has run.json + signals.jsonl)")
    p.add_argument("--lake-root", default="data/lake")
    p.add_argument("--broker", default="fbs")
    p.add_argument("--tf", default="H1")
    p.add_argument("--fit-bars", type=int, default=DEFAULT_FIT_BARS)
    p.add_argument("--step-bars", type=int, default=DEFAULT_STEP_BARS)
    p.add_argument("--out", default="data/results")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    run_card = json.loads((Path(args.run_dir) / "run.json").read_text())
    symbols = run_card["symbols"]
    trades = _load_trades(args.run_dir)

    lake = Lake(args.lake_root)
    windows_by_symbol, per_symbol, all_episodes = {}, {}, []
    total_scored = total_alert = 0
    for sym in symbols:
        df = lake.load(sym, tf=args.tf, broker=args.broker)
        states = walk_forward_states(df, args.fit_bars, args.step_bars)
        fit_diag = _worst_fit_diag(df, compute_features(df), args.fit_bars, args.step_bars)
        wins = alert_windows(states)
        windows_by_symbol[sym] = wins
        n_scored = len(states)
        n_alert = sum(1 for s in states if s["alert"])
        total_scored += n_scored
        total_alert += n_alert
        sym_trades = [t for t in trades if t["symbol"] == sym]
        annotated = classify_trades(sym_trades, {sym: wins})
        inside = [t for t in annotated if t["inside_alert"]]
        outside = [t for t in annotated if not t["inside_alert"]]
        per_symbol[sym] = {
            "n_bars": int(len(df)), "n_scored": n_scored,
            "sha256": _sha256_bytes(df.to_csv(index=False).encode()),
            "alert_rate": (n_alert / n_scored) if n_scored else 0.0,
            "n_alert_windows": len(wins),
            "fit_diag": fit_diag,
            "inside": bucket_metrics(inside), "outside": bucket_metrics(outside),
        }
        for w in wins:
            all_episodes.append({"symbol": sym, **w})

    annotated_all = classify_trades(trades, windows_by_symbol)
    inside_all = [t for t in annotated_all if t["inside_alert"]]
    outside_all = [t for t in annotated_all if not t["inside_alert"]]
    pooled = {
        "alert_rate": (total_alert / total_scored) if total_scored else 0.0,
        "n_inside": len(inside_all), "n_outside": len(outside_all),
        "inside": bucket_metrics(inside_all), "outside": bucket_metrics(outside_all),
    }
    top_episodes = sorted(all_episodes, key=lambda w: w["peak_score"], reverse=True)[:10]

    card = build_study_card(args.run_dir, run_card, symbols, per_symbol, pooled,
                            top_episodes, args.fit_bars, args.step_bars)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / f"{ts}_antibody_study"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "study.json").write_text(json.dumps(card, indent=2, sort_keys=True, default=str))

    _print_report(card, out_dir)
    return 0


def _print_report(card, out_dir):
    p = card["pooled"]
    print(f"[ANTIBODY] pooled alert_rate={p['alert_rate']:.4f} "
          f"inside n={p['inside']['n']} exp={p['inside']['expectancy']:+.3f}R "
          f"outside n={p['outside']['n']} exp={p['outside']['expectancy']:+.3f}R")
    gap = p["outside"]["expectancy"] - p["inside"]["expectancy"]
    print(f"[ANTIBODY] inside-vs-outside expectancy gap = {gap:+.3f}R")
    c = card["criteria"]
    print(f"[ANTIBODY] criteria: alert_rate<{c['max_pooled_alert_rate']} "
          f"n_inside>={c['min_inside_trades']} inside<0 gap>={c['min_expectancy_gap_r']}R")
    print(f"[ANTIBODY] top episodes: {len(card['top_episodes'])}")
    print(f"[ANTIBODY] wrote {out_dir}/study.json")


if __name__ == "__main__":
    raise SystemExit(main())
