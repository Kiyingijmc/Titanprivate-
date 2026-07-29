import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.research.costs import (  # noqa: E402
    FBS_SPREAD_TICKS, RESEARCH_TICK_SPECS, CostModelError,
    spread_ticks, spread_price, tick_spec,
)


class SpreadTable(unittest.TestCase):
    def test_covers_every_live_pair(self):
        """Every symbol in config strategies.silver_bullet.pairs must be priceable.

        A missing entry is what made US100/ETHUSD/XTIUSD unstudiable: pooled
        research_run hard-errors on them, and the legacy Backtester path
        silently substituted 20 ticks.
        """
        import yaml
        with open(os.path.join(REPO, "config", "config.yaml")) as f:
            cfg = yaml.safe_load(f)
        live_pairs = cfg["strategies"]["silver_bullet"]["pairs"]
        missing = [s for s in live_pairs if s not in FBS_SPREAD_TICKS]
        self.assertEqual(missing, [], f"no spread entry for live pairs: {missing}")

    def test_measured_values_from_universe_screen(self):
        # data/results/universe_screen_20260728/screen_candidates.py:29
        self.assertEqual(FBS_SPREAD_TICKS["US100"], 200)
        self.assertEqual(FBS_SPREAD_TICKS["ETHUSD"], 193)
        self.assertEqual(FBS_SPREAD_TICKS["XTIUSD"], 2)

    def test_incumbent_values_unchanged(self):
        """The 11 original values must be byte-identical to the retired tables,
        or the re-baseline would conflate a spread change with the fill fix."""
        self.assertEqual(FBS_SPREAD_TICKS["EURUSD"], 8)
        self.assertEqual(FBS_SPREAD_TICKS["GBPUSD"], 12)
        self.assertEqual(FBS_SPREAD_TICKS["USDJPY"], 10)
        self.assertEqual(FBS_SPREAD_TICKS["AUDUSD"], 10)
        self.assertEqual(FBS_SPREAD_TICKS["USDCAD"], 12)
        self.assertEqual(FBS_SPREAD_TICKS["GBPCAD"], 30)
        self.assertEqual(FBS_SPREAD_TICKS["GBPJPY"], 25)
        self.assertEqual(FBS_SPREAD_TICKS["XAUUSD"], 20)
        self.assertEqual(FBS_SPREAD_TICKS["US30"], 200)
        self.assertEqual(FBS_SPREAD_TICKS["BTCUSD"], 1000)
        self.assertEqual(FBS_SPREAD_TICKS["XBRUSD"], 30)


class Accessors(unittest.TestCase):
    def test_spread_ticks_known_symbol(self):
        self.assertEqual(spread_ticks("EURUSD"), 8)

    def test_spread_ticks_unknown_symbol_raises(self):
        """Fail closed, never guess. Mirrors RiskManager.calculate_lot_size,
        which returns 0 rather than inventing a spec."""
        with self.assertRaises(CostModelError) as ctx:
            spread_ticks("NOTAPAIR")
        self.assertIn("NOTAPAIR", str(ctx.exception))

    def test_spread_price_converts_via_tick_size(self):
        self.assertAlmostEqual(spread_price("EURUSD", 1e-05), 8e-05)
        self.assertAlmostEqual(spread_price("US100", 0.01), 2.0)
        self.assertAlmostEqual(spread_price("ETHUSD", 0.01), 1.93)

    def test_spread_price_rejects_nonpositive_tick_size(self):
        with self.assertRaises(CostModelError):
            spread_price("EURUSD", 0.0)


class ResearchTickSpecs(unittest.TestCase):
    """data/specs.json is gitignored and machine-specific, so the pairs adopted
    in 2026-07 have no reproducible tick spec. These are the broker-probed
    values, checked in so any machine can reproduce the re-baseline."""

    def test_us100_matches_the_broker_probe(self):
        # data/results/universe_screen_20260728/candidate_probe.json["US100"]["info"]
        self.assertEqual(tick_spec("US100"), {
            "tick_value": 0.1, "tick_size": 0.01, "vol_min": 0.01, "vol_step": 0.01})

    def test_ethusd_matches_the_broker_probe(self):
        self.assertEqual(tick_spec("ETHUSD"), {
            "tick_value": 0.1, "tick_size": 0.01, "vol_min": 0.01, "vol_step": 0.01})

    def test_xtiusd_is_absent_because_it_was_never_probed(self):
        """candidate_probe.json["XTIUSD"] is null. Its tick_value=10.0 exists
        only as a hand-entered value in the screen harness, so it must NOT be
        checked in as if it were measured."""
        self.assertIsNone(tick_spec("XTIUSD"))

    def test_unknown_symbol_returns_none_not_an_error(self):
        self.assertIsNone(tick_spec("NOTAPAIR"))

    def test_does_not_shadow_symbols_already_in_specs_json(self):
        """Symbols data/specs.json already covers must not be duplicated here,
        or the two would drift and the table read would decide the numbers."""
        already_covered = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                           "GBPCAD", "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"}
        overlap = already_covered & set(RESEARCH_TICK_SPECS)
        self.assertEqual(overlap, set(), f"duplicated tick specs: {overlap}")


if __name__ == "__main__":
    unittest.main()
