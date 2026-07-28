---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S012"
date:          "2026-07-28"
slug:          "featurebus-bar-index-single-counter-defect"
parent_session: "none"
task_domain:   "order_lifecycle"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S012 · 2026-07-28 · "featurebus-bar-index-single-counter-defect"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Timeframe-scoped thesis aging in the Arbiter (fix the `_bar_index` single-counter defect — v15 Advisory C)

**Why it matters / what it unblocks:** Despite the backlog slug saying "FeatureBus", the defect lives in the **Arbiter** (`src/arbiter/arbiter.py`): one global `_bar_index` increments whenever `bar_key` changes (`:137`), and `bar_key` is just the bar timestamp (`src/core/system_controller.py:679` `own_token`, no timeframe in it). Today that is accidentally correct — SilverBullet is H1-only, all symbols' H1 bars share a timestamp, so the counter ticks once per hour and `thesis_ttl_bars: 12` ≈ 12 hours. The moment ANY M5 strategy activates, M5 closes advance the same counter ~12×/hour and every H1 thesis ages out in ~1 hour instead of 12 (and M5 theses age in mixed-timeframe units). This is v15 Advisory C: **REQUIRED before any M5 strategy / any live flip**. It blocks the entire Trading-OS arsenal roadmap at the arbiter.

**Exact scope (what "doing this task" means):**
- `src/arbiter/arbiter.py`: scope thesis aging by timeframe.
  - `resolve(open_positions, bar_key="")` gains a `timeframe=""` keyword (default keeps every existing caller/fixture byte-compatible: all calls with the default land in one bucket, which IS today's behavior).
  - Replace the scalar `_bar_index` / `_last_bar_key` with per-timeframe maps; `_advance_bar(bar_key, timeframe)` increments only that timeframe's counter (same "same bar_key ⇒ no increment" rule per timeframe).
  - `_thesis_memory[thesis]` becomes `(timeframe, index)`: a thesis is aged and purged ONLY against its own timeframe's counter. `thesis_ttl_bars` therefore means "bars of the thesis's own timeframe" — document that in the module docstring's aging section (`:38-50`), which currently describes the single counter.
  - Preserve, and keep the tests proving: same-bar re-resolve never ages; a blocked replay does NOT refresh its stored index; memory stays bounded per timeframe (each timeframe's entries purge within its trailing TTL window). Document the accepted edge: entries of a timeframe that stops arriving linger until that timeframe ticks again.
  - Do NOT change: rule order (test-locked), `GRADE_RANK`, priority handling, opposition policy, caps, `Intent`, or the `stats()` shape.
- `src/core/system_controller.py`: pass `timeframe=tf` at the single `resolve()` call site (`:757`). No other controller changes.
- TDD, red first: a regression test reproducing the conflation — seed an H1 thesis, then advance the arbiter with ~12 distinct M5-timestamp bar_keys (`timeframe="M5"`), and assert the H1 thesis is STILL blocked as a replay on its next H1 sighting. Observe it FAIL against the current single counter before the fix, then pass. Add alongside the existing aging tests in `tests/unit/test_arbiter.py`; also assert plain H1-only aging still expires at exactly `thesis_ttl_bars` H1 advances (no off-by-one drift from the refactor).
- Frozen-parity gate: the golden signal-parity suite (`test_signal_parity`) and the controller-arbiter tests must pass unchanged — SB-H1-only behavior must be bit-identical (with one timeframe in play the per-timeframe counters degenerate to the old single counter).

**Explicitly OUT of scope (do NOT touch this session):**
- Renaming the backlog slug or "fixing" `bar_key` to embed symbol/timeframe strings — the timeframe keyword covers the defect; bar_key semantics stay as-is.
- Any M5 strategy work, manifest changes, or enabling anything — this only removes the blocker.
- FeatureBus (`src/features/`) — the slug's misnomer; nothing there changes.
- Per-timeframe TTL configuration (different TTLs per tf) — `thesis_ttl_bars` stays one value, now correctly denominated in own-timeframe bars.
- `tradebot/` — entirely untouched; this is v14/v15 live-engine work.
- Advisory A (cross-symbol total cap) — separate backlog row.

**Relevant project docs / decisions:** v15 P05 carry-forward Advisory C (pinned in `docs/research/2026-07-14-gyroscope-gate-results.md` and the P05 final review); `src/arbiter/arbiter.py` module docstring (aging section); frozen parity harness (Plan 03).

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] A regression test exists in `tests/unit/test_arbiter.py` proving M5-bar advances no longer age H1 theses (H1 thesis still replay-blocked after ≥ `thesis_ttl_bars` M5 advances) — and the session log/commit history shows it observed RED against the current single counter before the fix (TDD, not retrofitted).
- [ ] H1-only aging still expires at exactly `thesis_ttl_bars` H1 advances; same-bar re-resolve never ages; a blocked replay does not refresh its index — all covered by tests that pass.
- [ ] `resolve()`'s `timeframe` keyword defaults to `""` and every pre-existing test passes WITHOUT modification (fixtures never pass it) — proving default-bucket behavior is byte-compatible.
- [ ] `src/core/system_controller.py:757` passes `timeframe=tf`; no other controller line changes.
- [ ] The arbiter module docstring's aging section describes per-timeframe counters and defines `thesis_ttl_bars` as own-timeframe bars, including the silent-timeframe lingering edge.
- [ ] Frozen parity (`test_signal_parity`) green; `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` fully green (617+, no regressions).
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
