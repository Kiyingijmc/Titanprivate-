---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S003"
date:          "2026-07-27"
slug:          "m0-2-tradebot-core-clock-py"
parent_session: "none"
task_domain:   "models"
spec_state:    "approved"
needs:         "m0-1-tradebot-skeleton-top-level"            # advisory cross-track dep (ADR-031)
status:        "DONE"
---

# titan-ict-bot — Session S003 · 2026-07-27 · "m0-2-tradebot-core-clock-py"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** M0-2: `tradebot/core/clock.py` (Clock protocol, LiveClock, SimClock) + `tradebot/core/events.py` (§1 envelope, registry, canonical JSON, upcasters)

**Why it matters / what it unblocks:** Every later M0 piece — the chained event log (M0-3), projections/recovery (M0-4), the adapted bus (M0-5) — depends on a fixed event shape and a time source; without them nothing downstream has a contract to build against, and the backtest/live parity promise (pass3 §5.1: "same engine, zero drift") hinges on `Clock` being the only place live vs. sim time diverges.

**Exact scope (what "doing this task" means):**
- Create `tradebot/core/__init__.py` + `tradebot/core/clock.py`:
  - A `Clock` protocol (pass3-systems.md:446) with `now_ns() -> int` and `call_at(ts_ns: int, cb: Callable[[], None]) -> <cancel handle>`.
  - `LiveClock`: at construction, anchors `time.monotonic_ns()` to `time.time_ns()` once (F-033 discipline: "comparisons inside the core use monotonic; wall time only at edges" — pass3-systems.md:22,446,665). `now_ns()` returns `wall_anchor + (monotonic_ns() - monotonic_anchor)`, so a backward jump in system wall-clock never makes `now_ns()` go backward. **Out of scope**: LiveClock does not itself query NTP servers — NTP discipline is the OS's job (chrony/w32tm) and offset *monitoring* is `ops/health.py` (Pass 6, not yet built); "NTP" in LiveClock's name means "wall-anchored," not "does its own NTP handshake." No new dependency (no `ntplib`).
  - `SimClock`: virtual time, starts at a given `ts_ns`. `now_ns()` returns the current virtual time. `call_at` enqueues `(ts_ns, cb)` in a deterministic (ts, insertion-order) priority queue. An `advance_to(ts_ns)` (or `advance_by(delta_ns)`) method moves virtual time forward and fires all due callbacks in `(ts_ns, insertion-order)` sequence — no dependency on `time.time()`/`time.monotonic()` at all, so it is reproducible under mocked or frozen wall-clock.
- Create `tradebot/core/events.py` implementing pass3-systems.md §1.1's envelope, **minus** the two fields the sole writer computes (`prev_hash`/`row_hash` — pass3-systems.md:29-30, explicitly `event_log.py`'s job, M0-3):
  - A frozen `Envelope` dataclass/model with: `event_id` (uuid7), `schema: str` (dotted, e.g. `market.candle_closed`), `schema_version: int`, `ts_event: int`, `ts_ingest: int`, `correlation_id: str | None`, `parent_ids: tuple[str, ...]` (default empty), `idempotency_key: str | None`, `actor: str`, `payload: dict`, plus `seq: int | None = None` (log-assigned later, per pass3-systems.md:18).
  - `event_id` generation: a minimal stdlib-only RFC 9562 UUIDv7 generator (`time.time_ns()` + `os.urandom`) — no new third-party dependency (no `uuid6`/`uuid7` package).
  - A schema registry: `register(schema: str, version: int)` decorator (or equivalent function) mapping `(schema, schema_version)` → payload type, following the existing `src/core/events.py` `EVENT_TYPES`/`_register`/`from_dict` pattern as prior art for shape only — **do not import from or extend `src/core/events.py`**; this is an independent module (`tradebot/` must not depend on `src/`, per `tradebot/config/schema.py`'s own docstring rule).
  - `canonical_json(payload: dict) -> str|bytes`: sorted keys, raises on `NaN`/`Infinity`, numerics normalized (int-valued floats emitted as ints, no exponent notation, `-0` → `0`) — the exact F-038 rule already documented for `params_hash` (pass3-systems.md:28,363), reused here for envelope payloads (this module owns the canonicalizer; `features/registry.py`'s future `params_hash` reuses it — do not reimplement it there later).
  - Upcasters: a registration mechanism mapping `(schema, from_version)` → an upgrade function to the next version; decoding a payload registered at an older `schema_version` chains upcasters until it reaches the schema's current registered version.
- Add `tests/unit/test_tradebot_clock.py` and `tests/unit/test_tradebot_events.py` (picked up by `VERIFY_CMD`'s `discover -s tests/unit`). **These MUST live flat under `tests/unit/`, NOT in a `tests/unit/tradebot/` package** — a test package named `tradebot` shadows the real top-level `tradebot` package during `unittest discover -s tests/unit`, so `import tradebot.core.clock` would resolve to the test package and every case would error on import. This is settled precedent: see the "NOTE ON LOCATION" docstring in `tests/unit/test_config_schema.py` (S001, where RS001 accepted the same deviation):
  - LiveClock: monkeypatch `time.time`/`time.time_ns` to jump backward between two `now_ns()` calls and assert the result is still non-decreasing (monotonic-core insulation).
  - SimClock: register `call_at` callbacks out of chronological order, `advance_to` past all of them, assert firing order is strictly by `ts_ns` (ties broken by insertion order) and reproducible across two fresh `SimClock` instances fed the identical schedule.
  - Envelope/canonical JSON: `{"n": 20}` and `{"n": 20.0}` canonicalize to byte-identical output (mirrors the already-documented P7 params_hash test in pass3-systems.md:585, now proven at the envelope layer); a payload containing `NaN`/`Infinity` raises.
  - Determinism acceptance (the backlog's literal bar): construct a fixed (non-random) list of `Envelope`s, serialize the identical stream twice end-to-end (encode → decode via registry → re-encode) and assert byte-identical output both passes.
  - Upcasting: register schema versions 1 and 2 for one dummy schema with an upcaster 1→2; decoding a v1-shaped payload through the registry yields the v2 shape.

**Explicitly OUT of scope (do NOT touch this session):**
- `tradebot/core/event_log.py` (sole-writer chained SQLite log, `prev_hash`/`row_hash` computation, snapshots, archive, backup/restore-verify) — M0-3.
- `tradebot/core/projection.py`, `tradebot/core/recovery.py` — M0-4.
- `tradebot/core/bus.py` (ADAPT of `src/core/bus.py`) and `tradebot/core/sta.py` — M0-5.
- Any actual NTP-offset querying/monitoring (`ops/health.py`, Pass 6) — LiveClock only anchors monotonic-to-wall at boot, it does not measure or alarm on drift.
- `params_hash` itself (`features/registry.py`, M1) — only the shared `canonical_json` helper it will consume is built here.
- Any change to the existing, unrelated `src/core/events.py` / `src/core/time_engine.py` (legacy Titan v14 "Trading OS B0" bus events) or any other file under `src/`, `config/config.yaml`, `main.py`.
- Any change to `tradebot/config/schema.py` (M0-1, already DONE) or `tradebot/pyproject.toml` beyond adding no new dependency (none is needed for this session).
- `tradebot/core/controller.py` and any real asyncio wiring/timer usage of `Clock` — later milestones; this session only needs `Clock`/`LiveClock`/`SimClock` to satisfy the protocol and the determinism tests above.

**Relevant project docs / decisions:** brainstorm-v2/pass3-systems.md §1.1 (envelope), §4.2/P7 (canonical JSON, F-038), §5.1/§5.5 (Clock protocol, determinism), §6.1 (repo tree — clock.py/events.py both [R]); pass1-audit.md F-033, F-038; pass8-synthesis.md line 224 (M0 scope grouping); prior art `src/core/events.py` (shape only, not imported)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `tradebot/core/clock.py` exists; `Clock` protocol + `LiveClock` + `SimClock` all importable via `.venv/bin/python -c "import tradebot.core.clock"` with no errors.
- [ ] `tradebot/core/events.py` exists; `Envelope`, registry, `canonical_json`, upcaster mechanism all importable with no errors; module does not import anything from `src/`.
- [ ] LiveClock test proves monotonic-core insulation against a backward wall-clock jump.
- [ ] SimClock test proves deterministic, wall-clock-independent `call_at` firing order under `advance_to`.
- [ ] Canonical JSON test proves `{"n": 20}` / `{"n": 20.0}` collide and `NaN`/`Infinity` payloads raise.
- [ ] Determinism acceptance test proves an identical fixed event stream, serialized twice end-to-end, produces byte-identical output both times.
- [ ] Upcaster test proves a v1-shaped payload decodes to the current (v2) shape through the registry.
- [ ] The new test modules are `tests/unit/test_tradebot_clock.py` and `tests/unit/test_tradebot_events.py` (flat); no `tests/unit/tradebot/` directory is created.
- [ ] `VERIFY_CMD` (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`) passes clean, including those two new modules, with zero regressions to existing tests (Titan v14 or M0-1). Confirm the count rises from the 464-test baseline — a flat count would mean the new modules failed collection rather than ran.
- [ ] No files under `src/`, `config/config.yaml`, `main.py`, or `tradebot/config/schema.py` touched; no new third-party dependency added (`pyproject.toml`/`requirements.txt` unchanged).
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
