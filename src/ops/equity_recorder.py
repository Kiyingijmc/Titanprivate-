"""Equity time series recorder (spec 2026-07-31).

Two tiers in titan_core.db: equity_fine (10s, pruned at 48h) and equity_coarse
(300s buckets, retained). Columns are generated from SERIES, so adding a metric
later is one tuple entry plus an automatic ALTER TABLE.

All timestamps are UTC epoch seconds. Never naive local datetimes: RISK-10 in the
2026-07-30 audit is a live bug caused by mixing the two in one buffer.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

SCHEMA_VERSION = 1

FINE_TABLE = "equity_fine"
COARSE_TABLE = "equity_coarse"


@dataclass(frozen=True)
class Sample:
    """One accepted heartbeat."""
    ts: float          # UTC epoch seconds
    equity: float
    balance: float
    peak: float        # running max equity as of this sample


@dataclass(frozen=True)
class Series:
    """One recorded metric.

    agg  — how a bucket collapses: 'last' | 'min' | 'max' | 'sum'
    tier — 'fine' | 'coarse' | 'both'
    """
    name: str
    agg: str
    source: Callable[[Sample], float]
    tier: str = "both"


SERIES: tuple[Series, ...] = (
    Series("equity", "last", lambda s: s.equity),
    Series("balance", "last", lambda s: s.balance),
    Series("peak", "max", lambda s: s.peak),
    Series("equity_min", "min", lambda s: s.equity, tier="coarse"),
    Series("equity_max", "max", lambda s: s.equity, tier="coarse"),
)


def series_for(tier: str) -> tuple[Series, ...]:
    return tuple(s for s in SERIES if s.tier in ("both", tier))


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create both tables and ALTER in any registered series that is missing.

    Only the key column is declared. Every series column is a nullable REAL, which
    is what ALTER TABLE ADD COLUMN supports without a default and is exactly the
    semantics we want: a series registered later reads NULL for older rows.
    """
    conn.execute(f"CREATE TABLE IF NOT EXISTS {FINE_TABLE} (ts REAL PRIMARY KEY)")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {COARSE_TABLE} (bucket_ts INTEGER PRIMARY KEY)")
    for tier, table in (("fine", FINE_TABLE), ("coarse", COARSE_TABLE)):
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for s in series_for(tier):
            if s.name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {s.name} REAL")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
