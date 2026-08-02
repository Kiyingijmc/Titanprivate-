# tests/unit/test_gui_pending_and_risk.py
"""The `orders`, `risk` and `market` blocks of build_snapshot.

Motivation (2026-08-02 operator report): the dashboard showed "Open Positions 0"
and no pending-order surface at all while MT5 held two resting limits, one of
them an untracked stopless orphan. The heartbeat already carried them
(SystemController.current_pending_orders) -- the snapshot simply never exported
them. Same story for the RISK-01 daily anchor and the book-wide exposure cap:
both can halt trading outright and neither was visible anywhere in the GUI.

Every block here is defensive by the same rule as `dollar`: a controller that
predates the attribute must degrade, never crash the snapshot.
"""
import unittest
from datetime import datetime, timedelta

from src.ops.web.state_view import build_snapshot


class FakeRisk:
    """Mirrors the real RiskManager surface build_snapshot touches."""
    current_equity = 9800.0
    starting_balance = 10000.0
    day_start_equity = 10000.0
    max_dd = 3.0

    def __init__(self):
        self.last_uncomputable_row = None
        self._book = 150.0

    @staticmethod
    def throttle_factor():
        return 1.0

    def check_can_trade(self):
        return True

    def aggregate_open_risk(self, open_positions, pending_orders=None):
        # The real one always writes this attribute; the snapshot must restore
        # whatever was there before so it cannot clobber a live diagnostic.
        self.last_uncomputable_row = None
        return self._book


class FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 0, "approved": 0, "blocked_by": {}}


class FakeRegistry:
    @staticmethod
    def report():
        return []


class FakeState:
    def __init__(self, rows=None, pending=None):
        self._rows = rows or {}
        self._pending = pending or []

    def get_order(self, ticket):
        return self._rows.get(ticket)

    def get_pending_orders(self):
        return list(self._pending)


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now() - timedelta(seconds=1)
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.arbiter = FakeArbiter()
        self.registry = FakeRegistry()
        self.config = {"risk": {"account": {"max_total_open_risk_pct": 5.0}}}
        self.current_open_positions = []
        # Exactly the EA's pending-order shape (Titan_Gateway.mq5:225):
        # t/s/p/type/vol -- note there is NO sl or tp on the wire.
        self.current_pending_orders = [
            {"t": 1939200606, "s": "ETHUSD", "p": 1855.30, "type": 2, "vol": 0.03},
            {"t": 1936559060, "s": "EURUSD", "p": 1.15718, "type": 3, "vol": 0.15},
        ]
        self.active_symbols = ["EURUSD", "ETHUSD", "US30"]
        self.state_manager = FakeState(
            rows={1939200606: {"grade": "B", "strategy": "SilverBullet",
                               "initial_sl": 1844.18, "initial_tp": 1877.53}},
            pending=[{"ticket_id": 1939200606, "symbol": "ETHUSD",
                      "initial_entry": 1855.30, "initial_sl": 1844.18, "lots": 0.03}],
        )


class TestPendingOrders(unittest.TestCase):
    def test_pending_orders_are_exported(self):
        orders = build_snapshot(FakeController())["orders"]
        self.assertEqual(len(orders), 2)
        self.assertEqual([o["ticket"] for o in orders], [1939200606, 1936559060])

    def test_titan_order_enriched_from_db_row(self):
        eth = build_snapshot(FakeController())["orders"][0]
        self.assertEqual(eth["symbol"], "ETHUSD")
        self.assertEqual(eth["side"], "BUY")
        self.assertEqual(eth["kind"], "LIMIT")
        self.assertEqual(eth["lots"], 0.03)
        self.assertEqual(eth["price"], 1855.30)
        self.assertEqual(eth["sl"], 1844.18)
        self.assertEqual(eth["tp"], 1877.53)
        self.assertEqual(eth["grade"], "B")
        self.assertEqual(eth["strategy"], "SilverBullet")
        self.assertTrue(eth["tracked"])

    def test_untracked_orphan_is_flagged_and_has_no_stop(self):
        """The whole point of the panel: an order Titan did not place has no DB
        row, so it carries no stop the risk cap can price. It must be visibly
        distinct rather than rendered as a normal order."""
        eur = build_snapshot(FakeController())["orders"][1]
        self.assertEqual(eur["symbol"], "EURUSD")
        self.assertEqual(eur["side"], "SELL")
        self.assertEqual(eur["kind"], "LIMIT")
        self.assertFalse(eur["tracked"])
        self.assertEqual(eur["sl"], 0.0)
        self.assertEqual(eur["grade"], "")

    def test_stop_order_types_map_to_side_and_kind(self):
        c = FakeController()
        c.current_pending_orders = [
            {"t": 1, "s": "US30", "p": 100.0, "type": 4, "vol": 0.1},
            {"t": 2, "s": "US30", "p": 100.0, "type": 5, "vol": 0.1},
        ]
        orders = build_snapshot(c)["orders"]
        self.assertEqual((orders[0]["side"], orders[0]["kind"]), ("BUY", "STOP"))
        self.assertEqual((orders[1]["side"], orders[1]["kind"]), ("SELL", "STOP"))

    def test_controller_without_pending_attribute_yields_empty_list(self):
        c = FakeController()
        del c.current_pending_orders
        self.assertEqual(build_snapshot(c)["orders"], [])

    def test_raising_get_order_does_not_propagate(self):
        class RaisingState(FakeState):
            def get_order(self, ticket):
                raise RuntimeError("db locked")

        c = FakeController()
        c.state_manager = RaisingState()
        orders = build_snapshot(c)["orders"]   # must not raise
        self.assertFalse(orders[0]["tracked"])
        self.assertEqual(orders[0]["sl"], 0.0)


class TestRiskBlock(unittest.TestCase):
    def test_day_pnl_is_measured_against_the_dd_anchor(self):
        """Regression: the Overview tile used equity - starting_balance, which is
        floating P&L since process boot and silently re-bases on every restart.
        Day P&L must come off day_start_equity (the RISK-01 persisted anchor)."""
        risk = build_snapshot(FakeController())["risk"]
        self.assertEqual(risk["day_anchor"], 10000.0)
        self.assertEqual(risk["day_pnl"], -200.0)
        self.assertAlmostEqual(risk["day_pnl_pct"], -2.0)

    def test_anchor_differs_from_boot_balance(self):
        c = FakeController()
        c.risk_manager.day_start_equity = 9900.0
        risk = build_snapshot(c)["risk"]
        self.assertEqual(risk["day_pnl"], -100.0)   # not -200 (equity - balance)

    def test_unanchored_day_reports_none_not_zero(self):
        c = FakeController()
        c.risk_manager.day_start_equity = 0.0
        risk = build_snapshot(c)["risk"]
        self.assertIsNone(risk["day_pnl"])
        self.assertIsNone(risk["day_pnl_pct"])

    def test_breaker_state_and_limit_exposed(self):
        risk = build_snapshot(FakeController())["risk"]
        self.assertTrue(risk["can_trade"])
        self.assertEqual(risk["max_daily_dd_pct"], 3.0)

    def test_tripped_breaker_surfaces(self):
        c = FakeController()
        c.risk_manager.check_can_trade = lambda: False
        self.assertFalse(build_snapshot(c)["risk"]["can_trade"])

    def test_book_risk_reported_against_cap(self):
        risk = build_snapshot(FakeController())["risk"]
        self.assertEqual(risk["book_risk"], 150.0)
        self.assertAlmostEqual(risk["book_risk_pct"], 150.0 / 9800.0 * 100.0, places=3)
        self.assertEqual(risk["max_book_risk_pct"], 5.0)
        self.assertIsNone(risk["blocker"])

    def test_uncomputable_book_surfaces_the_offending_row(self):
        """An un-computable row blocks EVERY symbol. A total trading stop must
        not be indistinguishable from a quiet market on the dashboard."""
        c = FakeController()

        def bad(open_positions, pending_orders=None):
            c.risk_manager.last_uncomputable_row = {
                "ticket": 42, "symbol": "GBPUSD", "source": "position"}
            return None

        c.risk_manager.aggregate_open_risk = bad
        risk = build_snapshot(c)["risk"]
        self.assertIsNone(risk["book_risk"])
        self.assertIsNone(risk["book_risk_pct"])
        self.assertEqual(risk["blocker"], {"ticket": 42, "symbol": "GBPUSD",
                                           "source": "position"})

    def test_snapshot_restores_last_uncomputable_row(self):
        """build_snapshot is polled once a second and shares the RiskManager with
        the trading loop. aggregate_open_risk always writes last_uncomputable_row,
        so the read-only snapshot must put back whatever it found."""
        c = FakeController()
        sentinel = {"ticket": 7, "symbol": "XAUUSD", "source": "pending"}
        c.risk_manager.last_uncomputable_row = sentinel
        build_snapshot(c)
        self.assertIs(c.risk_manager.last_uncomputable_row, sentinel)

    def test_risk_block_degrades_on_a_bare_risk_manager(self):
        class Bare:
            current_equity = 0.0
            starting_balance = 0.0

            @staticmethod
            def throttle_factor():
                return 1.0

        c = FakeController()
        c.risk_manager = Bare()
        risk = build_snapshot(c)["risk"]   # must not raise
        self.assertIsNone(risk["day_pnl"])
        self.assertIsNone(risk["book_risk"])


class TestMarketBlock(unittest.TestCase):
    """The GUI drew a hard "Markets closed" banner off its own FX-only calendar
    while SilverBullet was placing ETHUSD limits on a Sunday. The engine already
    knows better (SystemController: `should_monitor = not is_weekend or
    has_crypto`) -- so export that truth instead of recomputing it in TypeScript."""

    def test_crypto_in_the_universe_is_reported(self):
        market = build_snapshot(FakeController())["market"]
        self.assertTrue(market["has_crypto"])

    def test_fx_only_universe_reports_no_crypto(self):
        c = FakeController()
        c.active_symbols = ["EURUSD", "GBPUSD", "XAUUSD"]
        self.assertFalse(build_snapshot(c)["market"]["has_crypto"])

    def test_detection_matches_the_engine_rule(self):
        c = FakeController()
        c.active_symbols = ["BTCUSD"]
        self.assertTrue(build_snapshot(c)["market"]["has_crypto"])

    def test_missing_active_symbols_degrades_to_false(self):
        c = FakeController()
        del c.active_symbols
        self.assertFalse(build_snapshot(c)["market"]["has_crypto"])


if __name__ == "__main__":
    unittest.main()
