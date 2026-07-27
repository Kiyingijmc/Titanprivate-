---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S005"
date:          "2026-07-27"
slug:          "m0-4-tradebot-core-projection-py"
parent_session: "none"
task_domain:   "data"
spec_state:    "approved"
needs:         "m0-3-tradebot-core-event-log"            # advisory cross-track dep (ADR-031)
status:        "DONE"
---

# titan-ict-bot — Session S005 · 2026-07-27 · "m0-4-tradebot-core-projection-py"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** M0-4: `tradebot/core/projection.py` (fold(events)→state) + `core/recovery.py` (verify_and_replay boot sequence) + boot-level sole-writer lock

**Why it matters / what it unblocks:** Closes the M0-3→M0-4 handoff event_log.py itself calls out ("real projection content... arrives with core/projection.py in M0-4"; "the RECOVERY_REQUIRED operating mode belongs to core/recovery.py"): today `verify_chain()` only produces the integrity signal, nothing yet folds events into usable state or turns a chain break into a real boot decision, and nothing stops two core processes from booting against the same log.

**Exact scope (what "doing this task" means):**
- Add `tradebot/core/projection.py` implementing pass3-systems.md §1.3's "project(snap); apply tail events" step as a pure fold, not tied to any concrete event family (none exist yet in `tradebot/`; §1.2's `market.*`/`order.*`/etc. schemas are design-doc only, not yet registered via `events.register`):
  - `fold(events: Iterable[Envelope], state: dict | None = None) -> dict`: applies a per-`schema` reducer registry (mirroring `events.register`'s decorator shape, e.g. `@register_reducer("some.schema")`) to `state`, defaulting to `{}`/caller-supplied `state` when `state=None`; an `Envelope` whose `schema` has no registered reducer is skipped (logged-and-ignored, per the §2 "unlisted (state,event) pair" convention), never an error. `snapshot.projection` rows themselves must be skipped by `fold` (a snapshot is a derived artifact of prior folding, not a source fact to re-fold).
  - Track only `state["last_seq"]` (the highest `seq` folded) as the built-in bookkeeping field — **not** `row_hash`/`chain_head`: `Envelope` (per `tradebot/core/events.py:154-165`) carries no `row_hash`, so `fold()` cannot and must not attempt to reconstruct the chain hash; `EventLog.head()`/`verify_chain()` remain the sole source of the hashed chain head, exactly as today.
  - This module has zero I/O and does not import `sqlite3`/`EventLog` — it is a pure function over `Envelope`s, testable without a database.
- Add `tradebot/core/recovery.py` implementing pass3-systems.md §1.3's boot pseudocode, scoped to what this codebase actually has:
  - `verify_and_replay(event_log: EventLog) -> BootResult` (or equivalently-named result type): calls `event_log.verify_chain()` first. On success: picks the newest retained snapshot via `event_log.snapshot_seqs()` (or none), reads the tail via `event_log.read(from_seq=...)`, folds tail on top of the snapshot's own payload as the initial state via `projection.fold`, and returns a result carrying `status="OK"`, the folded `state`, and the verified `ChainHead`.
  - On `RecoveryRequired`: returns/raises a result with `status="RECOVERY_REQUIRED"` and **no** usable state — never a partial/best-effort projection, per pass3-systems.md:123 ("best-effort replay and go is a forbidden code path"). Do not implement the feature-restart policy (§4.5/F-014) or STARTUP broker reconciliation (§3.3) steps from the pseudocode — no `features/` or `broker/` package exists yet under `tradebot/`; note this explicitly as a scope simplification in the module docstring, matching the S004 precedent of not inventing APIs for subsystems that don't exist yet.
  - Sole-writer enforcement (F-015 §1.4, "the core process is the sole writer... total"): add a **boot-level** exclusive lock (e.g. a `<db_path>.boot.lock` sidecar acquired non-blocking via stdlib `fcntl.flock` — WSL/Linux runtime only, consistent with this project's Python side) that `verify_and_replay` (or a small lock helper it calls, e.g. `acquire_boot_lock(db_path)`) takes before returning a usable boot result, released on the caller's exit/close. A second boot attempt against the same log must fail **immediately** — this is deliberately a harder guarantee than M0-3's existing SQLite `busy_timeout` contention path (`tests/unit/test_tradebot_event_log.py:782-811`'s `TestSoleWriter`, which proves two raw `EventLog` instances safely *interleave*, not that a second one is refused). Do **not** touch `event_log.py` to add this lock — keep it entirely inside `recovery.py` so `EventLog`'s own construction contract (including `verify_backup`'s internal second-instance probe, and both existing M0-3 `TestSoleWriter` tests) is unchanged.
- Add `tests/unit/test_tradebot_projection.py` (flat, per the settled M0-1/M0-3 precedent — must not live under `tests/unit/tradebot/`):
  - Reducer registry + `fold()` over a synthetic registered test schema: correct accumulation, unregistered-schema events skipped without error, `snapshot.projection` rows skipped, `last_seq` tracks correctly, no `row_hash`/chain_head attribute appears on the result.
- Add `tests/unit/test_tradebot_recovery.py` (flat):
  - Clean chain (no snapshot yet; and separately, with a snapshot + tail) ⇒ `verify_and_replay` returns `status="OK"` with the expected folded state and a `ChainHead` matching `event_log.head()`.
  - Each of the 5 corruption modes already proven at the `EventLog.verify_chain()` layer in M0-3 (truncate, payload bit-flip, `row_hash` bit-flip, row delete, sidecar corrupt) ⇒ `verify_and_replay` returns/raises `status="RECOVERY_REQUIRED"` with no usable state, never a clean `"OK"` result.
  - Chain-head determinism: an identical fixed event stream (snapshot + tail) appended into two independent fresh `EventLog`s, each booted via `verify_and_replay` ⇒ byte-identical folded `state` and identical verified `ChainHead`.
  - Boot-level sole-writer test: a second `verify_and_replay`/lock-acquire attempt against the same `db_path` while the first is still held fails immediately (not after `busy_timeout_ms`), and does not corrupt or double-write anything.

**Explicitly OUT of scope (do NOT touch this session):**
- Any concrete `market.*`/`order.*`/`position.*`/`breaker.*` event-family payload schemas from pass3-systems.md §1.2 — none exist in `tradebot/core/events.py` yet; `fold()`'s reducer registry must stay generic/schema-agnostic, proven only against synthetic test schemas.
- Feature restart policy (§4.5/F-014) and STARTUP broker-truth reconciliation (§3.3) inside `verify_and_replay` — no `tradebot/features/` or broker adapter package exists yet; these remain a documented gap, not a stub.
- Any human-ack UX (GUI/Telegram) for resuming from `RECOVERY_REQUIRED` — this session only needs `verify_and_replay` to correctly refuse a usable state; the ack workflow is a later session's concern.
- Modifying `tradebot/core/event_log.py`, `tradebot/core/clock.py`, or `tradebot/core/events.py` in any way (including the existing M0-3 `TestSoleWriter` tests, which must keep passing unchanged).
- The "`Envelope` is unhashable" carry-over defect — already attributed to `core/bus.py` (M0-5) per `event_log.py`'s own OUT-of-scope note; not this session's.
- Anything under `src/`, `config/config.yaml`, `main.py`.
- Windows/cross-platform lock portability — the boot lock may rely on POSIX `fcntl` since the Python side only needs to run in WSL/Linux per CLAUDE.md.

**Relevant project docs / decisions:** pass3-systems.md §1.3 (F-004 boot pseudocode, corruption drills), §1.4 (F-015 sole-writer); pass1-audit.md F-004/F-015; S004 (m0-3-tradebot-core-event-log) as direct prior art/dependency.

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `tradebot/core/projection.py` exists; importable via `.venv/bin/python -c "import tradebot.core.projection"`; no `sqlite3`/`EventLog` import; no new third-party dependency.
- [ ] `tradebot/core/recovery.py` exists; importable via `.venv/bin/python -c "import tradebot.core.recovery"`; uses only `tradebot.core.event_log`/`tradebot.core.projection`/`tradebot.core.events`/`tradebot.core.clock` + stdlib.
- [ ] `fold()` correctly accumulates over a synthetic registered schema, skips unregistered-schema events and `snapshot.projection` rows without error, and never references `row_hash`.
- [ ] Clean-chain boot (with and without a prior snapshot) returns `status="OK"` with correct folded state and a `ChainHead` equal to `event_log.head()`.
- [ ] All 5 corruption modes (truncate, payload bit-flip, `row_hash` bit-flip, row delete, sidecar corrupt) each drive `verify_and_replay` to `status="RECOVERY_REQUIRED"` with no usable state; zero produce a clean `"OK"` boot.
- [ ] Chain-head determinism test: identical fixed event stream replayed via `verify_and_replay` into two independent fresh `EventLog`s ⇒ byte-identical folded state and identical verified `ChainHead`.
- [ ] Boot-level sole-writer test: a second concurrent boot attempt against the same `db_path` fails immediately (bounded, well under `busy_timeout_ms`), proven distinct from and in addition to M0-3's existing SQLite-contention `TestSoleWriter` tests (both of which still pass unchanged).
- [ ] `tests/unit/test_tradebot_projection.py` and `tests/unit/test_tradebot_recovery.py` are flat under `tests/unit/` (no `tests/unit/tradebot/` package).
- [ ] `VERIFY_CMD` (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`) passes clean; test count strictly increases over the pre-session baseline; zero regressions to any existing test (including all of `test_tradebot_event_log.py`).
- [ ] No files under `src/`, `config/config.yaml`, `main.py`, `tradebot/core/event_log.py`, `tradebot/core/clock.py`, `tradebot/core/events.py`, `tradebot/core/bus.py` touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
