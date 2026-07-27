---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S006"
date:          "2026-07-27"
slug:          "m0-5-tradebot-core-bus-py"
parent_session: "none"
task_domain:   "infra"
spec_state:    "approved"
needs:         "m0-2-tradebot-core-clock-py"            # advisory cross-track dep (ADR-031)
status:        "DONE"
---

# titan-ict-bot — Session S006 · 2026-07-27 · "m0-5-tradebot-core-bus-py"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** M0-5: `tradebot/core/bus.py` (schema-keyed sync bus + critical tier) + `core/sta.py` STA skeleton

**Why it matters / what it unblocks:** Closes the last M0-3/M0-4 dependency chain link (`event_log.py`'s own note: the RS003 "Envelope unhashable" landmine "lands in core/bus.py's pub/sub dedup path, M0-5") and gives every future subsystem (risk, OMS, journal) a typed, deterministic delivery channel plus the single-serialization-point actor pass3 §2.1 requires before any signal lifecycle can be built.

**Exact scope (what "doing this task" means):**
- Add `tradebot/core/bus.py`: ADAPT `src/core/bus.py`'s `EventBus` (sync, in-subscription-order delivery; `stats()`) onto `tradebot.core.events.Envelope`:
  - Dispatch key is `envelope.schema` (str), not `type(event)` — every tradebot event is an `Envelope` instance differentiated by `.schema` (`tradebot/core/events.py:154-165`), unlike `src/core/bus.py`'s one-Python-class-per-event model. `subscribe(schema: str, handler, name=None, tier="normal")` and `subscribe_all(handler, name=None)` (receives every envelope regardless of schema).
  - Two subscriber tiers, `"normal"` and `"critical"`: `normal` keeps today's behavior verbatim (exception caught, counted, circuit-opens after `max_failures` consecutive failures, never raises). `critical` is never circuit-broken and never swallows — an exception is logged CRITICAL (mirroring the existing `logger.log_event(...)` call shape) then re-raised out of `publish()`, halting delivery to any remaining subscribers for that call ("halt+alert" per the backlog line).
  - `publish(envelope) -> int` stays sync; `stats()` keeps its `{delivered, failed, circuit_open}` shape per subscriber name, extended with `tier`.
  - Drop the async fire-and-forget branch (`inspect.iscoroutinefunction`, `no_loop_drops`, `create_task`) — the §6.1 tree entry describes only "typed sync in-order bus, per-sub stats/circuit" and nothing in `tradebot/` consumes an async path yet (no `controller.py`).
- **Actually fix the RS003 MINOR attributed to this session** ("`Envelope` is unhashable" — `RS003.md:132-145`, `S004 archive:43`). Verified still live on main: `@dataclass(frozen=True)` (`tradebot/core/events.py:153`) auto-generates `__hash__` over every field including `payload: dict`, so `hash(env)` and `{env}` both raise `TypeError: unhashable type: 'dict'`.
  - The fix is one line in `tradebot/core/events.py`, and `field` is already imported there (`:23`): change `payload: dict` to `payload: dict = field(hash=False)`, excluding it from the generated `__hash__` while keeping it in `__eq__`. Every remaining field is already hashable (`str`/`int`/`tuple`/`None`). `field()` with no default keeps `payload` required, so declaration order is unaffected. Two envelopes differing only in payload then hash equal but compare unequal — a legal collision, not a defect.
  - This is a deliberate, narrow exception to the "don't touch `events.py`" fence below: making the bus merely *avoid* hashing would leave the crash armed for every future consumer (OMS, journal, risk, any M1+ dedup), while letting the ledger record the finding as closed. Do not widen it — this one field declaration and its test, nothing else in `events.py`.
  - Add the proof to `tests/unit/test_tradebot_events.py`: `hash(envelope)` returns an int and `{envelope}` / `{envelope: "v"}` both succeed; two envelopes differing only in `payload` remain `!=`.
- Add `tradebot/core/sta.py`: a **skeleton** Signal Transition Actor per pass3-systems.md §2.1's "Single transition owner (F-008 mechanism)" paragraph, generic and schema-agnostic (no `SigState`/`TransitionCause`/`signal.*` schemas exist yet — M1+):
  - One in-process FIFO `asyncio.Queue` of transition requests; a single-consumer loop processes exactly one request at a time (no concurrent handler execution).
  - A request carries a guard callable (evaluated **inside** the handler at processing time, per §2.1) and an apply callable building an `Envelope`; guard-fail resolves to a generic rejected/"race_loser" outcome instead of raising (mirrors "losing requests emit `confirm.resolved.race_losers`" without inventing that concrete schema).
  - Takes an injected `tradebot.core.bus.EventBus` (this session's own module) and publishes an accepted transition's `Envelope` through it.
  - FIFO ordering is provable under concurrent `submit()` calls.
- Add `tests/unit/test_tradebot_bus.py` (flat): schema-keyed dispatch, `subscribe_all` fan-out, normal-tier circuit-breaking (ported from `tests/unit/test_bus.py`), critical-tier halt-on-exception. The Envelope-hashing regression belongs in `test_tradebot_events.py` per §2 — do NOT instead monkeypatch `Envelope.__hash__` to raise and assert the bus never calls it; that would prove only that this one caller avoids the defect, which is exactly the evasion this session exists to end.
- Add `tests/unit/test_tradebot_sta.py` (flat): FIFO ordering under concurrent submits, single-consumer serialization, guard-fail → race-loser outcome (no exception), guard-pass → `apply()` result published through a real `EventBus` and observed by a subscriber.

**Explicitly OUT of scope (do NOT touch this session):**
- Any concrete `signal.*` schema / `SigState` / `TransitionCause` enum, or the full §2.1 28-row signal lifecycle table — no risk engine, OMS, or child strategies exist yet.
- `tradebot/core/controller.py` (asyncio composition root) — separate, not-yet-built module.
- Any change to `tradebot/core/event_log.py`, `projection.py`, `recovery.py`, `clock.py`, `config/schema.py`. `events.py` is off-limits too **except** for the single `payload: dict = field(hash=False)` declaration named in §2 — no other edit to that module.
- Any change to `src/core/bus.py` or anything under `src/`, `config/config.yaml`, `main.py` — `tradebot/` stays independent (prior art by shape only).
- Re-adding the async fire-and-forget subscriber path or a `no_loop_drops`-style counter.
- Real alerting/Telegram delivery for the critical-tier "alert" half — a structured CRITICAL log line only; no `ops/` package exists in `tradebot/` yet.
- Wiring risk/OMS/journal as actual critical subscribers — this session proves the mechanism only.

**Relevant project docs / decisions:** pass3-systems.md §2.1 (Signal lifecycle / STA mechanism), §6.1 (repo tree — bus.py ADAPT, sta.py REBUILD verdicts), §6.2 (v15 event bus ADAPT rationale); pass1-audit.md F-008; RS003.md (Envelope-unhashable MINOR finding); S004 archive (finding attribution to M0-5)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `tradebot/core/bus.py` exists; importable via `.venv/bin/python -c "import tradebot.core.bus"`; no new third-party dependency.
- [ ] `tradebot/core/sta.py` exists; importable via `.venv/bin/python -c "import tradebot.core.sta"`; imports only `tradebot.core.bus`/`tradebot.core.events` + stdlib.
- [ ] `EventBus` dispatches by `envelope.schema`; two envelopes of different schemas reach only their own schema-subscribers, and `subscribe_all` receives both.
- [ ] Normal-tier subscriber: exception swallowed, counted, circuit-opens after `max_failures` consecutive failures (ported `test_bus.py` assertions pass against the new module).
- [ ] Critical-tier subscriber: exception logged CRITICAL and re-raised out of `publish()`; repeated failures never set `circuit_open` for that subscriber.
- [ ] `hash(envelope)` returns an int and `{envelope}` / `{envelope: "v"}` both succeed — i.e. the RS003 MINOR is closed at the source, in `events.py`, not merely avoided by this one caller. Two envelopes differing only in `payload` still compare unequal.
- [ ] `tradebot/core/events.py`'s diff for this session is the single `payload` field declaration and nothing else.
- [ ] No async fire-and-forget branch present in `tradebot/core/bus.py`.
- [ ] `SignalTransitionActor` processes exactly one queued request at a time in FIFO enqueue order under concurrent `submit()`.
- [ ] Failed guard resolves to a race-loser-style outcome without raising; passed guard's `apply()` result is published through an injected `EventBus` and observed by a subscriber in the test.
- [ ] `tests/unit/test_tradebot_bus.py` and `tests/unit/test_tradebot_sta.py` are flat under `tests/unit/` (no `tests/unit/tradebot/` package).
- [ ] `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` passes clean; test count strictly increases over the pre-session baseline; zero regressions to any existing test.
- [ ] No files under `src/`, `config/config.yaml`, `main.py`, `tradebot/core/event_log.py`, `projection.py`, `recovery.py`, `clock.py`, `controller.py` touched (`events.py` only as bounded above).
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
