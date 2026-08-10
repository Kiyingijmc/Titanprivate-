"""trigger_panic must verify its own outcome from HEARTBEAT state, not report
success from commands-sent counts.

CLOSE_POS/CANCEL are fire-and-forget on the PUSH socket -- an EA reject (e.g.
10018 market closed, or a wedged/offline EA) is invisible to Python. A panic
that reports "Closed X | Cancelled Y" unconditionally is indistinguishable
from a panic that actually flattened the book, so the operator gets false
assurance while a position sits unmanaged. See S019 (PAUSED must not freeze
in-trade management) for the same failure shape one state over.
"""
import asyncio
import os, sys, unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.system_controller import SystemController, BotState  # noqa: E402


class FakeBridge:
    """poll_data() returns one queued batch per call; empty once exhausted."""
    def __init__(self, heartbeat_batches):
        self.commands = []
        self._batches = list(heartbeat_batches)

    async def send_command(self, action, payload=None):
        self.commands.append((action, dict(payload or {})))
        return True

    async def poll_data(self):
        if self._batches:
            return self._batches.pop(0)
        return []


class FakeState:
    def exists(self, ticket): return True
    def register_order(self, *a, **kw): pass
    def backfill_position_state(self, *a, **kw): pass


class FakeLogger:
    def log_event(self, *a, **kw): pass


class FakeTelemetry:
    def __init__(self): self.messages = []
    async def send_message(self, text, **kw): self.messages.append(text)


def heartbeat(pos=None, orders=None):
    return {"type": "HEARTBEAT", "bal": 0, "eq": 0, "pos": pos or [], "orders": orders or []}


def make_controller(open_positions, pending_orders, heartbeat_batches):
    sc = object.__new__(SystemController)
    sc.bridge = FakeBridge(heartbeat_batches)
    sc.state_manager = FakeState()
    sc.logger = FakeLogger()
    sc.telemetry = FakeTelemetry()
    sc.current_open_positions = open_positions
    sc.current_pending_orders = pending_orders
    from datetime import datetime
    sc.last_heartbeat_time = datetime.now()
    sc.state = BotState.ACTIVE
    return sc


def run(coro):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class PanicReportsVerifiedOutcome(unittest.TestCase):
    def test_cleanly_closing_position_reports_verified_success_no_escalation(self):
        # One open EURUSD position, one pending GBPUSD order; the next
        # heartbeat after CLOSE_POS/CANCEL shows an empty book.
        sc = make_controller(
            open_positions=[{"t": 42, "s": "EURUSD"}],
            pending_orders=[{"t": 99, "s": "GBPUSD"}],
            heartbeat_batches=[[heartbeat(pos=[], orders=[])]],
        )
        run(sc.trigger_panic())

        self.assertEqual(sc.state, BotState.EMERGENCY)
        self.assertEqual(
            [a for a, _ in sc.bridge.commands], ["CLOSE_POS", "CANCEL"])
        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("Global Flatten Verified", joined)
        self.assertNotIn("UNVERIFIED", joined)

    def test_surviving_position_triggers_escalation_alert(self):
        # The EA silently rejects the close (e.g. market closed): two
        # successive heartbeats still show ticket 42 open.
        sc = make_controller(
            open_positions=[{"t": 42, "s": "EURUSD"}],
            pending_orders=[],
            heartbeat_batches=[
                [heartbeat(pos=[{"t": 42, "s": "EURUSD"}])],
                [heartbeat(pos=[{"t": 42, "s": "EURUSD"}])],
            ],
        )
        run(sc.trigger_panic())

        self.assertEqual(sc.state, BotState.EMERGENCY)
        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("#42", joined)
        self.assertNotIn("Global Flatten Verified", joined)

    def test_surviving_pending_order_triggers_escalation_alert(self):
        sc = make_controller(
            open_positions=[],
            pending_orders=[{"t": 99, "s": "GBPUSD"}],
            heartbeat_batches=[
                [heartbeat(orders=[{"t": 99, "s": "GBPUSD"}])],
                [heartbeat(orders=[{"t": 99, "s": "GBPUSD"}])],
            ],
        )
        run(sc.trigger_panic())

        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("#99", joined)


if __name__ == "__main__":
    unittest.main()
