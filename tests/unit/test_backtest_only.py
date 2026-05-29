import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
os.chdir(REPO)
import backtest_engine as bt  # noqa: E402

FIX = "tests/backtest/fixtures/golden_smoke.csv"

class OnlyFilter(unittest.TestCase):
    def test_only_runs_one_strategy(self):
        engine = bt.Backtester(FIX, shift_hours=0, only="SilverBullet")
        self.assertEqual([s.name for s in engine.strategies], ["SilverBullet"])

    def test_default_runs_all_four(self):
        engine = bt.Backtester(FIX, shift_hours=0)
        self.assertEqual(len(engine.strategies), 4)

if __name__ == "__main__":
    unittest.main()
