import unittest

import numpy as np

from scripts.poc_sb_stops import resolve


def _bars(highs, lows):
    n = len(highs)
    return {"high": np.array(highs, dtype=float),
            "low": np.array(lows, dtype=float),
            "atr": np.full(n, 1.0),
            "times": np.arange(n),
            "disp_bull": np.zeros(n, dtype=bool),
            "disp_bear": np.zeros(n, dtype=bool)}


# One BUY signal at bar 0. ATR10 stop => sl = entry - 1.0*atr = 99.0, risk = 1.0.
# Bar 1 touches entry (fill). Price then rises to 101.6 without ever hitting 99.
SIG = [{"bar_idx": 0, "dir": "BUY", "entry": 100.0, "atr": 1.0,
        "far_extreme": 99.5, "sig_high": 100.0, "sig_low": 100.0}]
HIGHS = [100.0, 100.2, 101.6, 101.6]
LOWS = [100.0, 99.9, 100.1, 100.5]


class TestResolveRRParam(unittest.TestCase):
    def test_default_rr_is_two(self):
        # tp = 100 + 2.0*1.0 = 102.0, never reached -> no closed trade
        out = resolve(SIG, _bars(HIGHS, LOWS), "ATR10")
        self.assertEqual(out, [])

    def test_rr_one_point_five_fills_and_wins(self):
        # tp = 100 + 1.5*1.0 = 101.5, reached on bar 2
        out = resolve(SIG, _bars(HIGHS, LOWS), "ATR10", rr=1.5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outcome"], "TP")
        self.assertAlmostEqual(out[0]["tp"], 101.5)
        self.assertAlmostEqual(out[0]["r"], 1.5)

    def test_rr_affects_r_on_tp_not_on_sl(self):
        # a losing path: bar 1 fills, bar 2 takes out the stop at 99.0
        lows = [100.0, 99.9, 98.5, 98.5]
        out = resolve(SIG, _bars([100.0, 100.2, 100.3, 100.3], lows),
                      "ATR10", rr=3.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outcome"], "SL")
        self.assertAlmostEqual(out[0]["r"], -1.0)
