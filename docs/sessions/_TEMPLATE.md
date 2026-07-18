---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "{{session_id}}"
date:          "{{date}}"
slug:          "{{slug}}"
parent_session: "{{parent_session}}"
task_domain:   ""
status:        "DRAFT"
---

# titan-ict-bot — Session {{session_id}} · {{date}} · "{{slug}}"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** {{ONE-LINE TASK TITLE}}

**Why it matters / what it unblocks:** {{1–2 lines}}

**Exact scope (what "doing this task" means):**
{{bullet the concrete deliverable(s). Be specific enough that "done" is testable.}}

**Explicitly OUT of scope (do NOT touch this session):**
{{list adjacent things you must resist. Scope creep ends the chain's value.}}

**Relevant project docs / decisions:** {{e.g. Vol 14 Ticketing; ADR-015}}

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] {{concrete outcome 1 — e.g. "verify command passes on a clean checkout"}}
- [ ] {{concrete outcome 2 — e.g. "the affected flow still works end-to-end"}}
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
