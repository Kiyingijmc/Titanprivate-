# Equity Time Series — Recorder & API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist equity, balance and running-peak equity as a queryable two-tier time series, and expose it over `GET /api/equity?range=<r>` with honest coverage and gap reporting.

**Architecture:** A registry-driven `EquityRecorder` samples the `HEARTBEAT` branch of the controller every 10 s, buffers in memory, and flushes to two SQLite tables in `titan_core.db` — `equity_fine` (10 s, pruned at 48 h) and `equity_coarse` (300 s buckets, retained). A read-only `equity_view` module derives tier and bucket size from the requested range and downsamples in SQL. Nothing visible changes in the UI; this phase is verified entirely by the Python suite.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, stdlib `unittest` (there is no pytest in this repo), FastAPI (already present).

**Spec:** `docs/superpowers/specs/2026-07-31-equity-timeseries-and-range-selector-design.md`

## Global Constraints

- **Timestamps are UTC epoch seconds (`float`) everywhere on this path.** No `datetime.fromtimestamp()`, no naive local datetimes. RISK-10 in `docs/audit-2026-07-30/02-AUDIT-REPORT.md` is a live bug caused by exactly that mixture.
- **Nothing on this path may raise into the trading loop.** `record()` and `flush()` catch broadly and count, matching the contract in `src/ops/jsonlog.py:32`.
- **Never `INSERT OR REPLACE`.** Use `ON CONFLICT(...) DO UPDATE SET` naming every column. Audit OBS-03 is the bug where `INSERT OR REPLACE` silently zeroed unnamed columns.
- **Tests use stdlib `unittest`.** Run with `.venv/bin/python -m unittest <module> -v`. Full suite: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- **Every test file** starts with the repo's path shim:
  ```python
  import os, sys
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
  ```
- **`MAX_POINTS = 300`**, fine cadence `10`, coarse bucket `300` — derived, never hand-tabulated.
- **Clocks are injected** (`clock=time.time`, `monotonic=time.monotonic`) so tests are deterministic. This is deliberate design, not a test accommodation — contrast the `getattr` guards the audit flags at `system_controller.py:414`.
- Do not modify sizing, risk gates, the trading decision path, or any MQL5 file.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/ops/equity_recorder.py` (create) | Series registry, `Sample`, schema migration, `EquityRecorder` (record/flush/prune/counters) |
| `src/ops/web/equity_view.py` (create) | Read-only: range→tier/bucket derivation, SQL downsample, gap + coverage assembly |
| `src/ops/web/server.py` (modify) | `GET /api/equity` route |
| `src/ops/web/state_view.py` (modify) | `equity_recorder` counters in the health block |
| `src/core/system_controller.py` (modify) | Construct recorder; call `record()` in HEARTBEAT; call `prune()` on the 60 s timer |
| `config/config.yaml` (modify) | `ops.equity` block |
| `tests/unit/test_equity_recorder.py` (create) | Tasks 1–4 |
| `tests/unit/test_equity_view.py` (create) | Task 5 |
| `tests/unit/test_gui_equity_api.py` (create) | Task 6 |
| `tests/unit/test_equity_controller_wiring.py` (create) | Task 7 |

---

## Task 1: Series registry and schema migration

**Files:**
- Create: `src/ops/equity_recorder.py`
- Test: `tests/unit/test_equity_recorder.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Sample(ts, equity, balance, peak)`; `Series(name, agg, source, tier)`; `SERIES` tuple; `series_for(tier) -> tuple[Series, ...]`; `ensure_schema(conn) -> None`; `SCHEMA_VERSION = 1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_equity_recorder.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.equity_recorder'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/equity_recorder.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add src/ops/equity_recorder.py tests/unit/test_equity_recorder.py
git commit -m "feat(equity): registry-driven schema for the equity time series"
```

---

## Task 2: `record()` — cadence gate, validation, counters

**Files:**
- Modify: `src/ops/equity_recorder.py`
- Test: `tests/unit/test_equity_recorder.py`

**Interfaces:**
- Consumes: `Sample`, `SERIES`, `ensure_schema` from Task 1.
- Produces: `EquityRecorder(db_path, config=None, logger=None, clock=time.time, monotonic=time.monotonic)` with `.record(balance, equity) -> bool`, `.buffer` (list[Sample]), `.peak` (float), `.counters` (dict with keys `dropped_stale`, `dropped_invalid`, `dropped_overflow`, `flush_errors`).

`record()` returns `True` when a sample was accepted into the buffer, `False` otherwise (cadence-skipped or rejected). A cadence skip is **not** a drop and increments nothing.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_equity_recorder.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: FAIL — `ImportError: cannot import name 'EquityRecorder'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/ops/equity_recorder.py`:

```python
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
                    and mono - self._last_sample_mono < self.cfg["fine_cadence_s"]):
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
        """Placeholder until Task 3."""
        self._last_flush_mono = self._monotonic()
```

Note the cadence gate is checked **before** validation so an invalid sample arriving inside the
window is a skip, not a double-count.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add src/ops/equity_recorder.py tests/unit/test_equity_recorder.py
git commit -m "feat(equity): record() with cadence gate, fail-closed validation and counters"
```

---

## Task 3: `flush()` — fine insert and coarse rollup upsert

**Files:**
- Modify: `src/ops/equity_recorder.py`
- Test: `tests/unit/test_equity_recorder.py`

**Interfaces:**
- Consumes: `EquityRecorder`, `Sample`, `series_for` from Tasks 1–2.
- Produces: working `EquityRecorder.flush()`; module helper `bucket_of(ts, size) -> int`.

Rollup SQL is generated from each series' `agg`:

| `agg` | `DO UPDATE SET` expression |
|---|---|
| `last` | `excluded.<n>` |
| `max` | `MAX(COALESCE(<table>.<n>, excluded.<n>), excluded.<n>)` |
| `min` | `MIN(COALESCE(<table>.<n>, excluded.<n>), excluded.<n>)` |
| `sum` | `COALESCE(<table>.<n>, 0) + excluded.<n>` |

The `COALESCE` is required: SQLite's scalar `MAX(a, b)` returns `NULL` if either argument is `NULL`,
so a series added by a later migration would poison its own first rollup without it.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_equity_recorder.py`:

```python
from src.ops.equity_recorder import bucket_of


class FlushAndRollup(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_bucket_of_floors_to_size(self):
        self.assertEqual(bucket_of(1_000_000.0, 300), 999_900)
        self.assertEqual(bucket_of(999_900.0, 300), 999_900)
        self.assertEqual(bucket_of(1_000_199.9, 300), 1_000_050)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: FAIL — `ImportError: cannot import name 'bucket_of'`

- [ ] **Step 3: Write minimal implementation**

Add `bucket_of` at module level and replace the placeholder `flush()`:

```python
def bucket_of(ts: float, size: int) -> int:
    """Floor a UTC epoch timestamp to its bucket start."""
    return int(ts // size) * size


_AGG_SQL = {
    "last": "excluded.{n}",
    "max": "MAX(COALESCE({t}.{n}, excluded.{n}), excluded.{n})",
    "min": "MIN(COALESCE({t}.{n}, excluded.{n}), excluded.{n})",
    "sum": "COALESCE({t}.{n}, 0) + excluded.{n}",
}
```

```python
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
```

`INSERT OR IGNORE` on the fine tier is safe: `ts` is unique per sample by the monotonic guard, so a
conflict can only mean a duplicate replay, which should be ignored rather than rewritten.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: PASS, 22 tests

- [ ] **Step 5: Commit**

```bash
git add src/ops/equity_recorder.py tests/unit/test_equity_recorder.py
git commit -m "feat(equity): flush with registry-driven coarse rollup upsert"
```

---

## Task 4: `prune()` — fine-tier retention

**Files:**
- Modify: `src/ops/equity_recorder.py`
- Test: `tests/unit/test_equity_recorder.py`

**Interfaces:**
- Consumes: `EquityRecorder` from Tasks 1–3.
- Produces: `EquityRecorder.prune() -> int` (rows deleted).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder.Prune -v`
Expected: FAIL — `AttributeError: 'EquityRecorder' object has no attribute 'prune'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_recorder -v`
Expected: PASS, 25 tests

- [ ] **Step 5: Commit**

```bash
git add src/ops/equity_recorder.py tests/unit/test_equity_recorder.py
git commit -m "feat(equity): fine-tier prune with retention boundary"
```

---

## Task 5: `equity_view` — range derivation, downsample, gaps, coverage

**Files:**
- Create: `src/ops/web/equity_view.py`
- Test: `tests/unit/test_equity_view.py`

**Interfaces:**
- Consumes: `series_for`, `FINE_TABLE`, `COARSE_TABLE` from `src.ops.equity_recorder`.
- Produces: `RANGES` (dict name→seconds), `MAX_POINTS = 300`, `resolve_range(name) -> (str, int)`, `plan_query(range_name) -> (tier, table, bucket_s, points)`, `equity_series(conn, range_name, now=None) -> dict`.

Derivation rule (spec §3): tier is `fine` when `range_seconds <= 43200`, else `coarse`; bucket is the
smallest whole multiple of the tier cadence (10 s fine, 300 s coarse) for which
`range_seconds / bucket <= MAX_POINTS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_equity_view.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_view -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.equity_view'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/equity_view.py
"""Read-only assembly of the /api/equity response (spec 2026-07-31 §3, §7).

Tier and bucket size are DERIVED from the requested range, never tabulated, so
changing a cadence or MAX_POINTS cannot leave a stale hand-computed number behind.
"""
from __future__ import annotations

import math
import time

from src.ops.equity_recorder import COARSE_TABLE, FINE_TABLE, series_for

MAX_POINTS = 300
FINE_CADENCE_S = 10
COARSE_CADENCE_S = 300
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

    agg_sql = {"last": "MAX", "max": "MAX", "min": "MIN", "sum": "SUM"}
    selects = []
    for s in cols:
        if s.agg == "last":
            # last value in the bucket = the one at the greatest key
            selects.append(
                f"(SELECT i.{s.name} FROM {table} i "
                f" WHERE CAST(i.{key_col} / {bucket_s} AS INTEGER) = b "
                f"   AND i.{s.name} IS NOT NULL "
                f" ORDER BY i.{key_col} DESC LIMIT 1) AS {s.name}")
        else:
            selects.append(f"{agg_sql[s.agg]}({s.name}) AS {s.name}")

    sql = (f"SELECT CAST({key_col} / {bucket_s} AS INTEGER) AS b, "
           + ", ".join(selects) +
           f" FROM {table} WHERE {key_col} >= ? AND {key_col} <= ? "
           f" GROUP BY b ORDER BY b")
    rows = conn.execute(sql, (start, now)).fetchall()

    points: list = []
    gaps: list[list[int]] = []
    prev_b = None
    for row in rows:
        b = row[0]
        ts = int(b * bucket_s)
        if prev_b is not None and (b - prev_b) > 2:
            points.append(None)
            gaps.append([int(prev_b * bucket_s), ts])
        point = {"ts": ts}
        for i, s in enumerate(cols, start=1):
            point[s.name] = row[i]
        points.append(point)
        prev_b = b

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_view -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/equity_view.py tests/unit/test_equity_view.py
git commit -m "feat(equity): derived range planning, SQL downsample, gap and coverage reporting"
```

---

## Task 6: `GET /api/equity` and health counters

**Files:**
- Modify: `src/ops/web/server.py:49-51` (add route beside `/api/history`)
- Modify: `src/ops/web/state_view.py:22-29` (health block)
- Test: `tests/unit/test_gui_equity_api.py`

**Interfaces:**
- Consumes: `equity_series`, `RANGES` from Task 5; `EquityRecorder.counters` from Task 2.
- Produces: `GET /api/equity?range=<name>`; `health.equity_recorder` in the `/api/state` snapshot.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_equity_api.py
"""Route-level tests for GET /api/equity and the recorder health counters."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from src.ops.equity_recorder import ensure_schema
from src.ops.web import auth, server


class _Recorder:
    def __init__(self, conn):
        self.conn = conn
        self.counters = {"dropped_stale": 1, "dropped_invalid": 2,
                         "dropped_overflow": 3, "flush_errors": 4}


class _Controller:
    def __init__(self, conn):
        self.equity_recorder = _Recorder(conn)


AUTH = {"Authorization": "Bearer sekret"}


def _client(conn):
    """Mirrors tests/unit/test_gui_server.py::_make — same env + throttle reset."""
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    os.environ.pop("TITAN_GUI_READONLY", None)
    auth.THROTTLE.reset()
    app = server.create_app(_Controller(conn), settings_store=None, bridge=None)
    return TestClient(app), AUTH


class EquityRoute(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_schema(self.conn)

    def test_requires_auth(self):
        client, _ = _client(self.conn)
        self.assertEqual(client.get("/api/equity").status_code, 401)

    def test_default_range_is_1d(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity", headers=hdr).json()
        self.assertEqual(body["range"], "1d")
        self.assertEqual(body["tier"], "coarse")

    def test_known_range_is_honoured(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity?range=15m", headers=hdr).json()
        self.assertEqual(body["range"], "15m")
        self.assertEqual(body["tier"], "fine")

    def test_unknown_range_falls_back_to_1d(self):
        client, hdr = _client(self.conn)
        body = client.get("/api/equity?range=nope", headers=hdr).json()
        self.assertEqual(body["range"], "1d")

    def test_empty_store_returns_empty_points_not_an_error(self):
        client, hdr = _client(self.conn)
        resp = client.get("/api/equity?range=1y", headers=hdr)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["points"], [])


if __name__ == "__main__":
    unittest.main()
```

Also append to `tests/unit/test_gui_equity_api.py`:

```python
class HealthCounters(unittest.TestCase):
    def test_state_view_exposes_recorder_counters(self):
        from src.ops.web.state_view import _equity_recorder_health
        conn = sqlite3.connect(":memory:")
        ensure_schema(conn)
        c = _Controller(conn)
        self.assertEqual(_equity_recorder_health(c), {
            "dropped_stale": 1, "dropped_invalid": 2,
            "dropped_overflow": 3, "flush_errors": 4})

    def test_missing_recorder_reports_none_not_a_crash(self):
        from src.ops.web.state_view import _equity_recorder_health
        self.assertIsNone(_equity_recorder_health(object()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_equity_api -v`
Expected: FAIL — 404 on `/api/equity`, and `ImportError: cannot import name '_equity_recorder_health'`

- [ ] **Step 3: Write minimal implementation**

In `src/ops/web/server.py`, add the import beside the existing `state_view` import:

```python
from .equity_view import equity_series
```

and the route immediately after `get_history` (currently `server.py:49-51`):

```python
    @app.get("/api/equity", dependencies=read)
    def get_equity(range: str = "1d"):
        rec = getattr(controller, "equity_recorder", None)
        conn = getattr(rec, "conn", None)
        if conn is None:
            return {"range": range, "tier": None, "bucket_s": None, "series": [],
                    "points": [], "coverage": {"first_sample_ts": None, "n": 0,
                                               "series_first_ts": {}, "gaps": []}}
        return equity_series(conn, range)
```

In `src/ops/web/state_view.py`, add the helper and wire it into the health block:

```python
def _equity_recorder_health(controller):
    """Recorder loss counters, or None when the recorder is absent/disabled."""
    rec = getattr(controller, "equity_recorder", None)
    counters = getattr(rec, "counters", None)
    return dict(counters) if isinstance(counters, dict) else None
```

```python
        "health": {
            "bridge_connected": age <= _HEARTBEAT_STALE_S,
            "last_heartbeat_age_s": round(age, 1),
            "paused": bool(getattr(controller, "is_manual_pause", False)),
            "last_error": getattr(controller, "last_error", None),
            "equity_recorder": _equity_recorder_health(controller),
        },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_equity_api -v`
Expected: PASS, 7 tests

Then confirm no existing GUI test regressed:
Run: `.venv/bin/python -m unittest tests.unit.test_gui_server tests.unit.test_gui_auth -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/server.py src/ops/web/state_view.py tests/unit/test_gui_equity_api.py
git commit -m "feat(equity): GET /api/equity route and recorder counters on /api/state"
```

---

## Task 7: Controller wiring, config block, fake controller

**Files:**
- Modify: `src/core/system_controller.py:171-179` (construct recorder), `:713` (record on heartbeat), `:321-324` (prune on the recon timer)
- Modify: `config/config.yaml` (`ops.equity` block, after `ops.health`)
- Modify: `src/ops/web/fake_controller.py` (synthetic series for devserver)
- Test: `tests/unit/test_equity_controller_wiring.py`

**Interfaces:**
- Consumes: `EquityRecorder` from Tasks 1–4.
- Produces: `controller.equity_recorder`; a `fake_controller` whose `.equity_recorder.conn` is populated.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_equity_controller_wiring.py
"""The recorder is constructed, fed by HEARTBEAT, and pruned on the recon timer."""
import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController
from src.ops.equity_recorder import EquityRecorder


class _NullLogger:
    def log_event(self, *a, **k):
        pass


def _run(coro):
    """Drive a coroutine on a fresh loop.

    Matches tests/unit/test_controller_routing.py:72. Do NOT use
    asyncio.get_event_loop() — this venv is Python 3.12, where calling it with
    no running loop is deprecated and slated to raise.
    """
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _bare_controller(recorder):
    """Controller shell without __init__ — the fixture pattern this repo already uses."""
    c = object.__new__(SystemController)
    c.equity_recorder = recorder
    c.logger = _NullLogger()
    c.risk_manager = type("RM", (), {"update_account_info": lambda *a: None,
                                     "track_equity": lambda *a: None})()
    c.current_open_positions = []
    c.current_pending_orders = []
    c._publish = lambda evt: None
    c.state_manager = type("SM", (), {"exists": lambda *a: True})()
    return c


class HeartbeatFeedsRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rec = EquityRecorder(os.path.join(self.tmp, "core.db"),
                                  config={"enabled": True, "fine_cadence_s": 0})

    def test_heartbeat_records_balance_and_equity(self):
        c = _bare_controller(self.rec)
        msg = {"type": "HEARTBEAT", "bal": 1221.59, "eq": 1327.0, "pos": [], "orders": []}
        _run(c._process_incoming_data(msg))
        self.assertEqual(len(self.rec.buffer), 1)
        self.assertEqual(self.rec.buffer[0].equity, 1327.0)
        self.assertEqual(self.rec.buffer[0].balance, 1221.59)

    def test_zero_equity_heartbeat_records_nothing(self):
        c = _bare_controller(self.rec)
        msg = {"type": "HEARTBEAT", "bal": 1221.59, "eq": 0.0, "pos": [], "orders": []}
        _run(c._process_incoming_data(msg))
        self.assertEqual(self.rec.buffer, [])


class ConfigBlock(unittest.TestCase):
    def test_config_yaml_declares_ops_equity(self):
        import yaml
        with open("config/config.yaml") as fh:
            cfg = yaml.safe_load(fh)
        eq = cfg["ops"]["equity"]
        self.assertTrue(eq["enabled"])
        self.assertEqual(eq["fine_cadence_s"], 10)
        self.assertEqual(eq["fine_retention_h"], 48)
        self.assertEqual(eq["coarse_bucket_s"], 300)
        self.assertEqual(eq["flush_interval_s"], 60)
        self.assertEqual(eq["max_buffer_samples"], 600)


class FakeControllerSeries(unittest.TestCase):
    def test_fake_controller_serves_a_populated_series(self):
        from src.ops.web.equity_view import equity_series
        from src.ops.web.fake_controller import FakeController
        c = FakeController()
        out = equity_series(c.equity_recorder.conn, "1d")
        self.assertGreater(len([p for p in out["points"] if p]), 10)


if __name__ == "__main__":
    unittest.main()
```

`FakeController` is the correct class name — verified at `src/ops/web/fake_controller.py:52`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_controller_wiring -v`
Expected: FAIL — `KeyError: 'equity'` on the config test, and the heartbeat test records nothing.

- [ ] **Step 3: Write minimal implementation**

`config/config.yaml`, appended to the existing `ops:` block after `health:`:

```yaml
  equity:
    enabled: true
    fine_cadence_s: 10        # one stored sample per 10s
    fine_retention_h: 48      # fine tier pruned beyond this
    coarse_bucket_s: 300      # 5-minute retained buckets
    flush_interval_s: 60      # buffer -> sqlite
    max_buffer_samples: 600   # hard cap; overflow drops oldest and counts
```

`src/core/system_controller.py` — construct after `self.state_manager` (currently `:172`):

```python
        self.equity_recorder = EquityRecorder(
            str(self.root_dir / "data/db/titan_core.db"),
            config=(self.config.get("ops", {}) or {}).get("equity", {}),
            logger=self.logger,
        )
```

with the import beside the other `src.ops` imports at the top of the file:

```python
from src.ops.equity_recorder import EquityRecorder
```

In `_process_incoming_data`, inside the `HEARTBEAT` branch, immediately after the existing
`self._publish(HeartbeatReceived(...))` call (currently `:717-721`):

```python
            if eq > 0:
                self.equity_recorder.record(bal, eq)
```

In `run()`, inside the existing 60 s reconciliation block (currently `:321-324`):

```python
                if now_ts - self.last_recon_time > self.recon_interval:
                    await self._perform_reconciliation()
                    self.equity_recorder.prune()
                    self.last_recon_time = now_ts
```

`src/ops/web/fake_controller.py` — add an in-memory recorder seeded with a synthetic walk so
`devserver.py` can drive every range with MT5 offline:

```python
def _fake_equity_recorder():
    """In-memory series: 3 days of 5-minute buckets with one deliberate gap."""
    import math as _math
    import sqlite3
    import time as _time

    from src.ops.equity_recorder import ensure_schema

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    ensure_schema(conn)
    now = int(_time.time())
    rows = []
    equity, peak = 10_000.0, 10_000.0
    for i in range(864):                      # 3 days of 300s buckets
        ts = now - (864 - i) * 300
        if 300 < i < 400:                     # a ~8h outage, so gap rendering is drivable
            continue
        equity += _math.sin(i / 18.0) * 12.0
        peak = max(peak, equity)
        rows.append((ts, equity, equity - 40.0, peak, equity - 6.0, equity + 6.0))
    conn.executemany(
        "INSERT INTO equity_coarse "
        "(bucket_ts, equity, balance, peak, equity_min, equity_max) VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return type("_FakeRecorder", (), {"conn": conn, "counters": {
        "dropped_stale": 0, "dropped_invalid": 0,
        "dropped_overflow": 0, "flush_errors": 0}})()
```

and assign `self.equity_recorder = _fake_equity_recorder()` in the fake controller's `__init__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_equity_controller_wiring -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK. Baseline before this plan is 683 tests; expect ~683 + 47.

> This suite takes 600–2100 s. `rc=124` is a **timeout**, not a failure — see
> `.mig/config` `VERIFY_TIMEOUT`. Before trusting any timing, check `uptime` and
> `ps aux | grep 'unittest discover'` for a concurrent run.

- [ ] **Step 6: Commit**

```bash
git add src/core/system_controller.py config/config.yaml src/ops/web/fake_controller.py \
        tests/unit/test_equity_controller_wiring.py
git commit -m "feat(equity): wire recorder into the controller heartbeat and prune timer"
```

---

## Self-review notes

Checked against the spec:

- §3 ranges/derivation → Task 5 (`plan_query`, table-driven test asserting all eleven).
- §4 storage → Task 1.
- §5 registry, `user_version`, nullable columns, ALTER path → Task 1.
- §6 recorder: feed point, cadence, buffer cap, rejection rules, counters, peak seeding, prune, config → Tasks 2, 3, 4, 7.
- §7 API: route, default, downsample, gaps, coverage, per-series coverage → Tasks 5, 6.
- §8 frontend → **deliberately out of scope**; Phase 2 plan.
- §9 testing: every Python bullet maps to a named test above. Frontend bullets are Phase 2.
- §10 risks → mitigations implemented in Tasks 2–4 (bounded buffer, never-raise, prune, retained-buffer-on-error).

Known follow-ups, not defects in this plan:

- The `last` aggregation uses a correlated subquery per bucket. Correct, and fine at ≤300 buckets against an indexed primary key; if a future range ever needs thousands of buckets, revisit with a window function.
- `_equity_recorder_health` returns `None` when the recorder is absent so the field is always present in the snapshot and the frontend can distinguish "disabled" from "zero drops".
