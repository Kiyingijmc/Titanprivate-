"""Range derivation, downsampling, gap and coverage tests for /api/equity."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.equity_recorder import COARSE_BUCKET_S, FINE_CADENCE_S, ensure_schema
from src.ops.web.equity_view import (MAX_POINTS, RANGES, build_series_sql, empty_series,
                                     equity_series, plan_query, resolve_range)


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
        """Asserted on the RESPONSE, not on plan_query's arithmetic.

        plan_query computes ceil(seconds/bucket), but the query window is a
        rolling `now - seconds` and is therefore not bucket-aligned, so a dense
        series straddles one extra PARTIAL bucket: 1y measured 301 points while
        this test, reading the planner, still said 300.
        """
        now = 1_700_000_000.0
        for name in RANGES:
            conn = _dense(name, now)
            points = equity_series(conn, name, now=now)["points"]
            self.assertLessEqual(len(points), MAX_POINTS, name)
            self.assertNotIn(None, points, name)      # dense: no gap markers
            self.assertGreater(len(points), 0, name)

    def test_one_year_of_dense_rows_is_clamped_to_exactly_max_points(self):
        """The unaligned window touches 301 bucket indices here; the response
        must still be 300. This is the case that measured 301 before."""
        now = 1_700_000_000.0
        out = equity_series(_dense("1y", now), "1y", now=now)
        self.assertEqual(len(out["points"]), MAX_POINTS)
        self.assertEqual(out["coverage"]["n"], MAX_POINTS)

    def test_unknown_range_falls_back_to_1d(self):
        self.assertEqual(resolve_range("nonsense")[0], "1d")
        self.assertEqual(resolve_range(None)[0], "1d")


def _empty_conn():
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    return conn


def _dense(range_name, now):
    """A gap-free series covering one range's whole window at the STORAGE
    cadence (10s fine / 300s coarse) — i.e. exactly what the live DB holds."""
    tier, _table, _bucket_s, _ = plan_query(range_name)
    _key, seconds = resolve_range(range_name)
    step = FINE_CADENCE_S if tier == "fine" else COARSE_BUCKET_S
    conn = _empty_conn()
    keys = []
    ts = now - seconds
    if tier == "coarse":                    # stored bucket_ts is always aligned
        ts = (int(ts) // COARSE_BUCKET_S) * COARSE_BUCKET_S
    while ts <= now:
        keys.append(ts)
        ts += step
    if tier == "fine":
        conn.executemany(
            "INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)",
            [(float(k), 100.0, 90.0, 100.0) for k in keys])
    else:
        conn.executemany(
            "INSERT INTO equity_coarse "
            "(bucket_ts, equity, balance, peak, equity_min, equity_max) VALUES (?,?,?,?,?,?)",
            [(int(k), 100.0, 90.0, 100.0, 99.0, 101.0) for k in keys])
    conn.commit()
    return conn


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

    def test_gap_threshold_is_two_bucket_widths(self):
        """Spec §7: a gap is consecutive samples more than 2 x bucket_s apart.
        Just over the threshold -> gap; exactly on it -> not a gap."""
        now = 1_000_000.0
        over = _seeded([(int(now) - 1200, 100.0, 90.0, 100.0, 100.0, 100.0),
                        (int(now) - 300, 110.0, 90.0, 110.0, 110.0, 110.0)])
        out = equity_series(over, "1d", now=now)          # 900s apart, bucket 300
        self.assertEqual(len(out["coverage"]["gaps"]), 1)
        self.assertEqual(out["coverage"]["gaps"][0], [int(now) - 1200, int(now) - 300])

        on = _seeded([(int(now) - 900, 100.0, 90.0, 100.0, 100.0, 100.0),
                      (int(now) - 300, 110.0, 90.0, 110.0, 110.0, 110.0)])
        self.assertEqual(equity_series(on, "1d", now=now)["coverage"]["gaps"], [])

    def test_gap_is_measured_in_TIME_not_in_bucket_indices(self):
        """The case that separates the two rules.

        Coarse rows are bucket-ALIGNED, so their time delta is always a whole
        multiple of bucket_s and (ts - prev) > 2*bucket_s and (b - prev_b) > 2
        agree on every one of them — the earlier threshold test above passes
        under BOTH rules and cannot see this bug. Fine rows are not aligned to
        the query bucket: 21s apart at bucket_s=10 is a gap by the spec's clock
        (21 > 20) but only TWO bucket indices apart, which the old index rule
        reported as contiguous. Two samples 6 minutes apart in a 15m window are
        exactly the outage shape this endpoint exists to show.
        """
        now = 1_000_000.0
        base = int(now) - 400                             # aligned to bucket 10
        conn = _seeded([(float(base), 100.0, 90.0, 100.0),
                        (float(base + 21), 110.0, 90.0, 110.0)],
                       table="equity_fine")
        out = equity_series(conn, "15m", now=now)
        self.assertEqual(out["bucket_s"], 10)
        # index rule: 40 -> 42, a difference of 2, i.e. "not a gap"
        self.assertEqual((base + 21) // 10 - base // 10, 2)
        self.assertEqual(len(out["coverage"]["gaps"]), 1)
        self.assertEqual(out["coverage"]["gaps"][0], [base, base + 21])
        self.assertIn(None, out["points"])

    def test_real_outage_shape_is_reported_as_one_gap(self):
        """The 2026-07-29 demo outage: ~9h of no samples inside a 1d window."""
        now = 1_000_000.0
        rows = [(int(now) - 86_400 + i * 300, 100.0, 90.0, 100.0, 99.0, 101.0)
                for i in range(60)]                       # 5h of data, then...
        rows += [(int(now) - 86_400 + 60 * 300 + 32_400 + i * 300,
                  110.0, 90.0, 110.0, 109.0, 111.0) for i in range(60)]   # ...9h later
        out = equity_series(_seeded(rows), "1d", now=now)
        self.assertEqual(len(out["coverage"]["gaps"]), 1)
        gap = out["coverage"]["gaps"][0]
        self.assertGreaterEqual(gap[1] - gap[0], 32_400)
        self.assertEqual(out["points"].count(None), 1)

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


class CoverageIsTierIndependent(unittest.TestCase):
    """first_sample_ts must describe STORED HISTORY, not the tier this query
    happened to hit. equity_fine is pruned at 48h, so reading MIN(ts) from it
    made range=15m report "history starts 48h ago" while range=1d reported a
    year — and the phase-2 selector would enable different ranges depending on
    which range you were already looking at."""

    def setUp(self):
        self.now = 1_000_000.0
        self.old = int(self.now) - 300 * 86_400        # ~10 months of coarse
        self.conn = _empty_conn()
        self.conn.executemany(
            "INSERT INTO equity_coarse "
            "(bucket_ts, equity, balance, peak, equity_min, equity_max) VALUES (?,?,?,?,?,?)",
            [(self.old, 50.0, 50.0, 50.0, 50.0, 50.0),
             (int(self.now) - 300, 110.0, 90.0, 110.0, 110.0, 110.0)])
        # fine holds ONLY the recent rows -- exactly what the 48h prune leaves
        self.conn.executemany(
            "INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)",
            [(self.now - i * 10, 100.0 + i, 90.0, 200.0) for i in range(4)])
        self.conn.commit()

    def test_fine_range_reports_the_coarse_tiers_first_sample(self):
        out = equity_series(self.conn, "15m", now=self.now)
        self.assertEqual(out["tier"], "fine")
        self.assertGreater(len([p for p in out["points"] if p]), 0)
        self.assertEqual(out["coverage"]["first_sample_ts"], self.old)

    def test_coarse_and_fine_ranges_agree_on_first_sample(self):
        fine = equity_series(self.conn, "15m", now=self.now)
        coarse = equity_series(self.conn, "1d", now=self.now)
        self.assertEqual(fine["coverage"]["first_sample_ts"],
                         coarse["coverage"]["first_sample_ts"])
        self.assertEqual(fine["coverage"]["series_first_ts"]["equity"],
                         coarse["coverage"]["series_first_ts"]["equity"])


class QueryShape(unittest.TestCase):
    """C1: the 'last' aggregation must be one pass over the WINDOW, not a
    correlated subquery re-scanning the whole table per bucket (measured 3.7s at
    48h of fine rows, 66s at a year of coarse). Asserted on the query PLAN, never
    on wall-clock — this box is shared and a timing assertion is a coin flip."""

    def test_sqlite_supports_window_functions(self):
        major, minor = (int(x) for x in sqlite3.sqlite_version.split(".")[:2])
        self.assertGreaterEqual((major, minor), (3, 25), sqlite3.sqlite_version)

    def _plan(self, range_name):
        tier, table, bucket_s, _ = plan_query(range_name)
        sql = build_series_sql(tier, table, bucket_s)
        conn = _empty_conn()
        return [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, (0, 1))], sql

    def test_plan_has_no_correlated_subquery(self):
        for name in ("15m", "1d", "1y"):
            plan, _ = self._plan(name)
            joined = " | ".join(plan)
            self.assertNotIn("CORRELATED", joined.upper(), f"{name}: {joined}")

    def test_plan_scans_the_source_table_once(self):
        """One pass. The old form showed 'SCAN i' inside a per-row subquery on
        top of the outer scan."""
        for name in ("15m", "1d", "1y"):
            plan, _ = self._plan(name)
            table = plan_query(name)[1]
            touches = [ln for ln in plan
                       if ln.startswith(("SCAN", "SEARCH")) and table in ln]
            self.assertEqual(len(touches), 1, f"{name}: {plan}")

    def test_window_bound_is_in_the_main_from(self):
        """The old query's correlated subquery had no window predicate at all,
        so it read rows outside the requested range."""
        _plan, sql = self._plan("1y")
        self.assertIn("BETWEEN ? AND ?", sql)
        self.assertEqual(sql.count("?"), 2)

    def test_thousands_of_rows_downsample_correctly_in_one_pass(self):
        now = 1_700_000_000.0
        conn = _empty_conn()
        # 4000 fine rows across a 12h window; equity FALLS inside every bucket so
        # a bare MAX() would be visibly wrong.
        rows = [(now - (4000 - i) * 10, 1000.0 - (i % 15), 90.0, 2000.0)
                for i in range(4000)]
        conn.executemany(
            "INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)", rows)
        conn.commit()

        out = equity_series(conn, "12h", now=now)
        self.assertEqual(out["tier"], "fine")
        self.assertEqual(out["bucket_s"], 150)
        real = [p for p in out["points"] if p is not None]
        self.assertLessEqual(len(real), MAX_POINTS)
        self.assertGreater(len(real), 250)

        # Independently recompute 'last' for one bucket straight from the rows.
        probe = real[len(real) // 2]
        b = probe["ts"] // 150
        in_bucket = sorted((ts, eq) for ts, eq, _b, _p in rows if int(ts) // 150 == b)
        self.assertEqual(probe["equity"], in_bucket[-1][1])
        self.assertEqual(probe["peak"], max(p for _ts, _e, _b, p in rows
                                            if int(_ts) // 150 == b))


class DisabledRecorderBody(unittest.TestCase):
    """M3: the no-recorder body must be the SAME contract as the live one —
    resolved range, real tier/bucket_s, same field types."""

    def test_empty_series_resolves_the_range_and_keeps_field_types(self):
        body = empty_series("nope")
        live = equity_series(_empty_conn(), "nope", now=1_000_000.0)
        self.assertEqual(body["range"], "1d")
        self.assertEqual(body["tier"], live["tier"])
        self.assertEqual(body["bucket_s"], live["bucket_s"])
        self.assertEqual(body["series"], live["series"])
        self.assertEqual(set(body["coverage"]), set(live["coverage"]))
        self.assertIsInstance(body["bucket_s"], int)

    def test_empty_series_honours_a_fine_range(self):
        body = empty_series("15m")
        self.assertEqual(body["range"], "15m")
        self.assertEqual(body["tier"], "fine")
        self.assertEqual(body["bucket_s"], 10)


if __name__ == "__main__":
    unittest.main()
