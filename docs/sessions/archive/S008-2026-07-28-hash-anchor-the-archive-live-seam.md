---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S008"
date:          "2026-07-28"
slug:          "hash-anchor-the-archive-live-seam"
parent_session: "none"
task_domain:   "data"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S008 · 2026-07-28 · "hash-anchor-the-archive-live-seam"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Hash-anchor the archive↔live seam in event_log.verify_chain

**Why it matters / what it unblocks:** Closes RS004 MINOR: after an archive, verify_chain anchors continuity on a seq watermark only, so the first retained row's prev_hash is never checked against the archived chain — a mismatched/foreign archive (the S004 MAJOR failure mode, or archive-dir tampering) passes verification undetected. This unblocks M0-4's verify_and_replay, which relies on verify_chain actually proving continuity across the archive boundary.

**Exact scope (what "doing this task" means):**
- In `archive_before` (tradebot/core/event_log.py ~L755-845), alongside persisting `_META_ARCHIVED_THROUGH` (~L812), persist a new `log_meta` key `archived_through_row_hash` = the `row_hash` of the row at `seq == archived_through`.
- In `verify_chain` (~L546-630), when `archived_through > 0`, require `rows[0]["prev_hash"] == log_meta["archived_through_row_hash"]` for the first retained row; raise `RecoveryRequired` (matching the module's existing error style) on mismatch or if the meta key is missing while `archived_through > 0`.
- In `_write_parquet` (~L1082-1189), in the existing-file append/dedup path (~L1133-1157), read back the existing file's `chain_last_row_hash` schema metadata (proven idiom: `table.schema.metadata[b"chain_last_row_hash"]`, tests/unit/test_tradebot_event_log.py:498-505) and cross-check that incoming rows chain from it; raise `RecoveryRequired` on mismatch.
- Add regression tests in tests/unit/test_tradebot_event_log.py: (a) tamper with the first retained row's prev_hash (or the persisted archived_through_row_hash) after an archive and assert verify_chain now raises RecoveryRequired, mirroring test_archive_refuses_when_the_target_file_holds_a_different_history (:435); (b) confirm the existing happy path test_appending_after_an_archive_keeps_the_chain_verifiable (:533) still passes; (c) assert archived_through_row_hash is persisted in log_meta after archive_before.
- In the session doc, explicitly state this session supersedes the S005 OUT-of-scope fence on event_log.py, scoped only to the surface touched here.

**Explicitly OUT of scope (do NOT touch this session):**
- tradebot/core/clock.py, tradebot/core/events.py, tradebot/core/bus.py, tradebot/core/recovery.py — untouched.
- TestSoleWriter and its concurrency contract — unchanged.
- RS004's second MINOR (sidecar bundling growth / prunable sidecars) — separate finding, separate session.
- No migration of already-archived Parquet files; fix affects new archives and verify_chain's runtime check only.
- No general logging/observability additions beyond clear RecoveryRequired messages.

**Relevant project docs / decisions:** docs/session-reviews/RS004.md; docs/sessions/archive/S004-2026-07-27-m0-3-tradebot-core-event-log.md; docs/sessions/archive/S005-2026-07-27-m0-4-tradebot-core-projection-py.md (fence being scoped-superseded)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] archive_before persists archived_through_row_hash in log_meta alongside archived_through_seq
- [ ] verify_chain raises RecoveryRequired when the first retained row's prev_hash doesn't match archived_through_row_hash (when archived_through > 0)
- [ ] _write_parquet cross-checks appended rows' chain continuity against an existing archive file's stored chain_last_row_hash metadata
- [ ] New regression test proves the S004-MINOR-style mismatch is now caught (previously silently accepted)
- [ ] Full tests/unit suite passes, including TestArchive and TestSoleWriter unchanged (.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py')
- [ ] Session doc explicitly states it supersedes the S005 event_log.py fence for this scoped surface
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
