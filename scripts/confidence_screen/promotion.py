"""Promotion criteria (spec §4.5) — economic floor, sign consistency, tie-break."""
import numpy as np

from scripts.confidence_screen import MIN_CELL_N


def _group_means(values, skew, min_cell_n):
    means = []
    for level in np.unique(values):
        cell = skew[values == level]
        if len(cell) >= min_cell_n:
            means.append(float(cell.mean()))
    return means


def economic_spread(values, skew, kind, min_cell_n=MIN_CELL_N):
    """Top-vs-bottom spread in R. Cells below min_cell_n are excluded so a
    thin group cannot manufacture a spread."""
    values = np.asarray(values)
    skew = np.asarray(skew, dtype=float)
    if len(skew) == 0:
        return 0.0

    if kind == "continuous":
        vals = values.astype(float)
        lo_cut, hi_cut = np.quantile(vals, 0.2), np.quantile(vals, 0.8)
        bottom, top = skew[vals <= lo_cut], skew[vals >= hi_cut]
        if len(bottom) < min_cell_n or len(top) < min_cell_n:
            return 0.0
        return float(top.mean() - bottom.mean())

    means = _group_means(values, skew, min_cell_n)
    return float(max(means) - min(means)) if len(means) >= 2 else 0.0


def sign_consistency(values, skew, groups, kind, min_cell_n=MIN_CELL_N):
    """How many groups (symbols or years) agree with the pooled direction."""
    values, skew, groups = np.asarray(values), np.asarray(skew, dtype=float), np.asarray(groups)
    pooled = economic_spread(values, skew, kind, min_cell_n)
    sign = int(np.sign(pooled))
    agree = 0
    total = 0
    for g in np.unique(groups):
        mask = groups == g
        cell = economic_spread(values[mask], skew[mask], kind, min_cell_n=1)
        if cell == 0.0:
            continue
        total += 1
        if int(np.sign(cell)) == sign:
            agree += 1
    return {"agree": agree, "total": total, "sign": sign}


def select_winner(results):
    """Exactly one feature is promoted, ranked on economic-floor MAGNITUDE.

    Not on p-value: under clustered inference the p-value is the noisier
    quantity, and ranking on it selects on sampling error (spec §4.4).
    """
    passing = [r for r in results if r.get("promoted")]
    if not passing:
        return None
    return max(passing, key=lambda r: abs(r["spread"]))
