"""Read-only assembly of the /api/equity response (spec 2026-07-31 §3, §7).

Tier and bucket size are DERIVED from the requested range, never tabulated, so
changing a cadence or MAX_POINTS cannot leave a stale hand-computed number behind.
"""
from __future__ import annotations

import math
import time

from src.ops.equity_recorder import _DEFAULTS, COARSE_TABLE, FINE_TABLE, series_for

MAX_POINTS = 300
# Single source of truth: the recorder's own defaults (ops.equity.fine_cadence_s /
# coarse_bucket_s in config/config.yaml). Hardcoding a second copy here would let
# a config change silently desync the view's bucket math from what was stored.
FINE_CADENCE_S = int(_DEFAULTS["fine_cadence_s"])
COARSE_CADENCE_S = int(_DEFAULTS["coarse_bucket_s"])
FINE_MAX_RANGE_S = 43_200          # 12h — above this we read the coarse tier
DEFAULT_RANGE = "1d"

RANGES: dict[str, int] = {
    "15m": 900, "30m": 1_800, "1h": 3_600, "4h": 14_400, "12h": 43_200,
    "1d": 86_400, "1w": 604_800, "1mo": 2_592_000, "4mo": 10_368_000,
    "6mo": 15_552_000, "1y": 31_536_000,
}


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
        tier, table, cadence = "coarse", COARSE_TABLE, COARSE_CADENCE_S
    # smallest whole multiple of cadence with seconds/bucket <= MAX_POINTS
    steps = math.ceil(seconds / MAX_POINTS / cadence)
    bucket = max(cadence, steps * cadence)
    return tier, table, bucket, math.ceil(seconds / bucket)


def equity_series(conn, range_name, now: float | None = None) -> dict:
    """Downsample the stored series for one lookback window."""
    key, seconds = resolve_range(range_name)
    tier, table, bucket_s, _points = plan_query(key)
    now = float(now if now is not None else time.time())
    start = now - seconds
    key_col = "ts" if tier == "fine" else "bucket_ts"
    cols = series_for(tier)

    agg_sql = {"max": "MAX", "min": "MIN", "sum": "SUM"}
    selects = []
    for s in cols:
        if s.agg == "last":
            # last value in the bucket = the one at the greatest key, NOT
            # SQLite's bare MAX() (that returns the largest VALUE, which
            # differs from the latest one whenever equity falls inside the
            # bucket) — a correlated subquery ordered by the key column.
            selects.append(
                f"(SELECT i.{s.name} FROM {table} i "
                f" WHERE CAST(i.{key_col} / {bucket_s} AS INTEGER) = "
                f"       CAST({table}.{key_col} / {bucket_s} AS INTEGER) "
                f"   AND i.{s.name} IS NOT NULL "
                f" ORDER BY i.{key_col} DESC LIMIT 1) AS {s.name}")
        else:
            selects.append(f"{agg_sql[s.agg]}({s.name}) AS {s.name}")

    sql = (f"SELECT CAST({key_col} / {bucket_s} AS INTEGER) AS b, "
           f"MAX({key_col}) AS raw_ts, "
           + ", ".join(selects) +
           f" FROM {table} WHERE {key_col} >= ? AND {key_col} <= ? "
           f" GROUP BY b ORDER BY b")
    rows = conn.execute(sql, (start, now)).fetchall()

    points: list = []
    gaps: list[list[int]] = []
    prev_b = None
    prev_ts = None
    for row in rows:
        b = row[0]
        ts = int(row[1])
        if prev_b is not None and (b - prev_b) > 2:
            points.append(None)
            gaps.append([prev_ts, ts])
        point = {"ts": ts}
        for i, s in enumerate(cols, start=2):
            point[s.name] = row[i]
        points.append(point)
        prev_b = b
        prev_ts = ts

    first_row = conn.execute(f"SELECT MIN({key_col}) FROM {table}").fetchone()
    first_ts = int(first_row[0]) if first_row and first_row[0] is not None else None
    series_first: dict[str, int | None] = {}
    for s in cols:
        r = conn.execute(
            f"SELECT MIN({key_col}) FROM {table} WHERE {s.name} IS NOT NULL").fetchone()
        series_first[s.name] = int(r[0]) if r and r[0] is not None else None

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
