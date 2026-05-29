import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
import backtest_engine as bt  # noqa: E402


class TradeDollars(unittest.TestCase):
    def test_winning_trade_net_of_costs(self):
        spec = {"tick_value": 1.0, "tick_size": 0.00001, "vol_step": 0.01}
        # entry/sl 0.0050 / 0.00001 = 500 ticks; money/lot = 500*1 = $500; risk $100 -> 0.20 lots
        d = bt.trade_dollars(r=2.0, entry=1.1000, sl=1.0950, spec=spec,
                             spread_points=10, commission_per_lot=7.0, risk_dollars=100.0)
        self.assertAlmostEqual(d["lots"], 0.20, places=2)
        self.assertAlmostEqual(d["gross"], 200.0, places=2)
        self.assertAlmostEqual(d["commission"], 1.40, places=2)
        self.assertAlmostEqual(d["spread_cost"], 2.0, places=2)
        self.assertAlmostEqual(d["net"], 196.60, places=2)

    def test_zero_money_per_lot_is_safe(self):
        spec = {"tick_value": 0.0, "tick_size": 0.0001, "vol_step": 0.01}
        d = bt.trade_dollars(2.0, 1.1, 1.09, spec, 10, 7.0, 100.0)
        self.assertEqual(d["lots"], 0.0)
        self.assertEqual(d["net"], 0.0)


class SplitTrades(unittest.TestCase):
    def test_70_30_chronological(self):
        trades = [{"bar_idx": i, "r": 0.0} for i in [5, 1, 9, 3, 7, 2, 8, 4, 6, 10]]
        train, test = bt.split_trades(trades, train_frac=0.7)
        self.assertEqual([t["bar_idx"] for t in train], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([t["bar_idx"] for t in test], [8, 9, 10])

    def test_empty(self):
        self.assertEqual(bt.split_trades([], 0.7), ([], []))


class WinRateCI(unittest.TestCase):
    def test_known_wilson_interval(self):
        p, lo, hi = bt.win_rate_ci(50, 100)
        self.assertAlmostEqual(p, 0.50, places=3)
        self.assertAlmostEqual(lo, 0.404, places=2)
        self.assertAlmostEqual(hi, 0.596, places=2)

    def test_zero_n_safe(self):
        self.assertEqual(bt.win_rate_ci(0, 0), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
