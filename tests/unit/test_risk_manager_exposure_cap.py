"""Portfolio-wide aggregate open-risk cap (v15 Plan 10 Advisory A).

The count gate (ExposureManager.check_exposure) and the per-trade sizer both
pass happily while total $ risk across the book climbs past what the account
was ever meant to carry. These tests pin the aggregate gate: sum risk-to-stop
over every open position, add the proposed trade's risk, and block above
`risk.account.max_total_open_risk_pct` of equity.

Fail-safe discipline mirrors calculate_lot_size: when the aggregate cannot be
computed (a stopless position, a symbol whose broker specs never loaded, or no
equity snapshot) the gate BLOCKS rather than guessing a number.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController  # noqa: E402
from src.risk.exposure import ExposureManager  # noqa: E402
from src.risk.risk_manager import RiskManager  # noqa: E402


def _config(max_total_open_risk_pct=5.0):
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
                "static_commission_usd": 0.0,
            },
        },
    }


def _risk_manager(equity=10000.0):
    rm = RiskManager(_config())
    rm.update_account_info(equity, equity)
    # XAUUSD: tick_value $1.00 per 0.01 move -> $100 per 1.00 move per lot.
    rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
    # EURUSD: tick_value $1.00 per 0.0001 move -> $10,000 per 1.00 move per lot.
    rm.update_symbol_specs("EURUSD", val=1.0, size=0.0001, v_min=0.01, v_step=0.01)
    return rm


def _pos(symbol, price, sl, vol):
    """A heartbeat position row (Titan_Gateway.mq5:194 shape)."""
    return {"t": 1, "s": symbol, "p": price, "sl": sl, "tp": 0.0, "vol": vol}


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
    async def notify_signal(self, *a, **kw):
        pass


def _controller(open_positions, cap=5.0, equity=10000.0):
    c = object.__new__(SystemController)
    c.config = _config(cap)
    c.bridge = FakeBridge()
    c.logger = FakeLogger()
    c.telemetry = FakeTelemetry()
    c.risk_manager = _risk_manager(equity)
    c.exposure_manager = ExposureManager(c.config, {})
    c.current_open_positions = open_positions
    c.live_prices = {}
    c.pending_signal_meta = {}
    return c


# EURUSD long, 100-pip stop: at 1% of $10,000 the sizer lands on 1.00 lot,
# so the proposed trade carries exactly $100 of risk.
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
        # $300 open + $100 proposed = 4.00% of equity, under the 5% cap.
        c = _controller([_pos("XAUUSD", 2000.0, 1997.0, 1.0)])
        self._fire(c)
        self.assertEqual(len(c.bridge.reliable), 1)

    def test_book_over_cap_is_blocked_and_logged(self):
        # $450 open + $100 proposed = 5.50% of equity, over the 5% cap.
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


if __name__ == "__main__":
    unittest.main()
