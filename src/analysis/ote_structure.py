# src/analysis/ote_structure.py
# ==============================================================================
# Canonical OTE detection primitives — SHARED by the backtest rig
# (scripts/poc_ote_canonical.py) and the future live strategy (on GO).
# Pure functions only: no pandas, no I/O, no logging. Spec:
# docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md
# Definitions ported from scripts/poc_mtf_pb.py / poc_mtf_pb2.py (frozen studies).
# ==============================================================================
import bisect


def is_swing_high(highs, j, lk):
    """True when highs[j] is strictly greater than all lk neighbours each side."""
    window = list(highs[j - lk:j + lk + 1])
    return highs[j] > max(window[:lk] + window[lk + 1:])


def is_swing_low(lows, j, lk):
    """True when lows[j] is strictly less than all lk neighbours each side."""
    window = list(lows[j - lk:j + lk + 1])
    return lows[j] < min(window[:lk] + window[lk + 1:])


def confirmed_swings(highs, lows, lk):
    """Index lists (his, los) of confirmed swing highs / lows (lk bars each side)."""
    n = len(highs)
    his = [j for j in range(lk, n - lk) if is_swing_high(highs, j, lk)]
    los = [j for j in range(lk, n - lk) if is_swing_low(lows, j, lk)]
    return his, los


def structure_bias(highs, lows, lk=3):
    """Per-bar BOS bias. BULLISH when the last two confirmed swing highs are
    higher-high AND the last two confirmed swing lows are higher-low; BEARISH on
    the mirror; else NEUTRAL. A swing at j is 'confirmed' from bar j+lk on
    (no look-ahead); bias[i] is usable at the close of bar i."""
    n = len(highs)
    his, los = confirmed_swings(highs, lows, lk)
    cl_h = [j + lk for j in his]
    cl_l = [j + lk for j in los]
    out = []
    hp = lp = 0
    for i in range(n):
        while hp < len(cl_h) and cl_h[hp] <= i:
            hp += 1
        while lp < len(cl_l) and cl_l[lp] <= i:
            lp += 1
        if hp >= 2 and lp >= 2:
            hh = highs[his[hp - 1]] > highs[his[hp - 2]]
            hl = lows[los[lp - 1]] > lows[los[lp - 2]]
            lh = highs[his[hp - 1]] < highs[his[hp - 2]]
            ll = lows[los[lp - 1]] < lows[los[lp - 2]]
            out.append("BULLISH" if (hh and hl) else
                       "BEARISH" if (lh and ll) else "NEUTRAL")
        else:
            out.append("NEUTRAL")
    return out
