---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S002"
date:          "2026-07-19"
slug:          "fix-plan-06-flake-test-research"
parent_session: "none"
task_domain:   ""
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S002 · 2026-07-19 · "fix-plan-06-flake-test-research"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Make TestSpreadFlowsIntoNetR hermetic to ambient data/specs.json

**Why it matters / what it unblocks:** `tests/unit/test_research_run.py::TestSpreadFlowsIntoNetR` silently resolves BTCUSD's tick spec from the real, untracked `data/specs.json` on disk (scripts/research_run.py's `DEFAULT_SPECS_PATH`) whenever the test doesn't pass `--specs`; a worktree without that untracked file falls back to `_DEFAULT_SPEC` instead, giving different net-R math and a flaky pass/fail. Fixing it unblocks mig verify gates from tripping on workspace state that has nothing to do with the code under test.

**Exact scope (what "doing this task" means):**
- In `tests/unit/test_research_run.py`, `TestSpreadFlowsIntoNetR.test_different_spreads_produce_different_expectancy`: stop depending on the ambient/default `--specs` path. Write a fixture `specs.json` with a fixed, known BTCUSD entry (e.g. `tick_size`/`tick_value`/`vol_step`) into the test's own tempdir (`self._tmpdir`, already torn down by `_ResearchRunTestBase.tearDown`) and pass its path explicitly via `--specs` on both the cheap (`--spread-pips 5`) and expensive (`--spread-pips 500`) `_run` calls.
- Keep the test's existing assertions (`n_signals > 0`, `assertNotEqual` on expectancy, `assertGreaterEqual` cheap-vs-expensive) passing against the fixed fixture values.
- Ensure no fixture file or state can leak across test runs: confirm the existing base-class `tearDown` (`shutil.rmtree(self._tmpdir)`) covers the fixture once it lives under `self._tmpdir`; if the fixture is written anywhere else, add explicit cleanup.
- Regression-verify the actual flake mechanism by hand: run the affected test with the real `data/specs.json` present, then with it moved aside/absent, and confirm identical (passing) results both times post-fix. This is a manual verification step, not new permanent test infrastructure.

**Explicitly OUT of scope (do NOT touch this session):**
- Deciding the fate of the real untracked `data/specs.json` (commit vs. discard) — that's the separate backlog item `commit-or-discard-untracked-data-specs`.
- Any change to production code in `scripts/research_run.py` (`_load_specs`, `_spec_source`, `DEFAULT_SPECS_PATH`) — this is a test-only fix.
- Any other test class in `tests/unit/test_research_run.py` (e.g. `TestEndToEndRun`, `TestPooledEndToEnd`) — they already tolerate either spec source and aren't flaky.
- A broader "make all tests hermetic" refactor across the suite.

**Relevant project docs / decisions:** CLAUDE.md "Working style for this repo" (TDD, verify-before-done); Plan 06 research_run CLI (docs/superpowers/plans)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `TestSpreadFlowsIntoNetR::test_different_spreads_produce_different_expectancy` passes a fixture path via `--specs` and never reads the repo's real `data/specs.json`.
- [ ] `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` passes with `data/specs.json` present in the working tree.
- [ ] The same suite passes with `data/specs.json` temporarily moved aside/absent, then the file is restored exactly (never deleted) as part of verification.
- [ ] No files under `scripts/` or `src/` touched.
- [ ] Changes committed forward-only, scoped to `tests/unit/test_research_run.py` only; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
