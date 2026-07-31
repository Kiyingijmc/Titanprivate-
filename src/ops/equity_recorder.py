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


import math
import time
from pathlib import Path

_DEFAULTS = {
    "enabled": True,
    "fine_cadence_s": 10,
    "fine_retention_h": 48,
    "coarse_bucket_s": 300,
    "flush_interval_s": 60,
    "max_buffer_samples": 600,
}


def bucket_of(ts: float, size: int) -> int:
    """Floor a UTC epoch timestamp to its bucket start."""
    return int(ts // size) * size


_AGG_SQL = {
    "last": "excluded.{n}",
    "max": "MAX(COALESCE({t}.{n}, excluded.{n}), excluded.{n})",
    "min": "MIN(COALESCE({t}.{n}, excluded.{n}), excluded.{n})",
    "sum": "COALESCE({t}.{n}, 0) + excluded.{n}",
}


class EquityRecorder:
    """Samples equity/balance from the heartbeat into a durable two-tier series.

    Contract: record() and flush() never raise into the trading loop. Every loss
    is counted and surfaced on /api/state — a silent-loss counter nobody reads is
    not an observability mechanism (audit OBS-02).
    """

    def __init__(self, db_path, config=None, logger=None,
                 clock=time.time, monotonic=time.monotonic):
        cfg = dict(_DEFAULTS)
        cfg.update(config or {})
        self.cfg = cfg
        self.enabled = bool(cfg["enabled"])
        self.logger = logger
        self._clock = clock
        self._monotonic = monotonic

        self.buffer: list[Sample] = []
        self.peak = 0.0
        self.counters = {"dropped_stale": 0, "dropped_invalid": 0,
                         "dropped_overflow": 0, "flush_errors": 0}

        self._last_ts = 0.0
        self._last_sample_mono = None
        self._last_flush_mono = self._monotonic()

        self.conn = None
        if self.enabled:
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
                self.conn.execute("PRAGMA journal_mode=WAL;")
                self.conn.execute("PRAGMA synchronous=NORMAL;")
                ensure_schema(self.conn)
                self.peak = self._load_peak()
            except Exception as e:                      # never fatal
                self._log(f"init failed: {e}")
                self.conn = None
                self.enabled = False

    # ── internals ────────────────────────────────────────────────────────────
    def _log(self, msg):
        try:
            if self.logger:
                self.logger.log_event("OPS", "EQUITY", msg)
        except Exception:
            pass

    def _load_peak(self) -> float:
        row = self.conn.execute(f"SELECT MAX(peak) FROM {COARSE_TABLE}").fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    @staticmethod
    def _valid(x) -> bool:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return False
        return math.isfinite(v) and v > 0

    # ── public ───────────────────────────────────────────────────────────────
    def record(self, balance, equity) -> bool:
        """Accept one heartbeat sample. Returns True if buffered."""
        if not self.enabled:
            return False
        try:
            mono = self._monotonic()
            if (self._last_sample_mono is not None
                    and 0 <= mono - self._last_sample_mono < self.cfg["fine_cadence_s"]):
                return False                            # by design, not a loss

            if not self._valid(equity) or not self._valid(balance):
                self.counters["dropped_invalid"] += 1
                return False

            ts = float(self._clock())
            if ts <= self._last_ts:
                self.counters["dropped_stale"] += 1
                return False

            equity = float(equity)
            self.peak = max(self.peak, equity)
            self.buffer.append(Sample(ts=ts, equity=equity,
                                      balance=float(balance), peak=self.peak))
            self._last_ts = ts
            self._last_sample_mono = mono

            cap = int(self.cfg["max_buffer_samples"])
            while len(self.buffer) > cap:
                self.buffer.pop(0)
                self.counters["dropped_overflow"] += 1

            if mono - self._last_flush_mono >= self.cfg["flush_interval_s"]:
                self.flush()
            return True
        except Exception as e:                          # never raise into the loop
            self.counters["flush_errors"] += 1
            self._log(f"record failed: {e}")
            return False

    def flush(self) -> None:
        """Write buffered samples to both tiers in one transaction.

        On failure the buffer is RETAINED so a transient error self-heals on the
        next cycle; only the overflow cap can actually discard a sample.
        """
        self._last_flush_mono = self._monotonic()
        if not self.enabled or self.conn is None or not self.buffer:
            return
        pending = list(self.buffer)
        try:
            fine = series_for("fine")
            fine_cols = ", ".join(s.name for s in fine)
            fine_ph = ", ".join("?" for _ in fine)
            self.conn.executemany(
                f"INSERT OR IGNORE INTO {FINE_TABLE} (ts, {fine_cols}) "
                f"VALUES (?, {fine_ph})",
                [(s.ts, *[c.source(s) for c in fine]) for s in pending],
            )

            coarse = series_for("coarse")
            size = int(self.cfg["coarse_bucket_s"])
            coarse_cols = ", ".join(s.name for s in coarse)
            coarse_ph = ", ".join("?" for _ in coarse)
            updates = ", ".join(
                f"{s.name}=" + _AGG_SQL[s.agg].format(t=COARSE_TABLE, n=s.name)
                for s in coarse
            )
            sql = (f"INSERT INTO {COARSE_TABLE} (bucket_ts, {coarse_cols}) "
                   f"VALUES (?, {coarse_ph}) "
                   f"ON CONFLICT(bucket_ts) DO UPDATE SET {updates}")
            # One row per sample, in order: the ON CONFLICT clause folds them.
            self.conn.executemany(
                sql,
                [(bucket_of(s.ts, size), *[c.source(s) for c in coarse]) for s in pending],
            )

            self.conn.commit()
            del self.buffer[:len(pending)]
        except Exception as e:
            self.counters["flush_errors"] += 1
            self._log(f"flush failed: {e}")
