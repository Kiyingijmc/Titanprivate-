"""Regression coverage for broker-confirmed partial-exit lifecycle state."""
import asyncio
import os
import tempfile
import unittest

from src.core.bus import EventBus
from src.core.state_manager import StateManager
from src.core.system_controller import SystemController


class _Risk:
    def money_for_move(self, _symbol, distance, lots):
        return abs(float(distance)) * float(lots or 0.0)


class _Telemetry:
    def __init__(self):
        self.partials, self.closes = [], []

    async def notify_partial(self, *args): self.partials.append(args)
    async def notify_close(self, *args): self.closes.append(args)


def _controller(state_manager):
    controller = SystemController.__new__(SystemController)
    controller.bus = EventBus()
    controller.state_manager = state_manager
    controller.risk_manager = _Risk()
    controller.telemetry = _Telemetry()
    controller.daily_closed_trades = []
    return controller


def _run(coro):
    loop = asyncio.new_event_loop()
    try: return loop.run_until_complete(coro)
    finally: loop.close()


class PartialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "trade_state.db")
        self.sm = StateManager(self.path)
        self.sm.register_order(1978989795, "US30", "SilverBullet", "MARKET",
                               status="ACTIVE", entry=53199.3, tp=53000,
                               sl=53266.09, lots=1.49, grade="A+")

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def test_partial_preserves_identity_and_original_risk_inputs(self):
        before = self.sm.get_order(1978989795)
        self.sm.mark_partial_requested(1978989795, 1)
        self.assertTrue(self.sm.record_exit_deal(1978989795, 1234, 326.70, 1.05,
                                                  confirm_requested_stage=True))
        after = self.sm.get_order(1978989795)
        self.assertEqual(after["strategy"], "SilverBullet")
        self.assertEqual(after["time_placed"], before["time_placed"])
        self.assertAlmostEqual(after["initial_entry"], 53199.3)
        self.assertAlmostEqual(after["initial_sl"], 53266.09)
        self.assertAlmostEqual(after["initial_tp"], 53000)
        self.assertAlmostEqual(after["remaining_volume"], 1.05)
        self.assertAlmostEqual(after["realized_pnl"], 326.70)
        self.assertEqual((after["partial_stage_requested"], after["partial_stage"]), (1, 1))
        self.assertEqual(after["partial_stage_status"], "CONFIRMED")

    def test_exact_duplicate_deal_has_no_second_accounting_mutation(self):
        self.sm.mark_partial_requested(1978989795, 1)
        self.assertTrue(self.sm.record_exit_deal(1978989795, 1234, 326.70, 1.05,
                                                  confirm_requested_stage=True))
        self.assertFalse(self.sm.record_exit_deal(1978989795, 1234, 326.70, 1.05,
                                                   confirm_requested_stage=True))
        row = self.sm.get_order(1978989795)
        self.assertAlmostEqual(row["realized_pnl"], 326.70)
        self.assertAlmostEqual(row["remaining_volume"], 1.05)

    def test_distinct_second_partial_accumulates_once_and_advances_stage(self):
        self.sm.mark_partial_requested(1978989795, 1)
        self.sm.record_exit_deal(1978989795, 1234, 100.0, 1.05, confirm_requested_stage=True)
        self.sm.mark_partial_requested(1978989795, 2)
        self.assertTrue(self.sm.record_exit_deal(1978989795, 1235, 200.0, 0.50,
                                                  confirm_requested_stage=True))
        row = self.sm.get_order(1978989795)
        self.assertAlmostEqual(row["realized_pnl"], 300.0)
        self.assertAlmostEqual(row["remaining_volume"], 0.50)
        self.assertEqual((row["partial_stage"], row["partial_stage_requested"]), (2, 2))

    def test_restart_restores_partial_lifecycle_state(self):
        self.sm.update_ratchet_level(1978989795, 2)
        self.sm.mark_partial_requested(1978989795, 1)
        self.sm.record_exit_deal(1978989795, 1234, 326.70, 1.05, confirm_requested_stage=True)
        self.sm.close()
        self.sm = StateManager(self.path)
        row = self.sm.get_order(1978989795)
        self.assertEqual(row["strategy"], "SilverBullet")
        self.assertAlmostEqual(row["remaining_volume"], 1.05)
        self.assertAlmostEqual(row["realized_pnl"], 326.70)
        self.assertEqual((row["partial_stage"], row["ratchet_level"]), (1, 2))

    def test_known_partial_position_is_not_replaced_by_adopted_registration(self):
        self.sm.mark_partial_requested(1978989795, 1)
        self.sm.record_exit_deal(1978989795, 1234, 1.0, 1.05, confirm_requested_stage=True)
        self.sm.register_order(1978989795, "US30", "Adopted", "MARKET", status="ACTIVE",
                               entry=0.0, tp=0.0, sl=0.0, lots=1.05)
        self.assertEqual(self.sm.get_order(1978989795)["strategy"], "SilverBullet")

    def test_partial_event_with_remaining_volume_never_archives_active_trade(self):
        controller = _controller(self.sm)
        controller.current_open_positions = [{'t': 1978989795, 'vol': 1.49}]
        self.sm.mark_partial_requested(1978989795, 1)
        _run(controller._process_incoming_data({"type": "EXECUTION", "status": "PARTIAL",
              "ticket": 1978989795, "deal": 1234, "s": "US30", "pn": 50.0,
              "volume": 0.44, "remaining_volume": 1.05}))
        self.assertIsNotNone(self.sm.get_order(1978989795))
        self.assertEqual(controller.telemetry.partials[0][0], "Broker-confirmed partial")
        self.assertAlmostEqual(controller.current_open_positions[0]['vol'], 1.05)

    def test_closed_zero_remaining_archives_once_with_all_realized_pnl(self):
        controller = _controller(self.sm)
        self.sm.mark_partial_requested(1978989795, 1)
        self.sm.record_exit_deal(1978989795, 1234, 100.0, 1.05, confirm_requested_stage=True)
        closed = {"type": "EXECUTION", "status": "CLOSED", "ticket": 1978989795,
                  "deal": 1235, "s": "US30", "pn": 25.0, "remaining_volume": 0.0}
        _run(controller._process_incoming_data(closed))
        _run(controller._process_incoming_data(closed))
        self.assertIsNone(self.sm.get_order(1978989795))
        rows = self.sm.conn.execute("SELECT pnl FROM trade_history WHERE ticket_id=?", (1978989795,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["pnl"], 125.0)
        self.assertEqual(len(controller.daily_closed_trades), 1)
        self.assertAlmostEqual(controller.daily_closed_trades[0]["pnl"], 125.0)

    def test_cancel_requested_order_remains_risk_bearing_until_reconciled_absent(self):
        self.sm.register_order(99, "US30", "SilverBullet", "LIMIT", status="PENDING",
                               entry=53000, sl=52900, tp=53200, lots=0.10)
        self.sm.mark_cancel_requested(99)
        pending = {row["ticket_id"]: row for row in self.sm.get_pending_orders()}
        self.assertIn(99, pending)
        self.assertEqual(pending[99]["status"], "CANCEL_REQUESTED")


if __name__ == "__main__":
    unittest.main()
