"""Portfolio-wide aggregate open-risk cap (v15 Plan 10 Advisory A).

The count gate (ExposureManager.check_exposure) and the per-trade sizer both
pass happily while total $ risk across the book climbs past what the account
was ever meant to carry. These tests pin the aggregate gate: sum risk-to-stop
over everything COMMITTED, add the proposed trade's risk, and block above
`risk.account.max_total_open_risk_pct` of equity.

"Committed" is the load-bearing word, and RS013 caught two ways it can be read
too narrowly — both of which leave a green suite next to a cap that never
binds, so each has a seam-level test here:
  * resting LIMIT/STOP orders count. SilverBullet (the only approved strategy)
    enters on LIMIT and those rest for up to 12 bars, so a positions-only
    aggregate reads 0.0 precisely when the cap should be biting;
  * orders dispatched earlier in the same bar sweep count. The book snapshot is
    rebound only on HEARTBEAT, so without an in-flight reservation N signals in
    one sweep each measure against the same pre-sweep book and all pass.

Fail-safe discipline mirrors calculate_lot_size: when the aggregate cannot be
computed (a stopless position, a symbol whose broker specs never loaded, or no
equity snapshot) the gate BLOCKS rather than guessing a number. Unlike the
sizer's per-symbol skip that halt is book-wide, so it must also reach the
operator on Telegram -- pinned below.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController  # noqa: E402
from src.risk.exposure import ExposureManager  # noqa: E402
from src.risk.risk_manager import RiskManager  # noqa: E402


def _config(max_total_open_risk_pct=5.0, commission=0.0):
    return {
        "system": {"magic_number_base": 88000},
        "risk": {
            "account": {
                "max_daily_drawdown_pct": 3.0,
                "max_global_exposure_pct": 6.0,
                "max_total_open_risk_pct": max_total_open_risk_pct,
            },
            "trade": {
                "risk_per_trade_pct": 1.0,
                "hard_max_lots": 5.0,
                "static_commission_usd": commission,
            },
        },
    }


def _risk_manager(equity=10000.0, commission=0.0):
    rm = RiskManager(_config(commission=commission))
    rm.update_account_info(equity, equity)
    # XAUUSD: tick_value $1.00 per 0.01 move -> $100 per 1.00 move per lot.
    rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
    # EURUSD: tick_value $1.00 per 0.0001 move -> $10,000 per 1.00 move per lot.
    rm.update_symbol_specs("EURUSD", val=1.0, size=0.0001, v_min=0.01, v_step=0.01)
    return rm


def _pos(symbol, price, sl, vol, ticket=1):
    """A heartbeat position row (Titan_Gateway.mq5:194 shape)."""
    return {"t": ticket, "s": symbol, "p": price, "sl": sl, "tp": 0.0, "vol": vol}


def _pending(symbol, entry, sl, lots, ticket=1):
    """A resting LIMIT/STOP row as StateManager.get_pending_orders() returns it."""
    return {"ticket_id": ticket, "symbol": symbol, "status": "PENDING",
            "initial_entry": entry, "initial_sl": sl, "initial_tp": 0.0,
            "lots": lots, "strategy": "SilverBullet"}


# ---------------------------------------------------------------------------
# RiskManager.aggregate_open_risk
# ---------------------------------------------------------------------------

class AggregateOpenRiskTests(unittest.TestCase):
    def test_empty_book_is_zero_risk(self):
        self.assertEqual(_risk_manager().aggregate_open_risk([]), 0.0)

    def test_sums_risk_to_stop_across_positions(self):
        rm = _risk_manager()
        book = [
            _pos("XAUUSD", 2000.0, 1996.0, 1.0),   # 4.00 move  -> $400
            _pos("EURUSD", 1.1000, 1.0950, 0.50),  # 0.0050     -> $25
        ]
        self.assertAlmostEqual(rm.aggregate_open_risk(book), 425.0, places=6)

    def test_stopless_position_is_uncomputable(self):
        """sl == 0 (externally opened, no stop) -> risk to stop is undefined."""
        rm = _risk_manager()
        book = [_pos("XAUUSD", 2000.0, 1996.0, 1.0), _pos("EURUSD", 1.1000, 0.0, 1.0)]
        self.assertIsNone(rm.aggregate_open_risk(book))

    def test_position_without_broker_specs_is_uncomputable(self):
        """money_for_move returns its 0.0 'unknown' sentinel -> never count it as $0."""
        rm = _risk_manager()
        book = [_pos("US30", 40000.0, 39800.0, 1.0)]  # specs never loaded
        self.assertIsNone(rm.aggregate_open_risk(book))

    def test_resting_pending_orders_are_counted(self):
        """A placed LIMIT is committed risk long before it fills (RS013 CRITICAL)."""
        rm = _risk_manager()
        resting = [
            _pending("XAUUSD", 2000.0, 1996.0, 1.0, ticket=11),   # $400
            _pending("EURUSD", 1.1000, 1.0950, 0.50, ticket=12),  # $25
        ]
        self.assertAlmostEqual(rm.aggregate_open_risk([], resting), 425.0, places=6)

    def test_positions_and_pendings_sum_together(self):
        rm = _risk_manager()
        book = [_pos("XAUUSD", 2000.0, 1996.0, 1.0, ticket=1)]            # $400
        resting = [_pending("EURUSD", 1.1000, 1.0950, 0.50, ticket=2)]    # $25
        self.assertAlmostEqual(rm.aggregate_open_risk(book, resting), 425.0, places=6)

    def test_same_ticket_in_both_lists_counted_once(self):
        """Between a fill and the heartbeat's PENDING->ACTIVE backfill a trade
        shows up in both lists; double-counting it would over-block."""
        rm = _risk_manager()
        book = [_pos("XAUUSD", 2000.0, 1996.0, 1.0, ticket=77)]
        resting = [_pending("XAUUSD", 2000.0, 1996.0, 1.0, ticket=77)]
        self.assertAlmostEqual(rm.aggregate_open_risk(book, resting), 400.0, places=6)

    def test_stopless_pending_row_is_uncomputable(self):
        """Same fail-safe discipline on the pending side as on positions."""
        rm = _risk_manager()
        self.assertIsNone(rm.aggregate_open_risk([], [_pending("XAUUSD", 2000.0, 0.0, 1.0)]))

    def test_commission_is_included_matching_the_net_risk_sizer(self):
        """calculate_lot_size solves NET of commission; a gross-only aggregate
        would systematically under-count and admit more risk than configured."""
        rm = _risk_manager(commission=7.0)
        book = [_pos("XAUUSD", 2000.0, 1996.0, 2.0)]  # $800 gross + 2 x $7
        self.assertAlmostEqual(rm.aggregate_open_risk(book), 814.0, places=6)

    def test_money_for_move_stays_gross(self):
        """The commission belongs to risk_to_stop; money_for_move is reused by
        the ratchet's locked-profit math and must stay a pure P/L conversion."""
        rm = _risk_manager(commission=7.0)
        self.assertAlmostEqual(rm.money_for_move("XAUUSD", 4.0, 2.0), 800.0, places=6)


# ---------------------------------------------------------------------------
# ExposureManager.check_total_risk
# ---------------------------------------------------------------------------

class TotalRiskGateTests(unittest.TestCase):
    def _mgr(self, cap=5.0):
        return ExposureManager(_config(cap), {})

    def test_under_cap_allowed(self):
        allowed, _ = self._mgr().check_total_risk(300.0, 100.0, 10000.0)
        self.assertTrue(allowed)

    def test_over_cap_blocked_with_distinguishable_reason(self):
        allowed, reason = self._mgr().check_total_risk(450.0, 100.0, 10000.0)
        self.assertFalse(allowed)
        self.assertIn("Total Open Risk", reason)
        self.assertIn("5.50", reason)  # (450 + 100) / 10000 -> 5.50%

    def test_exactly_at_cap_allowed(self):
        """Boundary: the cap is a ceiling, not an exclusive bound."""
        allowed, reason = self._mgr().check_total_risk(400.0, 100.0, 10000.0)
        self.assertTrue(allowed, reason)

    def test_first_trade_on_empty_book_not_blocked(self):
        allowed, _ = self._mgr().check_total_risk(0.0, 100.0, 10000.0)
        self.assertTrue(allowed)

    def test_uncomputable_aggregate_blocks(self):
        allowed, reason = self._mgr().check_total_risk(None, 100.0, 10000.0)
        self.assertFalse(allowed)
        self.assertIn("un-computable", reason)

    def test_zero_equity_blocks_without_dividing(self):
        allowed, reason = self._mgr().check_total_risk(0.0, 100.0, 0.0)
        self.assertFalse(allowed)
        self.assertIn("un-computable", reason)

    def test_negative_equity_blocks(self):
        allowed, reason = self._mgr().check_total_risk(0.0, 100.0, -50.0)
        self.assertFalse(allowed)
        self.assertIn("un-computable", reason)

    def test_uncomputable_proposed_risk_blocks(self):
        allowed, reason = self._mgr().check_total_risk(100.0, 0.0, 10000.0)
        self.assertFalse(allowed)
        self.assertIn("un-computable", reason)


# ---------------------------------------------------------------------------
# SystemController._execute_signal wiring
# ---------------------------------------------------------------------------

class FakeBridge:
    def __init__(self):
        self.reliable = []

    async def send_order_reliable(self, payload, timeout=2500):
        self.reliable.append(dict(payload))
        return True


class FakeLogger:
    def __init__(self):
        self.events = []

    def log_event(self, *a, **kw):
        self.events.append(a)


class FakeTelemetry:
    def __init__(self):
        self.messages = []

    async def notify_signal(self, *a, **kw):
        pass

    async def send_message(self, text, parse_mode="HTML"):
        self.messages.append(text)


class FakeStateManager:
    """Only the surface _execute_signal / the HEARTBEAT branch touch."""

    def __init__(self, pending=None):
        self.pending = list(pending or [])

    def get_pending_orders(self):
        return list(self.pending)

    def exists(self, ticket):
        return False

    def register_order(self, *a, **kw):
        pass

    def backfill_position_state(self, *a, **kw):
        pass


def _controller(open_positions, cap=5.0, equity=10000.0, resting=None):
    c = object.__new__(SystemController)
    c.config = _config(cap)
    c.bridge = FakeBridge()
    c.logger = FakeLogger()
    c.telemetry = FakeTelemetry()
    c.risk_manager = _risk_manager(equity)
    c.exposure_manager = ExposureManager(c.config, {})
    c.state_manager = FakeStateManager(resting)
    c.current_open_positions = open_positions
    c.current_pending_orders = []
    c.live_prices = {}
    c.pending_signal_meta = {}
    c._reserved_risk = {}
    c._uncomputable_alert_at = None
    return c


# EURUSD long, 100-pip stop: at 1% of $10,000 the sizer targets 1.00 lot and
# vol-step flooring lands on 0.99, so the proposed trade carries ~$99 of risk.
# Every cap threshold below is chosen with margin either side of that.
DECISION = {"signal": "BUY", "type": "MARKET", "price": 1.1000, "sl": 1.0900, "tp": 1.1200}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ExecuteSignalGateTests(unittest.TestCase):
    def _fire(self, controller):
        _run(controller._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH"))

    def test_first_trade_is_sent(self):
        c = _controller([])
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 1)

    def test_book_under_cap_is_sent(self):
        # $300 open + ~$99 proposed = 3.99% of equity, under the 5% cap.
        c = _controller([_pos("XAUUSD", 2000.0, 1997.0, 1.0)])
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 1)

    def test_book_over_cap_is_blocked_and_logged(self):
        # $450 open + ~$99 proposed = 5.49% of equity, over the 5% cap.
        c = _controller([_pos("XAUUSD", 2000.0, 1995.5, 1.0)])
        self._fire(c)
        self.assertEqual(c.bridge.reliable, [])
        blocked = [e for e in c.logger.events
                   if e[0] == "RISK" and e[1] == "EXPOSURE" and "Total Open Risk" in e[2]]
        self.assertEqual(len(blocked), 1, c.logger.events)

    def test_stopless_open_position_blocks_new_trade(self):
        c = _controller([_pos("XAUUSD", 2000.0, 0.0, 1.0)])
        self._fire(c)
        self.assertEqual(c.bridge.reliable, [])
        self.assertTrue(any("un-computable" in e[2] for e in c.logger.events), c.logger.events)

    def test_no_equity_snapshot_blocks_new_trade(self):
        """Equity 0 (no heartbeat yet) must block, never divide by zero."""
        c = _controller([])
        c.risk_manager.current_equity = 0.0
        # Sizing would otherwise short-circuit on 0 lots; force a real lot through.
        c.risk_manager.calculate_lot_size = lambda *a, **kw: 1.0
        self._fire(c)
        self.assertEqual(c.bridge.reliable, [])
        self.assertTrue(any("un-computable" in e[2] for e in c.logger.events), c.logger.events)


# A LIMIT entry -- what SilverBullet, the only approved strategy, actually
# emits. Priced far from any live quote so _execute_signal's near-touch
# LIMIT->MARKET flip does not fire (live_prices is empty here anyway).
LIMIT_DECISION = {"signal": "BUY", "type": "LIMIT",
                  "price": 1.1000, "sl": 1.0900, "tp": 1.1200}


class RestingPendingOrderTests(unittest.TestCase):
    """RS013 CRITICAL: with a LIMIT-only strategy the positions-only aggregate
    is 0.0 at every evaluation, so the cap could never block anything."""

    def _fire(self, controller, decision=LIMIT_DECISION):
        _run(controller._execute_signal("EURUSD", decision, "SilverBullet", "BULLISH"))

    def test_resting_limits_can_exhaust_the_cap(self):
        # $450 resting (unfilled) + ~$99 proposed = 5.49% against a 5% cap.
        c = _controller([], resting=[_pending("XAUUSD", 2000.0, 1995.5, 1.0, ticket=9)])
        self._fire(c)
        self.assertEqual(c.bridge.reliable, [])
        self.assertTrue(any("Total Open Risk" in e[2] for e in c.logger.events),
                        c.logger.events)

    def test_resting_limits_under_cap_still_trade(self):
        c = _controller([], resting=[_pending("XAUUSD", 2000.0, 1997.0, 1.0, ticket=9)])
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 1)

    def test_eleven_limits_cannot_all_pass_a_five_percent_cap(self):
        """The reproduction from the review: 11 pairs x 1% through a 5% cap."""
        c = _controller([])
        for i in range(11):
            self._fire(c)
            # Each accepted send rests as a real pending order the next signal
            # must see -- the state the live book is normally in.
            if len(c.bridge.reliable) > len(c.state_manager.pending):
                sent = c.bridge.reliable[-1]
                c.state_manager.pending.append(
                    _pending(sent['symbol'], sent['price'], sent['sl'],
                             sent['volume'], ticket=100 + i))
                c._reserved_risk.clear()  # book now shows it; drop the reservation
        self.assertEqual(len(c.bridge.reliable), 5,
                         f"5% cap at ~1%/trade must stop at 5 sends: {c.bridge.reliable}")


class InCycleReservationTests(unittest.TestCase):
    """RS013 MAJOR: current_open_positions is rebound only on HEARTBEAT, so
    every signal of one bar sweep would otherwise see the same empty book."""

    def _fire(self, controller, symbol="EURUSD"):
        _run(controller._execute_signal(symbol, DECISION, "SilverBullet", "BULLISH"))

    def test_second_signal_in_the_sweep_sees_the_first(self):
        # 1.5% cap: one trade's ~0.99% fits, two (~1.98%) do not.
        c = _controller([], cap=1.5)
        self._fire(c)
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 1)
        self.assertTrue(any("Total Open Risk" in e[2] for e in c.logger.events),
                        c.logger.events)

    def test_reservation_matches_the_risk_actually_dispatched(self):
        c = _controller([])
        self.assertEqual(c._reserved_risk_total(), 0.0)
        self._fire(c)
        sent = c.bridge.reliable[0]
        expected = c.risk_manager.risk_to_stop(
            "EURUSD", abs(sent['price'] - sent['sl']), sent['volume'])
        self.assertGreater(expected, 0.0)
        self.assertAlmostEqual(c._reserved_risk_total(), expected, places=6)

    def test_expired_reservations_do_not_block_forever(self):
        """An order acked but never opened must not hold the cap hostage."""
        c = _controller([], cap=1.5)
        self._fire(c)
        stale = c._reserved_risk["EURUSD"][1] - SystemController.RESERVED_RISK_TTL_S - 1
        c._reserved_risk["EURUSD"] = (100.0, stale)
        self.assertEqual(c._reserved_risk_total(), 0.0)
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 2)

    def test_heartbeat_releases_the_reservation_it_can_now_see(self):
        """Otherwise the reservation and the real position double-count."""
        c = _controller([], cap=1.5)
        self._fire(c)
        self.assertIn("EURUSD", c._reserved_risk)
        _run(c._process_incoming_data({
            "type": "HEARTBEAT", "bal": 10000.0, "eq": 10000.0,
            "pos": [_pos("EURUSD", 1.1000, 1.0900, 1.0, ticket=5)], "orders": [],
        }))
        self.assertEqual(c._reserved_risk, {})

    def test_heartbeat_keeps_a_reservation_the_broker_has_not_reported(self):
        c = _controller([], cap=1.5)
        self._fire(c)
        _run(c._process_incoming_data({
            "type": "HEARTBEAT", "bal": 10000.0, "eq": 10000.0,
            "pos": [], "orders": [],
        }))
        self.assertIn("EURUSD", c._reserved_risk)


class UncomputableBookAlertTests(unittest.TestCase):
    """RS013 MAJOR: one stray row halts ALL symbols; a silent halt on an
    unattended forward test is indistinguishable from a quiet market."""

    def _fire(self, controller):
        _run(controller._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH"))

    def test_book_wide_halt_reaches_the_operator(self):
        c = _controller([_pos("XAUUSD", 2000.0, 0.0, 1.0)])  # stopless, manual
        self._fire(c)
        self.assertEqual(c.bridge.reliable, [])
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertIn("un-computable", c.telemetry.messages[0])

    def test_alert_is_throttled_not_repeated_per_signal(self):
        c = _controller([_pos("XAUUSD", 2000.0, 0.0, 1.0)])
        for _ in range(4):
            self._fire(c)
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)

    def test_alert_re_arms_once_the_book_is_computable_again(self):
        c = _controller([_pos("XAUUSD", 2000.0, 0.0, 1.0)])
        self._fire(c)
        c.current_open_positions = []          # operator set a stop / specs arrived
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 1)
        self.assertIsNone(c._uncomputable_alert_at)

    def test_a_plain_over_cap_block_does_not_alert(self):
        """Only an un-computable book is an outage; normal capping is routine."""
        c = _controller([_pos("XAUUSD", 2000.0, 1995.5, 1.0)])
        self._fire(c)
        self.assertEqual(c.bridge.reliable, [])
        self.assertEqual(c.telemetry.messages, [])


if __name__ == "__main__":
    unittest.main()
