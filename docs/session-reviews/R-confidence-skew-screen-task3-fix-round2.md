# Scoped Re-Review (Round 2): Confidence–Skew Screen — Task 3 fix (2R-boundary regression test that actually bites)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-94d56d1..87ffc0f.diff` — single commit `87ffc0f`
**Files touched (confirmed via `git diff --stat 94d56d1..87ffc0f`):** `tests/unit/test_confidence_screen_excursions.py` only — 15 insertions, 9 deletions. Nothing under `scripts/confidence_screen/excursions.py` changed in this round (it already carries the accepted Round 1 fix), nothing under `src/`.

## Background

Round 1 fixed the real asymmetry defect (tolerance on the 1R adverse check but not the mirror-image 2R favourable check) by introducing `_R_EPS` used at both boundaries — **accepted, not re-reviewed here**. The single open finding from Round 1 was that its regression test, `test_exact_2r_boundary_sets_hit_2r_flag`, did not bite: with `RISK = 0.0010` the 2.0R level rounds to `2.0000000000000018` (above 2.0), so strict `>= 2.0` and tolerant `>= 2.0 - _R_EPS` agree and the test passes either way.

## Requirement-by-requirement verdict

**1. Test rewritten with a value that genuinely lands below 2.0 — met.** The test now uses `risk_2r = 0.0005` (`ENTRY = 1.1000` unchanged). Independently recomputed, outside the test file, in a fresh Python process:

```
>>> ENTRY = 1.1000; risk_2r = 0.0005
>>> high = ENTRY + 2.0 * risk_2r          # 1.101
>>> (high - ENTRY) / risk_2r
1.9999999999997797
>>> (1.9999999999997797) < 2.0
True
```

This matches the value cited in the report and in the finding exactly. It is IEEE-754 float noise from ordinary arithmetic on values already in the file's style (`ENTRY`, a plain decimal `RISK`), not a hand-typed literal dressed up to look like a float artifact — the test itself also asserts this via `assertLess(expected_fav, 2.0, ...)` as a sanity check before exercising `excursions()`.

**2. Proof it bites, with real failure output — met, and independently reproduced.** I mutated `scripts/confidence_screen/excursions.py` myself (not trusting the report's transcript):

```bash
sed -i 's/if favourable >= 2.0 - _R_EPS:/if favourable >= 2.0:/' scripts/confidence_screen/excursions.py
.venv/bin/python -m unittest tests.unit.test_confidence_screen_excursions -v
```

Result: `test_exact_2r_boundary_sets_hit_2r_flag` — **FAIL**, all 7 other tests still `ok`:

```
FAIL: test_exact_2r_boundary_sets_hit_2r_flag (...)
AssertionError: False is not true : hit_2r_before_1r should be True even when favourable < 2.0
----------------------------------------------------------------------
Ran 8 tests in 0.234s
FAILED (failures=1)
```

This matches the report's recorded failure output verbatim (same assertion message, same line).

**3. All other tests still passing — met**, both under the mutation (7/8 green, only the target test red) and after restore (`git checkout -- scripts/confidence_screen/excursions.py`, confirmed `git diff --stat` empty and `git status --porcelain` clean for that file) — full module: `Ran 8 tests in 0.132s — OK`.

**4. Report's "not a natural test case" claim corrected — met, with a caveat.** The original claim (in the Round 1 section, "Regression Test Remarks") is left verbatim in place — this report is append-only across rounds, so history isn't rewritten. But the Round 2 section added directly beneath it states plainly: *"The initial report incorrectly claimed 'not a natural test case' would be needed to make it bite. The reviewer showed this was wrong by demonstrating ordinary RISK values that round below 2.0... Both are natural test values, not contrived."* The record no longer presents the original claim as standing/true — it is explicitly labeled incorrect and superseded. This satisfies the intent (the claim is not left unchallenged as fact) even though the append-only log format means the original sentence is still readable earlier in the same file.

## Independent checks beyond the four requirements

- **`_R_EPS` still used at both boundaries, no inline literal crept back:** `scripts/confidence_screen/excursions.py` line 64 (`if adverse >= 1.0 - _R_EPS:`) and line 69 (`if favourable >= 2.0 - _R_EPS:`) both route through the single module-level constant (line 25: `_R_EPS = 1e-10`). Confirmed by direct read of the current file — no `1e-10` or bare `2.0`/`1.0` literal reintroduced at either comparison.
- **Diff scope:** `git diff --stat 94d56d1..87ffc0f` shows only `tests/unit/test_confidence_screen_excursions.py` changed. Nothing under `src/`, nothing else under `scripts/`.

## Verify command

```
.venv/bin/python -m unittest tests.unit.test_confidence_screen_excursions -v
```
Ran 8 tests in 0.132s — OK (full log captured above under requirement 3).

## New breakage in the fix diff

None found. Test-only change, scoped to the one method, all 8 tests pass, mutation test confirms the new assertion is load-bearing.

## Verdict

**ADDRESSED.** The regression test now uses a fixture (`RISK = 0.0005`) whose float arithmetic genuinely lands below 2.0 (`1.9999999999997797`, independently reproduced), reverting the favourable comparison to strict `>= 2.0` turns exactly this test red with the recorded assertion failure, all other 7 tests remain green both under the mutation and after restore, `_R_EPS` is still the sole mechanism at both boundaries, the diff touches only the two expected files (this round touches only the test file), and the report's earlier "not a natural test case" claim is explicitly retracted in the Round 2 section rather than left standing as fact.

MIG-VERDICT: PASS
