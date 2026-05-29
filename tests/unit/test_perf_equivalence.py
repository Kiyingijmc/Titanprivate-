import os, sys, asyncio, csv, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
os.chdir(REPO)
import backtest_engine as bt  # noqa: E402

FIX = "tests/backtest/fixtures"

def _rows(path):
    with open(path) as f:
        return [(r["bar_idx"], r["strat"], r["outcome"], r["r"]) for r in csv.DictReader(f)]

class PerfEquivalence(unittest.TestCase):
    def test_optimized_engine_matches_golden_trades(self):
        out = "/tmp/perf_check_trades.csv"
        engine = bt.Backtester(f"{FIX}/golden_smoke.csv", shift_hours=-7)
        asyncio.run(engine.run(trades_out=out))
        self.assertEqual(_rows(out), _rows(f"{FIX}/golden_trades.csv"))

if __name__ == "__main__":
    unittest.main()
