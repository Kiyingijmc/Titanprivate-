"""Validity controls (spec §5.1, §5.2).

The permuted dry run validates calibration WITHOUT consuming a look at the
real data — it must run before any real outcome is touched.
"""
import numpy as np

from scripts.confidence_screen import INJECT_TARGET_RHO, SEED


def permute_within_symbol(y, symbols, seed=SEED):
    """Shuffle outcomes inside each symbol, preserving symbol-level structure."""
    y = np.asarray(y, dtype=float)
    symbols = np.asarray(symbols)
    rng = np.random.default_rng(seed)
    out = y.copy()
    for sym in np.unique(symbols):
        idx = np.where(symbols == sym)[0]
        out[idx] = y[rng.permutation(idx)]
    return out


def inject_synthetic(y, target_rho=INJECT_TARGET_RHO, seed=SEED):
    """A feature that is a known noisy function of the outcome.

    The pipeline MUST recover this at ~target_rho; failure means it cannot see
    an effect it was built to detect, and the run is void.
    """
    y = np.asarray(y, dtype=float)
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=len(y))
    signal = (y - y.mean()) / (y.std() or 1.0)
    # Pearson blend; Spearman lands near it for these ranges.
    weight = float(np.clip(target_rho, -1.0, 1.0))
    return weight * signal + np.sqrt(max(1.0 - weight ** 2, 0.0)) * noise
