# tests/unit/test_ict_zones.py
# Canonical Unicorn zone primitives (2026-08-01-ict-revival-gate.md, frozen
# rule set items 3-5): breaker candle, FVG-in-leg, zone overlap. Pure
# synthetic arrays; the CRT raid machine is exercised end-to-end in
# test_ict_revival_rig.py.
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.ict_zones import (
    opposing_candle_before, bull_fvg_in_leg, bear_fvg_in_leg, zone_overlap,
)


class TestOpposingCandleBefore(unittest.TestCase):
    # bullish setup wants the last BEARISH candle (close<open) at/before the
    # leg-origin index, searching back at most `lookback` bars.
    def test_finds_bearish_at_origin(self):
        opens = [1, 2, 3, 4]
        closes = [2, 3, 2.5, 5]      # index 2 is bearish
        self.assertEqual(opposing_candle_before(opens, closes, 2, bearish=True), 2)

    def test_searches_back_within_lookback(self):
        opens = [5, 4, 1, 2]
        closes = [4, 5, 2, 3]        # index 0 bearish, 1..3 bullish
        self.assertEqual(opposing_candle_before(opens, closes, 3, bearish=True,
                                                lookback=3), 0)

    def test_none_beyond_lookback(self):
        opens = [5, 1, 2, 3]
        closes = [4, 2, 3, 4]        # only index 0 bearish
        self.assertIsNone(opposing_candle_before(opens, closes, 3, bearish=True,
                                                 lookback=2))

    def test_bullish_mirror(self):
        opens = [2, 5, 6]
        closes = [3, 4, 5]           # index 0 bullish, 1..2 bearish
        self.assertEqual(opposing_candle_before(opens, closes, 2, bearish=False,
                                                lookback=3), 0)


class TestFvgInLeg(unittest.TestCase):
    def test_bull_fvg_found(self):
        #        0    1    2    3
        highs = [10, 11, 12, 15]
        lows = [9, 10, 10.0, 12.5]   # bar 3: low 12.5 > high[1]=11 -> gap (11, 12.5)
        self.assertEqual(bull_fvg_in_leg(highs, lows, 0, 3), (11, 12.5))

    def test_bull_fvg_first_after_origin(self):
        highs = [10, 10.5, 12, 13, 16]
        lows = [9, 9.5, 11, 12, 14]  # bar2: low 11 > high[0]=10 -> (10,11) first
        self.assertEqual(bull_fvg_in_leg(highs, lows, 0, 4), (10, 11))

    def test_bull_no_fvg(self):
        highs = [10, 11, 12]
        lows = [9, 9.5, 10.0]        # low[2]=10.0 == high[0] -> no strict gap
        self.assertIsNone(bull_fvg_in_leg(highs, lows, 0, 2))

    def test_bear_fvg_mirror(self):
        highs = [15, 14, 13.0, 10.5]
        lows = [13, 12, 11, 9]       # bar3: high 10.5 < low[1]=12 -> gap (10.5, 12)
        self.assertEqual(bear_fvg_in_leg(highs, lows, 0, 3), (10.5, 12))


class TestZoneOverlap(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(zone_overlap((1, 5), (3, 8)), (3, 5))

    def test_containment(self):
        self.assertEqual(zone_overlap((1, 10), (4, 6)), (4, 6))

    def test_disjoint_none(self):
        self.assertIsNone(zone_overlap((1, 2), (3, 4)))

    def test_touching_edges_none(self):
        # zero-width "overlap" is not a tradeable zone
        self.assertIsNone(zone_overlap((1, 3), (3, 5)))


if __name__ == "__main__":
    unittest.main()
