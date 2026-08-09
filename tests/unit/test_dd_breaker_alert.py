"""A tripped daily-drawdown breaker must be LOUD, and must actually bite.

`RiskManager.check_can_trade()` is the 3% max-loss-day circuit breaker, but
its only observable effect was `calculate_lot_size` returning 0.0 -- which
`_execute_signal` then logged as "unsizeable stop ... or specs missing". An
operator reading the log could not tell a deliberate max-loss-day halt from
a broker-specs outage, and Titan's OWN resting LIMIT orders kept sitting in
the book, free to fill and add exposure on exactly the day risk should be
shrinking.

These tests pin the fix:
  1. the skip log names the breaker AND states the real recovery condition
     (back above the day-loss line, not back above the anchor), and still
     says "specs missing" when the breaker is fine,
  2. the True -> False transition on HEARTBEAT alerts exactly once and sends
     a CANCEL for every Titan-placed pending order,
  3. a DB row is forgotten only once the broker stops reporting the ticket
     as resting -- an unsent or refused CANCEL keeps the row and is retried,
     and a ticket that filled instead is left to the adoption path,
  4. the one-shot re-arms on a GENUINE recovery (clear of the trip line by
     the hysteresis band) but not on equity oscillating across the line.
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.system_controller import SystemController
from src.risk.risk_manager import RiskManager


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
    """Mirrors ZMQBridge.send_command's contract: True on a successful send."""

    def __init__(self, ok=True):
        self.commands = []
        self.ok = ok

    async def send_command(self, action, payload=None):
        self.commands.append((action, dict(payload or {})))
        return self.ok

    def cancels(self):
        return [p['ticket'] for a, p in self.commands if a == "CANCEL"]


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

    def tickets(self):
        return [o['ticket_id'] for o in self.pending]

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
        self.max_dd = 3.0

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


class NoBreakerRisk(ScriptedRisk):
    """A risk manager that predates / does not implement the breaker at all."""

    check_can_trade = None


def _real_risk(max_dd=3.0):
    return RiskManager({'risk': {'account': {'max_daily_drawdown_pct': max_dd},
                                 'trade': {'risk_per_trade_pct': 1.0}}})


def _pending(ticket, symbol):
    return {"ticket_id": ticket, "symbol": symbol, "strategy": "SilverBullet",
            "time_placed": 0.0}


def _resting(ticket):
    """A heartbeat `orders` row, keyed as _perform_reconciliation reads them."""
    return {"t": ticket, "s": "EURUSD"}


def _position(ticket):
    return {"t": ticket, "s": "EURUSD", "p": 1.1, "tp": 1.12, "sl": 1.09,
            "vol": 0.1}


def _controller(risk, pending=None, bridge=None):
    c = object.__new__(SystemController)
    c.logger = FakeLogger()
    c.telemetry = FakeTelemetry()
    c.bridge = bridge if bridge is not None else FakeBridge()
    c.risk_manager = risk
    c.state_manager = FakeStateManager(pending)
    c.equity_recorder = FakeEquityRecorder()
    c.current_open_positions = []
    c.current_pending_orders = []
    c.live_prices = {}
    c._news_blocks_symbol = lambda s: (False, "")
    return c


def _heartbeat(equity=9600.0, orders=None, pos=None):
    return {"type": "HEARTBEAT", "bal": 10000.0, "eq": equity,
            "pos": list(pos or []), "orders": list(orders or [])}


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

    def test_skip_log_states_the_real_recovery_condition(self):
        """RS022 MINOR-3: check_can_trade clears at `pnl_pct > -max_dd`, i.e.
        back above the LINE it tripped on -- not back above the anchor."""
        c = _controller(ScriptedRisk(can_trade=False, equity=9600.0))
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH", grade="A"))
        joined = c.logger.joined()
        self.assertNotIn("above the anchor", joined,
                         f"skip log overstates the recovery bar: {c.logger.events}")
        self.assertIn("-3.0% day-loss line", joined, c.logger.events)


class TestUntrippedBreakerIsUnchanged(unittest.TestCase):
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
        book = [_resting(111), _resting(222)]

        _run(c._process_incoming_data(_heartbeat(9990.0, orders=book)))  # healthy: silent
        self.assertEqual(c.telemetry.messages, [])
        self.assertEqual(c.bridge.commands, [])

        risk.can_trade = False
        _run(c._process_incoming_data(_heartbeat(9600.0, orders=book)))

        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertEqual(c.bridge.cancels(), [111, 222])
        # The rows are NOT gone yet: a fire-and-forget CANCEL is not proof.
        self.assertEqual(c.state_manager.deleted, [])
        # The operator must be able to see WHAT was pulled.
        msg = c.telemetry.messages[0]
        self.assertIn("111", msg)
        self.assertIn("222", msg)
        self.assertIn("EURUSD", msg)
        self.assertIn("XAUUSD", msg)

    def test_row_is_deleted_only_once_the_broker_stops_reporting_it(self):
        """RS022 MAJOR-1: the DB row is the portfolio cap's only view of a
        resting order, and nothing can re-register a swept row -- so it may
        only go once the heartbeat proves the order is no longer resting."""
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])

        _run(c._process_incoming_data(_heartbeat(9600.0, orders=[_resting(111)])))
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(c.state_manager.tickets(), [111])

        # Broker no longer lists it: the CANCEL landed.
        _run(c._process_incoming_data(_heartbeat(9590.0, orders=[])))
        self.assertEqual(c.state_manager.deleted, [111])
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)

    def test_cancel_that_did_not_take_is_resent_on_the_next_heartbeat(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])
        book = [_resting(111)]

        _run(c._process_incoming_data(_heartbeat(9600.0, orders=book)))
        _run(c._process_incoming_data(_heartbeat(9595.0, orders=book)))

        self.assertEqual(c.bridge.cancels(), [111, 111],
                         "a refused CANCEL was never retried")
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertIn("did not take", c.logger.joined())

    def test_unsent_cancel_keeps_the_row_and_is_retried(self):
        """send_command returns False on a wire error and swallows the
        exception; deleting the row on that would lose the order forever."""
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        dead = FakeBridge(ok=False)
        c = _controller(risk, pending=[_pending(111, "EURUSD")], bridge=dead)
        book = [_resting(111)]

        _run(c._process_incoming_data(_heartbeat(9600.0, orders=book)))
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(c.state_manager.tickets(), [111])
        self.assertIn("failed to send", c.logger.joined())
        # The alert still fires -- but it must not claim the order was pulled.
        alert = c.telemetry.messages[0]
        self.assertNotIn("Cancelling resting orders", alert, alert)
        self.assertIn("could not be sent", alert, alert)
        self.assertIn("111", alert, alert)

        dead.ok = True  # wire recovers
        _run(c._process_incoming_data(_heartbeat(9595.0, orders=book)))
        self.assertEqual(dead.cancels(), [111, 111])
        self.assertEqual(c.state_manager.deleted, [])

        _run(c._process_incoming_data(_heartbeat(9590.0, orders=[])))
        self.assertEqual(c.state_manager.deleted, [111])

    def test_ticket_that_filled_is_left_to_the_adoption_path(self):
        """RS022 MINOR-4: on the heartbeat where a LIMIT fills AND the breaker
        trips, the DB row is still PENDING. Cancelling/deleting it would strip
        the row off a LIVE position, which the adoption loop then re-registers
        as 'Adopted', losing strategy, grade and journal linkage."""
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])

        _run(c._process_incoming_data(
            _heartbeat(9600.0, orders=[], pos=[_position(111)])))

        self.assertEqual(c.bridge.cancels(), [])
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(c.state_manager.tickets(), [111])
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)

    def test_second_tripped_heartbeat_is_silent(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])

        _run(c._process_incoming_data(_heartbeat(9600.0, orders=[_resting(111)])))
        self.assertEqual(len(c.telemetry.messages), 1)

        _run(c._process_incoming_data(_heartbeat(9590.0, orders=[_resting(111)])))
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)

    def test_trip_with_no_resting_orders_still_alerts(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[])
        _run(c._process_incoming_data(_heartbeat(9600.0)))
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertEqual(c.bridge.commands, [])


class TestReArmHysteresis(unittest.TestCase):
    def test_recovery_rearms_so_a_second_trip_alerts_again(self):
        risk = ScriptedRisk(can_trade=False, equity=9600.0)
        c = _controller(risk, pending=[_pending(111, "EURUSD")])

        _run(c._process_incoming_data(_heartbeat(9600.0, orders=[_resting(111)])))
        self.assertEqual(len(c.telemetry.messages), 1)

        risk.can_trade = True  # intraday recovery, or a fresh day's anchor roll
        risk.current_equity = 9800.0  # -2.00%, clear of the -2.75% re-arm line
        _run(c._process_incoming_data(_heartbeat(9800.0, orders=[])))
        self.assertEqual(len(c.telemetry.messages), 1)

        risk.can_trade = False
        c.state_manager.pending = [_pending(333, "GBPJPY")]
        _run(c._process_incoming_data(_heartbeat(9500.0, orders=[_resting(333)])))
        self.assertEqual(len(c.telemetry.messages), 2, c.telemetry.messages)
        self.assertIn("333", c.telemetry.messages[1])
        self.assertEqual(c.bridge.cancels(), [111, 333])

    def test_oscillating_equity_across_the_line_alerts_once(self):
        """RS022 MAJOR-2, against the REAL breaker: floating P&L parked on the
        -3% line flips check_can_trade every 5s heartbeat. Without hysteresis
        each crossing was a fresh trip -- up to ~12 Telegrams a minute during
        the most stressful minutes of a trading day."""
        risk = _real_risk()
        c = _controller(risk, pending=[])
        _run(c._process_incoming_data(_heartbeat(10000.0)))  # sets the anchor

        for eq in (9699.0, 9701.0, 9699.0, 9701.0, 9698.0, 9702.0):
            _run(c._process_incoming_data(_heartbeat(eq)))

        self.assertEqual(len(c.telemetry.messages), 1,
                         f"one alert per crossing: {c.telemetry.messages}")

    def test_genuine_recovery_past_the_band_rearms_the_real_breaker(self):
        risk = _real_risk()
        c = _controller(risk, pending=[])
        _run(c._process_incoming_data(_heartbeat(10000.0)))

        _run(c._process_incoming_data(_heartbeat(9690.0)))   # -3.10%: trip
        self.assertEqual(len(c.telemetry.messages), 1)

        _run(c._process_incoming_data(_heartbeat(9750.0)))   # -2.50%: clear
        self.assertIn("RE-ARMED", c.logger.joined())

        _run(c._process_incoming_data(_heartbeat(9680.0)))   # -3.20%: trip 2
        self.assertEqual(len(c.telemetry.messages), 2, c.telemetry.messages)


class TestBreakerGuards(unittest.TestCase):
    def test_risk_manager_without_check_can_trade_is_a_no_op(self):
        """The getattr guard: fixture/legacy risk managers have no breaker, and
        a missing breaker is never a trip."""
        c = _controller(NoBreakerRisk(can_trade=False, equity=9600.0),
                        pending=[_pending(111, "EURUSD")])
        _run(c._process_incoming_data(_heartbeat(9600.0, orders=[_resting(111)])))
        self.assertEqual(c.telemetry.messages, [])
        self.assertEqual(c.bridge.commands, [])
        self.assertEqual(c.state_manager.deleted, [])

    def test_breaker_latch_defaults_are_disarmed(self):
        """Every fixture in this module relies on these class-level defaults
        (none of them assigns the latch), so removing one turns the module red
        rather than silently starting the bot mid-trip."""
        self.assertIs(SystemController._dd_breaker_tripped, False)
        self.assertIsNone(SystemController._dd_breaker_cancel_sent)

    def test_instance_latch_does_not_leak_between_controllers(self):
        a = _controller(ScriptedRisk(can_trade=False, equity=9600.0))
        _run(a._process_incoming_data(_heartbeat(9600.0)))
        self.assertTrue(a._dd_breaker_tripped)

        b = _controller(ScriptedRisk(can_trade=False, equity=9600.0))
        self.assertFalse(b._dd_breaker_tripped)
        _run(b._process_incoming_data(_heartbeat(9600.0)))
        self.assertEqual(len(b.telemetry.messages), 1, b.telemetry.messages)


if __name__ == "__main__":
    unittest.main()
