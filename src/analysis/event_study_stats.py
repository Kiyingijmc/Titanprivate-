"""Pure-numpy bootstrap/OLS helpers for the Aftershock kill-screen.

No scipy/statsmodels in this repo — do not add them. Registered
protocol: docs/research/2026-08-01-wave2-gate-triage.md.
"""
from __future__ import annotations

import numpy as np


def session_bucket(hours: np.ndarray) -> np.ndarray:
    """0=Asia [0,8), 1=London [8,15), 2=NY-overlap [15,19), 3=NY-late [19,24)."""
    h = np.asarray(hours)
    return np.select([h < 8, h < 15, h < 19], [0, 1, 2], default=3)


def bootstrap_mean_ci(x, rng, n_draws: int = 5000):
    x = np.asarray(x, dtype=float)
    idx = rng.integers(0, len(x), size=(n_draws, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(x.mean()), float(lo), float(hi)


def bootstrap_diff_ci(a, b, rng, n_draws: int = 5000):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ia = rng.integers(0, len(a), size=(n_draws, len(a)))
    ib = rng.integers(0, len(b), size=(n_draws, len(b)))
    diffs = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(a.mean() - b.mean()), float(lo), float(hi)


def _design(signal: np.ndarray, hours: np.ndarray) -> np.ndarray:
    buckets = session_bucket(hours)
    return np.column_stack([
        np.ones(len(signal)),
        signal,
        (buckets == 1).astype(float),
        (buckets == 2).astype(float),
        (buckets == 3).astype(float),
    ])


def ols_signal_coef(y, signal, hours, rng, n_draws: int = 2000):
    """OLS beta of the signal dummy net of session buckets, + case-resampling CI."""
    y = np.asarray(y, dtype=float)
    signal = np.asarray(signal, dtype=float)
    hours = np.asarray(hours)
    X = _design(signal, hours)
    beta = np.linalg.lstsq(X, y, rcond=None)[0][1]
    n = len(y)
    betas = np.empty(n_draws)
    for d in range(n_draws):
        idx = rng.integers(0, n, size=n)
        betas[d] = np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][1]
    lo, hi = np.percentile(betas, [2.5, 97.5])
    return float(beta), float(lo), float(hi)
