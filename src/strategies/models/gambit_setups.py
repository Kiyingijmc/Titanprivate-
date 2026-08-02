# ==============================================================================
# FILE: src/strategies/models/gambit_setups.py
# Gambit playbook — pure setup logic (no I/O, no state, no pandas dependency
# beyond duck-typed sequences). The live chassis (gambit.py) AND the research
# harness (scripts/poc_gambit.py) both import these functions, so live and
# research logic cannot drift.
# Spec: docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md
# ==============================================================================
from datetime import timedelta


def _minutes(dt):
    return dt.hour * 60 + dt.minute


def compute_presession_range(ny_times, highs, lows,
                             range_start_min, range_end_min, min_bars=12):
    """High/low of the pre-session range anchored to the most recent
    range_end boundary at or before the last bar. start > end means the
    range window crosses midnight. Returns (hi, lo, n_bars) or None."""
    if not len(ny_times):
        return None
    last = ny_times[-1]
    # Most recent range_end boundary at or before `last`.
    anchor = last.replace(hour=range_end_min // 60, minute=range_end_min % 60,
                          second=0, microsecond=0)
    if anchor > last:
        anchor -= timedelta(days=1)
    duration_min = (range_end_min - range_start_min) % (24 * 60)
    start = anchor - timedelta(minutes=duration_min)
    hi = lo = None
    n = 0
    for i in range(len(ny_times) - 1, -1, -1):     # walk back; bars ascend
        t = ny_times[i]
        if t >= anchor:
            continue
        if t < start:
            break
        hi = highs[i] if hi is None else max(hi, highs[i])
        lo = lows[i] if lo is None else min(lo, lows[i])
        n += 1
    if n < min_bars:
        return None
    return hi, lo, n
