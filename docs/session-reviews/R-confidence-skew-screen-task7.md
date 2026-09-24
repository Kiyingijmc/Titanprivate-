# Review: Confidence–Skew Screen — Task 7 (Calendar-date split with purge and embargo)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-bf1cf44..f72b493.diff` (commit `f72b493`)
**Files:** `scripts/confidence_screen/splits.py`, `tests/unit/test_confidence_screen_splits.py`

## Verification performed

- Ran `.venv/bin/python -m unittest tests.unit.test_confidence_screen_splits -v` — 7/7 pass, matches the report.
- Confirmed via diff and `git show 8e4de23:scripts/confidence_screen/__init__.py` (current `__init__.py`) that `SPLIT_FRAC`/`H_BARS`/`EMBARGO_BUFFER_BARS` are imported, not redefined; only `numpy`/`pandas` imported; `git show --stat f72b493` touches only the two target files (nothing under `src/`, nothing from earlier tasks).
- Confirmed the implementation is a verbatim transcription of the brief's Step-3 code, matching the implementer's "No Deviations" claim.
- Did **not** trust the shipped tests for the leakage-critical claims. Built independent repro scripts against the installed `split_masks`/`week_clusters` (below) for each item on the scrutiny list.

## Findings

### CRITICAL — the wall-clock embargo under-purges across a weekend gap; a training signal's true outcome window can cross the cut undetected

The purge band is computed as `(horizon_bars + buffer_bars) * bar_minutes` = 16 wall-clock hours, and a signal is purged only if its timestamp falls within 16 *wall-clock* hours of the cut. But `H_BARS`/`EMBARGO_BUFFER_BARS` are **bar counts** on a 24/5 market with weekend closures — 16 H1 *bars* of real trading data can span far more than 16 wall-clock hours whenever the window crosses a weekend.

Reproduced directly against `split_masks`:

```
Friday 2024-01-05 06:00..21:00 hourly signals, market closed over the
weekend, trading resumes Sunday 2024-01-07 22:00, more hourly bars into
Monday 2024-01-08.

cut_time picked by the quantile: 2024-01-08 03:00 (5 bars after reopen)

Last Friday signal (2024-01-05 21:00) is 54 wall-clock hours before cut_time
  -> purged_mask = False, is_mask = True  (kept in TRAINING)

But that signal's real 16-bar forward window can only start accumulating
bars once the market reopens Sun 22:00, so it doesn't complete until
Mon ~14:00 — eleven hours AFTER the cut its outcome window has already
crossed into OOS territory.
```

So a signal sitting in `is_mask=True` (training) has its labeled outcome computed partly from bars that occurred after the IS/OOS boundary — exactly the silent leakage this task exists to prevent, and it inflates the study's apparent OOS edge because the "unseen" data has partially leaked into training. This isn't a rare corner case: it fires whenever the quantile-selected `cut_time` lands within roughly a day of a weekend reopen, which is a matter of chance on any given run of the screen, not an exotic adversarial input.

Away from a weekend boundary, the arithmetic is correct: for uniformly-spaced timestamps I confirmed the maximum `is_mask` time is exactly `cut_time - band`, so the training signal closest to the cut has a window that reaches `cut_time` and no further (verified by direct construction, not by re-deriving the shipped test's own formula).

Note on provenance: this code is transcribed verbatim from the brief's Step 3 — the flaw is baked into the brief's own reference implementation, not introduced by the implementer's own choices. I'm flagging it as a task-quality finding rather than excusing it, because the project's own conventions (CLAUDE.md: "24/5 market... weekend gaps" is called out explicitly elsewhere in this codebase, e.g. the embargo purpose itself) make this a foreseeable gotcha, and the report's "Concerns: None" / "Deviations: None" means it went unflagged to whoever owns the brief.

### IMPORTANT — the shipped boundary test cannot catch the weekend defect (false confidence)

`test_signals_whose_window_crosses_the_cut_are_in_neither_set` asserts against `band = (times > cut - np.timedelta64(16, "h")) & (times <= cut)` — i.e. it re-derives the *exact same* wall-clock formula the implementation uses, over a fixture (`_times(400, freq="1h")`) that has no weekend gap at all. Under uniform 1-hour spacing, wall-clock hours and bar counts are identical, so this test is structurally incapable of exercising the one scenario where the two diverge. It will pass against the current buggy implementation and would equally pass against a correct, bar-index-aware implementation — it doesn't discriminate between them. This isn't quite tautological (it does check real inequalities on real masks), but it provides no coverage of the failure mode the brief itself names as the reason purge/embargo exists.

## Items checked with no findings

- **Purge applied only on the training side**: confirmed — `oos_mask = times > cut_time` has no purge subtraction; a signal just after the cut is accepted into OOS unconditionally, matching the brief's stated intent ("that's fine").
- **`is_mask`/`oos_mask`/`purged_mask` partition exactly**: re-derived by hand and confirmed with a duplicate-timestamp-at-cut fixture — a signal exactly at `cut_time` lands in `purged_mask` (not `is_mask`), and the three masks sum to exactly 1 per row in every case tried, including ties.
- **`np.quantile` int64→float64 precision**: current-era `datetime64[ns]` epoch integers (~1.7×10¹⁸) do exceed 2⁵³, so `np.quantile`'s internal float64 interpolation is not bit-exact in principle — but the resulting error is bounded to a few hundred nanoseconds, roughly ten orders of magnitude below the hour-scale granularity every mask comparison operates at. Verified no observed drift in a direct int-math-vs-`np.quantile` comparison on a 1000-row H1 fixture (diff was exactly 0.0 ns in the case tried). Not a practical defect.
- **ISO year-week boundary collision**: `week_clusters` uses `idx.isocalendar()`'s `.year` column, which is the *ISO* year (already correctly rolled for the December/January boundary), not calendar `.year`. Verified directly: `2024-12-30` (a Monday belonging to ISO week 2025-W01) labels as `"2025-W01"`, distinct from `"2024-W01"`; `2023-01-01` (ISO week 2022-W52) labels as `"2022-W52"`, distinct from any 2023 week. No collision across the year boundary.
- **`test_roughly_seventy_percent_lands_in_train` band width (0.60–0.72)**: this test is coarse by design and would not catch a single-signal boundary leak (irrelevant at n=1000 scale), but it does catch gross errors — e.g. an accidental row-index split (~0.85, fails high) or a 10x-oversized purge band (~0.54, fails low) both fall outside the asserted range. Reasonable as a population-level sanity check; not the right tool for the leakage question, which the other tests are meant to cover.

## A) SPEC COMPLIANCE — PASS

- `SPLIT_FRAC`, `H_BARS`, `EMBARGO_BUFFER_BARS` imported from `scripts/confidence_screen/__init__.py`, not redefined. ✅
- numpy/pandas only; no scipy or other new dependency. ✅
- Nothing under `src/` modified; no earlier task's file modified (only the two new files in this diff). ✅
- stdlib `unittest` only. ✅
- Interfaces match the brief exactly: `split_masks(times, symbols, frac=SPLIT_FRAC, horizon_bars=H_BARS, buffer_bars=EMBARGO_BUFFER_BARS, bar_minutes=60) -> dict` with the four required keys; `week_clusters(times) -> np.ndarray`. ✅
- All 7 prescribed tests present and passing. ✅

The implementation is a byte-for-byte transcription of the brief, and the brief's own interface/steps are followed to the letter.

## B) TASK QUALITY — Not approved

The transcription is faithful and the process (TDD steps, git hygiene, only two files staged) was followed correctly — the implementer's process claims check out. But the CRITICAL finding above is real and consequential: this task's whole purpose is to prevent the leakage that silently inflates the study's OOS result, and the shipped code (matching the brief) fails to do that across weekend boundaries, with no test that would catch it. Given the review brief for this task explicitly names this exact risk ("does the wall-clock band under-purge across a weekend boundary"), shipping it unaddressed is a quality gap regardless of whether the root cause traces back to the brief's own reference code. This needs either a bar-index-aware embargo (walk forward N actual bars per symbol rather than a fixed wall-clock delta) or, at minimum, a widened/conservative wall-clock buffer with a test that models a real weekend gap, before this is safe to build the rest of the screen on top of.

## Verification note

No files were mutated during this review; all checks were run via read-only `unittest` execution and standalone scratch scripts against the already-committed module, not by editing repository files.
