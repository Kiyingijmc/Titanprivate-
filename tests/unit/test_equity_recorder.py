"""Unit tests for the equity time-series recorder (spec 2026-07-31)."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.equity_recorder import SCHEMA_VERSION, Series, ensure_schema, series_for


def _mem():
    return sqlite3.connect(":memory:")


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


class SchemaMigration(unittest.TestCase):
    def test_creates_both_tables_with_registry_columns(self):
        conn = _mem()
        ensure_schema(conn)
        self.assertEqual(_cols(conn, "equity_fine"), ["ts", "equity", "balance", "peak"])
        self.assertEqual(
            _cols(conn, "equity_coarse"),
            ["bucket_ts", "equity", "balance", "peak", "equity_min", "equity_max"],
        )

    def test_sets_user_version(self):
        conn = _mem()
        ensure_schema(conn)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_is_idempotent(self):
        conn = _mem()
        ensure_schema(conn)
        ensure_schema(conn)
        self.assertEqual(_cols(conn, "equity_fine"), ["ts", "equity", "balance", "peak"])

    def test_adds_a_newly_registered_series_to_existing_tables(self):
        """A series added to the registry later must ALTER in, and read NULL for old rows."""
        conn = _mem()
        ensure_schema(conn)
        conn.execute("INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (1.0, 10, 10, 10)")
        conn.commit()

        import src.ops.equity_recorder as mod
        original = mod.SERIES
        try:
            mod.SERIES = original + (Series("margin_level", "last", lambda s: 0.0),)
            ensure_schema(conn)
            self.assertIn("margin_level", _cols(conn, "equity_fine"))
            row = conn.execute("SELECT margin_level FROM equity_fine WHERE ts=1.0").fetchone()
            self.assertIsNone(row[0])
        finally:
            mod.SERIES = original

    def test_series_for_filters_by_tier(self):
        self.assertEqual([s.name for s in series_for("fine")], ["equity", "balance", "peak"])
        self.assertEqual(
            [s.name for s in series_for("coarse")],
            ["equity", "balance", "peak", "equity_min", "equity_max"],
        )


if __name__ == "__main__":
    unittest.main()
