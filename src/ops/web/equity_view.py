"""Read-only assembly of the /api/equity response (spec 2026-07-31 §3, §7).

Tier and bucket size are DERIVED from the requested range, never tabulated, so
changing a cadence or MAX_POINTS cannot leave a stale hand-computed number behind.

This module NEVER writes, and never reads through the recorder's own connection:
see read_connection() — a slow read on the writer's connection serialises against
the asyncio trading loop's flush()/prune().
"""
from __future__ import annotations

import math
import sqlite3
import time

from src.ops.equity_recorder import (
    COARSE_BUCKET_S,
    COARSE_TABLE,
    FINE_CADENCE_S,
    FINE_TABLE,
    series_for,
)

MAX_POINTS = 300
# FINE_CADENCE_S / COARSE_BUCKET_S are STRUCTURAL constants owned by the recorder
# (they are baked into every stored row). Imported, never copied and never
# re-derived from config -- see the comment on their definition.
FINE_MAX_RANGE_S = 43_200          # 12h — above this we read the coarse tier
DEFAULT_RANGE = "1d"

RANGES: dict[str, int] = {
    "15m": 900, "30m": 1_800, "1h": 3_600, "4h": 14_400, "12h": 43_200,
    "1d": 86_400, "1w": 604_800, "1mo": 2_592_000, "4mo": 10_368_000,
    "6mo": 15_552_000, "1y": 31_536_000,
}

_AGG_FN = {"max": "MAX", "min": "MIN", "sum": "SUM"}


def resolve_range(name) -> tuple[str, int]:
    """Map a caller-supplied range to (name, seconds); unknown -> the default."""
    key = name if name in RANGES else DEFAULT_RANGE
    return key, RANGES[key]


def plan_query(name) -> tuple[str, str, int, int]:
    """(tier, table, bucket_seconds, expected_points) for a range."""
    key, seconds = resolve_range(name)
    if seconds <= FINE_MAX_RANGE_S:
        tier, table, cadence = "fine", FINE_TABLE, FINE_CADENCE_S
    else:
        tier, table, cadence = "coarse", COARSE_TABLE, COARSE_BUCKET_S
    # smallest whole multiple of cadence with seconds/bucket <= MAX_POINTS
    steps = math.ceil(seconds / MAX_POINTS / cadence)
    bucket = max(cadence, steps * cadence)
    return tier, table, bucket, math.ceil(seconds / bucket)


def key_column(tier: str) -> str:
    return "ts" if tier == "fine" else "bucket_ts"


def build_series_sql(tier: str, table: str, bucket_s: int) -> str:
    """One-pass downsample SQL for a tier.

    The 'last' aggregation used to be a correlated subquery keyed on
    CAST(i.key/bucket)=CAST(outer.key/bucket). That predicate is non-sargable, so
    SQLite re-scanned the WHOLE table once per bucket per 'last' series and was
    not even restricted to the query window: 3.7s at 48h of fine rows, 66s at a
    year of coarse rows — on the recorder's own connection, i.e. stalling the
    trading loop past the 60s watchdog.

    ROW_NUMBER() OVER (PARTITION BY <bucket> ORDER BY <key> DESC) gives the same
    "value at the greatest key in the bucket" in a single pass (SQLite >= 3.25).
    The leading CASE in the ORDER BY preserves the old subquery's `IS NOT NULL`
    filter: the latest NON-NULL value wins, and the result is NULL only when the
    whole bucket is NULL for that series.

    Bound parameters are (window_start, window_end) — the window bound lives in
    the main FROM, so the scan is the window, not the table.
    """
    key_col = key_column(tier)
    cols = series_for(tier)
    bexpr = f"CAST({key_col} / {bucket_s} AS INTEGER)"

    inner = [f"{key_col} AS k", f"{bexpr} AS b"]
    inner += [s.name for s in cols]
    outer = ["b", "MAX(k) AS raw_ts"]
    for s in cols:
        if s.agg == "last":
            inner.append(
                f"ROW_NUMBER() OVER (PARTITION BY {bexpr} ORDER BY "
                f"CASE WHEN {s.name} IS NULL THEN 1 ELSE 0 END, {key_col} DESC)"
                f" AS rn_{s.name}")
            outer.append(f"MAX(CASE WHEN rn_{s.name} = 1 THEN {s.name} END) AS {s.name}")
        else:
            outer.append(f"{_AGG_FN[s.agg]}({s.name}) AS {s.name}")

    return (f"WITH w AS (SELECT {', '.join(inner)} FROM {table} "
            f"WHERE {key_col} BETWEEN ? AND ?) "
            f"SELECT {', '.join(outer)} FROM w GROUP BY b ORDER BY b")


def read_connection(rec) -> tuple[sqlite3.Connection | None, bool]:
    """(connection, caller_must_close) for one /api/equity request.

    NEVER hand back the recorder's write connection for a file-backed recorder:
    SQLite serialises statements per connection, so a read there queues behind —
    and stalls — the asyncio trading loop's flush()/prune(). A short-lived
    read-only connection to the same file has its own lock and its own cost.

    Returns (None, False) when the recorder is absent or disabled, which is the
    caller's signal to serve the empty-series body.
    """
    if rec is None or getattr(rec, "enabled", True) is False:
        return None, False
    path = getattr(rec, "db_path", None)
    if path and path != ":memory:":
        try:
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True), True
        except sqlite3.Error:
            try:
                return sqlite3.connect(path), True
            except sqlite3.Error:
                pass
    # In-memory recorders (devserver fake, unit fixtures) have no reopenable
    # path and no trading loop behind them; share their connection.
    conn = getattr(rec, "conn", None)
    return (conn, False) if conn is not None else (None, False)


def empty_series(range_name) -> dict:
    """The body served when there is no recorder to read.

    Same field TYPES and the same resolved range as the live path — a client
    must not have to special-case 'recorder disabled' to read tier/bucket_s.
    """
    key, _seconds = resolve_range(range_name)
    tier, _table, bucket_s, _points = plan_query(key)
    return {
        "range": key,
        "tier": tier,
        "bucket_s": bucket_s,
        "series": [s.name for s in series_for(tier)],
        "points": [],
        "coverage": {"first_sample_ts": None, "n": 0,
                     "series_first_ts": {s.name: None for s in series_for(tier)},
                     "gaps": []},
    }


def _coverage(conn, cols) -> tuple[int | None, dict]:
    """Stored-history extent, ALWAYS from the coarse (retained) tier.

    Reading MIN() from whichever tier served this query made first_sample_ts
    tier-scoped: a <=12h range reads equity_fine, which is pruned at 48h, so
    range=15m would report history starting 48h ago while range=1d reported a
    year. The range selector would then enable/disable ranges differently
    depending on which range you were already looking at.
    """
    row = conn.execute(f"SELECT MIN(bucket_ts) FROM {COARSE_TABLE}").fetchone()
    first_ts = int(row[0]) if row and row[0] is not None else None
    series_first: dict[str, int | None] = {}
    for s in cols:
        r = conn.execute(
            f"SELECT MIN(bucket_ts) FROM {COARSE_TABLE} "
            f"WHERE {s.name} IS NOT NULL").fetchone()
        series_first[s.name] = int(r[0]) if r and r[0] is not None else None
    return first_ts, series_first


def equity_series(conn, range_name, now: float | None = None) -> dict:
    """Downsample the stored series for one lookback window."""
    key, seconds = resolve_range(range_name)
    tier, table, bucket_s, _points = plan_query(key)
    now = float(now if now is not None else time.time())
    start = now - seconds
    cols = series_for(tier)

    rows = conn.execute(build_series_sql(tier, table, bucket_s), (start, now)).fetchall()
    # The window is a rolling `now - seconds`, so it is not bucket-aligned and
    # can straddle one extra PARTIAL bucket at the old edge. Keep the newest
    # MAX_POINTS; the response contract is a hard cap, not "usually".
    if len(rows) > MAX_POINTS:
        rows = rows[-MAX_POINTS:]

    points: list = []
    gaps: list[list[int]] = []
    prev_ts = None
    for row in rows:
        ts = int(row[1])
        # Spec §7 defines a gap in TIME, not in bucket indices: consecutive
        # samples more than 2 x bucket_s apart. Differencing bucket indices
        # misreports whenever the samples sit at opposite ends of their buckets.
        if prev_ts is not None and (ts - prev_ts) > 2 * bucket_s:
            points.append(None)
            gaps.append([prev_ts, ts])
        point = {"ts": ts}
        for i, s in enumerate(cols, start=2):
            point[s.name] = row[i]
        points.append(point)
        prev_ts = ts

    first_ts, series_first = _coverage(conn, cols)

    return {
        "range": key,
        "tier": tier,
        "bucket_s": bucket_s,
        "series": [s.name for s in cols],
        "points": points,
        "coverage": {
            "first_sample_ts": first_ts,
            "n": len([p for p in points if p is not None]),
            "series_first_ts": series_first,
            "gaps": gaps,
        },
    }
