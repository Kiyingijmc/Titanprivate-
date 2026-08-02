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


def _session_first_idx(ny_times, session_start_min):
    """Index of the first bar of the CURRENT session instance (most recent
    crossing of session_start at or before the last bar), or None."""
    last = ny_times[-1]
    anchor = last.replace(hour=session_start_min // 60,
                          minute=session_start_min % 60,
                          second=0, microsecond=0)
    if anchor > last:
        anchor -= timedelta(days=1)
    first = None
    for i in range(len(ny_times) - 1, -1, -1):
        if ny_times[i] < anchor:
            break
        first = i
    return first


def detect_judas(bars, ny_times, rng, session_start_min, bias, cfg):
    """Session-open sweep of the pre-session range, then displacement back
    inside, traded with H1 bias. Evaluates the LAST bar; pure. Spec section 3."""
    rng_hi, rng_lo = rng
    i = len(ny_times) - 1
    first = _session_first_idx(ny_times, session_start_min)
    if first is None:
        return None

    hi_breach = lo_breach = None
    for k in range(first, i + 1):
        if hi_breach is None and bars["high"][k] > rng_hi:
            hi_breach = k
        if lo_breach is None and bars["low"][k] < rng_lo:
            lo_breach = k
    if (hi_breach is None) == (lo_breach is None):
        return None                    # no sweep, or both sides = ambiguous

    atr = float(bars["atr"][i])
    if atr <= 0:
        return None
    body = abs(bars["close"][i] - bars["open"][i])
    if body < cfg["body_min_atr"] * atr:
        return None
    close = float(bars["close"][i])
    if not (rng_lo < close < rng_hi):
        return None                    # must close strictly back inside

    if hi_breach is not None:          # highs swept -> reversal SELL
        if i - hi_breach > cfg["sweep_ttl_bars"]:
            return None
        if bias != "BEARISH" or close >= bars["open"][i]:
            return None
        if not bars["is_fvg_bear"][i]:
            return None
        entry = float(bars["fvg_bottom"][i])
        sweep_ext = max(bars["high"][k] for k in range(hi_breach, i + 1))
        sl = sweep_ext + cfg["stop_buffer_atr"] * atr
        risk = sl - entry
        if risk <= 0:
            return None
        return {"signal": "SELL", "type": "LIMIT", "price": entry,
                "sl": sl, "tp": entry - cfg["rr"] * risk, "setup": "judas"}

    # lows swept -> reversal BUY
    if i - lo_breach > cfg["sweep_ttl_bars"]:
        return None
    if bias != "BULLISH" or close <= bars["open"][i]:
        return None
    if not bars["is_fvg_bull"][i]:
        return None
    entry = float(bars["fvg_top"][i])
    sweep_ext = min(bars["low"][k] for k in range(lo_breach, i + 1))
    sl = sweep_ext - cfg["stop_buffer_atr"] * atr
    risk = entry - sl
    if risk <= 0:
        return None
    return {"signal": "BUY", "type": "LIMIT", "price": entry,
            "sl": sl, "tp": entry + cfg["rr"] * risk, "setup": "judas"}


def detect_reprise(bars, bias, cfg):
    """Frozen SilverBullet FVG-displacement entry with the STRUCT stop model
    (poc_sb_stops stop_price, model='STRUCT'). Evaluates the LAST bar; pure."""
    i = len(bars["close"]) - 1
    if i < 2:
        return None
    atr = float(bars["atr"][i])
    if atr <= 0:
        return None
    if abs(bars["close"][i] - bars["open"][i]) < cfg["body_min_atr"] * atr:
        return None

    if bars["is_fvg_bear"][i] and bias == "BEARISH":
        entry = float(bars["fvg_bottom"][i])
        d = abs(entry - float(bars["high"][i - 2])) + cfg["stop_buffer_atr"] * atr
        return {"signal": "SELL", "type": "LIMIT", "price": entry,
                "sl": entry + d, "tp": entry - cfg["rr"] * d, "setup": "reprise"}

    if bars["is_fvg_bull"][i] and bias == "BULLISH":
        entry = float(bars["fvg_top"][i])
        d = abs(entry - float(bars["low"][i - 2])) + cfg["stop_buffer_atr"] * atr
        return {"signal": "BUY", "type": "LIMIT", "price": entry,
                "sl": entry - d, "tp": entry + cfg["rr"] * d, "setup": "reprise"}
    return None
