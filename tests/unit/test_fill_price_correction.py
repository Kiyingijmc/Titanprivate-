"""Trade-management math must key off the ACTUAL fill, not the intended entry.

Audit 2026-08-07 finding D3: `active_orders.initial_entry` was frozen at the
send-time intended price. The EA sends MARKET orders with `deviation=20`
(Titan_Gateway.mq5), so the broker can fill away from that price -- and every
downstream decision (the L1 break-even stop, all three ratchet pct thresholds,
the close-time R-multiple) keyed off the stale number. A slipped BUY whose
break-even stop is set at the *intended* entry sits BELOW the real fill: the
"risk-free" stop locks in a loss.

`backfill_position_state` only ever filled `initial_entry` WHEN it was zero, so
the non-zero value written at EXECUTION:OPENED was never corrected. The fix
overwrites it once, from the heartbeat's POSITION_PRICE_OPEN, for MARKET rows.
"""
import asyncio
import os
import sys
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.state_manager import StateManager        # noqa: E402
from src.core.system_controller import SystemController  # noqa: E402
from src.execution.trade_manager import TradeManager   # noqa: E402


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class FakeLogger:
    def __init__(self):
        self.events = []

    def log_event(self, *a, **kw):
        self.events.append(a)


class FakeTelemetry:
    def __init__(self):
        self.closes = []

    async def send_message(self, *a, **kw):
        pass

    async def notify_execution(self, *a, **kw):
        pass

    async def notify_close(self, ticket, pnl, symbol="?", strategy="?",
                           hold_seconds=None, r_multiple=None):
        self.closes.append({"ticket": ticket, "pnl": pnl, "r": r_multiple})


class FakeRisk:
    """Records money_for_move calls so a test can see WHICH entry price the
    R-multiple was measured from."""

    def __init__(self):
        self.move_calls = []

    def update_account_info(self, b, e):
        pass

    def track_equity(self, e):
        pass

    def money_for_move(self, symbol, price_distance, lots):
        self.move_calls.append((symbol, price_distance, lots))
        return price_distance * 100.0 * (lots or 1.0)

    def get_max_risk_amount(self):
        return 100.0

    def normalize_price(self, price, symbol):
        return round(float(price), 5)


class FakeEquityRecorder:
    def record(self, balance, equity):
        pass


def make_controller(state_manager):
    sc = object.__new__(SystemController)
    sc.state_manager = state_manager
    sc.logger = FakeLogger()
    sc.telemetry = FakeTelemetry()
    sc.risk_manager = FakeRisk()
    sc.equity_recorder = FakeEquityRecorder()
    sc.pending_signal_meta = {}
    sc.current_open_positions = []
    sc.current_pending_orders = []
    sc.daily_closed_trades = []
    sc._reserved_risk = {}
    return sc


def heartbeat(ticket, symbol, fill_price, sl, tp, vol=0.10):
    return {"type": "HEARTBEAT", "bal": 1000.0, "eq": 1000.0, "orders": [],
            "pos": [{"t": ticket, "s": symbol, "p": fill_price, "sl": sl,
                     "tp": tp, "pf": 0.0, "vol": vol, "type": 0}]}


class BackfillCorrectsMarketFill(unittest.TestCase):
    """state_manager level: the fill price replaces the intended entry, once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sm = StateManager(os.path.join(self.tmp.name, "state.db"))

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def test_market_entry_overwritten_by_heartbeat_fill_price(self):
        self.sm.register_order(1, "XAUUSD", "SilverBullet", "MARKET", status="ACTIVE",
                               entry=2400.00, tp=2410.00, sl=2395.00, lots=0.05)
        # Broker filled 1.50 above the intended price (deviation=20 points).
        self.sm.backfill_position_state(1, entry=2401.50, tp=2410.00)
        self.assertAlmostEqual(self.sm.get_order(1)["initial_entry"], 2401.50)

    def test_second_heartbeat_does_not_re_overwrite(self):
        self.sm.register_order(2, "XAUUSD", "SilverBullet", "MARKET", status="ACTIVE",
                               entry=2400.00, tp=2410.00, sl=2395.00, lots=0.05)
        self.sm.backfill_position_state(2, entry=2401.50, tp=2410.00)
        # A later heartbeat reporting a different price must be ignored: the
        # init price is a fixed reference, not a live field.
        self.sm.backfill_position_state(2, entry=2407.75, tp=2410.00)
        self.assertAlmostEqual(self.sm.get_order(2)["initial_entry"], 2401.50)

    def test_correction_survives_a_restart(self):
        """The once-only marker is persisted, not in-memory: a bot restart
        must not re-open the correction window and let a mid-trade heartbeat
        redefine the entry."""
        path = os.path.join(self.tmp.name, "restart.db")
        sm = StateManager(path)
        sm.register_order(3, "XAUUSD", "SB", "MARKET", status="ACTIVE",
                          entry=2400.0, tp=2410.0, sl=2395.0)
        sm.backfill_position_state(3, entry=2401.5, tp=2410.0)
        sm.close()

        reopened = StateManager(path)
        try:
            reopened.backfill_position_state(3, entry=2409.9, tp=2410.0)
            self.assertAlmostEqual(reopened.get_order(3)["initial_entry"], 2401.5)
        finally:
            reopened.close()

    def test_absent_fill_price_never_clobbers_the_intended_entry(self):
        """A heartbeat position missing `p` arrives as 0.0. Overwriting with
        zero would blank the entry and silently disable ALL management for the
        ticket (trade_manager skips rows with a zero entry)."""
        self.sm.register_order(4, "EURUSD", "SB", "MARKET", status="ACTIVE",
                               entry=1.1000, tp=1.1200, sl=1.0950)
        self.sm.backfill_position_state(4, entry=0.0, tp=1.1200)
        self.assertAlmostEqual(self.sm.get_order(4)["initial_entry"], 1.1000)
        # ...and the window is still open for the real fill price.
        self.sm.backfill_position_state(4, entry=1.1003, tp=1.1200)
        self.assertAlmostEqual(self.sm.get_order(4)["initial_entry"], 1.1003)

    def test_limit_and_stop_entries_keep_their_resting_price(self):
        """Out of scope by design: a LIMIT/STOP fills AT its resting price, so
        the heartbeat's open price carries no new information and the existing
        fill-if-zero semantics stand."""
        for ticket, otype in ((5, "LIMIT"), (6, "STOP")):
            self.sm.register_order(ticket, "XAUUSD", "SB", otype, status="PENDING",
                                   entry=2400.0, tp=2410.0, sl=2395.0)
            self.sm.backfill_position_state(ticket, entry=2400.9, tp=2410.0)
            row = self.sm.get_order(ticket)
            self.assertAlmostEqual(row["initial_entry"], 2400.0, msg=otype)
            self.assertEqual(row["status"], "ACTIVE", msg=otype)

    def test_initial_tp_backfill_stays_fill_if_zero(self):
        self.sm.register_order(7, "EURUSD", "SB", "MARKET", status="ACTIVE",
                               entry=0.0, tp=0.0)
        self.sm.backfill_position_state(7, entry=1.2345, tp=1.2400)
        self.sm.backfill_position_state(7, entry=1.2345, tp=9.9)
        self.assertAlmostEqual(self.sm.get_order(7)["initial_tp"], 1.2400)


class ControllerEndToEnd(unittest.TestCase):
    """OPENED at the intended price, HEARTBEAT at the real fill -> every
    consumer of initial_entry sees the fill."""

    P1 = 2400.00   # intended (what we sent)
    P2 = 2401.50   # actual fill (slipped 1.50 higher)
    SL = 2395.00
    TP = 2410.00

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sm = StateManager(os.path.join(self.tmp.name, "state.db"))
        self.sc = make_controller(self.sm)

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def _open_and_fill(self, fill_price=None):
        self.sc.pending_signal_meta["XAUUSD"] = {
            'strat': 'SilverBullet', 'cmd': 'MARKET', 'entry': self.P1,
            'sl': self.SL, 'tp': self.TP, 'lots': 0.05, 'grade': 'A'}
        run(self.sc._process_incoming_data(
            {"type": "EXECUTION", "status": "OPENED", "ticket": 50,
             "s": "XAUUSD", "cmd": "BUY", "strat": "SilverBullet"}))
        # Pre-heartbeat the DB holds the intended price -- that is the bug's
        # starting state, and it must be what changes.
        self.assertAlmostEqual(self.sm.get_order(50)["initial_entry"], self.P1)
        run(self.sc._process_incoming_data(
            heartbeat(50, "XAUUSD", fill_price or self.P2, self.SL, self.TP, vol=0.05)))

    def test_ratchet_state_reports_the_fill_price(self):
        self._open_and_fill()
        _lvl, init_entry, init_tp = self.sm.get_ratchet_state(50)
        self.assertAlmostEqual(init_entry, self.P2)
        self.assertAlmostEqual(init_tp, self.TP)

    def test_later_heartbeat_does_not_move_it_again(self):
        self._open_and_fill()
        run(self.sc._process_incoming_data(
            heartbeat(50, "XAUUSD", 2408.00, self.SL, self.TP, vol=0.05)))
        self.assertAlmostEqual(self.sm.get_ratchet_state(50)[1], self.P2)

    def test_break_even_stop_sits_above_the_real_fill(self):
        """The whole point: a BE stop placed at the INTENDED entry is 1.50
        below the real fill, i.e. still a losing stop."""
        self._open_and_fill()
        tm = TradeManager(FakeLogger(), self.sm, FakeRisk(), config={})
        # 0.382 of the 2401.50 -> 2410.00 range, comfortably past L1.
        curr = self.P2 + (self.TP - self.P2) * 0.5
        cmds = tm.sync_positions(
            [{"t": 50, "s": "XAUUSD", "p": self.P2, "sl": self.SL, "tp": self.TP,
              "pf": 5.0, "vol": 0.05, "type": 0}],
            {"XAUUSD": curr})
        l1 = next(c for c in cmds if c.get("comment") == "Ratchet L1")
        self.assertGreater(l1["sl"], self.P2)          # genuinely risk-free
        self.assertAlmostEqual(l1["sl"], self.P2 + 0.3, places=5)  # +3 pips

    def test_ratchet_thresholds_measure_from_the_fill(self):
        """A price that clears 0.382 of the INTENDED range but not of the
        (shorter) real range must not trigger L1."""
        self._open_and_fill()
        tm = TradeManager(FakeLogger(), self.sm, FakeRisk(), config={})
        # 0.382 of 2400.00->2410.00 is 2403.82; of 2401.50->2410.00 it is
        # 2404.75. This price sits between them.
        curr = 2404.00
        cmds = tm.sync_positions(
            [{"t": 50, "s": "XAUUSD", "p": self.P2, "sl": self.SL, "tp": self.TP,
              "pf": 5.0, "vol": 0.05, "type": 0}],
            {"XAUUSD": curr})
        self.assertEqual(cmds, [])

    def test_close_time_r_multiple_measures_from_the_fill(self):
        """system_controller's CLOSED handler reads the same initial_entry
        column, so it needs no change of its own -- proven here, not assumed."""
        self._open_and_fill()
        self.sc.risk_manager.move_calls.clear()
        run(self.sc._process_incoming_data(
            {"type": "EXECUTION", "status": "CLOSED", "ticket": 50,
             "s": "XAUUSD", "pn": 32.5}))
        _sym, distance, _lots = self.sc.risk_manager.move_calls[0]
        self.assertAlmostEqual(distance, abs(self.P2 - self.SL))
        self.assertNotAlmostEqual(distance, abs(self.P1 - self.SL))


class LegacyDatabaseMigration(unittest.TestCase):
    def test_marker_column_is_added_to_a_preexisting_database(self):
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE active_orders (
            ticket_id INTEGER PRIMARY KEY, symbol TEXT, strategy TEXT, order_type TEXT,
            time_placed REAL, status TEXT, phase INTEGER DEFAULT 0)""")
        conn.execute("INSERT INTO active_orders (ticket_id, symbol, order_type, status)"
                     " VALUES (8, 'XAUUSD', 'MARKET', 'ACTIVE')")
        conn.commit()
        conn.close()

        sm = StateManager(path)
        try:
            sm.backfill_position_state(8, entry=2401.5, tp=2410.0)
            self.assertAlmostEqual(sm.get_order(8)["initial_entry"], 2401.5)
            sm.backfill_position_state(8, entry=2405.0, tp=2410.0)
            self.assertAlmostEqual(sm.get_order(8)["initial_entry"], 2401.5)
        finally:
            sm.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
