# Scoped Re-Review: Confidence–Skew Screen — Task 3 fix (2R-boundary tolerance asymmetry)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-8e4de23..76aa85b.diff` — single commit `76aa85b`
**Files touched (confirmed via `git diff --name-only 8e4de23 76aa85b`):** `scripts/confidence_screen/excursions.py`, `tests/unit/test_confidence_screen_excursions.py` — exactly the two expected files, nothing under `src/`, nothing from other tasks. (Note: `git diff --name-only d2d3170..76aa85b` pulls in Task 4/5/6 files because those commits sit between `d2d3170` and `76aa85b` on the branch; the correct review range is `8e4de23..76aa85b`, which contains only the one fix commit.)

## The open finding — checklist verdict

Requirement 1, "tolerance applied consistently to both the 1R adverse and 2R favourable comparisons" — **met**. Line 64: `if adverse >= 1.0 - _R_EPS:`; line 69: `if favourable >= 2.0 - _R_EPS:`. `grep -n "_R_EPS\|1e-10\|>= 1.0\|>= 2.0"` confirms both boundary checks route through the same named constant, no leftover inline `1e-10` literal, no shadowing.

Requirement 2, "tolerance defined once as a named module-level constant with a comment" — **met**. `_R_EPS = 1e-10` at module scope (line 25) with a comment explaining the IEEE-754 rationale and giving the concrete failure mode (`2.0000000000000018`).

Requirement 3, "a new regression test exercising the EXACT 2.0R boundary... asserting `hit_2r_before_1r` is True" — **test exists, but it does not regress anything.** This is the substantive gap.

Requirement 4, "all 7 pre-existing tests still passing" — **met**, plus the new one: `Ran 8 tests in 0.118s — OK`.

## Falsifiability check (the specifically-required verification)

Reverted only the favourable comparison to the brief's original strict form (`sed -i 's/if favourable >= 2.0 - _R_EPS:/if favourable >= 2.0:/'` in `scripts/confidence_screen/excursions.py`) and reran the full module:

```
Ran 8 tests in 0.103s
OK
```

`test_exact_2r_boundary_sets_hit_2r_flag` **did not go red**. Root cause, confirmed algebraically:

```
(ENTRY + 2.0*RISK - ENTRY) / RISK == 2.0000000000000018   # > 2.0
```

The fixture's rounding error lands *above* 2.0, so the strict `>= 2.0` check the test is supposed to be guarding against already passes it. The test is not a regression test — it is a tautology that would pass with or without the fix. The implementer's own report admits this directly ("The test does NOT exercise a case where strict `>= 2.0` would fail and tolerance would pass... not a natural test case"), which is an honest disclosure but does not satisfy the requirement.

I then checked whether the implementer's claim that a biting fixture is "not natural" is actually true, since that claim is what the report leans on to excuse the gap. It is false. Sweeping the *same* `ENTRY = 1.1000` already used throughout this test file against other plausible `RISK` values (still 4-5 decimal places, same style as the file's own fixtures) finds several that round the other way, e.g.:

```
ENTRY=1.1, RISK=0.0005  -> (ENTRY + 2.0*RISK - ENTRY) / RISK == 1.9999999999997797   # < 2.0, strict fails
ENTRY=1.1, RISK=0.0025  -> 1.9999999999999574                                        # < 2.0, strict fails
```

Either of these — using the module's own `ENTRY` and a different `RISK` local to that one test — would have produced a fixture that fails under the pre-fix strict `>= 2.0` and passes under the post-fix tolerant comparison, i.e. an actual regression test. This was readily achievable with the same construction style as every other fixture in the file; it was not attempted.

Restored the mutated file immediately after: `git checkout -- scripts/confidence_screen/excursions.py`, confirmed via `git diff scripts/confidence_screen/excursions.py` (0 lines) and `git status --short` (clean) that the file is back to `76aa85b` exactly.

## Verdict

**NOT ADDRESSED**, on requirement 3 specifically. The code-level fix is real and correct — the tolerance is now applied consistently to both boundaries via a single documented named constant, which closes the actual asymmetry defect described in the finding. But the finding's explicit requirement for a regression test that "exercises the EXACT 2.0R boundary" is not met in substance: the added test passes identically under the old strict comparison and the new tolerant one, so it provides no protection against a future regression back to `>= 2.0` at this boundary — the exact failure mode the finding exists to guard against. A biting fixture was straightforward to construct from data already in the file (same `ENTRY`, a different `RISK`), so this is a fixable gap, not a fundamental limitation, but as delivered the regression coverage claimed in the report does not exist.

## New breakage in the fix diff

None found. Diff is scoped to the two intended files, all 8 tests pass, no other file touched, no behavior change outside the two boundary comparisons.

## Deferred minors (non-blocking)

- The report's "Regression Test Remarks" section (lines 129-137 of `task-3-report.md`) is the only place this gap is disclosed, and even there it understates it — it claims a biting fixture "would require rigging the arithmetic," when in fact one of the file's own already-used constants (`RISK` swapped to `0.0005` or `0.0025`) does it with zero rigging.

MIG-VERDICT: CHANGES
