# src/analysis/ict_zones.py
# Canonical Unicorn zone primitives — breaker candle, FVG-in-leg, overlap.
# Frozen rule set: docs/research/2026-08-01-ict-revival-gate.md (Unicorn items
# 3-5). Pure stdlib functions shared by the revival rig
# (scripts/poc_ict_revival.py) and the future live strategy on GO — the same
# split as src/analysis/ict_structure.py.


def opposing_candle_before(opens, closes, idx, bearish, lookback=3):
    """Index of the last opposing-body candle at `idx` or up to `lookback`
    bars before it (window [idx-lookback, idx], newest first). bearish=True
    finds close<open (breaker source for a BULLISH setup); bearish=False the
    mirror. None when no such candle exists in the window."""
    for j in range(idx, max(-1, idx - lookback - 1), -1):
        if j < 0:
            break
        if bearish and closes[j] < opens[j]:
            return j
        if not bearish and closes[j] > opens[j]:
            return j
    return None


def bull_fvg_in_leg(highs, lows, lo_idx, hi_idx):
    """First bullish 3-candle FVG strictly inside [lo_idx, hi_idx]:
    at bar k, low[k] > high[k-2] -> zone (high[k-2], low[k]). None if absent."""
    for k in range(lo_idx + 2, hi_idx + 1):
        if lows[k] > highs[k - 2]:
            return (highs[k - 2], lows[k])
    return None


def bear_fvg_in_leg(highs, lows, hi_idx, lo_idx):
    """Mirror: at bar k, high[k] < low[k-2] -> zone (high[k], low[k-2])."""
    for k in range(hi_idx + 2, lo_idx + 1):
        if highs[k] < lows[k - 2]:
            return (highs[k], lows[k - 2])
    return None


def zone_overlap(a, b):
    """Intersection of two (lo, hi) bands; None when empty or zero-width."""
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return (lo, hi) if hi > lo else None
