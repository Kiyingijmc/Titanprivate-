import os, sys, unittest
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_trend_h4 as tp


class Indicators(unittest.TestCase):
    def test_resample_h4_ohlc(self):
        rows = []
        for h in range(8):
            rows.append({"time": f"2026-01-01 {h:02d}:00:00", "open": h, "high": h + 2,
                         "low": h - 1, "close": h + 1})
        h4 = tp.resample_h4(pd.DataFrame(rows))
        self.assertEqual(len(h4), 2)
        self.assertEqual(h4.iloc[0]["open"], 0)
        self.assertEqual(h4.iloc[0]["high"], 5)
        self.assertEqual(h4.iloc[0]["low"], -1)
        self.assertEqual(h4.iloc[0]["close"], 4)

    def test_donchian_breakouts(self):
        bars = [{"open": 10, "high": 10.5, "low": 9.5, "close": 10} for _ in range(20)]
        bars.append({"open": 10, "high": 12, "low": 10, "close": 11.5})
        bars += [{"open": 11, "high": 11.2, "low": 10.8, "close": 11} for _ in range(20)]
        bars.append({"open": 11, "high": 11, "low": 8, "close": 8.5})
        h4 = pd.DataFrame(bars)
        sigs = tp.donchian_signals(h4, n=20)
        self.assertIn((20, "LONG"), sigs)
        self.assertTrue(any(i == 41 and d == "SHORT" for i, d in sigs))


class FlipAndCost(unittest.TestCase):
    def _bars(self, seq):
        return [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in seq]

    def test_flip_exit_on_opposite_signal(self):
        bars = self._bars([(10, 10, 10, 10),
                           (10, 11, 10, 11),
                           (11, 12, 11, 12),
                           (12, 12, 12, 11.0)])
        atrs = [1.0] * 4
        trades = tp.simulate_flip([(0, "LONG"), (3, "SHORT")], bars, atrs, stop_mult=2.0)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t["outcome"], "FLIP")
        self.assertAlmostEqual(t["r"], 0.5, places=3)

    def test_flip_stop_hit(self):
        bars = self._bars([(10, 10, 10, 10),
                           (10, 10, 7, 8)])
        trades = tp.simulate_flip([(0, "LONG")], bars, [1.0, 1.0], stop_mult=2.0)
        self.assertEqual(trades[0]["outcome"], "SL")
        self.assertAlmostEqual(trades[0]["r"], -1.0)

    def test_net_r_after_costs(self):
        net = tp.net_r_after_costs(1.0, 1.1000, 1.0950, 0.0001, 1e-5, 1.0)
        self.assertAlmostEqual(net, 0.932, places=3)


if __name__ == "__main__":
    unittest.main()
