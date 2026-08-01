"""Task 3: controller integration with the registry-driven strategy loader.

Runs the REAL SystemController._init_strategies() against the real repo
config (config/config.yaml) and real manifests (config/manifests/), with a
real FeatureBus (so the silver_bullet manifest's `requires` resolve) and a
stub logger/publish -- matching the test_controller_events.py fixture
pattern (SystemController.__new__ + minimal attribute set).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import yaml

from src.core.system_controller import SystemController
from src.features.feature_bus import FeatureBus
from src.features.packs.smc_pack import register_smc_pack
from src.strategies.models.almanac import Almanac
from src.strategies.models.silver_bullet import SilverBullet


def make_controller():
    c = SystemController.__new__(SystemController)
    c.root_dir = Path(REPO)
    with open(c.root_dir / "config" / "config.yaml", "r") as f:
        c.config = yaml.safe_load(f)
    c.logger = MagicMock()
    c.feature_bus = FeatureBus()
    register_smc_pack(c.feature_bus)
    c.feature_bus.validate()
    c.published = []
    c._publish = c.published.append
    c._init_strategies()
    return c


class TestControllerRegistryInit(unittest.TestCase):
    def test_init_strategies_activates_baseline_set(self):
        # Repo baseline since 2026-08-01: SilverBullet (live) + Almanac
        # (demo-soak canary), ordered by manifest priority (50 before 80).
        c = make_controller()
        self.assertEqual(len(c.strategies), 2)
        st = c.strategies[0]
        self.assertIsInstance(st, SilverBullet)
        self.assertEqual(st.name, "SilverBullet")
        self.assertEqual(getattr(st, "timeframe", "M5"), "H1")
        self.assertEqual(c.strategy_ttls["SilverBullet"], 12 * 3600)
        alm = c.strategies[1]
        self.assertIsInstance(alm, Almanac)
        self.assertEqual(alm.name, "Almanac")
        self.assertEqual(alm.timeframe, "H1")
        self.assertEqual(c.strategy_ttls["Almanac"], 12 * 3600)


class TestControllerRegistryEnableDisable(unittest.TestCase):
    def test_disable_then_enable_round_trips(self):
        c = make_controller()
        self.assertEqual(len(c.strategies), 2)

        msg = c.disable_strategy("silver_bullet")
        self.assertIn("disabled", msg.lower())
        self.assertEqual([type(s) for s in c.strategies], [Almanac])

        msg = c.enable_strategy("silver_bullet")
        self.assertIn("enabled", msg.lower())
        self.assertEqual(len(c.strategies), 2)
        self.assertIsInstance(c.strategies[0], SilverBullet)
        self.assertEqual(c.strategy_ttls["SilverBullet"], 12 * 3600)

        # both transitions recorded via _publish
        from src.core.events import StrategyActivated, StrategySuspended
        kinds = [type(e) for e in c.published]
        self.assertIn(StrategySuspended, kinds)
        self.assertIn(StrategyActivated, kinds)

    def test_unknown_strategy_id_returns_error_without_raising(self):
        c = make_controller()
        msg = c.disable_strategy("does_not_exist")
        self.assertIn("Unknown strategy", msg)
        msg = c.enable_strategy("does_not_exist")
        self.assertIn("Unknown strategy", msg)
        # untouched
        self.assertEqual(len(c.strategies), 2)


if __name__ == "__main__":
    unittest.main()
