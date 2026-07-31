"""Range derivation, downsampling, gap and coverage tests for /api/equity."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.equity_recorder import ensure_schema
from src.ops.web.equity_view import MAX_POINTS, RANGES, equity_series, plan_query, resolve_range


class RangeDerivation(unittest.TestCase):
    def test_all_eleven_ranges_exist(self):
        self.assertEqual(
            list(RANGES),
            ["15m", "30m", "1h", "4h", "12h", "1d", "1w", "1mo", "4mo", "6mo", "1y"])

    def test_derived_buckets_match_the_spec_table(self):
        expected = {
            "15m": ("fine", 10, 90), "30m": ("fine", 10, 180), "1h": ("fine", 20, 180),
            "4h": ("fine", 50, 288), "12h": ("fine", 150, 288),
            "1d": ("coarse", 300, 288), "1w": ("coarse", 2100, 288),
            "1mo": ("coarse", 8700, 298), "4mo": ("coarse", 34800, 298),
            "6mo": ("coarse", 51900, 300), "1y": ("coarse", 105300, 300),
        }
        for name, (tier, bucket, points) in expected.items():
            got_tier, _table, got_bucket, got_points = plan_query(name)
            self.assertEqual((got_tier, got_bucket), (tier, bucket), name)
            self.assertEqual(got_points, points, name)

    def test_no_range_exceeds_max_points(self):
        for name in RANGES:
            self.assertLessEqual(plan_query(name)[3], MAX_POINTS, name)

    def test_unknown_range_falls_back_to_1d(self):
        self.assertEqual(resolve_range("nonsense")[0], "1d")
        self.assertEqual(resolve_range(None)[0], "1d")


def _seeded(rows, table="equity_coarse"):
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    if table == "equity_coarse":
        conn.executemany(
            "INSERT INTO equity_coarse "
            "(bucket_ts, equity, balance, peak, equity_min, equity_max) VALUES (?,?,?,?,?,?)",
            rows)
    else:
        conn.executemany(
            "INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)", rows)
    conn.commit()
    return conn


class SeriesAssembly(unittest.TestCase):
    def test_returns_points_and_declared_series(self):
        now = 1_000_000.0
        rows = [(int(now) - i * 300, 100 + i, 90.0, 200.0, 99.0, 101.0) for i in range(5)]
        conn = _seeded(rows)
        out = equity_series(conn, "1d", now=now)
        self.assertEqual(out["range"], "1d")
        self.assertEqual(out["tier"], "coarse")
        self.assertEqual(out["bucket_s"], 300)
        self.assertEqual(out["series"], ["equity", "balance", "peak", "equity_min", "equity_max"])
        real = [p for p in out["points"] if p is not None]
        self.assertEqual(len(real), 5)

    def test_gap_wider_than_two_buckets_emits_null_and_is_reported(self):
        now = 1_000_000.0
        rows = [(int(now) - 3000, 100.0, 90.0, 100.0, 100.0, 100.0),
                (int(now) - 300, 110.0, 90.0, 110.0, 110.0, 110.0)]
        conn = _seeded(rows)
        out = equity_series(conn, "1d", now=now)
        self.assertIn(None, out["points"])
        self.assertEqual(len(out["coverage"]["gaps"]), 1)
        gap = out["coverage"]["gaps"][0]
        self.assertEqual(gap, [int(now) - 3000, int(now) - 300])

    def test_adjacent_buckets_are_not_a_gap(self):
        now = 1_000_000.0
        rows = [(int(now) - 600, 100.0, 90.0, 100.0, 100.0, 100.0),
                (int(now) - 300, 110.0, 90.0, 110.0, 110.0, 110.0)]
        conn = _seeded(rows)
        out = equity_series(conn, "1d", now=now)
        self.assertNotIn(None, out["points"])
        self.assertEqual(out["coverage"]["gaps"], [])

    def test_coverage_reports_first_sample_across_the_whole_table(self):
        """first_sample_ts must reflect stored history, not the queried window."""
        now = 1_000_000.0
        rows = [(int(now) - 900_000, 50.0, 50.0, 50.0, 50.0, 50.0),
                (int(now) - 300, 110.0, 90.0, 110.0, 110.0, 110.0)]
        conn = _seeded(rows)
        out = equity_series(conn, "1d", now=now)
        self.assertEqual(out["coverage"]["first_sample_ts"], int(now) - 900_000)

    def test_per_series_first_ts_ignores_nulls(self):
        now = 1_000_000.0
        conn = _seeded([(int(now) - 600, 100.0, 90.0, 100.0, 100.0, 100.0)])
        conn.execute("INSERT INTO equity_coarse (bucket_ts, equity) VALUES (?, ?)",
                     (int(now) - 900, 95.0))
        conn.commit()
        out = equity_series(conn, "1d", now=now)
        self.assertEqual(out["coverage"]["series_first_ts"]["equity"], int(now) - 900)
        self.assertEqual(out["coverage"]["series_first_ts"]["balance"], int(now) - 600)

    def test_empty_table_returns_empty_points_and_null_coverage(self):
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        out = equity_series(conn, "1d", now=1_000_000.0)
        self.assertEqual(out["points"], [])
        self.assertIsNone(out["coverage"]["first_sample_ts"])
        self.assertEqual(out["coverage"]["n"], 0)

    def test_last_aggregation_picks_the_later_sample_not_the_larger_value(self):
        """Two rows land in the SAME downsample bucket and equity falls across
        them. 'last' must return the value at the later timestamp (100), not
        the larger value (500) a bare SQL MAX() would return. This pins the
        exact correctness property the brief calls out: a regression that
        swapped the correlated subquery for MAX() would still pass every
        other test in this file, because they never put two rows in one
        bucket."""
        now = 1_000_000.0
        earlier_ts = int(now) - 250   # bucket index 3332 for bucket_s=300
        later_ts = int(now) - 200     # same bucket index 3332, later in time
        rows = [
            (earlier_ts, 500.0, 500.0, 500.0, 100.0, 500.0),
            (later_ts, 100.0, 100.0, 500.0, 100.0, 500.0),
        ]
        conn = _seeded(rows)
        out = equity_series(conn, "1d", now=now)
        self.assertEqual(len(out["points"]), 1)
        point = out["points"][0]
        self.assertEqual(point["equity"], 100.0)
        self.assertEqual(point["balance"], 100.0)

    def test_short_range_reads_the_fine_table(self):
        now = 1_000_000.0
        rows = [(now - i * 10, 100.0 + i, 90.0, 200.0) for i in range(4)]
        conn = _seeded(rows, table="equity_fine")
        out = equity_series(conn, "15m", now=now)
        self.assertEqual(out["tier"], "fine")
        self.assertEqual(len([p for p in out["points"] if p]), 4)
        self.assertEqual(out["series"], ["equity", "balance", "peak"])


if __name__ == "__main__":
    unittest.main()
