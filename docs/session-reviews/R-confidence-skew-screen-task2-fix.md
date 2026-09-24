# Scoped Re-Review: Confidence–Skew Screen — Task 2 fix (grading adapter, factors-parsing rewrite)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-d2d3170..58e3737.diff` (commit `58e3737` on branch `research/confidence-skew-screen`)
**Files touched:** `scripts/confidence_screen/grading.py`, `tests/unit/test_confidence_screen_grading.py` — confirmed via `git diff d2d3170..58e3737 --name-only`, no other files changed, nothing under `src/` touched.

## Findings verdicts

### FINDING 1(a) — missing epsilon tolerance on displacement — ADDRESSED

The old `grade_signal` recomputed `displacement_bucket` from raw `body_atr` with a bare `>=` and no epsilon. The fix deletes that recompute entirely and instead parses the trailing `+N` off whichever `"displacement=..."` string the shipped grader itself returned (`_parse_points(factors, "displacement=")`), so the epsilon behavior lives only in `src/analysis/signal_grader.py` and the adapter cannot drift from it by construction.

Empirically verified this is a real fix, not a test that happens to pass under both versions: I checked out the **pre-fix** `grading.py` (commit `d2d3170`) into the working tree, kept the **new** test file, and reran. Under the old code:
```
test_displacement_bucket_uses_the_graders_epsilon_tolerance ... FAIL
AssertionError: 15 != 20
```
matching exactly what the report claims. Restored the post-fix file afterward (`git status` confirms the file matches HEAD exactly, no diff).

### FINDING 1(b) — pd_array=0 for eq/unknown liq_status — ADDRESSED

Same mechanism: `pd_array` is now parsed off the grader's `"pd_array=..."` factor string (three shapes in `signal_grader.py`: `pd_array={status} +15`, `pd_array=eq/unknown +5`, `pd_array={status} +0` — all share the `pd_array=` prefix, so one `_parse_points` call covers all three). Empirically reran the new `liq_status=""` and `liq_status="EQ"` tests against the pre-fix code:
```
test_pd_array_awards_five_for_empty_liq_status ... FAIL: 0 != 5
test_pd_array_awards_five_for_eq_liq_status    ... FAIL: 0 != 5
```
Confirmed genuine regression coverage.

### RULING COMPLIANCE — parsing from `factors`, not recomputation — ADDRESSED

`grading.py` no longer touches `body_atr`, `liq_status`, or `SignalGrader.KILLZONES` to derive the four/five decomposed values. `bias_class`/`bias_points` come from `_parse_bias`, which matches the factor string's own prefix (`bias_aligned`/`bias_neutral`/`bias_counter`) rather than reimplementing the alignment condition — this is the correct reading of the ruling (immune to a future change in *which* biases count as aligned, not just to point-value changes). `displacement_bucket`/`pd_array`/`killzone` come from `_parse_points`, reading the trailing `+N` off the matching factor string. No hardcoded thresholds or point values remain in the adapter.

I enumerated every factor-string shape `SignalGrader.grade()` can emit (read `src/analysis/signal_grader.py` directly, not the brief's list) and checked each against the parser:
- Bias: `"bias_aligned +30"`, `"bias_neutral +10"`, `"bias_counter +0"` — three disjoint prefixes, `_parse_bias` matches correctly, all three have trailing `+N`.
- RR: `f"rr={rr:.2f} +{pts}"` — always present except the degenerate short-circuit; adapter reads this straight from `factors` in the test, not from the return dict (grade_signal doesn't need to parse RR itself, it's `result["score"]`-driven).
- Displacement: `f"displacement={ratio:.2f} +{pts}"` (normal path) and `"displacement=n/a +0"` (the `except (KeyError, TypeError, ValueError)` path when candle math fails) — both share the `displacement=` prefix, both have a trailing `+N`, both parse correctly.
- PD array: three shapes, all share `pd_array=` prefix as above — all parse correctly.
- Killzone: single shape `f"killzone +{pts}"` (no `=`) — adapter's prefix is `"killzone"` (no trailing `=`), correctly matches.
- Degenerate short-circuit: `factors == ['invalid_risk_distance']` — no factor matches any prefix, both `_parse_bias` and `_parse_points` fall through to their documented defaults (`("invalid", 0)` and `0` respectively) without raising.

No factor shape is missed and no prefix collides with another (e.g. `bias_aligned`/`bias_neutral`/`bias_counter` are mutually exclusive prefixes; `displacement=`/`pd_array=`/`killzone` don't overlap). `int(f.rsplit("+", 1)[1])` is safe for every shape since none of `rr=`, `displacement=`, `pd_array={status}` can itself contain a literal `+` for the values this codebase produces (non-negative floats, and status values DISCOUNT/PREMIUM/EQ/empty/None).

### `bias_points` new column — ADDRESSED

Added as `"bias_points": bias_points` (int, parsed alongside `bias_class`). Used by the sum-invariant test.

### Degenerate `entry == sl` case — ADDRESSED, with a real test

`test_degenerate_entry_equals_sl_does_not_crash_and_documents_defaults` constructs the sig dict directly (bypassing `add_stop_and_target`, which would itself reject a zero-distance stop before reaching the grader) and asserts `score=0, grade="C", bias_class="invalid", bias_points=0, displacement_bucket=0, pd_array=0, killzone=0`. Traced through the code: `SignalGrader.grade` appends the bias factor *before* computing risk, then short-circuits on `risk <= 1e-12` with a **fresh** dict `{'score': 0, 'grade': 'C', 'factors': ['invalid_risk_distance']}` — this discards the already-appended bias factor, so the adapter genuinely sees only `['invalid_risk_distance']` and must (and does) fall back to defaults rather than crash. Empirically confirmed passing:
```
test_degenerate_entry_equals_sl_does_not_crash_and_documents_defaults ... ok
```
and confirmed it fails under the pre-fix code (`AssertionError: 'aligned' != 'invalid'`), since the old recompute never looked at `factors` at all and would have derived `bias_class="aligned"` from the raw `bias`/`dir` inputs regardless of the degenerate short-circuit — genuine new coverage, not a vacuous test.

### Sum invariant — ADDRESSED, verified non-degenerate

`test_score_equals_sum_of_the_decomposed_factor_points` sweeps `itertools.product` over 2 directions × 3 bias values × 7 body_atr values (including both epsilon-boundary floats `0.9999999`/`1.4999999`) × 5 liq_status values (`DISCOUNT/PREMIUM/EQ/""/None`) × 7 hours = 1470 combinations, asserting `bias_points + rr_points + displacement_bucket + pd_array + killzone == score` for each, with `subTest` so each combination is independently reported. This genuinely varies four of the five scoring dimensions (RR stays pinned at 2.0 because `atr` isn't varied in this sweep — correct, since Task 2's own `test_rr_factor_is_constant_fifteen_for_every_signal` already established RR is a SilverBullet-wide constant; varying it here would be redundant, not missing coverage). Not degenerate: empirically, running this test against the pre-fix adapter produced 1470 subTest errors (`KeyError: 'bias_points'`, since the key didn't exist pre-fix) — confirming the sweep actually exercises code paths across the full combination space rather than short-circuiting on one factor pattern.

### All 6 original tests still passing — ADDRESSED

Diff shows the six original test bodies are untouched (only new tests appended). Ran the module directly:
```
.venv/bin/python -m unittest tests.unit.test_confidence_screen_grading -v
Ran 11 tests in ~0.5s — OK
```
All 6 original + 5 new = 11, matching the report. Independently re-verified (not taken from the report) both against post-fix code (all green) and pre-fix code (4 explicit failures + 1470 subTest errors on the sweep, 1 error on the standalone `bias_points` KeyError test) — the 5 new tests are genuine regression coverage, not tautologies.

## New breakage introduced by the fix diff

None found. Scope is exactly the two files the brief/report claim; `src/` untouched (read-only); no other task's files touched. The rewritten `grading.py` no longer imports `SignalGrader.KILLZONES` for its own logic (that constant is now unused in the adapter — cosmetic, not a defect, since it was only ever used by the deleted recompute).

## Deferred minors (non-blocking)

- The docstring added at the top of `grading.py` is accurate and useful; no changes suggested.
- `_parse_points`/`_parse_bias`'s reliance on `factors` string prefixes is inherently coupled to `SignalGrader`'s string *formatting* (not just its thresholds/weights) — if a future edit renames e.g. `"pd_array="` to `"pdarray="` the adapter would silently start returning 0 for that column instead of raising. This is an accepted trade-off of the owner's ruling (parse over recompute) and is not a defect in this fix; flagging only as a known fragility for anyone touching `signal_grader.py`'s factor strings later.

## Verdict

All findings ADDRESSED, all required tests present and independently confirmed to genuinely regress against the pre-fix code (not just pass-under-both), no new breakage in the diff, only the two intended files touched.

MIG-VERDICT: PASS
