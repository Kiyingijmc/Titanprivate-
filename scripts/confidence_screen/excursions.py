"""Entry-skew excursions: MFE/MAE in R, measured from the entry LEVEL.

Two rules that look like bugs and are not (spec §2.3):

1. MFE truncates at the first 1R adverse touch. Favourable movement after the
   stop would have fired is unrealizable; crediting it inverts the ranking of
   exactly the trades a confidence score exists to separate.
2. A signal whose entry level is never touched within W scores 0.0 and is
   RETURNED, not dropped. Zero is the realizable outcome of a signal that never
   becomes a position; dropping it selects on a post-signal event.

Intrabar ordering is unknowable, so a bar containing both the favourable and
the adverse extreme resolves ADVERSE FIRST — pessimistic, matching the SL-first
convention already used by poc_sb_stops.resolve.
"""
import numpy as np

from scripts.confidence_screen import H_BARS, W_BARS

_M5_PER_H1 = 12
# Tolerance for R-multiple boundary checks (1.0 and 2.0) to account for IEEE 754
# floating-point precision. Arithmetic like (ENTRY + 2.0 * RISK - ENTRY) / RISK
# may yield 2.0000000000000018 instead of exactly 2.0. This tolerance only catches
# precision artifacts (~1e-13 relative error), not real data deviations.
_R_EPS = 1e-10


def excursions(sig, m5, h_bars=H_BARS, w_bars=W_BARS):
    entry = float(sig["entry"])
    risk = float(sig["risk"])
    is_long = sig["dir"] == "BUY"

    empty = {"filled": False, "touch_idx": None, "mfe": 0.0, "mae": 0.0,
             "skew": 0.0, "hit_2r_before_1r": False}
    if risk <= 0.0:
        return empty

    start = np.searchsorted(m5["time"], np.datetime64(sig["time"]), side="right")
    highs, lows = m5["high"], m5["low"]
    n = len(highs)

    wait_end = min(start + w_bars * _M5_PER_H1, n)
    touch = None
    for k in range(start, wait_end):
        if lows[k] <= entry <= highs[k]:
            touch = k
            break
    if touch is None:
        return empty

    mfe = 0.0
    mae = 0.0
    hit_2r = False
    window_end = min(touch + h_bars * _M5_PER_H1, n)
    for k in range(touch, window_end):
        if is_long:
            adverse = (entry - lows[k]) / risk
            favourable = (highs[k] - entry) / risk
        else:
            adverse = (highs[k] - entry) / risk
            favourable = (entry - lows[k]) / risk

        # Adverse first (pessimistic) — see module docstring.
        if adverse >= 1.0 - _R_EPS:
            mae = 1.0
            break
        mae = max(mae, max(adverse, 0.0))
        favourable = max(favourable, 0.0)
        if favourable >= 2.0 - _R_EPS:
            hit_2r = True
        mfe = max(mfe, favourable)

    return {"filled": True, "touch_idx": int(touch), "mfe": float(mfe),
            "mae": float(mae), "skew": float(mfe - mae),
            "hit_2r_before_1r": bool(hit_2r)}
