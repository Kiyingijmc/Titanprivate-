# Scoped Re-Review: Confidence–Skew Screen — Task 4 fix (look-ahead test teeth + causal f4)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-76aa85b..94d56d1.diff` — single commit `94d56d1`
**Files touched (confirmed via `git show --stat 94d56d1`):** `scripts/confidence_screen/features.py`, `tests/unit/test_confidence_screen_features.py` — exactly the two expected files, nothing under `src/`, nothing from other tasks.

## Verification performed (independent, not taken from the report)

- Ran `.venv/bin/python -m unittest tests.unit.test_confidence_screen_features -v` on HEAD (`bf1cf44`, `features.py` unchanged since `94d56d1`): **11/11 pass**, matching the report's claimed output exactly.
- Saved a pristine copy of `features.py`, then ran three independent mutation trials, each restored via `git checkout --` and confirmed byte-identical (`diff` against the saved copy, and a final `git status --short` / `git diff --stat` showing clean) before moving to the next:
  1. **Global off-by-one** — all six `[:i + 1]` slices (`hi`, `lo`, `close`, `open_`, `atr`, and the new `time`) changed to `[:i + 2]`. **RED**: both `test_mutating_bars_after_the_signal_changes_no_feature` and `test_mutating_bars_immediately_after_signal_changes_no_feature` fail on `f1_atr_pct` (`0.484 != 1.0`).
  2. **Isolated `atr`-only leak** — only `atr = h1["atr"][:i + 1]` changed to `[:i + 2]`, every other field left correctly truncated. **RED**: both tamper tests fail on `f1_atr_pct` (`0.484 != 1.0`). This is precisely the leak the original CRITICAL finding said was structurally undetectable (constant `atr` fixture); with the now-varying, seeded `atr` fixture it bites cleanly.
  3. **Isolated `low`-only leak**, scoped exactly like the implementer's own "Mutation B" (a local `lo_leak = h1["low"][:i + 2]` used only inside `f7`'s `r_lo` computation, leaving the shared `lo`/`hi`/`close`/`open_`/`atr` locals untouched) — **RED**: both tamper tests fail on `f7_range_pos` (`0.177 != 0.00016`). This is precisely the second leak the original CRITICAL finding said was undetectable (tamper test only touched `close`/`high`).
  
  (Note: my first attempt at the `low`-leak trial mutated the shared `lo` variable directly, which also feeds `f4`'s `lo[mask]` read — that produced an `IndexError` from a length mismatch between `mask` and the now-differently-sized `lo`, not a clean assertion failure. That was an artifact of my own mutation being broader than the implementer's described one, not a defect in the fix; re-running with a leak scoped identically to the implementer's report (touching only `f7`'s local, not the shared `lo`) produced the clean RED shown above.)
- After each trial: `git checkout -- scripts/confidence_screen/features.py` then `diff` against the saved pristine copy → byte-identical every time; final state confirmed clean (`git status --short` empty, `git diff --stat` empty).
- **Fixture variance/determinism** (independently recomputed, not just read): `atr = 0.0010 + 0.00002*sin(arange(400)/6) + 0.000005*rng.normal(...)`, `abs(...) + 0.0003`, `rng = np.random.default_rng(7)` continuing the same stream as `close`. Recomputed twice with fresh `default_rng(7)` instances: 400/400 unique values, all strictly positive (min `0.001267`, max `0.001329`), and the two independent computations are exactly equal (`np.array_equal` True) — genuinely varying, deterministic, and seeded, not flaky.
- **`f4` causality by trace**: `time = h1["time"][:i + 1]` (same cutoff as `hi`/`lo`/`close`/`open_`/`atr`, computed at the top of the function); `bar_dates`, `prev_dates`, and `mask` are all derived from that already-truncated `time`, and `hi[mask]`/`lo[mask]` index into the same-length, already-truncated `hi`/`lo` locals. No read anywhere in the new branch reaches past index `i`. Hand-traced the weekend test's own arithmetic (`bar_idx = 18 + 2 = 20`, so `time[:21]` = all 18 Friday bars + first 3 Monday bars; `cur_date` = Monday; `prev_dates.max()` = Friday; `mask` selects exactly the first 18 (Friday) elements) and confirmed it matches the test's independently-computed `fri_hi`/`fri_lo` expectation. New code path is causal.
- **Frozen panel**: `len(FEATURE_SPECS) == 8`, `len(PLACEBO_NAMES) == 2`, same 8 key names and same `("placebo_a", "placebo_b")` tuple as the original `5e8cbd7` implementation — no renames, no additions/removals (checked via direct `python -c` import, not just reading the diff).
- **`f6`/import purity**: `build_features(sig, h1, seed=SEED, h4_bias=None)` signature unchanged; `f6 = 0 if h4_bias is None else int(h4_bias == sig["bias"])` unchanged; `grep "^import\|^from"` on `features.py` shows only `hashlib`, `numpy`, and `NY_SHIFT, SEED` from the package `__init__` — no `BiasEngine`, no `pandas` imported into the module (pandas remains test-only, pre-existing from before this fix, used only for `pd.Timestamp` in the test fixture).
- **Scope**: `git show --stat 94d56d1` confirms exactly the two files listed above changed; no `src/` file touched.

## Findings — verdict

### CRITICAL (look-ahead tests couldn't catch an `atr` or `low` leak) — **ADDRESSED**

Both originally-undetectable leaks are now caught, verified by direct reproduction (trials 2 and 3 above), not by re-reading the report's claims. The fix's two components are both real and both necessary: the `atr` fixture now varies (a constant fixture makes any read of it invariant to leak-vs-no-leak, independent of any tamper-test change), and the tamper helper now perturbs all five consumed arrays with field-specific, non-cancelling magnitudes (`low` pushed down rather than up, so a `.min()`-based leak can't hide behind "increases can't create a new minimum"; `open`/`close` shifted by different amounts, so `close - open` can't cancel a leak that reads a future close/open pair together). I additionally re-derived the min/subtraction-cancellation reasoning from first principles rather than taking the report's explanation on faith, and it holds.

### IMPORTANT (`f4`'s fixed `day_len=24` doesn't bound a real calendar day) — **ADDRESSED**

Replaced with a calendar-date derivation from `h1["time"]`, confirmed causal by trace (above) and confirmed correct against the new weekend-gap test's independently-computed expected value. This is a materially better fix than a "known limitation" comment would have been — it actually eliminates the drift the finding described, not just documents it.

### MINOR (missing zero-denominator guards on `f2`/`f4`) — **ADDRESSED**

`f2_atr_ratio`: `denom = float(atr[-50:].mean()); f2 = ... if denom > 0 else 1.0`. `f4_prev_day_dist`: `risk <= 0` folded into the existing empty-window guard, both falling back to `0.0`. Consistent in style with `f3`/`f7`/`f8`'s pre-existing guards, as the report claims.

## Item 2 — the residual `open`-leak-at-depth-`i+5` gap (report's own disclosure)

Assessed by reasoning about the two tamper tests' actual coverage, not just accepting the report's framing. `test_mutating_bars_after_the_signal_changes_no_feature` tampers with an **open-ended** slice (`slice(IDX + 1, None)`) — it perturbs every index from `bar_idx+1` through the end of the 400-bar array (indices 301–399), not just a narrow window. `test_mutating_bars_immediately_after_signal_changes_no_feature` tampers only `IDX+1..IDX+3`. The near test's range is a strict subset of the far test's range. So a leak reading any fixed offset — `i+1`, `i+3`, `i+5`, `i+6`, anything up to `i+99` — is still caught by the far test; the disclosed gap is only that the *near*-named test specifically doesn't fire for a fixed offset of `+5` when its own window stops at `+3`. This is not a hole in the module's overall leak-detection coverage (verified independently: I did not find any offset that evades both tests), it's a naming/scope mismatch in one of two overlapping tests. **Classification: non-blocking / cosmetic.** It would only become a real gap if the far test's tamper slice were ever narrowed to match the near test's window, which it isn't. The report's own transparency about it (rather than silently omitting the one non-red result) is itself a positive signal, not a defect to chase further.

## New breakage in the fix diff

None found. All 11 tests pass on the unmutated file; the three independent mutation trials (including one I initially got wrong through my own broader mutation, corrected and re-run) all restore cleanly to a byte-identical file; no other file touched; no change to sign orientation, R-unit scaling, `FEATURE_SPECS`/`PLACEBO_NAMES`, or the `f6` injection contract.

## Deferred minors (non-blocking, out of scope for this fix)

- No test exercises `f4_prev_day_dist`'s direction-orientation (`raw`/`-raw` for BUY/SELL) the way `f7`/`f8` are — still true post-fix, was flagged as minor in the original review and not part of this fix's required scope.
- The weekend-gap test builds its own bespoke `h1` fixture with a constant `atr` (`np.full(n, 0.0012)`) rather than reusing the now-varying `_h1()` helper — harmless here since that test doesn't exercise look-ahead, only `f4`'s date logic, but worth noting for consistency if this file is touched again.

MIG-VERDICT: PASS
