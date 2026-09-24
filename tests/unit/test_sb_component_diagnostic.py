"""Guard the diagnostic's admission order and the live neutral-bias rule."""
import unittest

from scripts.sb_component_diagnostic import bias_passes, grade_passes, evaluate


def signal(**overrides):
    s = dict(bar_idx=0, time="2024-01-01 00:00:00", dir="BUY", entry=100.,
             atr=1., body_atr=1., bias="BULLISH", liq_status="PREMIUM", hour=0)
    return {**s, **overrides}


class ComponentDiagnosticTest(unittest.TestCase):
    def test_neutral_admits_both_directions_and_opposition_is_blocked(self):
        for direction in ("BUY", "SELL"):
            self.assertTrue(bias_passes(signal(dir=direction, bias="NEUTRAL")))
        self.assertFalse(bias_passes(signal(bias="BEARISH")))
        self.assertFalse(bias_passes(signal(dir="SELL")))

    def test_grade_is_separate_from_bias_veto(self):
        # Aligned +30, 2R +15, 1ATR body +15 =60, outside killzone.
        self.assertTrue(grade_passes(signal()))
        # Neutral +10 gives 40, so bias accepts but B-grade rejects.
        self.assertTrue(bias_passes(signal(bias="NEUTRAL")))
        self.assertFalse(grade_passes(signal(bias="NEUTRAL")))

    def test_rejected_pending_order_does_not_block_later_candidate(self):
        signals = [signal(bias="BEARISH"),
                   signal(bar_idx=2, time="2024-01-01 02:00:00", entry=102.)]
        bars = {"high": [101., 101., 103., 103., 105.],
                "low": [100.5, 100.5, 102.5, 101.5, 103.5]}
        specs = {"EURUSD": {"tick_size": .00001, "tick_value": 1.}}
        rows, counts = evaluate(signals, bars, "EURUSD", specs)
        self.assertEqual(counts["raw"]["resolved"], 0)
        self.assertEqual(counts["bias"]["resolved"], 1)
        fixed = [r for r in rows if r["gate"] == "bias" and r["exit"] == "fixed"]
        self.assertEqual(len(fixed), 1)
        self.assertGreater(fixed[0]["net_r"], 1.99)


if __name__ == "__main__":
    unittest.main()
