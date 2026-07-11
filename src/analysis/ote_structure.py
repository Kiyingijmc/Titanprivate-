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


def impulse_leg(highs, lows, upto, lk, bias, swh=None, swl=None):
    """Most recent leg in the bias direction that BROKE the prior swing, using
    bars [0..upto]. BULL: a confirmed swing high exceeding the previous confirmed
    swing high (BOS up); origin = most recent confirmed swing low before it.
    Returns (leg_low, leg_high, lo_idx, hi_idx) or None.
    Pass precomputed full-series swh/swl (confirmed_swings on the whole array)
    for the O(log n) fast path; both paths are behavior-equivalent."""
    if bias not in ("BULLISH", "BEARISH"):
        return None
    if swh is None or swl is None:
        swh, swl = confirmed_swings(highs[:upto + 1], lows[:upto + 1], lk)
        nh, nl = len(swh), len(swl)
    else:
        cutoff = upto - lk
        nh = bisect.bisect_right(swh, cutoff)
        nl = bisect.bisect_right(swl, cutoff)
    if bias == "BULLISH":
        for k in range(nh - 1, 0, -1):
            if highs[swh[k]] > highs[swh[k - 1]]:            # BOS up
                hi = swh[k]
                p = bisect.bisect_left(swl, hi, 0, nl) - 1   # last low before hi
                if p >= 0:
                    lo = swl[p]
                    return (lows[lo], highs[hi], lo, hi)
        return None
    for k in range(nl - 1, 0, -1):
        if lows[swl[k]] < lows[swl[k - 1]]:                  # BOS down
            lo = swl[k]
            p = bisect.bisect_left(swh, lo, 0, nh) - 1       # last high before lo
            if p >= 0:
                hi = swh[p]
                return (lows[lo], highs[hi], lo, hi)
    return None


def ote_zone(leg_low, leg_high, bias, lo=0.62, hi=0.79):
    """Golden-zone price band (z_lo, z_hi). BULL: measured down from the high."""
    rng = leg_high - leg_low
    if bias == "BULLISH":
        return (leg_high - hi * rng, leg_high - lo * rng)
    return (leg_low + lo * rng, leg_low + hi * rng)


def zone_invalidation(z_lo, z_hi, atr, is_long, buffer_mult=0.1):
    """Level the stop must sit at/beyond: past the 0.79 edge + 0.1*ATR buffer."""
    return (z_lo - buffer_mult * atr) if is_long else (z_hi + buffer_mult * atr)


def precompute_last_swings(highs, lows, lk):
    """For each bar i, the index of the most recent CONFIRMED swing high / low
    usable at i (a swing at j is confirmed once j+lk < i). O(n). -1 where none."""
    n = len(highs)
    swh, swl = confirmed_swings(highs, lows, lk)
    last_swh = [-1] * n
    last_swl = [-1] * n
    p, cur = 0, -1
    for i in range(n):
        while p < len(swh) and swh[p] + lk < i:
            cur = swh[p]; p += 1
        last_swh[i] = cur
    p, cur = 0, -1
    for i in range(n):
        while p < len(swl) and swl[p] + lk < i:
            cur = swl[p]; p += 1
        last_swl[i] = cur
    return last_swh, last_swl


def mss_confirm(highs, lows, closes, i, bias, last_swh, last_swl):
    """M5 market-structure shift at bar i in the trend direction: the close
    breaks the last confirmed opposing minor swing. Pure timing signal — the
    stop is H1-anchored by spec and never derives from M5 structure."""
    if bias == "BULLISH":
        sh = last_swh[i]
        return sh >= 0 and closes[i] > highs[sh]
    sl = last_swl[i]
    return sl >= 0 and closes[i] < lows[sl]


# --- setup lifecycle states -------------------------------------------------
AWAIT_ZONE = "AWAIT_ZONE"   # leg + zone exist; price hasn't traded into the zone
IN_ZONE = "IN_ZONE"         # price has touched the zone; watching for M5 MSS
CONFIRMED = "CONFIRMED"     # MSS printed -> enter MARKET at next bar open
DEAD = "DEAD"               # leg origin breached; setup invalid


def stop_anchor(entry, pullback_ext, inval_level, atr, is_long, floor_mult=0.5):
    """H1-anchored stop: the most protective of (a) beyond the pullback extreme,
    (b) beyond zone invalidation, (c) >= floor_mult*ATR(H1) from entry. The M5
    confirmation NEVER tightens the stop (spec section 1)."""
    if is_long:
        return min(pullback_ext, inval_level, entry - floor_mult * atr)
    return max(pullback_ext, inval_level, entry + floor_mult * atr)


def advance_setup(state, is_long, z_lo, z_hi, leg_origin,
                  bar_high, bar_low, bar_close, mss_ok):
    """One closed-M5-bar transition of the setup state machine.
    AWAIT_ZONE -> IN_ZONE on zone touch; IN_ZONE -> CONFIRMED on MSS; any live
    state -> DEAD when the bar trades beyond the leg origin. A single bar that
    both touches the zone and prints MSS confirms immediately (accepted edge)."""
    if state in (CONFIRMED, DEAD):
        return state
    if (is_long and bar_low <= leg_origin) or \
       (not is_long and bar_high >= leg_origin):
        return DEAD
    if state == AWAIT_ZONE:
        touched = (bar_low <= z_hi) if is_long else (bar_high >= z_lo)
        if not touched:
            return AWAIT_ZONE
        state = IN_ZONE
    if state == IN_ZONE and mss_ok:
        return CONFIRMED
    return state
