"""Equity time series recorder (spec 2026-07-31).

Two tiers in titan_core.db: equity_fine (10s, pruned at 48h) and equity_coarse
(300s buckets, retained). Columns are generated from SERIES, so adding a metric
later is one tuple entry plus an automatic ALTER TABLE.

All timestamps are UTC epoch seconds. Never naive local datetimes: RISK-10 in the
2026-07-30 audit is a live bug caused by mixing the two in one buffer.

Migration mechanism: `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` in
ensure_schema(). There is deliberately no schema-version counter — `user_version`
is a single per-DATABASE integer and titan_core.db is shared with AuditLogger,
so writing it here would clobber another owner's value to record something the
table_info path never reads.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

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
    conn.commit()


import math
import time
from pathlib import Path

# ── STRUCTURAL CONSTANTS — deliberately NOT operator-tunable ─────────────────
# These two values are baked into every row already on disk: the fine tier is
# written at FINE_CADENCE_S and the coarse tier is keyed by a bucket start
# floored to COARSE_BUCKET_S. Changing either at runtime would leave the DB
# holding rows aligned to the OLD size while the view buckets at the NEW one, so
# a query bucket would straddle a fraction of a stored row (spec §3) — silently,
# and permanently for the historical rows. There is no migration for that, so
# the knob does not exist. equity_view imports these; it must never keep a
# second copy. Everything that does NOT affect stored alignment (enabled,
# fine_retention_h, flush_interval_s, max_buffer_samples) stays in config.
FINE_CADENCE_S = 10       # one stored fine sample per 10s
COARSE_BUCKET_S = 300     # 5-minute retained buckets

_DEFAULTS = {
    "enabled": True,
    "fine_retention_h": 48,
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
        # Everything the rest of the class touches is seeded BEFORE the first
        # line that can fail. A malformed ops.equity block (a bare `true`, a
        # string, a list) makes dict.update() raise, and this object is built
        # inside SystemController.__init__ — an escape here is a bot that does
        # not boot (same failure class as the S014 GUI-bind incident). A typo in
        # a chart's config must cost the chart, never the engine.
        self.cfg = dict(_DEFAULTS)
        self.logger = logger
        self._clock = clock
        self._monotonic = monotonic
        self.db_path = str(db_path)

        self.buffer: list[Sample] = []
        self.peak = 0.0
        self.counters = {"dropped_stale": 0, "dropped_invalid": 0,
                         "dropped_overflow": 0, "flush_errors": 0}

        self._last_ts = 0.0
        self._last_sample_mono = None
        self._last_flush_mono = self._monotonic()
        self.last_flush_ts = None

        self.conn = None
        self.enabled = False
        try:
            self.cfg.update(config or {})
            self.enabled = bool(self.cfg["enabled"])
            if self.enabled:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
                self.conn.execute("PRAGMA journal_mode=WAL;")
                self.conn.execute("PRAGMA synchronous=NORMAL;")
                # titan_core.db now has two writers (AuditLogger + this). The
                # default 5s busy stall would land on the asyncio trading loop.
                self.conn.execute("PRAGMA busy_timeout=1000;")
                ensure_schema(self.conn)
                self.peak = self._load_peak()
        except Exception as e:                      # never fatal
            self._log(f"init failed ({type(e).__name__}: {e}); recorder disabled")
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
                    and 0 <= mono - self._last_sample_mono < FINE_CADENCE_S):
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
            size = COARSE_BUCKET_S
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
            self.last_flush_ts = float(self._clock())
        except Exception as e:
            # Discard the partially-applied transaction. Without this the fine
            # rows written before the failure stay pending on the connection and
            # the NEXT commit (prune()'s, say) would silently persist them —
            # and, because the buffer is retained and replayed, the 'sum' agg
            # would double-count them into the coarse bucket.
            try:
                self.conn.rollback()
            except Exception:
                pass
            self.counters["flush_errors"] += 1
            self._log(f"flush failed: {e}")

    def prune(self) -> int:
        """Delete fine-tier rows older than retention. Returns rows deleted."""
        if not self.enabled or self.conn is None:
            return 0
        try:
            cutoff = float(self._clock()) - int(self.cfg["fine_retention_h"]) * 3600
            cur = self.conn.execute(f"DELETE FROM {FINE_TABLE} WHERE ts < ?", (cutoff,))
            self.conn.commit()
            return cur.rowcount or 0
        except Exception as e:
            self.counters["flush_errors"] += 1
            self._log(f"prune failed: {e}")
            return 0

    def close(self) -> None:
        try:
            self.flush()
            if self.conn:
                self.conn.close()
        except Exception:
            pass
