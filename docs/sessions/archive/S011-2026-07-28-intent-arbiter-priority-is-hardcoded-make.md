---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S011"
date:          "2026-07-28"
slug:          "intent-arbiter-priority-is-hardcoded-make"
parent_session: "none"
task_domain:   "infra"
spec_state:    "draft"          # spec-gate: mig approve <ID> flips to approved (ADR-031 amendment)
status:        "DRAFT"
---

# titan-ict-bot — Session S011 · 2026-07-28 · "intent-arbiter-priority-is-hardcoded-make"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Make Arbiter's grade-rank ordering config-driven (retire hardcoded GRADE_RANK ladder)

**Why it matters / what it unblocks:** The Arbiter's tie-break ordering (sort key + opposition tie-break) depends on a hardcoded GRADE_RANK dict (src/arbiter/intent.py:9) with no config surface, so retuning grade priority requires a code change. The sibling strategy-priority hardcode was already resolved via registry.priority_of() (Plan 07 Advisory-B); this closes the remaining half of that advisory.

**Exact scope (what "doing this task" means):**
- Add a grade-rank mapping to config/config.yaml's existing `arbiter:` block (e.g. `grade_ranks:`), defaulting to today's values (A++:6, A+:5, A:4, B+:3, B:2, C:1), following the block's existing inline-comment provenance style.
- Change `Arbiter.__init__` (src/arbiter/arbiter.py:60-65) to read this mapping from its config dict (falling back to the current table when absent/malformed) and expose an instance-level grade-rank lookup.
- Update both call sites that currently use the module-level `grade_rank()` from src/arbiter/intent.py — the sort key (arbiter.py:111-113) and the opposition tie-break (arbiter.py:197) — to use the Arbiter instance's config-sourced lookup instead.
- Confirm `SystemController.__init__` (system_controller.py:145) already passes the full `arbiter:` config dict through to `Arbiter(...)`, so the new key flows through without additional wiring; add a test proving it does.
- Update tests/unit/test_intent.py's `test_grade_rank_ordering` (currently asserts the hardcoded table verbatim) so it still documents the default table, and add new coverage: (a) a custom config-supplied grade-rank mapping changes Arbiter sort/opposition outcomes, (b) missing/malformed config reproduces today's default table byte-for-byte.

**Explicitly OUT of scope (do NOT touch this session):**
- src/analysis/signal_grader.py's separate GRADE_RANK table (different values, missing "B+") — do not touch or reconcile; flag only, for a future session.
- Intent.priority / manifest priority plumbing — already resolved (Plan 07 Advisory-B, registry.priority_of()); do not re-touch.
- opposition_policy, max_positions_per_symbol, max_total_positions, thesis_ttl_bars — existing arbiter config keys, unchanged.
- No new CLI/UI/config-editing surface — config.yaml edits only.

**Relevant project docs / decisions:** docs/superpowers/plans/2026-07-13-plan-05-arbiter-v15_2.md (original Arbiter design); docs/superpowers/specs/2026-07-14-plan-07-gyroscope-gate-design.md §Advisory-B (sibling, already-resolved priority advisory)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] config/config.yaml's `arbiter:` block gains a grade-rank config key with today's values as defaults, matching the block's existing comment style.
- [ ] Arbiter's sort key and opposition tie-break use a per-instance, config-sourced grade-rank lookup — no longer solely the module-level constant in src/arbiter/intent.py.
- [ ] New/updated tests in tests/unit/test_intent.py and tests/unit/test_arbiter.py prove: custom config changes ordering outcomes; default/missing config is byte-identical to today's behavior.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path; only the files above touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
