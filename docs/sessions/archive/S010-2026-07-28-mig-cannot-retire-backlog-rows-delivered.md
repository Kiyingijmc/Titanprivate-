---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S010"
date:          "2026-07-28"
slug:          "mig-cannot-retire-backlog-rows-delivered"
parent_session: "none"
task_domain:   "infra"
spec_state:    "draft"          # spec-gate: mig approve <ID> flips to approved (ADR-031 amendment)
status:        "DRAFT"
---

# titan-ict-bot — Session S010 · 2026-07-28 · "mig-cannot-retire-backlog-rows-delivered"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Add `mig backlog done <slug> --by <sha>` so commit-delivered backlog rows can retire

**Why it matters / what it unblocks:** `_slug_delivered` (mig:142) and Cat-1 auto-retire (mig:1474, via `_row_cited_id`) only recognize delivery by a DONE session id in `_INDEX.md`; a plain commit SHA never matches that regex, so rows delivered outside a mig session can never be marked done or auto-retired. This currently strands `decide-fate-of-docs-trading-bot` (status stuck at `promoted` despite a hand-written "DELIVERED ... commit 3979ade" desc) and blocks three more 2026-07-27 rows.

**Exact scope (what "doing this task" means):**
- In `~/.local/bin/mig`, add a `done` subcommand to `cmd_backlog` (alongside `add|ls|show|promote|import|route`): `mig backlog done <slug> --by <sha>`.
  - Die if `<slug>` has no matching backlog row, or `--by <sha>` is missing/not 7-40 hex chars.
  - Rewrite that row's status cell (col 4) to `done`.
  - Record the delivering SHA in the row in a form the Cat-1 retire path can parse as proof-of-delivery (e.g. a `delivered-by:<sha>` marker written into/prefixed onto the desc cell, col 9), distinct from the existing session-id `_row_cited_id` marker.
- Extend `_retire_cat1` (mig:1474) so a `status=done` row carrying a SHA delivery marker is retired directly (no `_index_status` lookup — a commit SHA has no `_INDEX.md` row), producing the same `- retired <slug> (delivered by <sha>) — mig triage <date>` promoted-log audit line the session-id path already writes.
- Leave the session-id Cat-1 path (`_row_cited_id`, `_index_status` DONE check) unchanged for rows delivered via a mig session.
- Run `mig backlog done <slug> --by <sha>` for the four rows this affects, then run `mig triage` to retire them from `docs/sessions/_BACKLOG.md`:
  - `commit-or-discard-the-untracked-test --by 2ae4dbb`
  - `wire-scripts-gui-demo-server-py --by a9e678f`
  - `commit-or-discard-untracked-data-specs --by d05efd3`
  - `decide-fate-of-docs-trading-bot --by 3979ade` (currently status=`promoted` with a hand-written "DELIVERED ... commit 3979ade" desc — the row the backlog idea calls out as permanently stuck)
- Update `.claude/skills/mig/SKILL.md`'s command summary line to mention `mig backlog done`.

**Explicitly OUT of scope (do NOT touch this session):**
- Category-2 premise gate / `_slug_delivered` (mig:142) — used by `mig session new` to block re-promoting an already-shipped slug; unrelated bug, do not touch.
- Any titan-ict-bot application code under `src/`, `tests/`, `tradebot/`, `bridge/` — this session only changes the `mig` orchestrator tool and `docs/sessions/_BACKLOG.md` data.
- New backlog table columns or a schema redesign — the fix must fit the existing 9-column markdown table.
- SHA verification against git history/remote (e.g. `git rev-parse --verify`) — format-only validation is in scope; network or repo-presence checks are not required.
- Any other backlog rows/slugs not explicitly named above.

**Relevant project docs / decisions:** ADR-031 (spec-gate amendment); `.claude/skills/mig/SKILL.md` invariants (mig owns `_BACKLOG.md`/`_INDEX.md` — no hand-edits going forward)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `mig backlog done <slug> --by <sha>` exists, is listed in `cmd_backlog`'s usage/die message, and rejects a missing/malformed `--by`.
- [ ] Running it on a real slug flips that row's status to `done` and leaves a SHA delivery marker `_retire_cat1` can read.
- [ ] `mig triage` auto-retires a SHA-marked done row (removes it from `_BACKLOG.md`'s table, appends a promoted-log audit line) without any `_INDEX.md` lookup.
- [ ] Existing session-id-based Cat-1 auto-retire (e.g. a row citing a DONE `S0xx`) still behaves exactly as before — no regression to `_row_cited_id`/`_index_status` path.
- [ ] `commit-or-discard-the-untracked-test`, `wire-scripts-gui-demo-server-py`, `commit-or-discard-untracked-data-specs`, and `decide-fate-of-docs-trading-bot` are all retired (absent) from `docs/sessions/_BACKLOG.md`'s table.
- [ ] `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` still green (no titan-ict-bot regression from touching `_BACKLOG.md`).
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
