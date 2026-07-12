"""Verifies the B0 publish-only integration: processing bridge messages
publishes the corresponding typed events, and trading behavior is
untouched (publishes are additive)."""
import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.core.system_controller import SystemController, BotState
from src.core.bus import EventBus
from src.core.events import (TickReceived, HeartbeatReceived,
                             ExecutionReceived, SpecsUpdated, BarClosed,
                             SystemStateChanged)


async def _async_noop(*a, **k):
    pass


def make_controller():
    c = SystemController.__new__(SystemController)
    c.bus = EventBus()
    c.state = BotState.PAUSED          # TICK branch: no candle processing
    c.live_prices = {}
    c.current_open_positions = []
    c.current_pending_orders = []
    c.market_data = {}
    c.risk_manager = MagicMock()
    c.state_manager = MagicMock()
    c.state_manager.exists.return_value = True
    c.telemetry = MagicMock()
    c.telemetry.notify_execution = _async_noop
    c.telemetry.notify_close = _async_noop
    c.pending_signal_meta = {}
    c.daily_closed_trades = []
    c.last_heartbeat_time = datetime.now()
    c.strategies = []
    c.active_symbols = set()
    c.is_manual_pause = False
    return c


def capture(bus, evt_cls):
    seen = []
    bus.subscribe(evt_cls, seen.append)
    return seen


class TestControllerPublishes(unittest.TestCase):
    def _process(self, c, msg):
        asyncio.new_event_loop().run_until_complete(c._process_incoming_data(msg))

    def test_tick_publishes_tick_event(self):
        c = make_controller()
        seen = capture(c.bus, TickReceived)
        self._process(c, {"type": "TICK", "s": "EURUSD", "b": 1.09})
        self.assertEqual(seen, [TickReceived(symbol="EURUSD", bid=1.09)])
        self.assertEqual(c.live_prices["EURUSD"], 1.09)   # behavior untouched

    def test_heartbeat_publishes(self):
        c = make_controller()
        seen = capture(c.bus, HeartbeatReceived)
        self._process(c, {"type": "HEARTBEAT", "bal": 100.0, "eq": 99.5,
                          "pos": [], "orders": []})
        self.assertEqual(seen, [HeartbeatReceived(balance=100.0, equity=99.5,
                                                  n_positions=0, n_orders=0)])

    def test_history_with_specs_publishes_specs_updated(self):
        c = make_controller()
        c.market_data = {"XAUUSD": MagicMock()}
        seen = capture(c.bus, SpecsUpdated)
        self._process(c, {"type": "HISTORY", "symbol": "XAUUSD", "tf": "H1",
                          "data": [], "tv": 1.0, "ts": 0.01, "vm": 0.01, "vs": 0.01})
        self.assertEqual(seen, [SpecsUpdated(symbol="XAUUSD")])

    def test_execution_closed_publishes(self):
        c = make_controller()
        c.state_manager.get_order.return_value = None   # unknown ticket: no crash
        seen = capture(c.bus, ExecutionReceived)
        self._process(c, {"type": "EXECUTION", "status": "CLOSED",
                          "ticket": 7, "s": "EURUSD", "pn": 3.2})
        self.assertEqual(seen, [ExecutionReceived(status="CLOSED", ticket=7,
                                                  symbol="EURUSD", pnl=3.2)])

    def test_bar_closed_publishes_on_candle_close(self):
        # The routing test's fixtures make the candle path reachable without a
        # full MultiTimeframeStore: fake process_tick() to return one closed
        # M5 bar and leave strategies=[] so _run_strategies short-circuits
        # immediately after the publish (see brief's insertion point).
        c = make_controller()
        c.state = BotState.ACTIVE
        df = pd.DataFrame([{
            "time": "2026-07-12T10:00:00", "open": 1.10, "high": 1.11,
            "low": 1.09, "close": 1.105,
        }])
        store = MagicMock()
        store.process_tick.return_value = [("M5", df)]
        c.market_data = {"EURUSD": store}
        seen = capture(c.bus, BarClosed)
        self._process(c, {"type": "TICK", "s": "EURUSD", "b": 1.105})
        self.assertEqual(seen, [BarClosed(
            symbol="EURUSD", tf="M5", bar_time="2026-07-12T10:00:00",
            open=1.10, high=1.11, low=1.09, close=1.105)])

    def test_set_system_pause_publishes_state_change(self):
        c = make_controller()
        seen = capture(c.bus, SystemStateChanged)
        c.set_system_pause(True)
        c.set_system_pause(False)
        self.assertEqual(seen, [SystemStateChanged(state="PAUSED"),
                                SystemStateChanged(state="ACTIVE")])
        # behavior untouched
        self.assertEqual(c.state, BotState.ACTIVE)
        self.assertFalse(c.is_manual_pause)


if __name__ == "__main__":
    unittest.main()
