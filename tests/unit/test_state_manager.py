import os, sys, tempfile, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.state_manager import StateManager  # noqa: E402


class StateManagerRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sm = StateManager(os.path.join(self.tmp.name, "state.db"))

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def test_register_with_full_trade_record(self):
        self.sm.register_order(1, "EURUSD", "SilverBullet", "LIMIT", status="PENDING",
                               entry=1.1000, tp=1.1200, sl=1.0950, lots=0.10, grade="A+")
        row = self.sm.get_order(1)
        self.assertEqual(row["status"], "PENDING")
        self.assertAlmostEqual(row["initial_entry"], 1.1000)
        self.assertAlmostEqual(row["initial_tp"], 1.1200)
        self.assertAlmostEqual(row["initial_sl"], 1.0950)
        self.assertAlmostEqual(row["lots"], 0.10)
        self.assertEqual(row["grade"], "A+")

    def test_backfill_fills_only_zero_fields_and_activates(self):
        self.sm.register_order(2, "EURUSD", "SilverBullet", "MARKET", status="ACTIVE",
                               entry=0.0, tp=0.0)
        self.sm.backfill_position_state(2, entry=1.2345, tp=1.2400)
        row = self.sm.get_order(2)
        self.assertAlmostEqual(row["initial_entry"], 1.2345)
        self.assertAlmostEqual(row["initial_tp"], 1.2400)
        self.assertEqual(row["status"], "ACTIVE")
        # A second backfill must NOT overwrite non-zero values
        self.sm.backfill_position_state(2, entry=9.9, tp=9.9)
        row = self.sm.get_order(2)
        self.assertAlmostEqual(row["initial_entry"], 1.2345)
        self.assertAlmostEqual(row["initial_tp"], 1.2400)

    def test_backfill_activates_pending_limit_fill(self):
        self.sm.register_order(3, "XAUUSD", "SilverBullet", "LIMIT", status="PENDING",
                               entry=2400.0, tp=2410.0, sl=2395.0)
        self.sm.backfill_position_state(3, entry=2400.1, tp=2410.0)
        row = self.sm.get_order(3)
        self.assertEqual(row["status"], "ACTIVE")
        self.assertAlmostEqual(row["initial_entry"], 2400.0)  # keeps intended entry

    def test_archive_copies_trade_record(self):
        self.sm.register_order(4, "EURUSD", "SilverBullet", "MARKET", status="ACTIVE",
                               entry=1.1, tp=1.12, sl=1.095, lots=0.2, grade="A++")
        self.sm.archive_trade(4, 55.0)
        self.assertFalse(self.sm.exists(4))
        row = self.sm.conn.execute("SELECT * FROM trade_history WHERE ticket_id=4").fetchone()
        self.assertAlmostEqual(row["pnl"], 55.0)
        self.assertAlmostEqual(row["entry"], 1.1)
        self.assertAlmostEqual(row["sl"], 1.095)
        self.assertAlmostEqual(row["tp"], 1.12)
        self.assertAlmostEqual(row["lots"], 0.2)
        self.assertEqual(row["grade"], "A++")

    def test_reboot_preserves_ratchet_level(self):
        self.sm.register_order(5, "EURUSD", "S", "MARKET", entry=1.1, tp=1.12)
        self.sm.update_ratchet_level(5, 2)
        # Re-registration (e.g. adoption after reboot) must keep the level
        self.sm.register_order(5, "EURUSD", "S", "MARKET", entry=1.1, tp=1.12)
        lvl, _, _ = self.sm.get_ratchet_state(5)
        self.assertEqual(lvl, 2)


class SchemaMigration(unittest.TestCase):
    def test_migrates_v14_schema(self):
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE active_orders (
            ticket_id INTEGER PRIMARY KEY, symbol TEXT, strategy TEXT, order_type TEXT,
            time_placed REAL, status TEXT, phase INTEGER DEFAULT 0)""")
        conn.execute("""CREATE TABLE trade_history (
            ticket_id INTEGER PRIMARY KEY, symbol TEXT, strategy TEXT,
            close_time REAL, pnl REAL, comment TEXT)""")
        conn.execute("INSERT INTO active_orders (ticket_id, symbol) VALUES (9, 'EURUSD')")
        conn.commit(); conn.close()

        sm = StateManager(path)
        sm.register_order(10, "EURUSD", "S", "MARKET", entry=1.1, tp=1.2, sl=1.05, lots=0.1, grade="B")
        sm.archive_trade(10, -12.0)
        row = sm.conn.execute("SELECT * FROM trade_history WHERE ticket_id=10").fetchone()
        self.assertEqual(row["grade"], "B")
        self.assertTrue(sm.exists(9))  # old row survived migration
        sm.close(); tmp.cleanup()


class RiskAnchorPersistence(unittest.TestCase):
    """RISK-01: the daily DD anchor must survive a process restart.

    day_start_equity was in-memory only, so every restart re-anchored the 3%
    circuit breaker to whatever equity the first post-boot heartbeat reported,
    discarding the day's realised drawdown.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state.db")
        self.sm = StateManager(self.path)

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def test_no_anchor_on_fresh_db(self):
        self.assertIsNone(self.sm.get_risk_anchor())

    def test_save_then_read_round_trip(self):
        self.sm.save_risk_anchor("2026-07-31", 1234.56)
        row = self.sm.get_risk_anchor()
        self.assertEqual(row["trading_day_key"], "2026-07-31")
        self.assertAlmostEqual(row["day_start_equity"], 1234.56)
        self.assertGreater(row["updated_at"], 0)

    def test_second_save_replaces_and_never_appends(self):
        self.sm.save_risk_anchor("2026-07-31", 1000.0)
        self.sm.save_risk_anchor("2026-08-01", 1100.0)
        n = self.sm.conn.execute("SELECT COUNT(*) FROM risk_state").fetchone()[0]
        self.assertEqual(n, 1)  # single-row table, not an append log
        row = self.sm.get_risk_anchor()
        self.assertEqual(row["trading_day_key"], "2026-08-01")
        self.assertAlmostEqual(row["day_start_equity"], 1100.0)

    def test_anchor_survives_reopening_the_database(self):
        """The actual restart scenario: new StateManager, same file."""
        self.sm.save_risk_anchor("2026-07-31", 987.65)
        self.sm.close()
        reopened = StateManager(self.path)
        try:
            row = reopened.get_risk_anchor()
            self.assertEqual(row["trading_day_key"], "2026-07-31")
            self.assertAlmostEqual(row["day_start_equity"], 987.65)
        finally:
            reopened.close()
            self.sm = StateManager(self.path)  # so tearDown's close() is valid

    def test_table_is_added_to_a_preexisting_database(self):
        """An existing trade_state.db must gain risk_state on next boot."""
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE active_orders (
            ticket_id INTEGER PRIMARY KEY, symbol TEXT, strategy TEXT, order_type TEXT,
            time_placed REAL, status TEXT, phase INTEGER DEFAULT 0)""")
        conn.commit(); conn.close()

        sm = StateManager(path)
        sm.save_risk_anchor("2026-07-31", 500.0)
        self.assertAlmostEqual(sm.get_risk_anchor()["day_start_equity"], 500.0)
        sm.close(); tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
