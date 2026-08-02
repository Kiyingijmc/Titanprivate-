"""Unit tests for the equity time-series recorder (spec 2026-07-31)."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.equity_recorder import Series, ensure_schema, series_for


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

    def test_does_not_write_user_version(self):
        """user_version is ONE counter per database and titan_core.db is shared
        with AuditLogger. Writing it here would clobber another owner's value to
        record something nothing reads — table_info/ALTER TABLE is the real
        migration path."""
        conn = _mem()
        before = conn.execute("PRAGMA user_version").fetchone()[0]
        ensure_schema(conn)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], before)

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
    # fine_cadence_s / coarse_bucket_s are deliberately absent: they are
    # structural constants (FINE_CADENCE_S / COARSE_BUCKET_S), not config.
    base = {"enabled": True, "fine_retention_h": 48,
            "flush_interval_s": 60, "max_buffer_samples": 600}
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


from src.ops.equity_recorder import bucket_of


class FlushAndRollup(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_bucket_of_floors_to_size(self):
        self.assertEqual(bucket_of(1_000_000.0, 300), 999_900)
        self.assertEqual(bucket_of(999_900.0, 300), 999_900)
        self.assertEqual(bucket_of(1_000_199.9, 300), 999_900)
        # The three above all land on the SAME bucket, so a bucket_of() that
        # ignored its argument entirely would pass them. This one crosses the
        # next edge.
        self.assertEqual(bucket_of(1_000_200.0, 300), 1_000_200)

    def test_flush_writes_fine_rows_and_clears_the_buffer(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        clock.tick(10)
        rec.record(100.0, 110.0)
        rec.flush()
        self.assertEqual(rec.buffer, [])
        rows = rec.conn.execute(
            "SELECT ts, equity, balance, peak FROM equity_fine ORDER BY ts").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], 100.0)
        self.assertEqual(rows[1][1], 110.0)
        self.assertEqual(rows[1][3], 110.0)

    def test_coarse_bucket_collapses_by_declared_agg(self):
        """last=final value, min/max=extremes, peak=running max — all in one bucket."""
        rec, clock = _recorder(self.tmp)
        for eq in (100.0, 130.0, 90.0, 120.0):
            rec.record(100.0, eq)
            clock.tick(10)
        rec.flush()
        row = rec.conn.execute(
            "SELECT bucket_ts, equity, balance, peak, equity_min, equity_max "
            "FROM equity_coarse").fetchall()
        self.assertEqual(len(row), 1)
        _, equity, balance, peak, emin, emax = row[0]
        self.assertEqual(equity, 120.0)      # last
        self.assertEqual(balance, 100.0)     # last
        self.assertEqual(peak, 130.0)        # max
        self.assertEqual(emin, 90.0)         # min
        self.assertEqual(emax, 130.0)        # max

    def test_second_flush_into_same_bucket_updates_without_zeroing(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        rec.flush()
        clock.tick(10)
        rec.record(100.0, 140.0)
        rec.flush()
        row = rec.conn.execute(
            "SELECT equity, peak, equity_min, equity_max FROM equity_coarse").fetchone()
        self.assertEqual(row, (140.0, 140.0, 100.0, 140.0))

    def test_samples_spanning_two_buckets_write_two_rows(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        clock.tick(310)                      # past the 300 s bucket edge
        rec.record(100.0, 200.0)
        rec.flush()
        rows = rec.conn.execute(
            "SELECT bucket_ts, equity FROM equity_coarse ORDER BY bucket_ts").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[1] for r in rows], [100.0, 200.0])

    def test_flush_error_rolls_back_the_partial_transaction(self):
        """The fine INSERT succeeds, the coarse one blows up. Without an explicit
        rollback the fine rows stay pending on the connection and the NEXT
        commit (prune's, say) persists them behind the retained buffer's back."""
        rec, _ = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        rec.conn.execute("DROP TABLE equity_coarse")
        rec.conn.commit()

        rec.flush()

        self.assertEqual(rec.counters["flush_errors"], 1)
        self.assertFalse(rec.conn.in_transaction)
        self.assertEqual(
            rec.conn.execute("SELECT COUNT(*) FROM equity_fine").fetchone()[0], 0)

    def test_flush_error_keeps_the_buffer_and_counts(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 100.0)
        rec.conn.close()                     # force a write failure
        rec.flush()
        self.assertEqual(rec.counters["flush_errors"], 1)
        self.assertEqual(len(rec.buffer), 1)   # retained for the next attempt

    def test_peak_is_reseeded_from_storage_on_restart(self):
        rec, clock = _recorder(self.tmp)
        rec.record(100.0, 175.0)
        rec.flush()
        db = rec.conn
        db.commit()
        rec2 = EquityRecorder(os.path.join(self.tmp, "core.db"),
                              config={"enabled": True}, clock=clock.time, monotonic=clock.time)
        self.assertEqual(rec2.peak, 175.0)

    def test_empty_flush_is_a_noop(self):
        rec, _ = _recorder(self.tmp)
        rec.flush()
        self.assertEqual(rec.counters["flush_errors"], 0)


class Prune(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_prune_deletes_only_rows_older_than_retention(self):
        rec, clock = _recorder(self.tmp, fine_retention_h=1)
        now = clock.now
        rec.conn.execute("INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)",
                         (now - 3601, 1, 1, 1))        # older than 1h -> deleted
        rec.conn.execute("INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)",
                         (now - 3600, 2, 2, 2))        # exactly 1h -> kept
        rec.conn.execute("INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)",
                         (now - 10, 3, 3, 3))          # recent -> kept
        rec.conn.commit()

        deleted = rec.prune()
        self.assertEqual(deleted, 1)
        kept = [r[0] for r in rec.conn.execute("SELECT equity FROM equity_fine ORDER BY ts")]
        self.assertEqual(kept, [2.0, 3.0])

    def test_prune_never_touches_the_coarse_tier(self):
        rec, clock = _recorder(self.tmp, fine_retention_h=1)
        rec.conn.execute(
            "INSERT INTO equity_coarse (bucket_ts, equity, balance, peak, equity_min, equity_max) "
            "VALUES (?,?,?,?,?,?)", (int(clock.now) - 999_999, 1, 1, 1, 1, 1))
        rec.conn.commit()
        rec.prune()
        self.assertEqual(rec.conn.execute("SELECT COUNT(*) FROM equity_coarse").fetchone()[0], 1)

    def test_prune_on_a_dead_connection_counts_and_does_not_raise(self):
        rec, _ = _recorder(self.tmp)
        rec.conn.close()
        self.assertEqual(rec.prune(), 0)
        self.assertEqual(rec.counters["flush_errors"], 1)


class MalformedConfigNeverKillsTheBot(unittest.TestCase):
    """A typo in the ops.equity block must cost the CHART, never the ENGINE.

    The recorder is built inside SystemController.__init__, so anything that
    escapes here is a bot that does not start — the same failure class as the
    S014 GUI-bind incident. Each of these makes dict.update() raise.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def _path(self):
        return os.path.join(self.tmp, "core.db")

    def test_bare_true_disables_instead_of_raising(self):
        rec = EquityRecorder(self._path(), config=True)      # `equity: true`
        self.assertFalse(rec.enabled)
        self.assertIsNone(rec.conn)

    def test_bare_string_disables_instead_of_raising(self):
        rec = EquityRecorder(self._path(), config="enabled")
        self.assertFalse(rec.enabled)
        self.assertIsNone(rec.conn)

    def test_list_disables_instead_of_raising(self):
        rec = EquityRecorder(self._path(), config=["enabled"])
        self.assertFalse(rec.enabled)
        self.assertIsNone(rec.conn)

    def test_a_disabled_recorder_is_still_fully_usable_as_an_object(self):
        """No attribute may be missing after the failed merge: the controller
        calls record()/prune() unconditionally on every heartbeat."""
        rec = EquityRecorder(self._path(), config=True)
        self.assertFalse(rec.record(100.0, 100.0))
        rec.flush()
        self.assertEqual(rec.prune(), 0)
        self.assertEqual(rec.buffer, [])

    def test_unwritable_db_path_disables_instead_of_raising(self):
        blocker = os.path.join(self.tmp, "not_a_dir")
        with open(blocker, "w") as fh:
            fh.write("")
        rec = EquityRecorder(os.path.join(blocker, "core.db"), config={"enabled": True})
        self.assertFalse(rec.enabled)
        self.assertIsNone(rec.conn)

    def test_none_config_uses_defaults_and_still_works(self):
        rec = EquityRecorder(self._path(), config=None)
        self.assertTrue(rec.enabled)
        self.assertIsNotNone(rec.conn)


class RecordNeverRaises(unittest.TestCase):
    """Spec §9 promises record() never raises into the trading loop. Without
    this test, deleting its whole try/except leaves the suite green."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_internal_error_is_counted_and_swallowed(self):
        class _Exploding(list):
            def append(self, item):
                raise RuntimeError("boom")

        rec, _ = _recorder(self.tmp)
        rec.buffer = _Exploding()
        try:
            accepted = rec.record(100.0, 100.0)
        except Exception as e:                       # pragma: no cover - the bug
            self.fail(f"record() raised into the caller: {e!r}")
        self.assertFalse(accepted)
        self.assertEqual(rec.counters["flush_errors"], 1)


class UtcDiscipline(unittest.TestCase):
    """Every other test injects a clock, which makes them timezone-BLIND: swapping
    time.time() for a local-time equivalent would shift every stored ts by the
    host's UTC offset and not one of them would notice (repo bug RISK-10). This
    one uses the REAL default clock."""

    def test_recorded_ts_is_utc_epoch_seconds_from_the_real_clock(self):
        import tempfile
        import time as _time
        rec = EquityRecorder(os.path.join(tempfile.mkdtemp(), "core.db"),
                             config={"enabled": True})
        before = _time.time()
        self.assertTrue(rec.record(100.0, 100.0))
        after = _time.time()
        ts = rec.buffer[0].ts
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)
        # A naive local-time datetime would be off by the UTC offset (up to 14h).
        self.assertLess(abs(ts - _time.time()), 5.0)


class EndToEndWriteThenRead(unittest.TestCase):
    """The only test that crosses the recorder/view seam.

    Everything else seeds SQL by hand on one side or the other, so bucket_of()
    and plan_query() could disagree arbitrarily and the suite would stay green.
    """

    def test_recorded_samples_read_back_bucket_aligned_with_last_values(self):
        import tempfile
        from src.ops.web.equity_view import equity_series

        clock = FakeClock(1_000_000.0)
        rec = EquityRecorder(os.path.join(tempfile.mkdtemp(), "core.db"),
                             config={"enabled": True},
                             clock=clock.time, monotonic=clock.time)
        for i in range(20):                 # 40s apart -> spans 3 coarse buckets
            self.assertTrue(rec.record(90.0 + i, 100.0 + i))
            clock.tick(40)
        rec.flush()
        self.assertEqual(rec.buffer, [])

        out = equity_series(rec.conn, "1d", now=clock.now)

        self.assertEqual(out["tier"], "coarse")
        self.assertEqual(out["bucket_s"], 300)
        self.assertNotIn(None, out["points"])
        self.assertEqual([p["ts"] for p in out["points"]],
                         [999_900, 1_000_200, 1_000_500])
        for p in out["points"]:
            self.assertEqual(p["ts"] % 300, 0)      # bucket-aligned
        # 'last' == the final sample in each bucket (i=4, i=12, i=19)
        self.assertEqual([p["equity"] for p in out["points"]], [104.0, 112.0, 119.0])
        self.assertEqual([p["balance"] for p in out["points"]], [94.0, 102.0, 109.0])
        self.assertEqual(out["coverage"]["n"], 3)
        self.assertEqual(out["coverage"]["first_sample_ts"], 999_900)


if __name__ == "__main__":
    unittest.main()
