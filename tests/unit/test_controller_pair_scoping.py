"""Per-strategy pair scoping on the live path.

Found during the Gyroscope v2b canary build (2026-08-01): active_symbols is
the UNION of all enabled strategies' pairs, and _run_strategies filtered by
timeframe only — so every strategy ran on every symbol. Almanac (pairs
US30/US100) would have entered turn-of-month BUYs on all 12 live symbols,
and Gyroscope would have traded the FX pairs its gate excluded. These tests
pin the fix: a strategy with a `pairs` list only sees its own symbols;
absent/empty pairs keeps the run-everywhere behavior (fixtures, backtester).
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.core.system_controller import SystemController
from src.strategies.base_strategy import BaseStrategy


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


class ScopedStrategy(BaseStrategy):
    """Real BaseStrategy subclass so the pairs plumbing under test is the
    production one, not a stub's."""
    def __init__(self, name, cfg):
        super().__init__(name, cfg, FakeLogger())
        self.calls = []

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        self.calls.append((context or {}).get("symbol"))
        return None


def make_controller(strategies, symbol="EURUSD"):
    c = SystemController.__new__(SystemController)
    c.logger = FakeLogger()
    c.strategies = strategies
    c.market_data = {symbol: FakeStore()}
    c.time_engine = FakeTimeEngine()
    c.feature_bus = FakeFeatureBus()
    c.current_open_positions = []
    return c


def _bar_df():
    return pd.DataFrame([{"time": "bar-1", "close": 1.1}])


class TestBaseStrategyPairs(unittest.TestCase):
    def test_pairs_read_from_config(self):
        s = ScopedStrategy("S", {"timeframe": "H1", "pairs": ["US30", "BTCUSD"]})
        self.assertEqual(s.pairs, ["US30", "BTCUSD"])

    def test_absent_pairs_is_none(self):
        s = ScopedStrategy("S", {"timeframe": "H1"})
        self.assertIsNone(s.pairs)


class TestPairScoping(unittest.TestCase):
    def test_strategy_skipped_off_its_pairs(self):
        s = ScopedStrategy("Scoped", {"timeframe": "H1", "pairs": ["US30"]})
        c = make_controller([s])
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(s.calls, [])

    def test_strategy_runs_on_its_pairs(self):
        s = ScopedStrategy("Scoped", {"timeframe": "H1", "pairs": ["EURUSD"]})
        c = make_controller([s])
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(s.calls, ["EURUSD"])

    def test_no_pairs_runs_everywhere(self):
        s = ScopedStrategy("Everywhere", {"timeframe": "H1"})
        c = make_controller([s])
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(s.calls, ["EURUSD"])

    def test_mixed_set_scopes_independently(self):
        a = ScopedStrategy("A", {"timeframe": "H1", "pairs": ["US30"]})
        b = ScopedStrategy("B", {"timeframe": "H1", "pairs": ["EURUSD"]})
        c = make_controller([a, b])
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(a.calls, [])
        self.assertEqual(b.calls, ["EURUSD"])


if __name__ == "__main__":
    unittest.main()
