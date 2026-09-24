# Review: Confidence–Skew Screen — Task 3 (Excursion engine: MFE/MAE with 1R truncation)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-465a594..d2d3170.diff` (commit `d2d3170`)
**Files:** `scripts/confidence_screen/excursions.py`, `tests/unit/test_confidence_screen_excursions.py`

## Verification performed

- Ran `.venv/bin/python -m unittest tests.unit.test_confidence_screen_excursions -v` — 7/7 pass, matching the implementer's report.
- Reproduced the declared deviation's necessity directly: reverted `if adverse >= 1.0 - 1e-10:` to the brief's literal `if adverse >= 1.0:` and re-ran the brief's own headline fixture (`-1R` then `+3R AFTER the stop`). Result: `skew=2.0000000000000018`, `hit_2r_before_1r=True` — i.e. **the brief's own Step-3 reference code, transcribed exactly, fails the brief's own Step-1 test** (`test_adverse_1r_first_truncates_the_favourable_path`, the test the brief calls out as guarding "the defect most likely to be simplified away"). Root cause confirmed algebraically: `(ENTRY - (ENTRY - 1.0*RISK)) / RISK == 0.9999999999998899` in binary64, not exactly `1.0`.
- Checked the magnitude: actual float noise here is ~1.1e-13; the implemented tolerance is 1e-10 — three orders of margin, translating to a price-space slack many orders below any real tick increment, so it cannot mask a genuine adverse move.
- Checked whether this is fixture-specific as the implementer's report claims ("an artifact of the test data construction method... no such tolerance is needed" in production): tested the mirrored production case (`entry - ATR10_MULT*atr`, matching `population.py`'s actual stop construction) — the same decimal-to-binary64 rounding applies whenever price exactly retraces to the stop level in real tick-grid data, so the fix is more broadly load-bearing than the report suggests, though this doesn't change its correctness.
- Traced `sig["entry"]/["risk"]/["dir"]/["time"]` back to Task 1 (`scripts/confidence_screen/population.py`, `scripts/poc_sb_stops.py:105-116`) to confirm the consumed interface is real, not just satisfied by the test's own fixture.
- Confirmed via the diff that only the two declared files changed — nothing under `src/`, nothing from Task 1/2 (`__init__.py`, `population.py`, `grading.py`).
- Manually verified the adverse-truncation vs. `hit_2r_before_1r` ordering: the `break` on adverse-truncation happens before `favourable`/`hit_2r`/`mfe` are touched for that bar, so `hit_2r_before_1r` cannot be set on the same bar that truncates — confirmed by `test_same_bar_ambiguity_resolves_adverse_first` (bar has both +3R and -1R; `hit_2r_before_1r` is `False`).
- Checked `np.searchsorted(..., side="right")`: correctly excludes the signal's own bar whether or not `m5["time"]` contains an exact match to `sig["time"]` — `side="right"` returns the index past any equal element, and returns the correct insertion point when no match exists (the brief's own fixture construction).
- Checked `mae` capping at exactly `1.0` on truncation (vs. recording the bar's true, possibly larger, adverse excursion): this is verbatim from the brief's own Step-3 code, not an implementer decision — not a deviation.
- `grep`'d `hit_2r_before_1r` across `scripts/confidence_screen/*.py` — unreferenced anywhere downstream (features.py, grading.py), so it is not yet load-bearing for any other task.

## A) SPEC COMPLIANCE — PASS

- `H_BARS`/`W_BARS` imported (not redefined) from `scripts/confidence_screen/__init__.py`; M5-per-H1 factor of 12 applied correctly to both the wait window and the excursion horizon.
- Intrabar convention (adverse resolved before favourable) implemented correctly and verified to hold even under the same-bar-ambiguity ordering-bug check.
- MFE truncates at the first 1R adverse touch; the canonical `-1R then +3R ⇒ skew=-1.0` case is asserted and passes (with the deviation in place — see below).
- Unfilled signals return `filled: False` with all fields exactly `0.0` and `touch_idx: None`, and are returned, not dropped (`test_untouched_level_scores_zero_and_is_still_returned`).
- `src/` untouched; no earlier-task file (`__init__.py`, `population.py`, `grading.py`) modified — diff is exactly the two declared new files.
- stdlib `unittest` only; all 7 brief-specified tests present, verbatim, and passing.
- Return dict shape matches the interface (`filled`, `touch_idx`, `mfe`, `mae`, `skew`, `hit_2r_before_1r`).

## B) TASK QUALITY — Approved

### The declared deviation: `if adverse >= 1.0 - 1e-10:` instead of `if adverse >= 1.0:`

**Judged legitimate and necessary, not a defect mask.** As shown above, the brief's own literal reference implementation fails the brief's own headline test due to binary64 representation error in the test fixture's `ENTRY - 1.0*RISK` construction — an error of ~1e-13, three orders below the 1e-10 tolerance applied, so it cannot suppress a real adverse move. It also generalizes beyond the test fixtures: production stop levels are built from the identical `entry - ATR10_MULT*atr` arithmetic (`population.py`), so an exact stop-level touch on real data reproduces the same rounding noise. The implementer's own rationale slightly undersells this ("no such tolerance is needed" in production) — a minor documentation inaccuracy, not a code defect — but the fix itself is correctly scoped and does not change which signals get truncated except within the same ~1e-10 R band it targets.

### Findings

- **Important** — `favourable >= 2.0` (governing `hit_2r_before_1r`) has no matching epsilon tolerance, an inconsistent application of the exact same floating-point-boundary fix. I constructed the mirror-image boundary case (`entry + 2.0*risk`) and found the rounding happens to land on the safe side for this specific entry/risk pair (`fav = 2.0000000000000018`), but that direction is not guaranteed for arbitrary entry/risk combinations — it depends on which way binary64 rounds for those particular values. No test exercises the exact-2.0R boundary, so this is currently unguarded. Impact today is nil (`hit_2r_before_1r` is unreferenced by any other module in the plan so far), but it should be resolved — either a symmetric tolerance or an explicit comment justifying the asymmetry — before Task 4/5 start consuming the flag.
- **Minor** — the report's claim that the tolerance is purely a test-fixture artifact and unnecessary on real data is not fully accurate (see verification above); doesn't affect the soundness of the fix, only the stated rationale for it.

No Critical findings. No tautological tests found — each assertion depends on genuinely computed values, not implementation echoes. No ordering bug in `hit_2r_before_1r` vs. truncation. `searchsorted` boundary behavior is correct.

MIG-VERDICT: PASS
