"""Gyroscope v2b GO wiring: strategies receive the live spread in context.

Audit F6: gyroscope.py gates on context['spread'] but the controller never
populated it, so the max_spread_atr_frac screen was inert live. These tests
pin the two halves: the TICK branch records ask-bid per symbol, and
_run_strategies passes it through the context dict (None when unknown --
fixtures without live_spreads keep working).
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.core.system_controller import SystemController


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class FakeLogger:
    def log_event(self, *a, **kw):
        pass


class FakeTimeEngine:
    def get_current_ny_string(self):
        return "10:00:00 EST"


class FakeStore:
    def get_data(self, tf):
        return None


class FakeFeatureBus:
    def evaluate(self, name, symbol, tf, token=None, window=None, h1_df=None):
        if name == "smc.enriched_df":
            return window
        if name == "smc.bias_context":
            return ("NEUTRAL", {})
        raise ValueError(name)


class CapturingStrategy:
    name = "Capture"
    timeframe = "H1"

    def __init__(self):
        self.contexts = []

    async def on_new_candle(self, df, context=None):
        self.contexts.append(context)
        return None


def make_controller(strategy):
    c = SystemController.__new__(SystemController)
    c.logger = FakeLogger()
    c.strategies = [strategy]
    c.market_data = {"EURUSD": FakeStore()}
    c.time_engine = FakeTimeEngine()
    c.feature_bus = FakeFeatureBus()
    c.current_open_positions = []
    return c


def _bar_df():
    return pd.DataFrame([{"time": "bar-1", "close": 1.1}])


class TestSpreadInContext(unittest.TestCase):
    def test_spread_passed_when_known(self):
        strat = CapturingStrategy()
        c = make_controller(strat)
        c.live_spreads = {"EURUSD": 0.00012}
        run(c._run_strategies("EURUSD", _bar_df(), "H1"))
        self.assertEqual(len(strat.contexts), 1)
        self.assertEqual(strat.contexts[0].get("spread"), 0.00012)

    def test_spread_none_when_unknown_symbol(self):
        strat = CapturingStrategy()
        c = make_controller(strat)
        c.live_spreads = {}
        run(c._run_strategies("EURUSD", _bar_df(), "H1"))
        self.assertIsNone(strat.contexts[0].get("spread"))

    def test_legacy_fixture_without_attr_still_works(self):
        strat = CapturingStrategy()
        c = make_controller(strat)  # no live_spreads attribute at all
        run(c._run_strategies("EURUSD", _bar_df(), "H1"))
        self.assertIsNone(strat.contexts[0].get("spread"))


class TestTickRecordsSpread(unittest.TestCase):
    def test_tick_branch_stores_ask_minus_bid(self):
        c = SystemController.__new__(SystemController)
        c.logger = FakeLogger()
        c.live_prices = {}
        c.live_spreads = {}
        c.current_open_positions = []
        c._publish = lambda *a, **k: None
        from src.core.system_controller import BotState
        c.state = BotState.PAUSED  # skip candle processing/management
        run(c._process_incoming_data(
            {"type": "TICK", "s": "EURUSD", "b": 1.10000, "a": 1.10012}))
        self.assertAlmostEqual(c.live_spreads["EURUSD"], 0.00012, places=9)
        self.assertEqual(c.live_prices["EURUSD"], 1.10000)

    def test_tick_without_ask_leaves_spread_unset(self):
        c = SystemController.__new__(SystemController)
        c.logger = FakeLogger()
        c.live_prices = {}
        c.live_spreads = {}
        c.current_open_positions = []
        c._publish = lambda *a, **k: None
        from src.core.system_controller import BotState
        c.state = BotState.PAUSED
        run(c._process_incoming_data({"type": "TICK", "s": "EURUSD", "b": 1.1}))
        self.assertNotIn("EURUSD", c.live_spreads)


if __name__ == "__main__":
    unittest.main()
