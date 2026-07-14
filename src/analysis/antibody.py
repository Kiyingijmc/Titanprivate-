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
