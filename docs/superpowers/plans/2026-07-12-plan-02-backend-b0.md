# Plan 02: Backend B0 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the Trading OS's nervous-system foundations — typed event bus, journaled golden tape, structured JSON logging, health probes with systemd watchdog integration, and systemd unit files — wired into the live controller as publish-only additions with zero trading-behavior change.

**Architecture:** Per `docs/research/2026-07-12-backend-infrastructure-blueprint.md` §5 (bus + journal + outbox-later), §9 (systemd), §11 (observability). One new core module (`src/core/bus.py`, plus `src/core/events.py`), three ops modules (`jsonlog`, `event_journal`, `health`), controller integration that only *publishes* (never alters the message-handling flow), and deploy artifacts. The event journal IS the golden tape that kernel v15.0's replay regression will consume.

**Tech Stack:** Python 3.11 stdlib only (asyncio, dataclasses, json, socket). No new dependencies. stdlib unittest.

## Global Constraints

- Test command: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`. Baseline entering this plan: **191 tests OK**; every task ends green (191 + new tests).
- No new pip dependencies. No FastAPI/uvicorn in this plan (that's B2); health probes use stdlib asyncio.
- The live loop's determinism rules (blueprint II §8): bus delivery to sync handlers is synchronous and in subscription order; a throwing subscriber must NEVER propagate into the caller (circuit-break it instead).
- All new writes are fail-safe: journal/log/probe failures may never crash or block trading (mirror `AuditLogger`'s silent-fail convention, but count drops).
- Controller integration is publish-only: no existing statement in `_process_incoming_data` / `run()` may be removed or reordered; publishes are inserted alongside.
- The existing `AuditLogger` stays untouched (migration to JSON schema is future scope; B0 adds the new `JsonLogger` for new components).
- Do NOT touch: `mql5_bridge/Experts/Titan_Gateway.mq5` (uncommitted user work), `data/specs.json`.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Work on branch `feat/trade-mgmt-pipeline` (continues from Plan 01's merge).

## File Structure

```
src/core/events.py            # frozen event dataclasses + registry (T1)
src/core/bus.py               # EventBus: typed pub/sub, circuit-broken subscribers (T2)
src/ops/jsonlog.py            # structured JSONL logger with date rotation (T3)
src/ops/event_journal.py      # bus->JSONL golden tape + iter_events reader (T4)
src/ops/health.py             # /healthz + /readyz stdlib server + sd_notify (T5)
src/core/system_controller.py # publish-only integration + ops config (T6)
config/config.yaml            # ops: block (T6)
deploy/systemd/titan-live.service   # (T7)
deploy/systemd/titan-demo.service   # (T7)
docs/runbooks/deploy-systemd.md     # (T7)
tests/unit/test_events.py / test_bus.py / test_jsonlog.py /
tests/unit/test_event_journal.py / test_health.py / test_controller_events.py
```

---

### Task 1: Typed events module

**Files:**
- Create: `src/core/events.py`
- Test: `tests/unit/test_events.py`

**Interfaces:**
- Produces: `Event` base (frozen dataclass) with `name: ClassVar[str]`, `to_dict() -> dict`, classmethod `from_dict(d) -> Event`; registry `EVENT_TYPES: dict[str, type]`; concrete events `BarClosed(symbol, tf, bar_time, open, high, low, close)`, `TickReceived(symbol, bid)`, `HeartbeatReceived(balance, equity, n_positions, n_orders)`, `ExecutionReceived(status, ticket, symbol, pnl)`, `SpecsUpdated(symbol)`, `SystemStateChanged(state)`. All fields JSON-scalar (str/float/int).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_events.py
import unittest
from src.core.events import (Event, EVENT_TYPES, BarClosed, TickReceived,
                             HeartbeatReceived, ExecutionReceived,
                             SpecsUpdated, SystemStateChanged)

class TestEvents(unittest.TestCase):
    def test_bar_closed_roundtrip(self):
        e = BarClosed(symbol="EURUSD", tf="H1", bar_time="2026-07-12 10:00",
                      open=1.1, high=1.2, low=1.05, close=1.15)
        d = e.to_dict()
        self.assertEqual(d["evt"], "BarClosed")
        e2 = Event.from_dict(d)
        self.assertEqual(e, e2)

    def test_all_types_registered_and_frozen(self):
        for name, cls in EVENT_TYPES.items():
            self.assertEqual(cls.name, name)
        t = TickReceived(symbol="XAUUSD", bid=2400.5)
        with self.assertRaises(Exception):
            t.bid = 1.0  # frozen

    def test_from_dict_unknown_returns_none(self):
        self.assertIsNone(Event.from_dict({"evt": "NoSuchEvent", "x": 1}))

    def test_every_concrete_event_roundtrips(self):
        samples = [
            TickReceived(symbol="A", bid=1.0),
            HeartbeatReceived(balance=100.0, equity=99.0, n_positions=1, n_orders=0),
            ExecutionReceived(status="OPENED", ticket=7, symbol="A", pnl=0.0),
            SpecsUpdated(symbol="A"),
            SystemStateChanged(state="ACTIVE"),
        ]
        for e in samples:
            self.assertEqual(Event.from_dict(e.to_dict()), e)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_events -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'src.core.events'`

- [ ] **Step 3: Write the implementation**

```python
# src/core/events.py
"""Typed events for the Titan event bus (Trading OS B0).

Frozen dataclasses; JSON-scalar fields only, so every event serializes
losslessly to the event journal (the golden tape) and back.
"""
from dataclasses import dataclass, asdict, fields
from typing import ClassVar, Optional

EVENT_TYPES: dict = {}


def _register(cls):
    EVENT_TYPES[cls.name] = cls
    return cls


@dataclass(frozen=True)
class Event:
    name: ClassVar[str] = "Event"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evt"] = type(self).name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Optional["Event"]:
        target = EVENT_TYPES.get(d.get("evt"))
        if target is None:
            return None
        keys = {f.name for f in fields(target)}
        return target(**{k: v for k, v in d.items() if k in keys})


@_register
@dataclass(frozen=True)
class BarClosed(Event):
    name: ClassVar[str] = "BarClosed"
    symbol: str = ""
    tf: str = ""
    bar_time: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0


@_register
@dataclass(frozen=True)
class TickReceived(Event):
    name: ClassVar[str] = "TickReceived"
    symbol: str = ""
    bid: float = 0.0


@_register
@dataclass(frozen=True)
class HeartbeatReceived(Event):
    name: ClassVar[str] = "HeartbeatReceived"
    balance: float = 0.0
    equity: float = 0.0
    n_positions: int = 0
    n_orders: int = 0


@_register
@dataclass(frozen=True)
class ExecutionReceived(Event):
    name: ClassVar[str] = "ExecutionReceived"
    status: str = ""
    ticket: int = 0
    symbol: str = ""
    pnl: float = 0.0


@_register
@dataclass(frozen=True)
class SpecsUpdated(Event):
    name: ClassVar[str] = "SpecsUpdated"
    symbol: str = ""


@_register
@dataclass(frozen=True)
class SystemStateChanged(Event):
    name: ClassVar[str] = "SystemStateChanged"
    state: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_events -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Full suite, then commit**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | grep -E "^(Ran|OK|FAILED)"`
Expected: `Ran 195 tests` … `OK`

```bash
git add src/core/events.py tests/unit/test_events.py
git commit -m "feat(b0): typed event dataclasses + registry (golden-tape schema)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: EventBus

**Files:**
- Create: `src/core/bus.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `src.core.events.Event`.
- Produces: `EventBus(logger=None, max_failures=5)` with `subscribe(event_cls, handler, name=None)`, `subscribe_all(handler, name=None)`, `publish(event) -> int` (count delivered), `stats() -> dict` (per-subscriber delivered/failed/circuit_open). Sync handlers called inline in subscription order; async handlers scheduled with `asyncio.get_running_loop().create_task` when a loop is running, else skipped and counted (`no_loop_drops`). A subscriber raising `max_failures` times consecutively is circuit-opened (skipped thereafter); one log line via `logger.log_event("ERROR", "BUS", ...)` if a logger was given.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_bus.py
import unittest
from src.core.bus import EventBus
from src.core.events import TickReceived, BarClosed

class TestEventBus(unittest.TestCase):
    def test_typed_delivery_in_order(self):
        bus, seen = EventBus(), []
        bus.subscribe(TickReceived, lambda e: seen.append(("a", e.bid)))
        bus.subscribe(TickReceived, lambda e: seen.append(("b", e.bid)))
        bus.subscribe(BarClosed, lambda e: seen.append(("c", 0)))
        n = bus.publish(TickReceived(symbol="X", bid=1.5))
        self.assertEqual(n, 2)
        self.assertEqual(seen, [("a", 1.5), ("b", 1.5)])

    def test_subscribe_all_receives_everything(self):
        bus, seen = EventBus(), []
        bus.subscribe_all(lambda e: seen.append(type(e).name))
        bus.publish(TickReceived(symbol="X", bid=1.0))
        bus.publish(BarClosed(symbol="X", tf="H1"))
        self.assertEqual(seen, ["TickReceived", "BarClosed"])

    def test_throwing_subscriber_is_isolated_and_circuit_broken(self):
        bus, ok = EventBus(max_failures=3), []
        def bad(e): raise RuntimeError("boom")
        bus.subscribe(TickReceived, bad, name="bad")
        bus.subscribe(TickReceived, lambda e: ok.append(1), name="good")
        for _ in range(5):
            bus.publish(TickReceived(symbol="X", bid=1.0))  # must not raise
        self.assertEqual(len(ok), 5)               # good never starved
        st = bus.stats()["bad"]
        self.assertTrue(st["circuit_open"])
        self.assertEqual(st["failed"], 3)          # skipped after 3 failures

    def test_success_resets_failure_count(self):
        bus = EventBus(max_failures=3)
        flaky_state = {"n": 0}
        def flaky(e):
            flaky_state["n"] += 1
            if flaky_state["n"] % 2 == 1:
                raise RuntimeError("odd call fails")
        bus.subscribe(TickReceived, flaky, name="flaky")
        for _ in range(10):
            bus.publish(TickReceived(symbol="X", bid=1.0))
        self.assertFalse(bus.stats()["flaky"]["circuit_open"])

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest tests.unit.test_bus -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.bus'`

- [ ] **Step 3: Write the implementation**

```python
# src/core/bus.py
"""Typed in-process event bus (Trading OS B0).

Sync handlers run inline in subscription order — deterministic within a
bar cycle. A misbehaving subscriber can only hurt itself: exceptions are
swallowed, counted, and circuit-broken after `max_failures` consecutive
failures. Async handlers are fire-and-forget fan-out (non-critical
consumers only).
"""
import asyncio
import inspect


class _Sub:
    __slots__ = ("handler", "name", "is_async", "delivered", "failed",
                 "consecutive", "circuit_open")

    def __init__(self, handler, name):
        self.handler = handler
        self.name = name or getattr(handler, "__name__", "anon")
        self.is_async = inspect.iscoroutinefunction(handler)
        self.delivered = 0
        self.failed = 0
        self.consecutive = 0
        self.circuit_open = False


class EventBus:
    def __init__(self, logger=None, max_failures=5):
        self._by_type = {}      # event class -> [_Sub]
        self._all = []          # [_Sub]
        self._logger = logger
        self._max_failures = max_failures
        self.no_loop_drops = 0

    def subscribe(self, event_cls, handler, name=None):
        self._by_type.setdefault(event_cls, []).append(_Sub(handler, name))

    def subscribe_all(self, handler, name=None):
        self._all.append(_Sub(handler, name))

    def publish(self, event) -> int:
        delivered = 0
        for sub in self._by_type.get(type(event), []) + self._all:
            if sub.circuit_open:
                continue
            if sub.is_async:
                try:
                    asyncio.get_running_loop().create_task(sub.handler(event))
                    sub.delivered += 1
                    delivered += 1
                except RuntimeError:
                    self.no_loop_drops += 1
                continue
            try:
                sub.handler(event)
                sub.delivered += 1
                sub.consecutive = 0
                delivered += 1
            except Exception as e:
                sub.failed += 1
                sub.consecutive += 1
                if sub.consecutive >= self._max_failures:
                    sub.circuit_open = True
                    if self._logger:
                        self._logger.log_event(
                            "ERROR", "BUS",
                            f"subscriber '{sub.name}' circuit-opened after "
                            f"{sub.consecutive} failures: {e}")
        return delivered

    def stats(self) -> dict:
        out = {}
        for subs in list(self._by_type.values()) + [self._all]:
            for s in subs:
                out[s.name] = {"delivered": s.delivered, "failed": s.failed,
                               "circuit_open": s.circuit_open}
        return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_bus -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Full suite, commit**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | grep -E "^(Ran|OK|FAILED)"`
Expected: `Ran 199 tests` … `OK`

```bash
git add src/core/bus.py tests/unit/test_bus.py
git commit -m "feat(b0): EventBus — deterministic pub/sub with subscriber circuit-breaking

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Structured JSON logger

**Files:**
- Create: `src/ops/jsonlog.py`
- Test: `tests/unit/test_jsonlog.py`

**Interfaces:**
- Produces: `JsonLogger(dir_path, name="titan")` with `log(level, domain, event, msg="", **fields)` writing one JSON line `{ts, level, domain, event, msg, ...fields}` to `<dir>/<name>-YYYYMMDD.jsonl` (UTC date; file switches automatically when the date changes), `bind(**ctx) -> BoundLogger` whose `log(...)` merges bound ctx, `drops` counter (writes that failed silently). Every write is flushed.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_jsonlog.py
import json, tempfile, unittest
from pathlib import Path
from src.ops.jsonlog import JsonLogger

class TestJsonLogger(unittest.TestCase):
    def test_writes_one_json_line_with_schema(self):
        with tempfile.TemporaryDirectory() as d:
            jl = JsonLogger(d)
            jl.log("INFO", "core", "boot", msg="hello", answer=42)
            files = list(Path(d).glob("titan-*.jsonl"))
            self.assertEqual(len(files), 1)
            rec = json.loads(files[0].read_text().strip())
            for key in ("ts", "level", "domain", "event", "msg"):
                self.assertIn(key, rec)
            self.assertEqual(rec["answer"], 42)
            self.assertEqual(rec["event"], "boot")

    def test_bind_merges_context(self):
        with tempfile.TemporaryDirectory() as d:
            jl = JsonLogger(d)
            child = jl.bind(bar_cycle_id="EURUSD:H1:t0")
            child.log("INFO", "bus", "publish")
            rec = json.loads(next(Path(d).glob("*.jsonl")).read_text().strip())
            self.assertEqual(rec["bar_cycle_id"], "EURUSD:H1:t0")

    def test_unserializable_field_never_raises(self):
        with tempfile.TemporaryDirectory() as d:
            jl = JsonLogger(d)
            jl.log("INFO", "x", "y", weird=object())  # must not raise
            self.assertEqual(jl.drops, 0)  # coerced via default=str, not dropped

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m unittest tests.unit.test_jsonlog -v` → `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/ops/jsonlog.py
"""Structured JSONL logging (Trading OS B0).

One JSON object per line; date-partitioned files; never raises into the
caller (a logging failure must not touch the trading loop).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path


class _Writer:
    def __init__(self, dir_path, name):
        self.dir = Path(dir_path)
        self.name = name
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self._day = None
        self.drops = 0

    def write(self, rec: dict):
        try:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            if self._fh is None or day != self._day:
                if self._fh:
                    self._fh.close()
                self._fh = open(self.dir / f"{self.name}-{day}.jsonl", "a",
                                encoding="utf-8")
                self._day = day
            self._fh.write(json.dumps(rec, default=str) + "\n")
            self._fh.flush()
        except Exception:
            self.drops += 1

    def close(self):
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass


class JsonLogger:
    def __init__(self, dir_path, name="titan"):
        self._w = _Writer(dir_path, name)
        self._ctx = {}

    @property
    def drops(self):
        return self._w.drops

    def bind(self, **ctx) -> "JsonLogger":
        child = JsonLogger.__new__(JsonLogger)
        child._w = self._w
        child._ctx = {**self._ctx, **ctx}
        return child

    def log(self, level, domain, event, msg="", **fields):
        rec = {"ts": time.time(), "level": level, "domain": domain,
               "event": event, "msg": msg, **self._ctx, **fields}
        self._w.write(rec)

    def close(self):
        self._w.close()
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m unittest tests.unit.test_jsonlog -v` → PASS (3 tests)

- [ ] **Step 5: Full suite, commit**

Expected: `Ran 202 tests` … `OK`

```bash
git add src/ops/jsonlog.py tests/unit/test_jsonlog.py
git commit -m "feat(b0): structured JSONL logger with date rotation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Event journal — the golden tape

**Files:**
- Create: `src/ops/event_journal.py`
- Test: `tests/unit/test_event_journal.py`

**Interfaces:**
- Consumes: `EventBus.subscribe_all`, `Event.to_dict/from_dict`, `_Writer`-style date-partitioned JSONL (reuse `src.ops.jsonlog._Writer`).
- Produces: `EventJournal(dir_path, tick_sample=50)` with `attach(bus)` (subscribes itself, name `"event_journal"`), `record(event)` (direct call, used by attach), `drops`/`written` counters; module function `iter_events(path) -> Iterator[Event | dict]` — yields reconstructed `Event`s, or the raw dict when the name is unknown (forward compatibility). `TickReceived` is sampled: only every Nth tick **per symbol** is written (N=`tick_sample`; the 1st tick of each symbol always writes).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_event_journal.py
import tempfile, unittest
from pathlib import Path
from src.core.bus import EventBus
from src.core.events import BarClosed, TickReceived, SystemStateChanged
from src.ops.event_journal import EventJournal, iter_events

class TestEventJournal(unittest.TestCase):
    def test_bus_roundtrip_golden_tape(self):
        with tempfile.TemporaryDirectory() as d:
            bus, j = EventBus(), EventJournal(d, tick_sample=1)
            j.attach(bus)
            sent = [SystemStateChanged(state="ACTIVE"),
                    BarClosed(symbol="EURUSD", tf="H1", bar_time="t1",
                              open=1.0, high=2.0, low=0.5, close=1.5),
                    TickReceived(symbol="EURUSD", bid=1.5)]
            for e in sent:
                bus.publish(e)
            tape = list(iter_events(next(Path(d).glob("events-*.jsonl"))))
            self.assertEqual(tape, sent)

    def test_tick_sampling_per_symbol(self):
        with tempfile.TemporaryDirectory() as d:
            j = EventJournal(d, tick_sample=10)
            for i in range(25):
                j.record(TickReceived(symbol="A", bid=float(i)))
            j.record(TickReceived(symbol="B", bid=99.0))  # 1st B tick writes
            tape = list(iter_events(next(Path(d).glob("events-*.jsonl"))))
            a_ticks = [e for e in tape if getattr(e, "symbol", "") == "A"]
            b_ticks = [e for e in tape if getattr(e, "symbol", "") == "B"]
            self.assertEqual(len(a_ticks), 3)   # ticks 1, 11, 21
            self.assertEqual(len(b_ticks), 1)

    def test_unknown_event_yields_raw_dict(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events-x.jsonl"
            p.write_text('{"evt": "FutureEvent", "z": 1}\n')
            out = list(iter_events(p))
            self.assertEqual(out, [{"evt": "FutureEvent", "z": 1}])

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: src.ops.event_journal`

- [ ] **Step 3: Write the implementation**

```python
# src/ops/event_journal.py
"""Event journal — the golden tape (Trading OS B0).

Subscribes to ALL bus events and appends them as JSONL. This file is the
replay source for the kernel v15.0 regression harness and the forensic
record for incidents. Ticks are sampled per symbol to bound volume.
"""
import json
from src.core.events import Event, TickReceived
from src.ops.jsonlog import _Writer


class EventJournal:
    def __init__(self, dir_path, tick_sample=50):
        self._w = _Writer(dir_path, "events")
        self._tick_sample = max(1, int(tick_sample))
        self._tick_counts = {}
        self.written = 0

    @property
    def drops(self):
        return self._w.drops

    def attach(self, bus):
        bus.subscribe_all(self.record, name="event_journal")

    def record(self, event):
        if isinstance(event, TickReceived):
            n = self._tick_counts.get(event.symbol, 0)
            self._tick_counts[event.symbol] = n + 1
            if n % self._tick_sample != 0:
                return
        self._w.write(event.to_dict())
        self.written += 1

    def close(self):
        self._w.close()


def iter_events(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            evt = Event.from_dict(d)
            yield evt if evt is not None else d
```

NOTE: `_Writer.write` adds nothing to the dict — but it serializes with `default=str`; `iter_events` equality with the sent events holds because event fields are JSON scalars (Task 1 contract). The `_Writer` records exactly `event.to_dict()` — do NOT add a `ts` wrapper in this task (replay equality is the contract; wall-time enrichment can come later as an envelope version bump).

- [ ] **Step 4: Run to verify pass** — PASS (3 tests)

- [ ] **Step 5: Full suite, commit**

Expected: `Ran 205 tests` … `OK`

```bash
git add src/ops/event_journal.py tests/unit/test_event_journal.py
git commit -m "feat(b0): event journal (golden tape) with per-symbol tick sampling + replay reader

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Health probes + sd_notify

**Files:**
- Create: `src/ops/health.py`
- Test: `tests/unit/test_health.py`

**Interfaces:**
- Produces: `HealthProbe(readiness_fn, bind="127.0.0.1", port=8787)` with async `start()`/`stop()`; serves `GET /healthz` → always `200 {"ok": true}` (loop is alive if it can answer), `GET /readyz` → `readiness_fn()` returns `(ready: bool, reasons: list[str])`; 200 with `{"ready": true}` or 503 with `{"ready": false, "reasons": [...]}`; any other path → 404. Also `sd_notify(msg: str)` module function: datagram to `$NOTIFY_SOCKET` (abstract-namespace aware: leading `@` → `\0`), silent no-op when unset; controller will send `READY=1` once ACTIVE and `WATCHDOG=1` periodically.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_health.py
import asyncio, json, os, socket, tempfile, unittest
from unittest.mock import patch
from src.ops.health import HealthProbe, sd_notify

async def _http_get(port, path):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(f"GET {path} HTTP/1.0\r\n\r\n".encode())
    await w.drain()
    data = await r.read()
    w.close()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    return status, json.loads(body) if body else {}

class TestHealthProbe(unittest.TestCase):
    def _run(self, coro):
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

    def test_healthz_readyz_and_404(self):
        async def scenario():
            state = {"ready": True, "reasons": []}
            probe = HealthProbe(lambda: (state["ready"], state["reasons"]),
                                bind="127.0.0.1", port=0)
            port = await probe.start()
            s, b = await _http_get(port, "/healthz")
            assert (s, b["ok"]) == (200, True)
            s, b = await _http_get(port, "/readyz")
            assert (s, b["ready"]) == (200, True)
            state["ready"], state["reasons"] = False, ["no heartbeat"]
            s, b = await _http_get(port, "/readyz")
            assert (s, b["reasons"]) == (503, ["no heartbeat"])
            s, _ = await _http_get(port, "/nope")
            assert s == 404
            await probe.stop()
        self._run(scenario())

    def test_readiness_fn_exception_returns_503_not_crash(self):
        async def scenario():
            def bad(): raise RuntimeError("boom")
            probe = HealthProbe(bad, bind="127.0.0.1", port=0)
            port = await probe.start()
            s, b = await _http_get(port, "/readyz")
            assert s == 503 and b["ready"] is False
            await probe.stop()
        self._run(scenario())

    def test_sd_notify_noop_without_socket_and_sends_with(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOTIFY_SOCKET", None)
            sd_notify("READY=1")  # must not raise
        with tempfile.TemporaryDirectory() as d:
            sock_path = os.path.join(d, "notify.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            srv.bind(sock_path)
            srv.settimeout(2)
            with patch.dict(os.environ, {"NOTIFY_SOCKET": sock_path}):
                sd_notify("WATCHDOG=1")
            self.assertEqual(srv.recv(64), b"WATCHDOG=1")
            srv.close()

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: src.ops.health`

- [ ] **Step 3: Write the implementation**

```python
# src/ops/health.py
"""Health probes + systemd notification (Trading OS B0).

Stdlib-only HTTP: /healthz (liveness) and /readyz (readiness via injected
callable). Replaced by the FastAPI control plane in backend phase B2; the
readiness_fn contract survives that migration.
"""
import asyncio
import json
import os
import socket


def sd_notify(msg: str):
    """Send a systemd notify datagram; silent no-op outside systemd."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            s.connect(addr)
            s.send(msg.encode())
        finally:
            s.close()
    except Exception:
        pass


class HealthProbe:
    def __init__(self, readiness_fn, bind="127.0.0.1", port=8787):
        self._readiness_fn = readiness_fn
        self._bind = bind
        self._port = port
        self._server = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle, self._bind, self._port)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            path = line.split()[1].decode() if len(line.split()) > 1 else "/"
            if path == "/healthz":
                status, body = 200, {"ok": True}
            elif path == "/readyz":
                try:
                    ready, reasons = self._readiness_fn()
                except Exception as e:
                    ready, reasons = False, [f"readiness_fn error: {e}"]
                status = 200 if ready else 503
                body = {"ready": bool(ready)}
                if not ready:
                    body["reasons"] = list(reasons)
            else:
                status, body = 404, {"error": "not found"}
            payload = json.dumps(body).encode()
            writer.write(
                f"HTTP/1.0 {status} X\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run to verify pass** — PASS (3 tests). Output must be pristine (close the event loops the tests create if warnings appear: call `loop.close()` in `_run`).

- [ ] **Step 5: Full suite, commit**

Expected: `Ran 208 tests` … `OK`

```bash
git add src/ops/health.py tests/unit/test_health.py
git commit -m "feat(b0): stdlib health probes (/healthz,/readyz) + sd_notify helper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Controller integration (publish-only) + ops config

**Files:**
- Modify: `src/core/system_controller.py` (imports; `__init__` ~line 55-118; `_process_incoming_data` ~line 328-440; `run()` ~line 130-215; `set_system_pause` ~line 658)
- Modify: `config/config.yaml` (append `ops:` block)
- Test: `tests/unit/test_controller_events.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: `self.bus` (EventBus), `self.jlog` (JsonLogger), `self.event_journal` (EventJournal or None), `self.health_probe` (HealthProbe or None), `self._readiness()` method returning `(bool, list[str])`. Publishes: `TickReceived` per TICK, `BarClosed` per closed candle, `HeartbeatReceived` per HEARTBEAT, `ExecutionReceived` per EXECUTION OPENED/CLOSED, `SpecsUpdated` when HISTORY carries specs, `SystemStateChanged` on WARMUP/ACTIVE transitions and pause toggles.

- [ ] **Step 1: Read the existing fixture pattern**

Read `tests/unit/test_controller_routing.py` first and mirror its way of instantiating/faking `SystemController` (it exercises controller methods without a live bridge). Build tests on the same pattern — typically `SystemController.__new__(SystemController)` plus setting only the attributes the method under test touches.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_controller_events.py
"""Verifies the B0 publish-only integration: processing bridge messages
publishes the corresponding typed events, and trading behavior is
untouched (publishes are additive)."""
import asyncio, unittest
from unittest.mock import MagicMock
from src.core.system_controller import SystemController, BotState
from src.core.bus import EventBus
from src.core.events import (TickReceived, HeartbeatReceived,
                             ExecutionReceived, SpecsUpdated, BarClosed)

def make_controller():
    c = SystemController.__new__(SystemController)
    c.bus = EventBus()
    c.state = BotState.PAUSED          # TICK branch: no candle processing
    c.live_prices = {}
    c.current_open_positions = []
    c.current_pending_orders = []
    c.market_data = {}
    c.risk_manager = MagicMock()
    c.state_manager = MagicMock()
    c.state_manager.exists.return_value = True
    c.telemetry = MagicMock()
    c.telemetry.notify_execution = _async_noop
    c.telemetry.notify_close = _async_noop
    c.pending_signal_meta = {}
    c.daily_closed_trades = []
    from datetime import datetime
    c.last_heartbeat_time = datetime.now()
    return c

async def _async_noop(*a, **k): pass

def capture(bus, evt_cls):
    seen = []
    bus.subscribe(evt_cls, seen.append)
    return seen

class TestControllerPublishes(unittest.TestCase):
    def _process(self, c, msg):
        asyncio.new_event_loop().run_until_complete(c._process_incoming_data(msg))

    def test_tick_publishes_tick_event(self):
        c = make_controller()
        seen = capture(c.bus, TickReceived)
        self._process(c, {"type": "TICK", "s": "EURUSD", "b": 1.09})
        self.assertEqual(seen, [TickReceived(symbol="EURUSD", bid=1.09)])
        self.assertEqual(c.live_prices["EURUSD"], 1.09)   # behavior untouched

    def test_heartbeat_publishes(self):
        c = make_controller()
        seen = capture(c.bus, HeartbeatReceived)
        self._process(c, {"type": "HEARTBEAT", "bal": 100.0, "eq": 99.5,
                          "pos": [], "orders": []})
        self.assertEqual(seen, [HeartbeatReceived(balance=100.0, equity=99.5,
                                                  n_positions=0, n_orders=0)])

    def test_history_with_specs_publishes_specs_updated(self):
        c = make_controller()
        c.market_data = {"XAUUSD": MagicMock()}
        seen = capture(c.bus, SpecsUpdated)
        self._process(c, {"type": "HISTORY", "symbol": "XAUUSD", "tf": "H1",
                          "data": [], "tv": 1.0, "ts": 0.01, "vm": 0.01, "vs": 0.01})
        self.assertEqual(seen, [SpecsUpdated(symbol="XAUUSD")])

    def test_execution_closed_publishes(self):
        c = make_controller()
        c.state_manager.get_order.return_value = None   # unknown ticket: no crash
        seen = capture(c.bus, ExecutionReceived)
        self._process(c, {"type": "EXECUTION", "status": "CLOSED",
                          "ticket": 7, "s": "EURUSD", "pn": 3.2})
        self.assertEqual(seen, [ExecutionReceived(status="CLOSED", ticket=7,
                                                  symbol="EURUSD", pnl=3.2)])

if __name__ == "__main__":
    unittest.main()
```

(If `make_controller()` needs additional attributes to satisfy untouched code paths, add them — the test contract is the published events plus one untouched-behavior assertion. Follow `test_controller_routing.py`'s prior art. A `BarClosed` publish test is required too IF the existing routing test's fixtures make the candle path reachable without a full MultiTimeframeStore; otherwise document it as covered by the journal smoke in Task 7.)

- [ ] **Step 3: Run to verify failure** — events not yet published → assertion failures.

- [ ] **Step 4: Implement the integration**

In `src/core/system_controller.py`:

(a) Imports:

```python
from src.core.bus import EventBus
from src.core.events import (TickReceived, BarClosed, HeartbeatReceived,
                             ExecutionReceived, SpecsUpdated, SystemStateChanged)
from src.ops.jsonlog import JsonLogger
from src.ops.event_journal import EventJournal
from src.ops.health import HealthProbe, sd_notify
```

(b) In `__init__`, after `self.signal_grader = SignalGrader(self.config)`:

```python
        # --- Trading OS B0: bus, structured log, golden tape ---
        ops_cfg = self.config.get('ops', {})
        self.bus = EventBus(logger=self.logger)
        self.jlog = JsonLogger(str(self.root_dir / "data" / "logs"))
        j_cfg = ops_cfg.get('journal', {})
        self.event_journal = None
        if j_cfg.get('enabled', True):
            self.event_journal = EventJournal(
                str(self.root_dir / j_cfg.get('dir', 'data/journal')),
                tick_sample=j_cfg.get('tick_sample', 50))
            self.event_journal.attach(self.bus)
        self.health_probe = None
        self._health_cfg = ops_cfg.get('health', {})
```

(c) In `_process_incoming_data`, insert publishes (additive; existing lines untouched):
- HISTORY branch, inside `if 'tv' in msg:` after `update_symbol_specs(...)`: `self.bus.publish(SpecsUpdated(symbol=sym))`
- EXECUTION branch, first thing after `status = msg.get('status')`:

```python
            self.bus.publish(ExecutionReceived(
                status=str(status or ""), ticket=int(msg.get('ticket', 0) or 0),
                symbol=str(msg.get('s', '') or ''), pnl=float(msg.get('pn', 0.0) or 0.0)))
```

- TICK branch, right after `self.live_prices[symbol] = float(msg.get('b', 0))`:

```python
            self.bus.publish(TickReceived(symbol=symbol, bid=self.live_prices[symbol]))
```

- inside the `for tf, df in closed_candles:` loop, before `await self._run_strategies(...)`:

```python
                    last = df.iloc[-1]
                    self.bus.publish(BarClosed(
                        symbol=symbol, tf=tf, bar_time=str(last.get('time', df.index[-1])),
                        open=float(last.get('open', 0.0)), high=float(last.get('high', 0.0)),
                        low=float(last.get('low', 0.0)), close=float(last.get('close', 0.0))))
```

- HEARTBEAT branch, after `self.current_pending_orders = msg.get('orders', [])`:

```python
            self.bus.publish(HeartbeatReceived(
                balance=bal, equity=eq,
                n_positions=len(self.current_open_positions),
                n_orders=len(self.current_pending_orders)))
```

(d) In `run()`: publish `SystemStateChanged(state="WARMUP")` right after `self.state = BotState.WARMUP`; after `self.state = BotState.ACTIVE` publish `SystemStateChanged(state="ACTIVE")` and add:

```python
        # systemd + health probe (B0)
        sd_notify("READY=1")
        if self._health_cfg.get('enabled', True):
            try:
                self.health_probe = HealthProbe(
                    self._readiness,
                    bind=self._health_cfg.get('bind', '127.0.0.1'),
                    port=int(self._health_cfg.get('port', 8787)))
                await self.health_probe.start()
            except Exception as e:
                self.logger.log_event("ERROR", "HEALTH", f"probe start failed: {e}")
```

In the main `while True:` loop, alongside the 10s PING block (same cadence gate), add `sd_notify("WATCHDOG=1")`.

(e) In `set_system_pause`, publish `SystemStateChanged(state="PAUSED" if p else "ACTIVE")`.

(f) Add `_readiness` method:

```python
    def _readiness(self):
        reasons = []
        age = (datetime.now() - self.last_heartbeat_time).total_seconds()
        if age > 30:
            reasons.append(f"heartbeat stale ({age:.0f}s)")
        if self.state not in (BotState.ACTIVE, BotState.PAUSED):
            reasons.append(f"state={self.state.name}")
        for sym in self.active_symbols:
            if not self.risk_manager.has_specs(sym) if hasattr(self.risk_manager, 'has_specs') else False:
                reasons.append(f"no specs: {sym}")
        return (not reasons, reasons)
```

IMPORTANT: check whether `RiskManager` exposes a spec-presence check (look for the dict `update_symbol_specs` writes into). If there is a clean attribute (e.g. `self.symbol_specs`), test membership directly instead of the `has_specs` hasattr dance — write it cleanly against what exists; do not add methods to RiskManager in this task.

(g) Append to `config/config.yaml`:

```yaml

ops:
  journal:
    enabled: true
    dir: data/journal
    tick_sample: 50
  health:
    enabled: true
    bind: 127.0.0.1
    port: 8787
```

- [ ] **Step 5: Run the new tests, then the full suite**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_events -v` → PASS
Run: full suite → `Ran 212 tests` (approx: 208 + new controller tests) … `OK`. **Every pre-existing test must still pass unmodified** — if any existing controller test breaks, your integration was not publish-only; fix the integration, not the test.

- [ ] **Step 6: Commit**

```bash
git add src/core/system_controller.py config/config.yaml tests/unit/test_controller_events.py
git commit -m "feat(b0): controller publishes typed events; golden tape + health probe wired (publish-only)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: systemd units + runbook + tape smoke

**Files:**
- Create: `deploy/systemd/titan-live.service`, `deploy/systemd/titan-demo.service`, `docs/runbooks/deploy-systemd.md`

**Interfaces:**
- Consumes: `sd_notify` behavior from Task 5/6 (`READY=1` on ACTIVE, `WATCHDOG=1` every 10s).

- [ ] **Step 1: Write the unit files**

```ini
# deploy/systemd/titan-live.service
[Unit]
Description=Titan trading engine (LIVE)
After=network-online.target

[Service]
Type=notify
NotifyAccess=main
WorkingDirectory=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro
ExecStart=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python main.py
Restart=on-failure
RestartSec=10
WatchdogSec=90
MemoryMax=2G
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```ini
# deploy/systemd/titan-demo.service
[Unit]
Description=Titan trading engine (DEMO stage — separate checkout, own ports/DBs)
After=network-online.target

[Service]
Type=notify
NotifyAccess=main
# NOTE: point at a SEPARATE demo checkout before enabling (see runbook).
WorkingDirectory=/home/kiyingijmc/projects/Titan_demo
ExecStart=/home/kiyingijmc/projects/Titan_demo/.venv/bin/python main.py
Restart=on-failure
RestartSec=10
WatchdogSec=90
MemoryMax=2G
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Write the runbook** — `docs/runbooks/deploy-systemd.md` containing: prerequisites (WSL systemd enabled: `[boot] systemd=true` in `/etc/wsl.conf`); install (`sudo cp deploy/systemd/titan-live.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now titan-live`); watchdog semantics (READY on ACTIVE; WATCHDOG=1 every 10s; systemd restarts after 90s silence — a wedged loop self-heals); health checks (`curl -s localhost:8787/readyz`); demo-stage caveats (separate checkout, different ZMQ ports in its config, FBS-Demo login, never share the live terminal); log access (`journalctl -u titan-live -f`); rollback (`systemctl stop` + git checkout of previous tag). Keep it under 60 lines.

- [ ] **Step 3: Verify units parse (best effort)**

Run: `systemd-analyze verify deploy/systemd/titan-live.service 2>&1 | head -5 || echo "systemd-analyze unavailable — skipped"`
Expected: no fatal errors (warnings about WorkingDirectory not existing for demo are acceptable and expected).

- [ ] **Step 4: Golden-tape smoke (end-to-end, no MT5)**

Run this exact snippet and include output in the report:

```bash
.venv/bin/python - <<'EOF'
import asyncio, glob, tempfile
from src.core.bus import EventBus
from src.core.events import BarClosed, TickReceived
from src.ops.event_journal import EventJournal, iter_events
d = tempfile.mkdtemp()
bus = EventBus(); j = EventJournal(d, tick_sample=10); j.attach(bus)
for i in range(100):
    bus.publish(TickReceived(symbol="EURUSD", bid=1.0 + i/1000))
bus.publish(BarClosed(symbol="EURUSD", tf="H1", bar_time="t", open=1, high=2, low=0.5, close=1.5))
tape = list(iter_events(glob.glob(d + "/events-*.jsonl")[0]))
print("written:", j.written, "drops:", j.drops, "tape length:", len(tape),
      "last:", type(tape[-1]).__name__)
assert j.drops == 0 and type(tape[-1]).__name__ == "BarClosed"
print("GOLDEN TAPE SMOKE: OK")
EOF
```

Expected: `written: 11 drops: 0 tape length: 11 last: BarClosed` then `GOLDEN TAPE SMOKE: OK`.

- [ ] **Step 5: Full suite one final time, commit**

```bash
git add deploy/systemd/ docs/runbooks/deploy-systemd.md
git commit -m "feat(b0): systemd units (live+demo, Type=notify watchdog) + deploy runbook

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Definition of done (Plan 02)

1. Suite green with all new tests (≈212+), zero pre-existing tests modified.
2. Golden-tape smoke passes (Task 7 Step 4 output captured).
3. `git diff` shows `_process_incoming_data`/`run()` changes are insert-only (no deleted/reordered pre-existing statements) — the final reviewer verifies this property explicitly.
4. Unit files parse; runbook exists.
5. Unblocks kernel v15.0: `iter_events` + `EventBus` are the replay harness's inputs.
