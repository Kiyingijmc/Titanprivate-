# STRAT-04 guard: the indicative-spread table is duplicated in the research
# script and the backtest engine; they must stay identical and must cover
# the full Gambit universe.
import unittest
import importlib.util
import sys
import os


class TestSpreadsSync(unittest.TestCase):
    def test_tables_identical(self):
        from scripts.poc_sb_stops import SPREADS as a

        # Load backtest_engine SPREADS using importlib since it's not at module level
        spec = importlib.util.spec_from_file_location(
            "backtest_engine_spreads",
            os.path.join(os.path.dirname(__file__), "../../tests/backtest/backtest_engine.py")
        )
        backtest_module = importlib.util.module_from_spec(spec)
        # Extract SPREADS from the module source via regex since it's inside a function
        with open(spec.origin) as f:
            content = f.read()

        # Find and extract the SPREADS dict from backtest_engine.py
        # The dict is at line 410-413
        import re
        match = re.search(
            r'SPREADS\s*=\s*\{[^}]*\}',
            content,
            re.DOTALL
        )
        self.assertIsNotNone(match, "Could not find SPREADS dict in backtest_engine.py")
        spreads_code = match.group(0)
        b = eval(spreads_code.split('=', 1)[1].strip())

        self.assertEqual(a, b)

    def test_gambit_universe_covered(self):
        from scripts.poc_sb_stops import SPREADS
        for sym in ["US30", "US100", "XAUUSD", "BTCUSD", "ETHUSD", "XTIUSD"]:
            self.assertIn(sym, SPREADS)


if __name__ == "__main__":
    unittest.main()
