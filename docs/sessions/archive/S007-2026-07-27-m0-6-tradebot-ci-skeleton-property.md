---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S007"
date:          "2026-07-27"
slug:          "m0-6-tradebot-ci-skeleton-property"
parent_session: "none"
task_domain:   "infra"
spec_state:    "approved"
needs:         "m0-1-tradebot-skeleton-top-level"            # advisory cross-track dep (ADR-031)
status:        "DONE"
---

# titan-ict-bot — Session S007 · 2026-07-27 · "m0-6-tradebot-ci-skeleton-property"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** M0-6: tradebot hypothesis property tests (P4/P5/P6 real, P7/P8/P11 groundwork stubs) + local CI-tier skeleton script

**Why it matters / what it unblocks:** Closes the last M0 session (pass8-synthesis.md §4.2 M0 acceptance names exactly "property tests P4–P8 + P11 groundwork; CI pipeline skeleton"); M0 is otherwise DONE (S001–S006 on main, 868a7ae), so this unblocks calling the trustworthy-skeleton milestone complete before M1 strategy work starts.

**Exact scope (what "doing this task" means):**
- **`hypothesis` is APPROVED by the owner (2026-07-27) — do not re-ask, and do not stop to request it.** It is already installed in the repo venv (`hypothesis 6.161.8`), which is the same interpreter `VERIFY_CMD` uses via its absolute path, so it resolves inside the worktree too. Your job is only to *pin* it: add `hypothesis>=6,<7` to `requirements.txt` and to `pyproject.toml`. Rationale on record: `pass3-systems.md:575` (`### 7.2 Property-based (hypothesis lib) — named invariants`) names this library for this exact test tier, so it is design-sanctioned rather than a new architectural choice; it is absent from the dependency line at `:492` only because that list is *runtime* deps. It is unittest-native (`@given` works directly on `unittest.TestCase` methods), so no pytest is pulled in and the repo's stdlib-unittest convention is unaffected.
- P4 (hash chain, pass3-systems.md §7.2): a hypothesis-driven test that generates random multi-row `tradebot/core/event_log.py` logs and random single-byte mutations / row deletions / truncations, asserting `verify_and_replay`/`verify_chain` always detects the corruption (never a silent clean boot). Extends — does not duplicate — the existing example-based drills in `tests/unit/test_tradebot_event_log.py::TestCorruptionDrills`.
- P6 (projection idempotency, §7.2): a hypothesis-driven test on `tradebot/core/projection.py` — random generated envelope streams fold to the same projection when replayed twice, and streams with writer-side duplicate-idempotency-key drops fold identically to the deduped stream.
- P5 groundwork (STA, §7.2): a hypothesis-driven test on the `tradebot/core/sta.py` skeleton — random interleavings of `(guard, apply)` submissions preserve single-consumer FIFO serialization (never concurrent `apply`), and guard is evaluated at drain time, matching the existing example test in `tests/unit/test_tradebot_sta.py`. (The full "no transition out of terminal states" invariant needs the real signal state machine, which is M1 — out of scope here.)
- P7 / P8 / P11 groundwork stubs: one placeholder test module documenting each invariant verbatim from source (P7 params_hash — pass3-systems.md §7.2 + §4.2/F-038; P8 normalize_price tick-grid — §7.2; P11 posting-balance rounding fuzz — pass6-accounting.md §1.3/§6.3), each as an explicitly `unittest.skip`-ed hypothesis test with a reason string naming the owning future milestone (P7→M1 `features/registry.py`, P8→M2 risk sizing, P11→M2 ledger) — visible in `-v` test output, not silently absent.
- A local CI-tier skeleton script at **`scripts/run_pr_checks.sh`** — NOT under `tradebot/`: `pyproject.toml:17` sets `include = ["tradebot*"]`, so anything placed there ships inside the distributed Python package, and a shell script does not belong in a wheel. The repo already has a top-level `scripts/` directory; use it. The script codifies the pass3-systems.md §8.6 PR-tier ordering scoped to what M0 actually has: unit tests → property tests (P4/P5/P6 real, P7/P8/P11 skip-and-report). Later tiers named in §8.6 (sim scenarios §7.3, golden parity §7.5, image build) are listed as clearly-commented no-ops, not implemented.
- Premise check before editing: confirm no `tests/unit/test_tradebot_property_*` files already exist, and confirm `hypothesis` is **absent from `requirements.txt` and `pyproject.toml`** (that absence is the gap this task closes). **Expect `import hypothesis` to SUCCEED** — 6.161.8 was installed into the venv when the dependency was approved. That is not a stale premise and is not a reason to stop: the module being importable while unpinned is precisely the state you are fixing.

**Explicitly OUT of scope (do NOT touch this session):**
- Wiring an actual hosted CI runner (GitHub Actions or similar) — the repo has no git remote (per project memory); that's a separate future decision, not this session's.
- Implementing `params_hash` (M1 `features/registry.py`), `normalize_price`/risk sizing (M2), or the double-entry posting/rounding engine (M2) — P7/P8/P11 stay documented skips until their owning milestone lands real code to test.
- The sim scenario library (§7.3), chaos/kill-9 drill tier (§7.4), or golden-replay parity tier (§7.5) — all explicitly post-M0.
- Adding ruff/mypy or any other lint/type-check tooling — not named in this backlog item; a separate new-dependency decision.
- Any change to `src/` (the live v14 ZMQ bot), strategies, GUI, or broker/bridge code.
- Full P1–P3, P9, P10 property tests (BarClock, sizing, ledger conservation, reconcile) — those need modules M0 doesn't build.

**Relevant project docs / decisions:** pass3-systems.md §7.2 (P4–P8 invariant table) + §8.6 (CI/CD pipeline tiers); pass6-accounting.md §1.3/§6.3 (P11 posting-balance rounding law); pass8-synthesis.md §4.2 (M0 milestone scope/acceptance)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `hypothesis>=6,<7` is pinned in BOTH `requirements.txt` and `pyproject.toml` (approved 2026-07-27; already installed as 6.161.8 — pin it, don't re-ask)
- [ ] `tests/unit/test_tradebot_property_p4_hash_chain.py` (or equivalent) exists, uses `@given`, and fails on a stubbed-out corruption-detection bug (verified red before green per TDD)
- [ ] `tests/unit/test_tradebot_property_p6_projection.py` (or added to `test_tradebot_projection.py`) exists and covers both plain double-replay and duplicate-idempotency-key-drop cases
- [ ] `tests/unit/test_tradebot_property_p5_sta.py` (or added to `test_tradebot_sta.py`) exists and fuzzes interleaved guard/apply submissions
- [ ] a groundwork test module contains explicitly-skipped P7/P8/P11 stubs, each citing its source doc section and owning milestone in the skip reason
- [ ] `scripts/run_pr_checks.sh` exists (NOT under `tradebot/`, which is a packaged directory), runs clean on a fresh checkout, and exits non-zero on any real test failure — prove the non-zero path, don't just assert it
- [ ] No new file was added anywhere under `tradebot/` for CI plumbing
- [ ] `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` stays fully green (593+ tests, no new failures/regressions)
- [ ] changes committed forward-only, scoped to `tests/unit/test_tradebot_*`, `scripts/run_pr_checks.sh`, `pyproject.toml`, `requirements.txt`; no out-of-scope files touched (this session adds tests, a script, and two dependency pins — it changes no `tradebot/` source)
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
