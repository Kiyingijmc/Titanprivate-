"""Adapter onto the SHIPPED SignalGrader.

Do not reimplement the scoring here. scripts/poc_sb_stops.py:549 already
carries an offline mirror that has drifted from src/analysis/signal_grader.py
(RR hardcoded, epsilon tolerances and the degenerate-risk guard missing);
reproducing that mistake is the specific failure this module prevents.
"""
from src.analysis.signal_grader import SignalGrader

from scripts.confidence_screen import NY_SHIFT

_DEFAULT_GRADER = SignalGrader({"signal_grading": {"enabled": True, "min_grade": "C"}})


def _ny_hour(broker_hour):
    return (int(broker_hour) + NY_SHIFT) % 24


def _bias_class(bias, direction):
    if (bias == "BULLISH" and direction == "BUY") or (bias == "BEARISH" and direction == "SELL"):
        return "aligned"
    return "neutral" if bias == "NEUTRAL" else "counter"


def grade_signal(sig, grader=None):
    """Score one signal with the shipped grader, plus decomposed factors."""
    grader = grader or _DEFAULT_GRADER
    direction = sig["dir"]

    decision = {"signal": direction, "price": sig["entry"], "sl": sig["sl"], "tp": sig["tp"]}
    context = {
        "bias": sig["bias"],
        "liquidity": {"STATUS": sig["liq_status"]},
        "ny_time": f"{_ny_hour(sig['hour'])}:00",
    }
    # The grader needs body/ATR; reconstruct a candle with the recorded ratio.
    body = float(sig["body_atr"]) * float(sig["atr"])
    candle = {"open": sig["entry"], "close": sig["entry"] + body, "ATR": sig["atr"]}

    result = grader.grade(decision, context, candle)

    ratio = float(sig["body_atr"])
    displacement = 20 if ratio >= 1.5 else 15 if ratio >= 1.0 else 10 if ratio >= 0.8 else 0
    status = sig["liq_status"]
    pd_array = 15 if (direction == "BUY" and status == "DISCOUNT") or \
                     (direction == "SELL" and status == "PREMIUM") else 0
    killzone = 15 if any(a <= _ny_hour(sig["hour"]) < b for a, b in SignalGrader.KILLZONES) else 0

    return {
        **result,
        "bias_class": _bias_class(sig["bias"], direction),
        "displacement_bucket": displacement,
        "pd_array": pd_array,
        "killzone": killzone,
    }
