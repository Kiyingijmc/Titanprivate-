"""Clustered inference for the screen (spec §4).

Naive p-values would assume ~2,200 independent observations against a far
lower effective count — eleven symbols share GBP/USD factors and signals
cluster within sessions. That is the standard way a panel study manufactures
a false positive, so every p-value here comes from a cluster bootstrap over
calendar-week blocks.
"""
import numpy as np

from scripts.confidence_screen import BOOTSTRAP_DRAWS, Q_FDR, SEED


def _midrank(values):
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)
    # Average ranks within tie groups.
    sorted_vals = values[order]
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or sorted_vals[i] != sorted_vals[start]:
            ranks[order[start:i]] = ranks[order[start:i]].mean()
            start = i
    return ranks


def rank_within_symbol(values, symbols):
    """Mid-rank within each symbol, scaled to [0,1].

    Removes cross-symbol level differences so a feature cannot score merely
    by proxying symbol identity (spec §4.2).
    """
    values = np.asarray(values, dtype=float)
    symbols = np.asarray(symbols)
    out = np.zeros(len(values), dtype=float)
    for sym in np.unique(symbols):
        mask = symbols == sym
        n = int(mask.sum())
        out[mask] = (_midrank(values[mask]) - 0.5) / n if n > 1 else 0.5
    return out


def spearman_rho(x, y):
    rx, ry = _midrank(x), _midrank(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


def benjamini_hochberg(pvalues, q=Q_FDR):
    """Reject H_(1..k) where k = max{i : p_(i) <= i*q/m}. Returns a mask in
    INPUT order."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    if m == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p, kind="mergesort")
    thresholds = (np.arange(1, m + 1) * q) / m
    passing = np.where(p[order] <= thresholds)[0]
    mask = np.zeros(m, dtype=bool)
    if len(passing):
        mask[order[: passing[-1] + 1]] = True
    return mask


def cluster_bootstrap(x, y, clusters, n_draws=BOOTSTRAP_DRAWS, seed=SEED):
    """Cluster bootstrap over calendar-week blocks.

    Whole clusters are resampled with replacement (all symbols move together),
    preserving serial AND cross-sectional dependence. The null distribution
    permutes the feature across clusters, so dependence survives while the
    feature-outcome link is broken.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    clusters = np.asarray(clusters)
    observed = spearman_rho(x, y)

    unique = np.unique(clusters)
    index_by_cluster = {c: np.where(clusters == c)[0] for c in unique}
    rng = np.random.default_rng(seed)

    boot, null = np.empty(n_draws), np.empty(n_draws)
    for d in range(n_draws):
        picked = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([index_by_cluster[c] for c in picked])
        boot[d] = spearman_rho(x[idx], y[idx])

        shuffled = rng.permutation(unique)
        remap = np.concatenate([index_by_cluster[c] for c in shuffled])
        straight = np.concatenate([index_by_cluster[c] for c in unique])
        null[d] = spearman_rho(x[remap], y[straight])

    pvalue = float((np.abs(null) >= abs(observed)).mean())
    return {"rho": float(observed), "pvalue": pvalue,
            "ci_lo": float(np.quantile(boot, 0.025)),
            "ci_hi": float(np.quantile(boot, 0.975))}


def icc(values, clusters):
    """One-way ICC: between-cluster variance share. Feeds the design effect."""
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    unique = np.unique(clusters)
    if len(unique) < 2:
        return 0.0
    grand = values.mean()
    between, within, sizes = 0.0, 0.0, []
    for c in unique:
        group = values[clusters == c]
        sizes.append(len(group))
        between += len(group) * (group.mean() - grand) ** 2
        within += ((group - group.mean()) ** 2).sum()
    k = len(unique)
    n_bar = float(np.mean(sizes))
    ms_between = between / (k - 1)
    ms_within = within / max(len(values) - k, 1)
    denom = ms_between + (n_bar - 1) * ms_within
    return float((ms_between - ms_within) / denom) if denom > 0 else 0.0
