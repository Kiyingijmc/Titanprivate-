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


if __name__ == "__main__":
    unittest.main()
