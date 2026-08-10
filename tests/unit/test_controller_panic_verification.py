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


class StarvedBridge(FakeBridge):
    """Never yields anything to *this* caller -- stands in for the real race:
    `run()` polls the same unlocked ZMQ PULL socket every ~1ms and drains the
    HEARTBEAT first whenever the panic is triggered from the web/GUI Task
    (`src/ops/web/server.py` serves on its own asyncio Task)."""
    def __init__(self):
        super().__init__([])
        self.polls = 0

    async def poll_data(self):
        self.polls += 1
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


class PanicVerifiesTheObservedBookNotThePrePanicSnapshot(unittest.TestCase):
    """RS026 CRITICAL-1. The pre-panic book can UNDERSTATE what the broker
    holds (EA reconnect gap, a fill between the last processed heartbeat and
    the command). Such a ticket is never even sent a CLOSE_POS, because
    close_all_market_orders iterates that same stale list -- so verifying
    against the pre-panic snapshot reports success on a fully open, untouched
    position. Verification must read what the fresh HEARTBEAT actually shows.
    """

    def test_position_unknown_at_panic_time_still_escalates(self):
        # Stale book: Titan knows of nothing open, the broker holds #77.
        sc = make_controller(
            open_positions=[],
            pending_orders=[],
            heartbeat_batches=[
                [heartbeat(pos=[{"t": 77, "s": "GBPJPY"}])],
                [heartbeat(pos=[{"t": 77, "s": "GBPJPY"}])],
            ],
        )
        run(sc.trigger_panic())

        # Documents the other half of the defect: nothing was even attempted.
        self.assertEqual(sc.bridge.commands, [])
        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("#77", joined)
        self.assertNotIn("Global Flatten Verified", joined)

    def test_pending_order_unknown_at_panic_time_still_escalates(self):
        sc = make_controller(
            open_positions=[],
            pending_orders=[],
            heartbeat_batches=[
                [heartbeat(orders=[{"t": 88, "s": "XAUUSD"}])],
                [heartbeat(orders=[{"t": 88, "s": "XAUUSD"}])],
            ],
        )
        run(sc.trigger_panic())

        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("#88", joined)
        self.assertNotIn("Global Flatten Verified", joined)

    def test_no_heartbeat_at_all_is_unverified_not_success(self):
        # Empty pre-panic book + a dead/silent EA: there is no evidence either
        # way, and "no news" must never render as a clean flatten.
        sc = make_controller(open_positions=[], pending_orders=[], heartbeat_batches=[])
        sc.PANIC_VERIFY_TIMEOUT_S = 0.6
        run(sc.trigger_panic())

        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("no fresh heartbeat", joined)
        self.assertNotIn("Global Flatten Verified", joined)


class PanicVerificationSurvivesAConcurrentPoller(unittest.TestCase):
    """RS026 MAJOR-1. A GUI/web panic runs on its own asyncio Task while
    `run()` polls the bridge every ~1ms, so the main loop wins the race for
    the HEARTBEAT nearly every time. Freshness therefore has to be read from
    the book stamp that whoever processed the message writes -- keying off
    this coroutine's own poll batch starves the verifier and cries "book still
    exposed" on a panic that actually worked.
    """

    def _run_with_competing_loop(self, sc, heartbeats):
        async def scenario():
            async def competing_main_loop():
                # Stands in for run()'s ingestion: it drains the socket and
                # processes the HEARTBEAT itself, on a different Task.
                for hb in heartbeats:
                    # Paced longer than the verifier's own 0.25s poll interval
                    # so each heartbeat lands as a distinct observation.
                    await asyncio.sleep(0.3)
                    await sc._process_incoming_data(hb)

            await asyncio.gather(sc.trigger_panic(), competing_main_loop())

        run(scenario())

    def test_flatten_verified_even_though_main_loop_drained_the_heartbeat(self):
        sc = make_controller(
            open_positions=[{"t": 42, "s": "EURUSD"}],
            pending_orders=[{"t": 99, "s": "GBPUSD"}],
            heartbeat_batches=[],
        )
        sc.bridge = StarvedBridge()
        sc.PANIC_VERIFY_TIMEOUT_S = 2.0

        self._run_with_competing_loop(sc, [heartbeat(pos=[], orders=[])])

        self.assertGreater(sc.bridge.polls, 0)      # it really was starved
        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("Global Flatten Verified", joined)
        self.assertNotIn("UNVERIFIED", joined)

    def test_survivor_still_escalates_when_main_loop_drained_the_heartbeat(self):
        sc = make_controller(
            open_positions=[{"t": 42, "s": "EURUSD"}],
            pending_orders=[],
            heartbeat_batches=[],
        )
        sc.bridge = StarvedBridge()
        sc.PANIC_VERIFY_TIMEOUT_S = 2.0

        self._run_with_competing_loop(
            sc,
            [heartbeat(pos=[{"t": 42, "s": "EURUSD"}]),
             heartbeat(pos=[{"t": 42, "s": "EURUSD"}])],
        )

        joined = "\n".join(sc.telemetry.messages)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("#42", joined)


if __name__ == "__main__":
    unittest.main()
