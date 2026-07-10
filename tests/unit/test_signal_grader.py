import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.analysis.signal_grader import SignalGrader  # noqa: E402


def decision(signal="BUY", entry=1.1000, sl=1.0950, tp=1.1100):
    return {"signal": signal, "type": "LIMIT", "price": entry, "sl": sl, "tp": tp}


def context(bias="BULLISH", status="DISCOUNT", ny_hour=10):
    return {
        "bias": bias,
        "liquidity": {"STATUS": status},
        "ny_time": f"{ny_hour:02d}:15:00 EST",
    }


def candle(body_atr=1.5):
    # ATR 0.0010, body scaled to requested ratio
    return {"open": 1.1000, "close": 1.1000 + 0.0010 * body_atr, "ATR": 0.0010}


class Scoring(unittest.TestCase):
    def setUp(self):
        self.g = SignalGrader({})

    def test_perfect_confluence_is_a_plus_plus(self):
        # Aligned bias (30) + RR 2 (15) + displacement 1.5 (20) + discount buy (15) + killzone (15) = 95
        res = self.g.grade(decision(), context(), candle(1.5))
        self.assertEqual(res["grade"], "A++")
        self.assertGreaterEqual(res["score"], 90)

    def test_neutral_bias_downgrades(self):
        res = self.g.grade(decision(), context(bias="NEUTRAL"), candle(1.5))
        aligned = self.g.grade(decision(), context(), candle(1.5))
        self.assertLess(res["score"], aligned["score"])

    def test_counter_bias_scores_zero_for_bias(self):
        res = self.g.grade(decision(signal="SELL"), context(bias="BULLISH", status="PREMIUM"), candle(1.5))
        self.assertNotIn("bias_aligned", [f.split("=")[0] for f in res["factors"] if "bias" in f and "+30" in f])
        self.assertLess(res["score"], 90)

    def test_high_rr_scores_more(self):
        rr3 = self.g.grade(decision(tp=1.1150), context(), candle(1.5))  # RR 3
        rr15 = self.g.grade(decision(tp=1.1075), context(), candle(1.5))  # RR 1.5
        self.assertGreater(rr3["score"], rr15["score"])

    def test_wrong_side_of_range_penalized(self):
        buy_premium = self.g.grade(decision(), context(status="PREMIUM"), candle(1.5))
        buy_discount = self.g.grade(decision(), context(status="DISCOUNT"), candle(1.5))
        self.assertGreater(buy_discount["score"], buy_premium["score"])

    def test_outside_killzone_penalized(self):
        kz = self.g.grade(decision(), context(ny_hour=10), candle(1.5))
        off = self.g.grade(decision(), context(ny_hour=12), candle(1.5))
        self.assertGreater(kz["score"], off["score"])

    def test_invalid_sl_distance_grades_c(self):
        res = self.g.grade(decision(sl=1.1000), context(), candle(1.5))  # zero risk distance
        self.assertEqual(res["grade"], "C")

    def test_missing_candle_still_grades(self):
        res = self.g.grade(decision(), context(), None)
        self.assertIn(res["grade"], ["C", "B", "A", "A+", "A++"])


class Gating(unittest.TestCase):
    def test_min_grade_gate(self):
        g = SignalGrader({"signal_grading": {"min_grade": "A"}})
        self.assertTrue(g.passes("A++"))
        self.assertTrue(g.passes("A"))
        self.assertFalse(g.passes("B"))
        self.assertFalse(g.passes("C"))

    def test_disabled_passes_everything(self):
        g = SignalGrader({"signal_grading": {"enabled": False, "min_grade": "A++"}})
        self.assertTrue(g.passes("C"))

    def test_default_gate_is_b(self):
        g = SignalGrader({})
        self.assertTrue(g.passes("B"))
        self.assertFalse(g.passes("C"))


if __name__ == "__main__":
    unittest.main()
