# STRAT-04 guard: the indicative-spread table is duplicated in the research
# script and the backtest engine; they must stay identical and must cover
# the full Gambit universe.
import ast
import os
import re
import unittest


class TestSpreadsSync(unittest.TestCase):
    def test_tables_identical(self):
        from scripts.poc_sb_stops import SPREADS as a

        # SPREADS in backtest_engine.py is a local variable inside BacktestHarness
        # method (line ~410), unreachable by import — extract the dict literal from source.
        backtest_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "tests", "backtest", "backtest_engine.py"
        )
        with open(backtest_path) as f:
            content = f.read()

        # Find and extract the SPREADS dict from backtest_engine.py
        match = re.search(
            r'SPREADS\s*=\s*\{[^}]*\}',
            content,
            re.DOTALL
        )
        self.assertIsNotNone(match, "Could not find SPREADS dict in backtest_engine.py")
        spreads_code = match.group(0)
        b = ast.literal_eval(spreads_code.split('=', 1)[1].strip())

        self.assertEqual(a, b)

    def test_gambit_universe_covered(self):
        from scripts.poc_sb_stops import SPREADS
        for sym in ["US30", "US100", "XAUUSD", "BTCUSD", "ETHUSD", "XTIUSD"]:
            self.assertIn(sym, SPREADS)


if __name__ == "__main__":
    unittest.main()
