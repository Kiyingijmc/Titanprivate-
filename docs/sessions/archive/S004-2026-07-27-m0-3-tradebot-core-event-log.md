---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S004"
date:          "2026-07-27"
slug:          "m0-3-tradebot-core-event-log"
parent_session: "none"
task_domain:   "data"
spec_state:    "approved"
needs:         "m0-2-tradebot-core-clock-py"            # advisory cross-track dep (ADR-031)
status:        "DONE"
---

# titan-ict-bot — Session S004 · 2026-07-27 · "m0-3-tradebot-core-event-log"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** M0-3: `tradebot/core/event_log.py` — sole-writer chained SQLite event log with snapshot cadence, archive, and backup/restore-verify

**Why it matters / what it unblocks:** This is the money-truth substrate (F-004): every later M0 piece (M0-4 `projection.py`/`recovery.py`, M0-5 `bus.py`, all of M1+) trusts that the event log is either provably intact or loudly refuses to boot — "best-effort replay and go" is a forbidden code path. Discharges F-004 and is the literal M0 milestone acceptance bar (pass8-synthesis.md:225a/b/c).

**Exact scope (what "doing this task" means):**
- Create `tradebot/core/event_log.py` implementing pass3-systems.md §1.1/§1.3/§1.4:
  - `EventLog(db_path, clock: Clock)` — sole-writer wrapper around one SQLite table `events`; `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL` (mirrors `src/core/state_manager.py`'s WAL/pragma/persistent-conn discipline per pass3-systems.md:502, shape only, not imported).
  - `append(schema, schema_version, ts_event, actor, payload, *, correlation_id=None, parent_ids=(), idempotency_key=None) -> Envelope`: one transaction — assigns gapless monotonic `seq`, stamps `ts_ingest` from `clock.now_ns()`, computes `prev_hash` (= prior row's `row_hash`, 32 zero bytes at genesis) and `row_hash = SHA-256(prev_hash‖seq‖schema‖schema_version‖ts_event‖canonical_json(payload))` (pass3-systems.md:29-30), reusing `tradebot.core.events.canonical_json`/`envelope_to_dict` — do not reimplement canonicalization here. A second `append()` with an already-seen `idempotency_key` is dropped (no new row) and counted, never raises.
  - `verify_chain(from_seq=0)`: walks `seq` gapless + `row_hash` recompute + `prev_hash` continuity + tail integrity; any break (gap, hash mismatch, undecodable row, or a referenced snapshot sidecar SHA-256 mismatch) yields a `RECOVERY_REQUIRED` outcome — name this literally (exception class or result-status token `RECOVERY_REQUIRED`) since M0-4's `recovery.py` boot sequence will consume this exact signal later; a clean walk returns the verified chain head (`seq`, `row_hash`).
  - Snapshot cadence: append a `snapshot.projection` event every 10,000 appended events or 24h since the last snapshot, whichever first, carrying a caller-supplied payload (dict or zero-arg callable — no real projection content exists yet, that's M0-4; this session proves cadence/storage against a synthetic payload) plus `chain_head`. Payloads > 256KB spill to `snapshots/<seq>.json.gz` (stdlib `gzip`, not `zstd` — see OUT) with the sidecar SHA-256 stored in the event and re-checked by `verify_chain()`.
  - `archive_before(snapshot_seq)`: exports events older than the second-newest verified snapshot to `archive/events-YYYYMM.parquet` (pyarrow — see DoD dependency note) with chain metadata, then deletes those rows from SQLite.
  - `backup_and_verify(dest_dir)`: `VACUUM INTO` a dated copy, gzip it, restore to a temp path, run `verify_chain()` + a smoke check (DB opens, chain clean, row count/chain head match source) — failing verification raises loudly; "unverified backup = no backup" (pass3-systems.md:127) is enforced, not just documented.
  - Sole-writer enforcement: a second `EventLog` on the same `db_path` attempting concurrent `append()` fails/blocks within `busy_timeout` rather than silently interleaving.
- Add `tests/unit/test_tradebot_event_log.py` (flat — must NOT live under `tests/unit/tradebot/`, which shadows the real top-level package under `unittest discover -s tests/unit`, per the settled S001/S003 precedent):
  - All 5 corruption drills from the backlog's own acceptance line (truncate, payload bit-flip, `row_hash` bit-flip, row delete, sidecar corrupt) each proven to produce `RECOVERY_REQUIRED`, never a clean/OK result.
  - Determinism: identical fixed event stream appended into two fresh `EventLog` instances ⇒ byte-identical chain head.
  - Idempotency, snapshot cadence + sidecar hash re-check, archive (post-archive chain still verifies clean relative to the retained snapshot), backup/restore-verify (good backup passes, corrupted backup fails loudly), sole-writer contention.
- Carry-over fix (RS003 MINOR, flagged for folding into this session): `tests/unit/test_tradebot_events.py`'s `TestUpcasting` writes into `tradebot.core.events`'s module-global `_REGISTRY`/`_CURRENT_VERSION`/`_UPCASTERS` with no teardown. Since this session's new test module also imports/exercises that same module, add `setUp`/`tearDown` (or `addCleanup`) snapshot-restore of those three dicts around `TestUpcasting` — a small, mechanical edit to that one existing file.

**Explicitly OUT of scope (do NOT touch this session):**
- `tradebot/core/projection.py`, `tradebot/core/recovery.py` (the actual `RECOVERY_REQUIRED` *operating-mode* wiring — refuse-new-trades, human-ack — is M0-4; this session only proves the underlying `verify_chain()` signal).
- `tradebot/core/bus.py`, `tradebot/core/sta.py`, `tradebot/core/controller.py`.
- The separate RS003 MINOR "`Envelope` is unhashable" finding — that lands in `core/bus.py`'s pub/sub dedup-by-identity path (M0-5, per the reviewer's own attribution); `event_log.py` never calls `hash(Envelope)` (its hashing is cryptographic SHA-256 over specific fields), so it's left for m0-5.
- Real projection content (open positions, ledger totals, feature-state manifest id, etc.) — snapshots here carry a synthetic/caller-supplied payload only.
- Off-box shipping of backups (object storage/rsync target) — `backup_and_verify` writes/restores to a caller-specified local `dest_dir` only.
- Adding the `zstandard` dependency — stdlib `gzip` is used for sidecars/backups instead, to avoid a new third-party dependency in this session.
- `ops/journal.py`, `ops/health.py`, a separate `ops/backup.py` module — backup/restore-verify logic lives inside `event_log.py` itself, matching the backlog's own M0-3 bundling (pass8-synthesis.md:224), not the idealized final file tree.
- Anything under `src/`, `config/config.yaml`, `main.py`.
- `tradebot/core/clock.py`, `tradebot/core/events.py` public APIs — no behavior change beyond the one test-teardown fix above.

**Relevant project docs / decisions:** pass3-systems.md §1.1/§1.3/§1.4 (F-004 design, file-tree line 502); pass1-audit.md F-004/F-015/F-038; pass8-synthesis.md M0 scope+acceptance (lines 224-227); RS003.md (carry-over MINOR findings)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `tradebot/core/event_log.py` exists; importable via `.venv/bin/python -c "import tradebot.core.event_log"`; uses only `tradebot.core.clock`/`tradebot.core.events` + stdlib + `pyarrow` — no other new third-party dependency.
- [ ] Repo-root `pyproject.toml` gains `pyarrow>=15.0` in `[project] dependencies` (matches the existing `requirements.txt` pin, already installed in `.venv`); no other dependency change.
- [ ] All 5 corruption drills each produce `RECOVERY_REQUIRED`; zero produce a clean/OK result.
- [ ] Determinism test: identical fixed event stream into two fresh `EventLog`s ⇒ byte-identical chain head.
- [ ] Idempotency test: duplicated `idempotency_key` ⇒ exactly one row + a countable drop.
- [ ] Snapshot cadence test: threshold triggers a `snapshot.projection` row with correct `chain_head`; >256KB payloads spill to a `.json.gz` sidecar whose SHA-256 is stored and re-checked by `verify_chain()`.
- [ ] Archive test: events before the second-newest verified snapshot move to `.parquet` (row count + chain metadata intact); retained SQLite chain still verifies clean relative to its retained snapshot.
- [ ] Backup/restore-verify test: good backup restores + verifies clean; corrupted backup fails loudly, not silently accepted.
- [ ] Sole-writer test: concurrent second writer on the same `db_path` fails/blocks rather than corrupting the chain.
- [ ] `tests/unit/test_tradebot_event_log.py` is flat under `tests/unit/` (no `tests/unit/tradebot/` package).
- [ ] `tests/unit/test_tradebot_events.py`'s `TestUpcasting` gains setUp/tearDown (or addCleanup) snapshot/restore of `_REGISTRY`/`_CURRENT_VERSION`/`_UPCASTERS` (RS003 carry-over fix).
- [ ] `VERIFY_CMD` (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`) passes clean; test count rises above the current 484-test baseline; zero regressions to any existing test.
- [ ] No files under `src/`, `config/config.yaml`, `main.py`, `tradebot/core/projection.py`, `tradebot/core/recovery.py`, `tradebot/core/bus.py` touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
