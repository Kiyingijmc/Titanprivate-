# tests/unit/test_gui_dollar.py
"""Tests for the additive `dollar` block in build_snapshot (Plan 2 Task 11)."""
import unittest
from datetime import datetime, timedelta
from src.ops.web.state_view import build_snapshot


class FakeRisk:
    current_equity = 10250.0
    starting_balance = 10000.0

    @staticmethod
    def throttle_factor():
        return 0.5


class FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 0, "approved": 0, "blocked_by": {}}


class FakeRegistry:
    @staticmethod
    def report():
        return []


class FakeState:
    @staticmethod
    def get_order(ticket):
        return None


class BareController:
    """No price-data attrs at all — must degrade to 'unavailable', never crash."""

    def __init__(self):
        self.last_heartbeat_time = datetime.now() - timedelta(seconds=2)
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.arbiter = FakeArbiter()
        self.registry = FakeRegistry()
        self.config = {"risk": {"drawdown_throttle": {"enabled": False}}}
        self.current_open_positions = []
        self.state_manager = FakeState()


class ComputedController(BareController):
    """Exposes market_prices for tracked USD pairs -> source 'computed'."""

    def __init__(self):
        super().__init__()
        self.market_prices = {
            "EURUSD": {"mid": 1.0850, "delta_pct": 0.20},   # USD base is quote -> USD weaker
            "GBPUSD": {"mid": 1.2650, "delta_pct": 0.10},
            "USDJPY": {"mid": 157.20, "delta_pct": 0.30},   # USD is base -> USD stronger
            "AUDUSD": {"mid": 0.6650, "delta_pct": -0.05},
            "USDCAD": {"mid": 1.3650, "delta_pct": 0.15},
            "USDCHF": {"mid": 0.8850, "delta_pct": 0.05},
        }


class IndexController(BareController):
    """Exposes a dollar_index helper -> source 'index'."""

    def __init__(self):
        super().__init__()

    @staticmethod
    def dollar_index():
        return {"value": 104.32, "bias": 42.0, "trend": [103.9, 104.1, 104.32],
                 "contributors": [{"symbol": "EURUSD", "contribution": -12.0}]}


class TestDollarBlock(unittest.TestCase):
    def test_bare_controller_is_unavailable_and_does_not_crash(self):
        snap = build_snapshot(BareController())
        dollar = snap["dollar"]
        self.assertEqual(dollar["source"], "unavailable")
        self.assertIsNone(dollar["value"])
        self.assertEqual(dollar["bias"], 0.0)
        self.assertEqual(dollar["trend"], [])
        self.assertEqual(dollar["contributors"], [])

    def test_computed_from_market_prices(self):
        snap = build_snapshot(ComputedController())
        dollar = snap["dollar"]
        self.assertEqual(dollar["source"], "computed")
        self.assertIsInstance(dollar["bias"], float)
        self.assertGreaterEqual(dollar["bias"], -100.0)
        self.assertLessEqual(dollar["bias"], 100.0)
        self.assertTrue(len(dollar["contributors"]) > 0)

    def test_index_source_used_when_available(self):
        snap = build_snapshot(IndexController())
        dollar = snap["dollar"]
        self.assertEqual(dollar["source"], "index")
        self.assertEqual(dollar["value"], 104.32)
        self.assertEqual(dollar["bias"], 42.0)

    def test_existing_keys_untouched(self):
        snap = build_snapshot(BareController())
        for key in ("health", "account", "positions", "arbiter", "registry"):
            self.assertIn(key, snap)


if __name__ == "__main__":
    unittest.main()
