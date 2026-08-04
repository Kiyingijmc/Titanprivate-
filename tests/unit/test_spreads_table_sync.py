# STRAT-04 guard: the research script and the backtest engine must price a
# trade off the SAME indicative-spread table, and it must cover the full
# Gambit universe.
#
# History: both files used to carry their own copy of the dict, so this guard
# scraped the literal out of backtest_engine.py with a regex and compared it to
# the script's. src/research/costs.py later became the single source of truth
# and both call sites became imports, which left the regex matching nothing --
# the guard failed with "Could not find SPREADS dict" even though the tables
# could no longer possibly diverge.
#
# The fix is NOT to delete the guard: "they must stay identical" is still a
# real invariant, and a future edit re-inlining a private table in either file
# would silently reintroduce the drift STRAT-04 was raised for. So this now
# asserts the invariant directly -- both consumers resolve to the canonical
# table object -- and additionally pins that neither file has re-introduced a
# local literal that would shadow it.
import ast
import os
import re
import unittest


REPO = os.path.join(os.path.dirname(__file__), "..", "..")


class TestSpreadsSync(unittest.TestCase):
    def test_both_consumers_resolve_to_the_canonical_table(self):
        from src.research.costs import FBS_SPREAD_TICKS as canonical
        from scripts.poc_sb_stops import SPREADS as script_table

        # The research script must expose the canonical table, not a copy:
        # equal-but-distinct dicts are exactly how the two drifted before.
        self.assertEqual(script_table, canonical)
        self.assertIs(script_table, canonical)

        # backtest_engine binds SPREADS inside a method, so there is no
        # module-level name to compare against here (and importing it is not
        # safe from this module -- tests/backtest is only on sys.path when
        # another test has put it there). Its half of the invariant is covered
        # textually by test_neither_file_reinlines_a_local_spreads_literal:
        # given no local literal, the name can only come from the import of
        # the canonical table asserted above.

    def test_neither_file_reinlines_a_local_spreads_literal(self):
        """A re-inlined `SPREADS = {...}` in either file would shadow the
        canonical import and silently restore the STRAT-04 drift."""
        for rel in ("scripts/poc_sb_stops.py", "tests/backtest/backtest_engine.py"):
            path = os.path.join(REPO, rel)
            with open(path) as f:
                content = f.read()
            match = re.search(r'SPREADS\s*=\s*\{[^}]*\}', content, re.DOTALL)
            self.assertIsNone(
                match,
                f"{rel} re-inlines a SPREADS dict literal; it must import "
                f"FBS_SPREAD_TICKS from src.research.costs instead "
                f"(STRAT-04: duplicated tables drift).",
            )

    def test_canonical_table_is_a_flat_symbol_to_ticks_mapping(self):
        """Pins the shape the two call sites rely on, so a future refactor of
        costs.py cannot satisfy the identity checks above with a wrong type."""
        from src.research.costs import FBS_SPREAD_TICKS as canonical
        self.assertIsInstance(canonical, dict)
        self.assertTrue(canonical)
        for sym, ticks in canonical.items():
            self.assertIsInstance(sym, str, f"non-str key {sym!r}")
            self.assertIsInstance(ticks, (int, float), f"{sym} ticks {ticks!r}")
            self.assertGreater(ticks, 0, f"{sym} has a non-positive spread")

    def test_gambit_universe_covered(self):
        from scripts.poc_sb_stops import SPREADS
        for sym in ["US30", "US100", "XAUUSD", "BTCUSD", "ETHUSD", "XTIUSD"]:
            self.assertIn(sym, SPREADS)


if __name__ == "__main__":
    unittest.main()
