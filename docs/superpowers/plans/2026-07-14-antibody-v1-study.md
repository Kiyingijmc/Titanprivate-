# Antibody v1 — OHLC Anomaly Sentinel + Counterfactual Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a validated *study only* — a pure OHLC anomaly scorer (`AntibodyScorer`) plus a walk-forward counterfactual that answers ONE pre-registered question: would blocking new SilverBullet entries during ALERT windows have improved expectancy over 3 years? No live wiring in this plan.

**Architecture:** Additive-only. A pure Mahalanobis scorer in `src/analysis/antibody.py` (numpy, no new deps) fits a per-symbol self-model over a trailing window and scores each H1 bar's abnormality; a state machine turns sustained high scores into ALERT windows. A walk-forward study CLI (`scripts/antibody_study.py`) rolls the fit quarterly (no lookahead), overlays SB trades from ONE pooled `research_run` invocation, and reports inside-alert vs outside-alert expectancy against frozen adoption criteria. Zero diffs under `src/core`/`src/execution`.

**Tech Stack:** Python 3.10+, numpy (existing dep), pandas (existing), stdlib `unittest`. Reuses `src/analysis/atr_simple.last_atr`, `src/data/lake.Lake` (frozen-glob load), `scripts/research_run.py` (SB trade generation), `tests/backtest/backtest_engine.py` (validated math — never reimplemented).

## Global Constraints

- **venv lives ONLY in the main checkout.** Every python/unittest command uses the absolute path `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python`. Work happens in the worktree `/home/kiyingijmc/projects/Titan_antibody` (branch `feat/antibody-study`).
- **Test command:** `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`. Full suite must be green at every task gate. Suite baseline entering: **377 OK**.
- **Parity is FROZEN.** Never modify `scripts/capture_parity_golden.py`, `tests/backtest/fixtures/*`, `tests/unit/test_signal_parity.py`. Parity stays green at every gate.
- **Zero diffs** under `src/core` and `src/execution`. This plan touches only `src/analysis`, `scripts`, `tests`, `docs`.
- **Validated math is imported, never duplicated** (from `tests/backtest/backtest_engine.py`). SB trades come from ONE pooled `research_run` — never a parallel replay.
- **No new dependencies.** Mahalanobis is numpy-only (isolation-forest/sklearn was rejected in the spec).
- **Staging discipline:** stage EXPLICIT file lists only. NEVER `git add -A`/`-u`/`.`. NEVER stage `data/specs.json`, `data/history` (symlink), `mql5_bridge/Experts/Titan_Gateway.mq5`, `scripts/check_bridge.py`, `tests/unit/test_check_bridge_ip.py`, `.superpowers/`. No git remote — never push; never touch `main`.
- **Commit trailer (every commit):** end the message with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Gate freeze:** while the Gyroscope gate is still running, do NOT commit to `feat/trade-mgmt-pipeline` in the plan07 worktree; this worktree (`feat/antibody-study`) is a separate branch and IS free to commit. The heavy study replay in Task 4 launches ONLY after the gate's 11 runs finish (compute courtesy).

---

## File Structure

- `src/analysis/antibody.py` — **new.** Pure scorer: `compute_features(df) -> list`, `AntibodyScorer(fit_features)` with `.score(vec) -> Reading` and `.refit(fit_features)`, frozen `Reading` dataclass. numpy + stdlib only. One responsibility: turn OHLC bars into abnormality readings.
- `tests/unit/test_antibody.py` — **new.** Synthetic-data unit tests for the scorer (features, state machine, alert rate, determinism, loud failure, refit continuity).
- `scripts/antibody_study.py` — **new.** Walk-forward study driver + CLI. Pure helpers (`window_bounds`, `walk_forward_states`, `alert_windows`, `classify_trades`, `build_study_card`) + `main(argv)`. Reads frozen H1 via `Lake`, SB trades via a run-card's `signals.jsonl`.
- `tests/unit/test_antibody_study.py` — **new.** Small-fixture tests for window arithmetic, overlay classification, alert-window extraction, refit continuity, study-card schema.
- `docs/research/2026-07-14-antibody-study.md` — **new.** Pre-registered adoption doc, committed BEFORE any run (Task 3).
- `docs/research/2026-07-14-antibody-study-results.md` — **new.** Results + verdict (Task 4, after the run).

---

## Task 1: `AntibodyScorer` + `compute_features` + synthetic unit tests

**Files:**
- Create: `src/analysis/antibody.py`
- Test: `tests/unit/test_antibody.py`

**Interfaces:**
- Consumes: `src/analysis/atr_simple.last_atr(df, period=14) -> float` (mean of the last `period` true ranges of the passed frame; returns 0.0 if `len(df) < 2`). numpy as `np`.
- Produces (later tasks rely on these EXACT signatures):
  - `Reading` — `@dataclass(frozen=True)` with fields `score: float`, `threshold: float`, `state: str` (`"PATROL"` | `"ALERT"`), `alert: bool` (True iff `state == "ALERT"`).
  - `compute_features(df) -> list` — length `len(df)`; element `k` is either a 4-tuple `(f1, f2, f3, f4)` of floats or `None` (warmup / degenerate). Element 0 is always `None` (no previous bar). Aligns 1:1 with `df` rows by index.
  - `AntibodyScorer(fit_features)` — `fit_features` is a list of 4-tuples (the `None`s already stripped by the caller). Raises `ValueError` if `len(fit_features) < MIN_FIT_SAMPLES` (=5) or if the regularized covariance is singular.
  - `AntibodyScorer.score(feature_vec) -> Reading` — `feature_vec` is a 4-tuple; advances the internal state machine; deterministic.
  - `AntibodyScorer.refit(fit_features) -> None` — recomputes mean/inv-cov/threshold from new `fit_features`; **preserves** the state-machine state and counters (used by the walk-forward driver for continuity across quarterly refits).
  - Module constants: `MIN_FIT_SAMPLES = 5`, `_EPS = 1e-9`, `_ATR_PERIOD = 14`, `_QUANTILE = 0.99`, `_ALERT_RUN = 2`, `_CLEAR_RUN = 3`.

**Feature definitions (locked — for bar index `k`, previous bar `k-1`):**
- `atr_k = last_atr(df.iloc[:k], period=14)` — ATR of the bars STRICTLY BEFORE `k` (lookahead-safe; the current bar never normalizes itself). `None` for that bar if `atr_k <= 0` or `k < 1`.
- `f1 = (high_k - low_k) / atr_k` — ATR-normalized range (the spec's "range/ATR"; Mahalanobis supplies the standardization across all four).
- `f2 = |close_k - open_k| / (high_k - low_k)` if `high_k > low_k` else `0.0` — body/range ratio.
- `f3 = |open_k - close_{k-1}| / atr_k` — ATR-normalized gap.
- `f4 = overlap / prev_range` if `prev_range > 0` else `0.0`, where `prev_range = high_{k-1} - low_{k-1}` and `overlap = max(0.0, min(high_k, high_{k-1}) - max(low_k, low_{k-1}))` — bar-overlap ratio.

**State machine (locked):** track `_high_run`, `_low_run`, `state` (start `"PATROL"`). Per scored bar: if `score > threshold` then `_high_run += 1; _low_run = 0` else `_low_run += 1; _high_run = 0`. Then: if `state == "PATROL"` and `_high_run >= 2` → `state = "ALERT"`; elif `state == "ALERT"` and `_low_run >= 3` → `state = "PATROL"` (the ALL-CLEAR transition). `Reading.alert = (state == "ALERT")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_antibody.py
# Antibody v1 / Task 1: pure OHLC anomaly scorer. Deterministic synthetic
# data only (no market data, no randomness beyond a seeded Random).
import math
import os
import random
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.antibody import (
    AntibodyScorer,
    Reading,
    compute_features,
    MIN_FIT_SAMPLES,
)


def _bars(rows):
    """rows: list of (open, high, low, close) -> DataFrame with a time column."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(
        {
            "time": idx,
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
        }
    )


def _benign(n, seed=7):
    """Small-range noise bars around 1.0000, ~5-pip ranges."""
    rng = random.Random(seed)
    rows, price = [], 1.0000
    for _ in range(n):
        drift = rng.uniform(-0.0002, 0.0002)
        o = price
        c = price + drift
        hi = max(o, c) + rng.uniform(0.0, 0.0003)
        lo = min(o, c) - rng.uniform(0.0, 0.0003)
        rows.append((o, hi, lo, c))
        price = c
    return _bars(rows)


class TestComputeFeatures(unittest.TestCase):
    def test_length_and_warmup(self):
        df = _benign(30)
        feats = compute_features(df)
        self.assertEqual(len(feats), len(df))
        self.assertIsNone(feats[0])  # first bar has no previous bar

    def test_feature_values_hand_computed(self):
        # 16 flat 20-pip bars, then a wide bar; check the wide bar's features.
        rows = [(1.0, 1.0010, 0.9990, 1.0) for _ in range(16)]
        rows.append((1.0, 1.0100, 0.9950, 1.0080))  # wide bar with a body
        df = _bars(rows)
        feats = compute_features(df)
        f1, f2, f3, f4 = feats[16]
        # prior ATR ~ mean TR of the flat 20-pip bars (~0.0020); range 150 pips.
        self.assertGreater(f1, 5.0)
        self.assertAlmostEqual(f2, abs(1.0080 - 1.0) / (1.0100 - 0.9950), places=9)
        self.assertGreaterEqual(f3, 0.0)
        self.assertGreaterEqual(f4, 0.0)

    def test_zero_range_body_ratio_is_zero(self):
        rows = [(1.0, 1.0010, 0.9990, 1.0) for _ in range(16)]
        rows.append((1.0, 1.0, 1.0, 1.0))  # zero-range bar
        df = _bars(rows)
        feats = compute_features(df)
        self.assertEqual(feats[16][1], 0.0)  # body/range -> 0 when range 0


class TestScorerStateMachine(unittest.TestCase):
    def _fit_scorer(self, n=400):
        df = _benign(n)
        feats = [f for f in compute_features(df) if f is not None]
        return AntibodyScorer(feats), df

    def test_single_anomaly_bar_does_not_alert(self):
        scorer, _ = self._fit_scorer()
        r1 = scorer.score((50.0, 0.9, 40.0, 0.0))
        self.assertTrue(r1.score > r1.threshold)
        self.assertEqual(r1.state, "PATROL")   # 1 high bar is not enough
        r2 = scorer.score((0.5, 0.2, 0.1, 0.9))  # benign-ish
        self.assertEqual(r2.state, "PATROL")

    def test_two_consecutive_anomalies_raise_alert(self):
        scorer, _ = self._fit_scorer()
        scorer.score((50.0, 0.9, 40.0, 0.0))
        r2 = scorer.score((60.0, 0.95, 45.0, 0.0))
        self.assertEqual(r2.state, "ALERT")
        self.assertTrue(r2.alert)

    def test_all_clear_after_three_calm_bars(self):
        scorer, _ = self._fit_scorer()
        scorer.score((50.0, 0.9, 40.0, 0.0))
        scorer.score((60.0, 0.95, 45.0, 0.0))  # -> ALERT
        calm = (0.5, 0.2, 0.1, 0.9)
        self.assertEqual(scorer.score(calm).state, "ALERT")  # 1 calm
        self.assertEqual(scorer.score(calm).state, "ALERT")  # 2 calm
        self.assertEqual(scorer.score(calm).state, "PATROL")  # 3 calm -> ALL-CLEAR

    def test_alert_rate_on_fresh_benign_is_near_one_percent(self):
        # q99 threshold => ~1% of same-distribution bars exceed it.
        df_fit = _benign(2000, seed=1)
        feats_fit = [f for f in compute_features(df_fit) if f is not None]
        scorer = AntibodyScorer(feats_fit)
        df_test = _benign(2000, seed=99)
        feats_test = [f for f in compute_features(df_test) if f is not None]
        exceed = sum(1 for f in feats_test if scorer.score(f).score > scorer.threshold)
        rate = exceed / len(feats_test)
        self.assertLess(rate, 0.05)  # generously bounded around the 1% design point


class TestDeterminismAndFailure(unittest.TestCase):
    def test_determinism(self):
        df = _benign(500, seed=3)
        feats = [f for f in compute_features(df) if f is not None]
        a = AntibodyScorer(feats)
        b = AntibodyScorer(feats)
        self.assertEqual(a.threshold, b.threshold)
        probe = [(0.3, 0.4, 0.2, 0.8), (5.0, 0.9, 4.0, 0.1), (0.3, 0.4, 0.2, 0.8)]
        self.assertEqual(
            [a.score(p).score for p in probe],
            [b.score(p).score for p in probe],
        )

    def test_too_few_fit_samples_fails_loud(self):
        with self.assertRaises(ValueError):
            AntibodyScorer([(1.0, 0.5, 0.1, 0.2)] * (MIN_FIT_SAMPLES - 1))

    def test_refit_preserves_state(self):
        df = _benign(600)
        feats = [f for f in compute_features(df) if f is not None]
        scorer = AntibodyScorer(feats[:300])
        scorer.score((50.0, 0.9, 40.0, 0.0))
        scorer.score((60.0, 0.95, 45.0, 0.0))  # -> ALERT
        self.assertEqual(scorer.state, "ALERT")
        scorer.refit(feats[300:])  # roll the model
        self.assertEqual(scorer.state, "ALERT")  # state carried across refit
        calm = (0.5, 0.2, 0.1, 0.9)
        scorer.score(calm)
        scorer.score(calm)
        self.assertEqual(scorer.score(calm).state, "PATROL")  # ALL-CLEAR still counts


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest tests.unit.test_antibody -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'src.analysis.antibody'`.

- [ ] **Step 3: Write the implementation**

```python
# src/analysis/antibody.py
"""Antibody v1 -- OHLC anomaly sentinel (study-only; no live wiring).

Learns "normal" per-symbol bar microbehavior from a trailing fit window and
scores each H1 bar's abnormality as a Mahalanobis distance against the fitted
self-model. A 2-of / 3-of state machine turns sustained high scores into ALERT
windows. Pure and deterministic: numpy + stdlib only, no I/O, no wall-clock,
no randomness. One scorer per symbol.

Four price-geometry features per bar (OHLC-only; tick-vol/spread are the
pre-registered v2 extension and are unavailable in the 3-yr frozen data):
  f1 = range / ATR(14)                     -- ATR-normalized bar range
  f2 = |body| / range                      -- body fraction (0 when range 0)
  f3 = |open - prev_close| / ATR(14)       -- ATR-normalized gap
  f4 = overlap(bar, prev) / prev_range     -- bar overlap (0 when prev range 0)
ATR(14) is the mean true range of the bars STRICTLY BEFORE the scored bar, so a
bar never normalizes itself (lookahead-safe). Mahalanobis supplies the
cross-feature standardization; the features themselves are raw geometry.
"""
from dataclasses import dataclass

import numpy as np

from src.analysis.atr_simple import last_atr

MIN_FIT_SAMPLES = 5      # need n > dim for a non-degenerate sample covariance
_EPS = 1e-9              # covariance ridge before inversion
_ATR_PERIOD = 14
_QUANTILE = 0.99         # ALERT threshold = q99 of the fit window's own scores
_ALERT_RUN = 2           # PATROL -> ALERT after this many consecutive highs
_CLEAR_RUN = 3           # ALERT -> PATROL after this many consecutive calms


@dataclass(frozen=True)
class Reading:
    score: float       # Mahalanobis distance vs the fitted self-model
    threshold: float   # q99 of the fit window scores
    state: str         # "PATROL" | "ALERT"
    alert: bool        # state == "ALERT"


def compute_features(df):
    """OHLC -> list aligned 1:1 with df rows. Element k is a 4-tuple
    (f1, f2, f3, f4) or None (bar 0, or a degenerate trailing ATR of 0)."""
    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    n = len(df)
    out = [None] * n
    for k in range(1, n):
        atr = last_atr(df.iloc[:k], period=_ATR_PERIOD)  # bars strictly before k
        if atr <= 0.0:
            continue  # warmup / degenerate -> leave None
        rng = highs[k] - lows[k]
        f1 = rng / atr
        f2 = (abs(closes[k] - opens[k]) / rng) if rng > 0 else 0.0
        f3 = abs(opens[k] - closes[k - 1]) / atr
        prev_rng = highs[k - 1] - lows[k - 1]
        overlap = max(0.0, min(highs[k], highs[k - 1]) - max(lows[k], lows[k - 1]))
        f4 = (overlap / prev_rng) if prev_rng > 0 else 0.0
        out[k] = (f1, f2, f3, f4)
    return out


def _fit_model(fit_features):
    """Return (mean, inv_cov, threshold). Fails LOUD on too-few samples or a
    covariance that is singular even after the epsilon ridge."""
    if len(fit_features) < MIN_FIT_SAMPLES:
        raise ValueError(
            f"antibody: need >= {MIN_FIT_SAMPLES} fit samples, got {len(fit_features)}"
        )
    x = np.asarray(fit_features, dtype=float)  # (n, 4)
    mean = x.mean(axis=0)
    cov = np.cov(x, rowvar=False, ddof=1)      # (4, 4) sample covariance
    cov = np.atleast_2d(cov) + _EPS * np.eye(x.shape[1])
    try:
        inv_cov = np.linalg.inv(cov)
    except np.linalg.LinAlgError as exc:  # singular even after the ridge
        raise ValueError(f"antibody: covariance singular after regularization: {exc}")
    diffs = x - mean
    dist = np.sqrt(np.maximum(0.0, np.einsum("ij,jk,ik->i", diffs, inv_cov, diffs)))
    threshold = float(np.quantile(dist, _QUANTILE))
    return mean, inv_cov, threshold


class AntibodyScorer:
    """One per symbol. Fit once (or refit rolling); score bar-by-bar. The state
    machine persists across refit() so a rolling study keeps ALERT continuity."""

    def __init__(self, fit_features):
        self._mean, self._inv_cov, self.threshold = _fit_model(fit_features)
        self.state = "PATROL"
        self._high_run = 0
        self._low_run = 0

    def refit(self, fit_features):
        """Roll the self-model; preserve the state-machine state and counters."""
        self._mean, self._inv_cov, self.threshold = _fit_model(fit_features)

    def _mahalanobis(self, feature_vec):
        diff = np.asarray(feature_vec, dtype=float) - self._mean
        q = float(diff @ self._inv_cov @ diff)
        return float(np.sqrt(max(0.0, q)))

    def score(self, feature_vec):
        s = self._mahalanobis(feature_vec)
        if s > self.threshold:
            self._high_run += 1
            self._low_run = 0
        else:
            self._low_run += 1
            self._high_run = 0
        if self.state == "PATROL" and self._high_run >= _ALERT_RUN:
            self.state = "ALERT"
        elif self.state == "ALERT" and self._low_run >= _CLEAR_RUN:
            self.state = "PATROL"
        return Reading(
            score=s, threshold=self.threshold, state=self.state, alert=self.state == "ALERT"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest tests.unit.test_antibody -v`
Expected: PASS (all tests OK).

- [ ] **Step 5: Run the full suite (foreground) to confirm no regression + parity green**

Run: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: `OK`, count = 377 + (number of new test methods). If the harness force-backgrounds it, do NOT set a Monitor and do NOT end the turn — poll the output file with Read until `Ran N tests` / `OK` appears.

- [ ] **Step 6: Commit**

```bash
cd /home/kiyingijmc/projects/Titan_antibody
git add src/analysis/antibody.py tests/unit/test_antibody.py
git commit -m "$(cat <<'EOF'
feat(antibody): OHLC anomaly scorer -- Mahalanobis self-model + 2/3 ALERT state machine

Pure numpy scorer (no new deps): 4 price-geometry features per H1 bar
(ATR-normalized range/gap, body ratio, prev-bar overlap), Mahalanobis distance
vs a trailing self-model, q99 ALERT threshold, PATROL->ALERT(2)->PATROL(3)
state machine. refit() rolls the model while preserving state for the
walk-forward study. Study-only; no src/core or src/execution diffs.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Walk-forward study CLI + small-fixture unit tests

**Files:**
- Create: `scripts/antibody_study.py`
- Test: `tests/unit/test_antibody_study.py`

**Interfaces:**
- Consumes: `src.analysis.antibody.{AntibodyScorer, compute_features}`; `src.data.lake.Lake` (`Lake(root).load(symbol, tf="H1", broker="fbs") -> DataFrame` with columns `time, open, high, low, close`; loads committed frozen data via the manifest-less glob fallback); a run-card's `signals.jsonl` (one JSON object per line; keys include `time`, `symbol`, `filled`, `outcome` in `{TP,SL,EXPIRED,OPEN_AT_END}`, `r`).
- Produces (helpers, all pure and independently testable):
  - `window_bounds(n_bars, fit_bars, step_bars) -> list[tuple[int, int, int, int]]` — each tuple `(fit_lo, fit_hi, score_lo, score_hi)` with `fit_hi == score_lo` and `score_hi == min(score_lo + step_bars, n_bars)`; the first window starts at `score_lo = fit_bars`; windows tile `[fit_bars, n_bars)` with no overlap and no gaps; empty list if `n_bars <= fit_bars`.
  - `walk_forward_states(df, fit_bars, step_bars) -> list[dict]` — one dict per SCORED bar with valid features: `{"i": int, "time": <Timestamp>, "score": float, "threshold": float, "state": str, "alert": bool}`. Uses ONE `AntibodyScorer`, `refit()` at each window boundary from that window's trailing fit features (valid vectors within `[fit_lo, fit_hi)`); lookahead-safe. Skips bars whose feature is `None`.
  - `alert_windows(states) -> list[dict]` — contiguous runs where `state == "ALERT"`, each `{"start_time", "end_time", "start_i", "end_i", "duration": int, "peak_score": float}`.
  - `classify_trades(trades, windows_by_symbol) -> list[dict]` — each trade annotated with `"inside_alert": bool` (True iff some window for `trade["symbol"]` has `start_time <= trade_time <= end_time`, `trade_time = pd.to_datetime(trade["time"])`).
  - `bucket_metrics(trades) -> dict` — `{"n": int, "expectancy": float, "profit_factor": float}` over trades with `outcome in {TP, SL}` (expectancy = mean `r`; PF = sum positive `r` / abs sum negative `r`, `inf` if no losers, `0.0` if empty).
  - `fit_diagnostics(fit_features) -> dict` — `{"min_variance": float, "cov_condition": float}` for one fit window: `min_variance` = smallest per-feature sample variance (`np.var(x, axis=0, ddof=1).min()`); `cov_condition` = `np.linalg.cond` of the SAME ε=1e-9-ridged covariance the scorer inverts. **Degeneracy diagnostic (carry-forward from Task-1 review, disclosure-C):** on real fit windows this surfaces whether any feature dimension is near-constant, which the fixed ε ridge would let dominate the Mahalanobis distance and distort q99. Recorded per-symbol (worst-across-windows: min of `min_variance`, max of `cov_condition`); Task 4 sanity-checks it, and the pre-registration doc (Task 3) names it. Does NOT change the spec-locked ε — it makes the risk empirical, not assumed. Fails loud (ValueError) on `< MIN_FIT_SAMPLES` fit rows, mirroring the scorer.
  - `build_study_card(...) -> dict` — study-card described below.
  - `main(argv=None) -> int` — CLI.

**Study-card schema (locked):**
```
{
  "git_sha": str, "timestamp": <iso>,
  "run_dir": str, "run_git_sha": str,          # provenance of the SB run consumed
  "fit_params": {"fit_bars": int, "step_bars": int, "quantile": 0.99, "atr_period": 14},
  "symbols": [str, ...],
  "per_symbol": { SYM: {"n_bars": int, "n_scored": int, "sha256": str,
                        "alert_rate": float, "n_alert_windows": int,
                        "fit_diag": {"min_variance": float, "cov_condition": float},
                        "inside": {n,expectancy,profit_factor},
                        "outside": {n,expectancy,profit_factor}} },
  "pooled": {"alert_rate": float, "n_inside": int, "n_outside": int,
             "inside": {...}, "outside": {...}},
  "top_episodes": [ {"symbol","start_time","end_time","duration","peak_score"}, ... up to 10 ],
  "criteria": { ... echoed from the pre-registered doc ... }
}
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_antibody_study.py
# Antibody v1 / Task 2: walk-forward study helpers. Small synthetic fixtures;
# no heavy data, no market files.
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.antibody_study import (
    window_bounds,
    alert_windows,
    classify_trades,
    bucket_metrics,
    fit_diagnostics,
    walk_forward_states,
)


class TestWindowBounds(unittest.TestCase):
    def test_tiles_without_overlap_or_gap(self):
        wins = window_bounds(n_bars=25, fit_bars=10, step_bars=5)
        self.assertEqual(wins[0], (0, 10, 10, 15))
        self.assertEqual(wins[1], (5, 15, 15, 20))
        self.assertEqual(wins[2], (10, 20, 20, 25))
        self.assertEqual([w[2] for w in wins], [10, 15, 20])
        self.assertEqual([w[3] for w in wins], [15, 20, 25])

    def test_partial_last_window(self):
        wins = window_bounds(n_bars=23, fit_bars=10, step_bars=5)
        self.assertEqual(wins[-1], (8, 18, 18, 23))  # last score region is 5 bars

    def test_no_windows_when_too_short(self):
        self.assertEqual(window_bounds(n_bars=10, fit_bars=10, step_bars=5), [])
        self.assertEqual(window_bounds(n_bars=8, fit_bars=10, step_bars=5), [])


class TestAlertWindows(unittest.TestCase):
    def _states(self, seq):
        idx = pd.date_range("2024-01-01", periods=len(seq), freq="h")
        return [
            {"i": k, "time": idx[k], "score": sc, "threshold": 1.0,
             "state": st, "alert": st == "ALERT"}
            for k, (st, sc) in enumerate(seq)
        ]

    def test_contiguous_runs(self):
        seq = [("PATROL", 0.1), ("ALERT", 5.0), ("ALERT", 9.0), ("PATROL", 0.2),
               ("ALERT", 4.0), ("PATROL", 0.1)]
        wins = alert_windows(self._states(seq))
        self.assertEqual(len(wins), 2)
        self.assertEqual(wins[0]["duration"], 2)
        self.assertEqual(wins[0]["peak_score"], 9.0)
        self.assertEqual(wins[1]["duration"], 1)
        self.assertEqual(wins[1]["peak_score"], 4.0)

    def test_no_alerts(self):
        seq = [("PATROL", 0.1)] * 4
        self.assertEqual(alert_windows(self._states(seq)), [])


class TestClassifyTrades(unittest.TestCase):
    def test_inside_and_boundary(self):
        win = {"start_time": pd.Timestamp("2024-01-01 05:00"),
               "end_time": pd.Timestamp("2024-01-01 08:00"),
               "start_i": 5, "end_i": 8, "duration": 4, "peak_score": 9.0}
        windows_by_symbol = {"EURUSD": [win]}
        trades = [
            {"symbol": "EURUSD", "time": "2024-01-01 06:00"},   # inside
            {"symbol": "EURUSD", "time": "2024-01-01 05:00"},   # boundary start -> inside
            {"symbol": "EURUSD", "time": "2024-01-01 08:00"},   # boundary end -> inside
            {"symbol": "EURUSD", "time": "2024-01-01 09:00"},   # outside
            {"symbol": "GBPUSD", "time": "2024-01-01 06:00"},   # other symbol -> outside
        ]
        out = classify_trades(trades, windows_by_symbol)
        self.assertEqual([t["inside_alert"] for t in out], [True, True, True, False, False])


class TestBucketMetrics(unittest.TestCase):
    def test_expectancy_and_pf(self):
        trades = [
            {"outcome": "TP", "r": 2.0}, {"outcome": "SL", "r": -1.0},
            {"outcome": "TP", "r": 1.0}, {"outcome": "EXPIRED", "r": 0.0},  # ignored
        ]
        m = bucket_metrics(trades)
        self.assertEqual(m["n"], 3)
        self.assertAlmostEqual(m["expectancy"], (2.0 - 1.0 + 1.0) / 3, places=9)
        self.assertAlmostEqual(m["profit_factor"], 3.0 / 1.0, places=9)

    def test_empty_bucket(self):
        m = bucket_metrics([{"outcome": "EXPIRED", "r": 0.0}])
        self.assertEqual(m["n"], 0)
        self.assertEqual(m["expectancy"], 0.0)


class TestFitDiagnostics(unittest.TestCase):
    def test_well_conditioned_window(self):
        import random
        rng = random.Random(4)
        feats = [(rng.gauss(1.0, 0.3), rng.gauss(0.5, 0.2),
                  rng.gauss(0.4, 0.15), rng.gauss(0.6, 0.2)) for _ in range(200)]
        d = fit_diagnostics(feats)
        self.assertGreater(d["min_variance"], 0.0)
        self.assertLess(d["cov_condition"], 1e6)  # all dims have real variance

    def test_degenerate_dimension_flagged(self):
        # a constant 3rd feature -> near-zero variance -> huge condition number
        import random
        rng = random.Random(4)
        feats = [(rng.gauss(1.0, 0.3), rng.gauss(0.5, 0.2), 0.0, rng.gauss(0.6, 0.2))
                 for _ in range(200)]
        d = fit_diagnostics(feats)
        self.assertLess(d["min_variance"], 1e-12)
        self.assertGreater(d["cov_condition"], 1e6)  # ridge lets it dominate

    def test_too_few_samples_fails_loud(self):
        with self.assertRaises(ValueError):
            fit_diagnostics([(1.0, 0.5, 0.4, 0.6)] * 4)


class TestWalkForwardLookahead(unittest.TestCase):
    def test_scored_region_and_refit_continuity(self):
        import random
        rng = random.Random(5)
        rows, price = [], 1.0
        for _ in range(60):
            d = rng.uniform(-0.0002, 0.0002)
            o, c = price, price + d
            rows.append((o, max(o, c) + 0.0002, min(o, c) - 0.0002, c))
            price = c
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=60, freq="h"),
            "open": [r[0] for r in rows], "high": [r[1] for r in rows],
            "low": [r[2] for r in rows], "close": [r[3] for r in rows],
        })
        states = walk_forward_states(df, fit_bars=20, step_bars=10)
        self.assertTrue(all(s["i"] >= 20 for s in states))
        self.assertTrue(all(s["state"] in ("PATROL", "ALERT") for s in states))
        idxs = [s["i"] for s in states]
        self.assertEqual(idxs, sorted(set(idxs)))  # monotone, no duplicates


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest tests.unit.test_antibody_study -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'scripts.antibody_study'`.

- [ ] **Step 3: Write the implementation**

```python
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
    """Tile [fit_bars, n_bars) into non-overlapping score regions, each with a
    trailing fit window of fit_bars ending where the score region begins."""
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest tests.unit.test_antibody_study -v`
Expected: PASS (all tests OK).

- [ ] **Step 5: Run the full suite (foreground) to confirm no regression + parity green**

Run: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: `OK`. If force-backgrounded, poll the output file with Read until `Ran N tests` / `OK` — do NOT Monitor, do NOT end the turn.

- [ ] **Step 6: Commit**

```bash
cd /home/kiyingijmc/projects/Titan_antibody
git add scripts/antibody_study.py tests/unit/test_antibody_study.py
git commit -m "$(cat <<'EOF'
feat(antibody): walk-forward counterfactual study CLI + helpers

Rolls the Antibody self-model quarterly (fit 6000 / step 1500 H1 bars,
lookahead-safe), extracts ALERT windows, overlays filled SB trades from ONE
pooled research_run signals.jsonl, and reports inside-alert vs outside-alert
expectancy/PF per-symbol + pooled with a top-10 episode catalogue. Writes a
provenance study-card. Study-only; imports validated readers, no reimplemented
math, no src/core or src/execution diffs.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Pre-registered adoption doc (committed BEFORE any run)

**Files:**
- Create: `docs/research/2026-07-14-antibody-study.md`

This task has no code and no tests — its deliverable is the frozen pre-registration. It is a separate reviewer gate because the criteria MUST be committed before the run (same falsification discipline as the Gyroscope gate). The reviewer verifies: (a) no study output exists at HEAD, (b) every number matches the code defaults in `scripts/antibody_study.py` (`CRITERIA`, `fit_bars=6000`, `step_bars=1500`, `quantile=0.99`) and the spec, (c) the honest limitations are all present.

- [ ] **Step 1: Write the doc**

```markdown
# Antibody v1 — Pre-Registered Counterfactual Study (adoption criteria frozen)

**Date:** 2026-07-14 (committed BEFORE any run — falsification discipline).
**Spec:** docs/superpowers/specs/2026-07-14-antibody-v1-study-design.md (commit 14064ab, user-approved).
**Plan:** docs/superpowers/plans/2026-07-14-antibody-v1-study.md.
**Branch:** feat/antibody-study (worktree Titan_antibody).

## Question (one, pre-registered)

Over the frozen 3-year 9-symbol H1 dataset, would blocking *new* SilverBullet
entries during Antibody ALERT windows have improved SB's expectancy?

## Method (frozen)

- **Scorer:** `src/analysis/antibody.py`. Four OHLC features per H1 bar
  (ATR(14)-normalized range, body/range, ATR-normalized gap, prev-bar overlap);
  Mahalanobis distance vs a trailing self-model; ALERT threshold = q99 of the
  fit window's own scores. State machine PATROL->ALERT (score>q99 for 2 bars)->
  PATROL (score<=q99 for 3 bars).
- **Walk-forward:** fit on a trailing **6000** H1 bars (~1 yr), score forward
  **1500** bars (~1 quarter), roll and refit. Every scored bar uses only past
  data. State carried across refits.
- **SB trades:** ONE pooled `research_run`, all 9 symbols, `--tf H1 --split 0.7`,
  **SB live config (min_grade B — the config default, NOT the gate's C floor)**,
  `--spread-mult 1.0`. Only FILLED trades (entered the market) are classified.
- **Overlay:** a trade is *inside-alert* iff its entry-bar timestamp falls within
  any ALERT window for its symbol (window = first ALERT bar through last ALERT
  bar before ALL-CLEAR). Report expectancy (mean net R over TP/SL), n, PF for
  inside vs outside, per-symbol + pooled; alert-rate per-symbol + pooled;
  top-10 alert episodes by peak score.

## Adoption criteria (ALL must hold to advance to a wiring plan)

1. Pooled alert rate **< 2%** of scored bars.
2. **n >= 30** SB trades entered inside alert windows (else: insufficient sample —
   record only, no adoption).
3. Inside-alert expectancy is **negative** AND at least **0.15 R/trade worse**
   than outside-alert expectancy.

Descriptive (non-gating): the top-10 episode catalogue should read as real
events (flash moves, liquidity holes), not artifacts.

**No post-hoc adjustment.** Criteria are frozen here; the run is executed once
(Task 4); the verdict is mechanical.

## Honest limitations (recorded up front)

- **OHLC-only.** The frozen data has no tick volume (`tick_volume=1` filler) and
  no spread history, so feed-pathology detection is weaker than v2 will be. Tick-
  vol z and spread z are the pre-registered v2 extension once live journaling
  accumulates them.
- **q99 is in-sample to each fit window** (non-parametric, no chi-square
  assumption); the ~1% design alert rate is a property of the fit window,
  validated out-of-sample by criterion 1.
- The first ~6000 bars per symbol are unscored (warmup); state resets are avoided
  across quarterly refits (one scorer, state carried).
- **Degeneracy diagnostic:** the fixed ε=1e-9 covariance ridge is scale-blind, so a
  near-constant feature dimension in a real fit window would dominate the Mahalanobis
  distance and distort q99. The study-card records per-symbol `fit_diag`
  (min per-feature variance, worst covariance condition number); the results doc
  sanity-checks that no symbol's windows are pathologically ill-conditioned. This
  does not alter the pre-registered ε — it makes the risk empirical.
- This is a **counterfactual overlay**, not a live A/B: it measures whether ALERT
  windows coincided with worse SB entries, not the causal effect of blocking.
```

- [ ] **Step 2: Verify no study output exists yet**

Run: `ls /home/kiyingijmc/projects/Titan_antibody/data/results/ 2>/dev/null | grep antibody || echo "clean — no antibody study output"`
Expected: `clean — no antibody study output`.

- [ ] **Step 3: Commit**

```bash
cd /home/kiyingijmc/projects/Titan_antibody
git add docs/research/2026-07-14-antibody-study.md
git commit -m "$(cat <<'EOF'
docs(antibody): pre-register the counterfactual study — 3 frozen adoption criteria

Committed BEFORE any run (falsification discipline): pooled alert-rate <2%,
n>=30 inside-alert SB trades, inside expectancy negative AND >=0.15R worse than
outside. Method frozen (fit 6000 / step 1500 H1, q99, SB live min_grade B,
spread-mult 1.0, 9 symbols). Honest OHLC-only limitation recorded.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Run the study + results doc + verdict

**Files:**
- Create: `docs/research/2026-07-14-antibody-study-results.md`

**Precondition (HARD):** the Gyroscope gate's 11 runs have finished (compute courtesy — the heavy SB replay must not contend with the gate). Confirm before launching:
`ps -p $(cat /home/kiyingijmc/projects/Titan_plan07/data/results/gate_run.pid) >/dev/null 2>&1 && echo "GATE STILL RUNNING — WAIT" || echo "gate done — clear to run"` and `grep -q "GATE RUNS COMPLETE" /home/kiyingijmc/projects/Titan_plan07/data/results/gate_run.log && echo "complete marker present"`.

This task is executed by the controller (not a fresh subagent): it is a long-running run + documentation step, not a TDD cycle.

- [ ] **Step 1: Confirm the SB live min_grade default is B**

Run: `grep -A3 "signal_grading:" /home/kiyingijmc/projects/Titan_antibody/config/config.yaml | grep min_grade`
Expected: `min_grade: "B"`. (If not B, STOP and escalate — the study must use live config.)

- [ ] **Step 2: Launch the single pooled SB research_run (detached, ~2-3h)**

```bash
cd /home/kiyingijmc/projects/Titan_antibody
PY=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python
nohup $PY scripts/research_run.py \
  --lake-symbols EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,GBPJPY,XAUUSD,US30,BTCUSD \
  --tf H1 --split 0.7 --strategy silver_bullet --spread-mult 1.0 \
  --out data/results \
  > data/results/antibody_sb_run.log 2>&1 &
echo $! > data/results/antibody_sb_run.pid
```
Note: NO `--set signal_grading.min_grade` — SB uses its live default (B). Poll `data/results/antibody_sb_run.log` for `[RESEARCH_RUN] wrote .../run.json`.

- [ ] **Step 3: Run the study against the produced run-dir**

```bash
cd /home/kiyingijmc/projects/Titan_antibody
PY=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python
RUN_DIR=$(ls -1dt data/results/*_silver_bullet_POOLED9_H1 | head -1)
$PY scripts/antibody_study.py --run-dir "$RUN_DIR" --out data/results
```
Expected: `[ANTIBODY] wrote data/results/<TS>_antibody_study/study.json` plus the pooled/inside/outside report line.

- [ ] **Step 4: Write the results doc with the mechanical verdict**

Create `docs/research/2026-07-14-antibody-study-results.md` from the `study.json`: per-criterion PASS/FAIL (alert-rate <2%; n_inside >=30; inside expectancy negative AND >=0.15R worse than outside), per-symbol + pooled inside/outside tables (n, expectancy, PF), pooled + per-symbol alert-rate, the top-10 episode catalogue with a one-line sanity read, and the `study.json` sha256 + the SB `run.json` git_sha for provenance. State the verdict plainly: **ADOPT (→ wiring plan)** only if all three criteria hold; otherwise **RECORD ONLY — Antibody stays research**.

- [ ] **Step 5: Commit the results doc**

```bash
cd /home/kiyingijmc/projects/Titan_antibody
git add docs/research/2026-07-14-antibody-study-results.md
git commit -m "$(cat <<'EOF'
docs(antibody): study results + mechanical verdict vs frozen criteria

<one-line verdict: ADOPT / RECORD-ONLY> — pooled alert-rate X%, n_inside=N,
inside exp <r>R vs outside <r>R (gap <g>R). Per-symbol + pooled tables, top-10
episode catalogue, study-card sha256 + SB run git_sha for provenance.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review (completed at plan-write time)

**Spec coverage:** §3 scorer → Task 1; §4 study → Task 2; §5 criteria → Task 3 (frozen) + Task 4 (verdict); §6 hard rules → Global Constraints; §7 task sketch (4 tasks) → Tasks 1-4. All covered.

**Placeholder scan:** every code step contains complete code; commands have expected output. No TBD/TODO. (Task 4 doc bodies are described, not stubbed, because their content is data-dependent on the run — the structure is fully specified.)

**Type consistency:** `Reading{score,threshold,state,alert}`, `compute_features -> list[4-tuple|None]`, `AntibodyScorer(fit_features)/.score()/.refit()`, `window_bounds/walk_forward_states/alert_windows/classify_trades/bucket_metrics/build_study_card` — names and signatures are identical across Tasks 1-2 and the tests. Study consumes `signals.jsonl` keys (`time,symbol,filled,outcome,r`) that match `research_run.py`'s writer.
