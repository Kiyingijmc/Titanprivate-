"""A tripped daily-drawdown breaker must be LOUD.

`RiskManager.check_can_trade()` is the 3% max-loss-day circuit breaker, but
its only observable effect was `calculate_lot_size` returning 0.0 -- which
`_execute_signal` then logged as "unsizeable stop ... or specs missing". An
operator reading the log could not tell a deliberate max-loss-day halt from
a broker-specs outage, and Titan's OWN resting LIMIT orders kept sitting in
the book, free to fill and add exposure on exactly the day risk should be
shrinking.

These tests pin the three halves of the fix:
  1. the skip log names the breaker (and still says "specs missing" when the
     breaker is fine),
  2. the True -> False transition on HEARTBEAT alerts exactly once and pulls
     every Titan-placed pending order,
  3. the one-shot re-arms, so a recovery-then-second-trip alerts again.
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.system_controller import SystemController


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeLogger:
    def __init__(self):
        self.events = []

    def log_event(self, level, tag, msg, *a, **kw):
        self.events.append((level, tag, msg))

    def joined(self):
        return " | ".join(f"{lv}:{tg}:{m}" for lv, tg, m in self.events)


class FakeTelemetry:
    def __init__(self):
        self.messages = []

    async def send_message(self, text, parse_mode="HTML"):
        self.messages.append(text)


class FakeBridge:
    def __init__(self):
        self.commands = []

    async def send_command(self, action, payload=None):
        self.commands.append((action, dict(payload or {})))


class FakeStateManager:
    """Only the surface the HEARTBEAT branch + the breaker sweep touch."""

    def __init__(self, pending=None):
        self.pending = list(pending or [])
        self.deleted = []

    def get_pending_orders(self):
        return list(self.pending)

    def delete_order(self, ticket):
        self.deleted.append(ticket)
        self.pending = [o for o in self.pending if o['ticket_id'] != ticket]

    def exists(self, ticket):
        return True

    def register_order(self, *a, **kw):
        pass

    def backfill_position_state(self, *a, **kw):
        pass


class FakeEquityRecorder:
    def __init__(self):
        self.recorded = []

    def record(self, balance, equity):
        self.recorded.append((balance, equity))


class ScriptedRisk:
    """RiskManager stand-in whose breaker verdict the test drives directly."""

    def __init__(self, can_trade=True, equity=10000.0, anchor=10000.0):
        self.can_trade = can_trade
        self.current_equity = equity
        self.day_start_equity = anchor
        self.starting_balance = anchor

    def update_account_info(self, balance, equity):
        self.current_equity = equity

    def track_equity(self, equity):
        pass

    def check_can_trade(self):
        return self.can_trade

    # --- _execute_signal surface -------------------------------------
    def normalize_price(self, p, s):
        return p

    def throttle_factor(self):
        return 1.0

    def calculate_lot_size(self, entry, sl, symbol, htf_bias, risk_mult=1.0):
        return 0.0


def _pending(ticket, symbol):
    return {"ticket_id": ticket, "symbol": symbol, "strategy": "SilverBullet",
            "time_placed": 0.0}


def _controller(risk, pending=None):
    c = object.__new__(SystemController)
    c.logger = FakeLogger()
    c.telemetry = FakeTelemetry()
    c.bridge = FakeBridge()
    c.risk_manager = risk
    c.state_manager = FakeStateManager(pending)
    c.equity_recorder = FakeEquityRecorder()
    c.current_open_positions = []
    c.current_pending_orders = []
    c.live_prices = {}
    c._dd_breaker_tripped = False
    c._news_blocks_symbol = lambda s: (False, "")
    return c


def _heartbeat(equity=9600.0):
    return {"type": "HEARTBEAT", "bal": 10000.0, "eq": equity,
            "pos": [], "orders": []}


DECISION = {"signal": "BUY", "type": "LIMIT",
            "price": 1.1000, "sl": 1.0900, "tp": 1.1200}


class TestSkipLogDistinguishesTheBreaker(unittest.TestCase):
    def test_tripped_breaker_skip_names_the_breaker(self):
        c = _controller(ScriptedRisk(can_trade=False, equity=9600.0))
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH", grade="A"))
        joined = c.logger.joined().lower()
        self.assertIn("eurusd", joined)
        self.assertIn("drawdown", joined,
                      f"skip log does not name the DD breaker: {c.logger.events}")
        self.assertNotIn("specs missing", joined,
                         f"breaker trip misattributed to specs: {c.logger.events}")

    def test_untripped_breaker_keeps_todays_specs_missing_message(self):
        c = _controller(ScriptedRisk(can_trade=True))
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH", grade="A"))
        joined = c.logger.joined()
        self.assertIn("unsizeable stop", joined)
        self.assertIn("or specs missing", joined)
        self.assertNotIn("drawdown", joined.lower())


class TestBreakerTripAlertsAndCancels(unittest.TestCase):
    def test_transition_alerts_once_and_cancels_every_pending_row(self):
        risk = ScriptedRisk(can_trade=True, equity=10000.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD"), _pending(222, "XAUUSD")])

        _run(c._process_incoming_data(_heartbeat(9990.0)))  # healthy: silent
        self.assertEqual(c.telemetry.messages, [])
        self.assertEqual(c.bridge.commands, [])

        risk.can_trade = False
        _run(c._process_incoming_data(_heartbeat(9600.0)))

        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertEqual([(a, p['ticket']) for a, p in c.bridge.commands],
                         [("CANCEL", 111), ("CANCEL", 222)])
        self.assertEqual(c.state_manager.deleted, [111, 222])
        # The operator must be able to see WHAT was pulled.
        msg = c.telemetry.messages[0]
        self.assertIn("111", msg)
        self.assertIn("222", msg)
        self.assertIn("EURUSD", msg)
        self.assertIn("XAUUSD", msg)

    def test_second_tripped_heartbeat_is_silent_and_cancels_nothing_more(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])

        _run(c._process_incoming_data(_heartbeat(9600.0)))
        self.assertEqual(len(c.telemetry.messages), 1)
        self.assertEqual(len(c.bridge.commands), 1)

        _run(c._process_incoming_data(_heartbeat(9590.0)))
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertEqual(len(c.bridge.commands), 1, c.bridge.commands)
        self.assertEqual(c.state_manager.deleted, [111])

    def test_recovery_rearms_so_a_second_trip_alerts_again(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])

        _run(c._process_incoming_data(_heartbeat(9600.0)))
        self.assertEqual(len(c.telemetry.messages), 1)

        risk.can_trade = True  # intraday recovery, or a fresh day's anchor roll
        _run(c._process_incoming_data(_heartbeat(9800.0)))
        self.assertEqual(len(c.telemetry.messages), 1)

        risk.can_trade = False
        c.state_manager.pending = [_pending(333, "GBPJPY")]
        _run(c._process_incoming_data(_heartbeat(9500.0)))
        self.assertEqual(len(c.telemetry.messages), 2, c.telemetry.messages)
        self.assertIn("333", c.telemetry.messages[1])
        self.assertEqual(c.state_manager.deleted, [111, 333])

    def test_trip_with_no_resting_orders_still_alerts(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[])
        _run(c._process_incoming_data(_heartbeat(9600.0)))
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertEqual(c.bridge.commands, [])


if __name__ == "__main__":
    unittest.main()
