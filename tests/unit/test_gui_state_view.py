# tests/unit/test_gui_state_view.py
import unittest
import sqlite3
from datetime import datetime, timedelta
from src.ops.web.state_view import build_snapshot, history_rows


class FakeRisk:
    current_equity = 10250.0
    starting_balance = 10000.0

    @staticmethod
    def throttle_factor():
        return 0.5


class FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 4, "approved": 3, "blocked_by": {"opposition": 1}}


class FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "silver_bullet", "version": "14.4.2", "family": "smc",
                 "tf": "H1", "status": "live", "state": "ACTIVE", "priority": 50}]


class FakeState:
    def __init__(self, rows):
        self._rows = rows

    def get_order(self, ticket):
        return self._rows.get(ticket)


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now() - timedelta(seconds=2)
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.arbiter = FakeArbiter()
        self.registry = FakeRegistry()
        self.config = {"risk": {"drawdown_throttle": {"enabled": True}}}
        self.current_open_positions = [
            {"t": 123, "s": "EURUSD", "p": 1.10, "sl": 1.095, "tp": 1.11,
             "pf": 12.5, "vol": 0.10, "type": 0, "comment": "SB"}]
        self.state_manager = FakeState({123: {"grade": "A+", "strategy": "silver_bullet"}})


class TestSnapshot(unittest.TestCase):
    def test_positions_mapped_with_journal_backfill(self):
        pos = build_snapshot(FakeController())["positions"][0]
        self.assertEqual(pos["ticket"], 123)
        self.assertEqual(pos["side"], "BUY")
        self.assertEqual(pos["grade"], "A+")
        self.assertEqual(pos["strategy"], "silver_bullet")

    def test_sell_side_and_missing_journal_row(self):
        c = FakeController()
        c.current_open_positions[0]["type"] = 1
        c.state_manager = FakeState({})
        pos = build_snapshot(c)["positions"][0]
        self.assertEqual(pos["side"], "SELL")
        self.assertEqual(pos["grade"], "")

    def test_health_account_arbiter_registry_blocks(self):
        snap = build_snapshot(FakeController())
        self.assertTrue(snap["health"]["bridge_connected"])
        self.assertEqual(snap["account"]["equity"], 10250.0)
        self.assertEqual(snap["arbiter"]["stats"]["approved"], 3)
        self.assertTrue(snap["arbiter"]["throttle"]["enabled"])
        self.assertEqual(snap["arbiter"]["throttle"]["current_mult"], 0.5)
        self.assertEqual(snap["registry"][0]["id"], "silver_bullet")
        self.assertEqual(snap["registry"][0]["state"], "ACTIVE")
        self.assertNotIn("family", snap["registry"][0])   # trimmed view

    def test_stale_heartbeat_marks_disconnected(self):
        c = FakeController()
        c.last_heartbeat_time = datetime.now() - timedelta(seconds=120)
        self.assertFalse(build_snapshot(c)["health"]["bridge_connected"])


class TestHistoryRows(unittest.TestCase):
    def test_reads_newest_first_with_limit(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE trade_history (ticket_id INT, symbol TEXT, pnl REAL)")
        for i in range(5):
            conn.execute("INSERT INTO trade_history VALUES (?, 'EURUSD', ?)", (i, i * 1.0))
        rows = history_rows(conn, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ticket_id"], 4)   # newest first


if __name__ == "__main__":
    unittest.main()
