"""Adapter onto the SHIPPED SignalGrader.

Do not reimplement the scoring here. scripts/poc_sb_stops.py:549 already
carries an offline mirror that has drifted from src/analysis/signal_grader.py
(RR hardcoded, epsilon tolerances and the degenerate-risk guard missing);
reproducing that mistake is the specific failure this module prevents.

The decomposed columns below (bias_class/bias_points/displacement_bucket/
pd_array/killzone) are PARSED out of the grader's own `factors` strings
rather than recomputed from raw inputs against hardcoded thresholds/points.
Recomputing drifted from the real grader in two confirmed ways: it lacked
the grader's `eps = 1e-6` float tolerance on the displacement thresholds,
and it returned 0 (not the grader's actual +5) for pd_array when
liq_status is eq/unknown ("", "EQ", None). Parsing the grader's own strings
makes the columns immune to any future change in its thresholds or point
weights.
"""
from src.analysis.signal_grader import SignalGrader

from scripts.confidence_screen import NY_SHIFT

_DEFAULT_GRADER = SignalGrader({"signal_grading": {"enabled": True, "min_grade": "C"}})

_BIAS_LABELS = {
    "bias_aligned": "aligned",
    "bias_neutral": "neutral",
    "bias_counter": "counter",
}


def _ny_hour(broker_hour):
    return (int(broker_hour) + NY_SHIFT) % 24


def _parse_points(factors, prefix):
    """Return the trailing +N integer of the factor string starting with
    `prefix`, or 0 if no such factor is present.

    The only case with no such factor is the grader's degenerate
    entry==sl short-circuit, which returns factors == ['invalid_risk_distance']
    with none of the usual per-factor strings (score is 0 there too).
    """
    for f in factors:
        if f.startswith(prefix):
            return int(f.rsplit("+", 1)[1])
    return 0


def _parse_bias(factors):
    """Return (bias_class, bias_points) parsed from whichever bias_* factor
    string the grader returned. Degenerate entry==sl signals carry no bias
    factor at all; documented here as ("invalid", 0) rather than guessed."""
    for prefix, label in _BIAS_LABELS.items():
        for f in factors:
            if f.startswith(prefix):
                return label, int(f.rsplit("+", 1)[1])
    return "invalid", 0


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
    factors = result["factors"]

    bias_class, bias_points = _parse_bias(factors)

    return {
        **result,
        "bias_class": bias_class,
        "bias_points": bias_points,
        "displacement_bucket": _parse_points(factors, "displacement="),
        "pd_array": _parse_points(factors, "pd_array="),
        "killzone": _parse_points(factors, "killzone"),
    }
