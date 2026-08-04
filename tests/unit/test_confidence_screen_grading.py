import itertools
import unittest
import pandas as pd

from scripts.confidence_screen.grading import grade_signal
from scripts.confidence_screen.population import add_stop_and_target


def _sig(**kw):
    base = {
        "bar_idx": 100, "time": pd.Timestamp("2024-01-02 10:00:00"),
        "dir": "BUY", "entry": 1.1000, "far_extreme": 1.0980,
        "sig_high": 1.1010, "sig_low": 1.0990, "atr": 0.0010, "body_atr": 1.6,
        "bias": "BULLISH", "liq_status": "DISCOUNT", "hour": 16, "year": 2024,
        "symbol": "EURUSD",
    }
    base.update(kw)
    return add_stop_and_target(base)


class TestGradeSignal(unittest.TestCase):
    def test_perfect_signal_scores_95_and_grades_a_plus_plus(self):
        """bias_aligned 30 + rr(2.0) 15 + displacement(1.6) 20
        + pd_array(BUY in DISCOUNT) 15 + killzone 15 = 95.
        hour 16 broker -> NY 9 -> inside the 07-11 killzone."""
        out = grade_signal(_sig())
        self.assertEqual(out["score"], 95)
        self.assertEqual(out["grade"], "A++")

    def test_counter_bias_loses_exactly_thirty(self):
        out = grade_signal(_sig(bias="BEARISH"))
        self.assertEqual(out["score"], 65)

    def test_outside_killzone_loses_exactly_fifteen(self):
        # hour 0 broker -> NY 17 -> outside all three killzones
        out = grade_signal(_sig(hour=0))
        self.assertEqual(out["score"], 80)

    def test_rr_factor_is_constant_fifteen_for_every_signal(self):
        """SilverBullet pins rr=2.0, so the grader's 20-point RR factor is a
        constant 15. This is the spec's §1.2 finding; if it ever varies, the
        panel's exclusion of RR is no longer valid."""
        for atr in (0.0005, 0.0010, 0.0050):
            for direction in ("BUY", "SELL"):
                out = grade_signal(_sig(atr=atr, dir=direction))
                rr_factors = [f for f in out["factors"] if f.startswith("rr=")]
                self.assertEqual(rr_factors, ["rr=2.00 +15"])

    def test_decomposed_factor_columns_match_the_score(self):
        out = grade_signal(_sig())
        self.assertEqual(out["bias_class"], "aligned")
        self.assertEqual(out["displacement_bucket"], 20)
        self.assertEqual(out["pd_array"], 15)
        self.assertEqual(out["killzone"], 15)

    def test_neutral_bias_is_its_own_class_not_counter(self):
        out = grade_signal(_sig(bias="NEUTRAL"))
        self.assertEqual(out["bias_class"], "neutral")
        self.assertEqual(out["score"], 75)

    # --- Regression tests: these fail against the old recompute-from-raw-inputs
    # adapter, which drifted from the real grader's epsilon tolerance and its
    # eq/unknown pd_array points. ---

    def test_displacement_bucket_uses_the_graders_epsilon_tolerance(self):
        """body_atr=1.4999999 is float-noise for 1.5. The real grader treats
        it as >= 1.5 - eps and awards 20 (score 95, A++); the old recompute
        used a bare `>=` with no epsilon and recorded 15 instead."""
        out = grade_signal(_sig(body_atr=1.4999999))
        self.assertEqual(out["displacement_bucket"], 20)
        self.assertEqual(out["score"], 95)
        self.assertEqual(out["grade"], "A++")

    def test_pd_array_awards_five_for_empty_liq_status(self):
        """liq_status="" is eq/unknown to the real grader: +5, not the old
        recompute's 0."""
        out = grade_signal(_sig(liq_status=""))
        self.assertEqual(out["pd_array"], 5)

    def test_pd_array_awards_five_for_eq_liq_status(self):
        """liq_status="EQ" is also eq/unknown: +5, not the old recompute's 0."""
        out = grade_signal(_sig(liq_status="EQ"))
        self.assertEqual(out["pd_array"], 5)

    def test_degenerate_entry_equals_sl_does_not_crash_and_documents_defaults(self):
        """The grader short-circuits entry==sl with
        factors == ['invalid_risk_distance'] and no per-factor +N strings at
        all. Parsing must not crash on that; the documented default is
        bias_class="invalid", and 0 for every point column."""
        sig = {
            "dir": "BUY", "entry": 1.1000, "sl": 1.1000, "tp": 1.1200,
            "atr": 0.0010, "body_atr": 1.6, "bias": "BULLISH",
            "liq_status": "DISCOUNT", "hour": 16,
        }
        out = grade_signal(sig)
        self.assertEqual(out["score"], 0)
        self.assertEqual(out["grade"], "C")
        self.assertEqual(out["bias_class"], "invalid")
        self.assertEqual(out["bias_points"], 0)
        self.assertEqual(out["displacement_bucket"], 0)
        self.assertEqual(out["pd_array"], 0)
        self.assertEqual(out["killzone"], 0)

    def test_score_equals_sum_of_the_decomposed_factor_points(self):
        """Strongest guard: for a spread of generated signals, the returned
        decomposed columns (plus the rr points read straight off `factors`)
        must always sum to exactly `score`. Any future drift between the
        columns and the real score is impossible to miss."""
        cases = itertools.product(
            ("BUY", "SELL"),
            ("BULLISH", "BEARISH", "NEUTRAL"),
            (0.3, 0.8, 0.9999999, 1.0, 1.4999999, 1.5, 2.5),
            ("DISCOUNT", "PREMIUM", "EQ", "", None),
            (0, 3, 6, 8, 12, 16, 23),
        )
        for direction, bias, body_atr, liq_status, hour in cases:
            with self.subTest(direction=direction, bias=bias, body_atr=body_atr,
                               liq_status=liq_status, hour=hour):
                out = grade_signal(_sig(
                    dir=direction, bias=bias, body_atr=body_atr,
                    liq_status=liq_status, hour=hour,
                ))
                rr_factors = [f for f in out["factors"] if f.startswith("rr=")]
                rr_points = int(rr_factors[0].rsplit("+", 1)[1])
                total = (
                    out["bias_points"] + rr_points + out["displacement_bucket"]
                    + out["pd_array"] + out["killzone"]
                )
                self.assertEqual(total, out["score"])


if __name__ == "__main__":
    unittest.main()
