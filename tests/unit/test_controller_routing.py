import asyncio
import os, sys, time, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.system_controller import SystemController  # noqa: E402


class FakeBridge:
    def __init__(self):
        self.commands = []       # (action, payload) via fire-and-forget PUSH
        self.reliable = []       # payloads via REQ/REP
    async def send_command(self, action, payload=None):
        self.commands.append((action, dict(payload or {})))
        return True
    async def send_order_reliable(self, payload, timeout=2500):
        self.reliable.append(dict(payload))
        return True


class FakeState:
    def __init__(self):
        self.registered = {}
        self.backfilled = []
        self.deleted = []
    def register_order(self, ticket, sym, strat, otype, status="PENDING", entry=0.0,
                       tp=0.0, sl=0.0, lots=0.0, grade=""):
        self.registered[ticket] = dict(sym=sym, strat=strat, otype=otype, status=status,
                                       entry=entry, tp=tp, sl=sl, lots=lots, grade=grade)
    def exists(self, t): return t in self.registered
    def backfill_position_state(self, t, entry=0.0, tp=0.0):
        self.backfilled.append((t, entry, tp))
    def get_pending_orders(self):
        return [{"ticket_id": 77, "strategy": "SilverBullet", "time_placed": time.time() - 9999}]
    def delete_order(self, t): self.deleted.append(t)
    def get_order(self, t): return None


class FakeLogger:
    def __init__(self): self.events = []
    def log_event(self, *a, **kw): self.events.append(a)


class FakeTelemetry:
    async def send_message(self, *a, **kw): pass
    async def notify_execution(self, *a, **kw): pass
    async def notify_management(self, *a, **kw): pass
    async def notify_partial(self, *a, **kw): pass


class FakeRisk:
    def update_account_info(self, b, e): pass
    def track_equity(self, e): pass
    def money_for_move(self, symbol, price_distance, lots): return 0.0


class FakeEquityRecorder:
    def __init__(self):
        self.recorded = []
    def record(self, balance, equity):
        self.recorded.append((balance, equity))


def make_controller():
    sc = object.__new__(SystemController)
    sc.bridge = FakeBridge()
    sc.state_manager = FakeState()
    sc.logger = FakeLogger()
    sc.telemetry = FakeTelemetry()
    sc.risk_manager = FakeRisk()
    sc.equity_recorder = FakeEquityRecorder()
    sc.pending_signal_meta = {}
    sc.current_open_positions = []
    sc.current_pending_orders = []
    sc.daily_closed_trades = []
    return sc


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class MgmtCommandRouting(unittest.TestCase):
    """Management commands are fire-and-forget on the PUSH socket; the REQ
    handshake is reserved for order entry (a slow SLTP ack wedged it live)."""

    def test_modify_routed_via_push(self):
        sc = make_controller()
        run(sc._dispatch_mgmt_command({"action": "MODIFY", "ticket": 5, "symbol": "EURUSD",
                                       "sl": 1.1003, "tp": 1.11, "comment": "Ratchet L1"}))
        self.assertEqual(sc.bridge.reliable, [])   # REQ untouched
        self.assertEqual(len(sc.bridge.commands), 1)
        action, p = sc.bridge.commands[0]
        self.assertEqual(action, "MODIFY")
        self.assertEqual(p["symbol"], "EURUSD")
        self.assertEqual(p["ticket"], 5)
        self.assertAlmostEqual(p["sl"], 1.1003)
        self.assertAlmostEqual(p["tp"], 1.11)

    def test_partial_routed_as_close_pos_with_volume(self):
        sc = make_controller()
        run(sc._dispatch_mgmt_command({"action": "CLOSE_PARTIAL", "ticket": 6, "volume": 0.03}))
        self.assertEqual(sc.bridge.commands, [("CLOSE_POS", {"ticket": 6, "volume": 0.03})])

    def test_close_pos_passthrough(self):
        sc = make_controller()
        run(sc._dispatch_mgmt_command({"action": "CLOSE_POS", "ticket": 7}))
        self.assertEqual(sc.bridge.commands[0][0], "CLOSE_POS")
        self.assertEqual(sc.bridge.commands[0][1]["ticket"], 7)


class ExecutionRegistration(unittest.TestCase):
    def test_opened_uses_pending_signal_meta(self):
        sc = make_controller()
        sc.pending_signal_meta["EURUSD"] = {'strat': 'SilverBullet', 'cmd': 'LIMIT',
                                            'entry': 1.1, 'sl': 1.095, 'tp': 1.12,
                                            'lots': 0.1, 'grade': 'A+'}
        run(sc._process_incoming_data({"type": "EXECUTION", "status": "OPENED",
                                       "ticket": 42, "s": "EURUSD", "cmd": "BUY",
                                       "strat": "SilverBullet"}))
        rec = sc.state_manager.registered[42]
        self.assertEqual(rec["status"], "PENDING")   # limit placements are pending
        self.assertAlmostEqual(rec["tp"], 1.12)      # real TP -> ratchet can engage
        self.assertAlmostEqual(rec["sl"], 1.095)
        self.assertEqual(rec["grade"], "A+")
        self.assertEqual(sc.pending_signal_meta, {})  # consumed

    def test_opened_market_registers_active(self):
        sc = make_controller()
        sc.pending_signal_meta["XAUUSD"] = {'strat': 'SB', 'cmd': 'MARKET', 'entry': 2400.0,
                                            'sl': 2395.0, 'tp': 2410.0, 'lots': 0.05, 'grade': 'A'}
        run(sc._process_incoming_data({"type": "EXECUTION", "status": "OPENED",
                                       "ticket": 43, "s": "XAUUSD", "cmd": "BUY", "strat": "SB"}))
        self.assertEqual(sc.state_manager.registered[43]["status"], "ACTIVE")

    def test_opened_with_zero_ticket_ignored(self):
        sc = make_controller()
        run(sc._process_incoming_data({"type": "EXECUTION", "status": "OPENED",
                                       "ticket": 0, "s": "EURUSD"}))
        self.assertEqual(sc.state_manager.registered, {})


class HeartbeatBackfill(unittest.TestCase):
    def test_known_ticket_backfilled_from_live_position(self):
        sc = make_controller()
        sc.state_manager.registered[42] = {"status": "PENDING"}
        hb = {"type": "HEARTBEAT", "bal": 1000.0, "eq": 1005.0,
              "pos": [{"t": 42, "s": "EURUSD", "p": 1.1001, "sl": 1.095, "tp": 1.12,
                       "pf": 1.0, "vol": 0.1, "type": 0}],
              "orders": []}
        run(sc._process_incoming_data(hb))
        self.assertEqual(sc.state_manager.backfilled, [(42, 1.1001, 1.12)])

    def test_unknown_ticket_adopted_with_sl_and_lots(self):
        sc = make_controller()
        hb = {"type": "HEARTBEAT", "bal": 1000.0, "eq": 1005.0,
              "pos": [{"t": 99, "s": "GBPUSD", "p": 1.30, "sl": 1.29, "tp": 1.32,
                       "pf": 0.0, "vol": 0.2, "type": 0}],
              "orders": []}
        run(sc._process_incoming_data(hb))
        rec = sc.state_manager.registered[99]
        self.assertEqual(rec["strat"], "Adopted")
        self.assertAlmostEqual(rec["sl"], 1.29)
        self.assertAlmostEqual(rec["lots"], 0.2)


class GhostCleanup(unittest.TestCase):
    def test_expired_pending_gets_proper_cancel(self):
        sc = make_controller()
        run(sc._cleanup_ghost_orders())
        self.assertEqual(sc.bridge.commands, [("CANCEL", {"ticket": 77})])
        self.assertEqual(sc.state_manager.deleted, [77])


if __name__ == "__main__":
    unittest.main()
