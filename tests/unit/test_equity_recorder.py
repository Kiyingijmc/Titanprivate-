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


from src.ops.equity_recorder import EquityRecorder


class FakeClock:
    """Injected wall + monotonic clock so cadence tests are deterministic."""
    def __init__(self, start=1_000_000.0):
        self.now = start

    def time(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def _recorder(tmpdir, clock=None, **cfg):
    clock = clock or FakeClock()
    base = {"enabled": True, "fine_cadence_s": 10, "fine_retention_h": 48,
            "coarse_bucket_s": 300, "flush_interval_s": 60, "max_buffer_samples": 600}
    base.update(cfg)
    rec = EquityRecorder(os.path.join(tmpdir, "core.db"), config=base,
                         clock=clock.time, monotonic=clock.time)
    return rec, clock


class RecordCadenceAndValidation(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_first_sample_is_accepted(self):
        rec, _ = _recorder(self.tmp)
        self.assertTrue(rec.record(100.0, 100.0))
        self.assertEqual(len(rec.buffer), 1)

    def test_samples_inside_the_cadence_window_are_skipped_not_dropped(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        clock.tick(3)
        self.assertFalse(rec.record(100.0, 101.0))
        self.assertEqual(len(rec.buffer), 1)
        self.assertEqual(sum(rec.counters.values()), 0)

    def test_sample_after_the_cadence_window_is_accepted(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        clock.tick(10)
        self.assertTrue(rec.record(100.0, 101.0))
        self.assertEqual(len(rec.buffer), 2)

    def test_non_finite_equity_is_rejected_and_counted(self):
        rec, clock = _recorder(self.tmp)
        clock.tick(10)
        self.assertFalse(rec.record(100.0, float("nan")))
        self.assertEqual(rec.counters["dropped_invalid"], 1)
        self.assertEqual(rec.buffer, [])

    def test_non_positive_balance_is_rejected_and_counted(self):
        rec, clock = _recorder(self.tmp)
        clock.tick(10)
        self.assertFalse(rec.record(0.0, 100.0))
        self.assertEqual(rec.counters["dropped_invalid"], 1)

    def test_backwards_clock_is_rejected_and_counted(self):
        """NTP step or replay: ts <= last_ts must never be written."""
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        clock.tick(20)
        rec.record(100.0, 101.0)
        clock.now -= 15          # clock steps backwards, past the cadence gate
        self.assertFalse(rec.record(100.0, 102.0))
        self.assertEqual(rec.counters["dropped_stale"], 1)
        self.assertEqual(len(rec.buffer), 2)

    def test_peak_is_monotonic(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        clock.tick(10)
        rec.record(100.0, 120.0)
        clock.tick(10)
        rec.record(100.0, 90.0)
        self.assertEqual(rec.peak, 120.0)
        self.assertEqual([s.peak for s in rec.buffer], [100.0, 120.0, 120.0])

    def test_buffer_overflow_drops_oldest_and_counts(self):
        rec, clock = _recorder(self.tmp, max_buffer_samples=3, flush_interval_s=10_000)
        for i in range(5):
            rec.record(100.0, 100.0 + i)
            clock.tick(10)
        self.assertEqual(len(rec.buffer), 3)
        self.assertEqual(rec.counters["dropped_overflow"], 2)
        self.assertEqual([s.equity for s in rec.buffer], [102.0, 103.0, 104.0])

    def test_disabled_recorder_accepts_nothing(self):
        rec, clock = _recorder(self.tmp, enabled=False)
        self.assertFalse(rec.record(100.0, 100.0))
        self.assertEqual(rec.buffer, [])
        self.assertEqual(sum(rec.counters.values()), 0)


if __name__ == "__main__":
    unittest.main()
