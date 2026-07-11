# tests/unit/test_ote_structure.py
import unittest

from src.analysis.ote_structure import (
    is_swing_high, is_swing_low, confirmed_swings, structure_bias,
)

# Shared fixture: lk=1 uptrend with confirmed HH+HL.
# Swing highs at j=2 (10) and j=6 (12); swing lows at j=4 (8) and j=8 (9).
HIGHS = [9.0, 9.5, 10.0, 9.2, 8.5, 9.5, 12.0, 10.0, 9.5, 10.5, 11.0]
LOWS  = [8.5, 9.0,  9.5, 8.8, 8.0, 9.0, 11.0,  9.2, 9.0,  9.8, 10.2]


class TestSwings(unittest.TestCase):
    def test_swing_high_strict(self):
        self.assertTrue(is_swing_high(HIGHS, 2, 1))
        self.assertFalse(is_swing_high(HIGHS, 3, 1))
        # ties are NOT swings (strict inequality)
        self.assertFalse(is_swing_high([1.0, 2.0, 2.0], 1, 1))

    def test_swing_low_strict(self):
        self.assertTrue(is_swing_low(LOWS, 4, 1))
        self.assertFalse(is_swing_low(LOWS, 5, 1))

    def test_confirmed_swings_indices(self):
        his, los = confirmed_swings(HIGHS, LOWS, 1)
        self.assertEqual(his, [2, 6])
        self.assertEqual(los, [4, 8])


class TestStructureBias(unittest.TestCase):
    def test_uptrend_turns_bullish_only_after_confirmation(self):
        bias = structure_bias(HIGHS, LOWS, lk=1)
        # SL@8 confirms at bar 9 (j+lk); before that, <2 confirmed lows -> NEUTRAL
        self.assertEqual(bias[8], "NEUTRAL")
        self.assertEqual(bias[9], "BULLISH")   # HH (12>10) and HL (9>8)
        self.assertEqual(bias[10], "BULLISH")

    def test_downtrend_mirror(self):
        h = [x for x in reversed(HIGHS)]
        l = [x for x in reversed(LOWS)]
        # reversed series trends down; find at least one BEARISH bar at the end
        bias = structure_bias(h, l, lk=1)
        self.assertIn("BEARISH", bias)
        self.assertEqual(bias[-1], "BEARISH")

    def test_short_series_all_neutral(self):
        self.assertEqual(structure_bias([1.0, 2.0], [0.5, 1.5], lk=3),
                         ["NEUTRAL", "NEUTRAL"])


if __name__ == "__main__":
    unittest.main()
