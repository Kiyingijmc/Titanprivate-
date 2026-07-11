import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController


class _FakeBridge:
    async def send_command(self, *a, **k):
        pass


class _FakeTelemetry:
    def __init__(self):
        self.mgmt = []
        self.partials = []

    async def notify_management(self, comment, ticket, new_sl=None, locked_money=None):
        self.mgmt.append((comment, ticket, new_sl, locked_money))

    async def notify_partial(self, comment, ticket, volume):
        self.partials.append((comment, ticket, volume))


class _FakeRisk:
    def __init__(self, specs=True):
        self._specs = specs
        self.money_for_move_calls = []

    def has_specs(self, symbol):
        return self._specs

    def money_for_move(self, symbol, distance, lots):
        self.money_for_move_calls.append((symbol, distance, lots))
        return 100.0  # non-zero so locked-in is computable


class _FakeState:
    def get_order(self, ticket):
        # long trade: initial_sl < initial_entry
        return {"initial_entry": 2000.0, "initial_sl": 1990.0, "lots": 0.10}


def _controller(specs=True):
    c = SystemController.__new__(SystemController)   # bypass __init__/live sockets
    c.bridge = _FakeBridge()
    c.telemetry = _FakeTelemetry()
    c.risk_manager = _FakeRisk(specs=specs)
    c.state_manager = _FakeState()
    c.current_open_positions = [{"t": 9, "vol": 0.05}]

    class _L:
        def log_event(self, *a, **k):
            pass
    c.logger = _L()
    return c


class MgmtDispatchNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_ratchet_modify_notifies_with_sl_and_locked(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "MODIFY", "ticket": 9, "symbol": "XAUUSD", "sl": 2005.0, "tp": 2025.0, "comment": "Ratchet L2"})
        self.assertEqual(len(c.telemetry.mgmt), 1)
        comment, ticket, new_sl, locked = c.telemetry.mgmt[0]
        self.assertEqual((comment, ticket, new_sl), ("Ratchet L2", 9, 2005.0))
        self.assertGreater(locked, 0)   # sl 2005 > entry 2000 on a long -> profit locked

    async def test_ratchet_uses_remaining_volume_not_db_lots(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "MODIFY", "ticket": 9, "symbol": "XAUUSD", "sl": 2005.0, "tp": 2025.0, "comment": "Ratchet L1"})
        self.assertEqual(len(c.risk_manager.money_for_move_calls), 1)
        symbol, distance, lots = c.risk_manager.money_for_move_calls[0]
        self.assertEqual(lots, 0.05)   # live remaining vol from heartbeat, not DB lots=0.10

    async def test_ratchet_locked_none_when_specs_unknown(self):
        c = _controller(specs=False)
        await c._dispatch_mgmt_command({"action": "MODIFY", "ticket": 9, "symbol": "XAUUSD", "sl": 2005.0, "tp": 2025.0, "comment": "Ratchet L2"})
        self.assertEqual(len(c.telemetry.mgmt), 1)
        comment, ticket, new_sl, locked = c.telemetry.mgmt[0]
        self.assertIsNone(locked)

    async def test_runner_trail_suppressed(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "MODIFY", "ticket": 9, "symbol": "XAUUSD", "sl": 2005.0, "tp": 2025.0, "comment": "Runner Trail"})
        self.assertEqual(c.telemetry.mgmt, [])

    async def test_partial_notifies(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "CLOSE_PARTIAL", "ticket": 9, "volume": 0.03, "comment": "Bank 30%"})
        self.assertEqual(len(c.telemetry.partials), 1)
        self.assertEqual(c.telemetry.partials[0], ("Bank 30%", 9, 0.03))

    async def test_risk_guard_close_notifies(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "CLOSE_POS", "ticket": 9, "comment": "Risk Guard"})
        self.assertEqual(len(c.telemetry.mgmt), 1)
        self.assertEqual(c.telemetry.mgmt[0][0], "Risk Guard")

    async def test_plain_close_does_not_notify_mgmt(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "CLOSE_POS", "ticket": 9, "comment": "Dust Guard Exit"})
        self.assertEqual(c.telemetry.mgmt, [])
