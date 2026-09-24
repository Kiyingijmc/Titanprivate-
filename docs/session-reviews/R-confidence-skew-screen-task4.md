# Review: Confidence–Skew Screen — Task 4 (Candidate feature panel with strict causality)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-58e3737..5e8cbd7.diff` (commit `5e8cbd7`)
**Files:** `scripts/confidence_screen/features.py`, `tests/unit/test_confidence_screen_features.py`

## Verification performed

- Ran `.venv/bin/python -m unittest tests.unit.test_confidence_screen_features -v` — 9/9 pass, matching the implementer's report. Diff is byte-for-byte the brief's own Step-1/Step-3 code (implementer's "None" deviation claim checks out via direct diff comparison).
- Confirmed via diff/`git status` that only the two declared files changed — nothing under `src/`, nothing from Task 1–3 (`__init__.py`, `population.py`, `grading.py`, `excursions.py`).
- Confirmed `NY_SHIFT`/`SEED` are imported from `scripts/confidence_screen/__init__.py`, not redefined; both match the frozen values there.
- Confirmed `f6_h4_agree` takes `h4_bias=None` default, returns `0` when `None`, and the module imports only `hashlib`/`numpy` plus the two constants — no `BiasEngine`, no `pandas`.
- Confirmed `FEATURE_SPECS` has exactly 8 entries, `PLACEBO_NAMES` exactly 2 (also test-enforced).
- **Mutation-tested the look-ahead guarantee directly** (all mutations applied, verified, then restored — confirmed byte-identical via `diff` against a saved copy):
  1. Introduced a global truncation off-by-one (`h1[field][:i+2]` instead of `:i+1` for all five arrays). **Caught** — `test_mutating_bars_after_the_signal_changes_no_feature` failed on `f3_efficiency` (`0.4476… != 0.9993…`).
  2. Introduced a leak isolated to `atr` only (f1/f2 read `h1["atr"][:i+6]` instead of the truncated `atr`), leaving every other field correctly truncated. **Not caught** — all 9 tests passed. Root cause: the test fixture builds `atr` as `np.full(n, 0.0010)` — a constant array. Every value in it is identical, so no possible look-ahead read of `atr` can ever change `f1_atr_pct` or `f2_atr_ratio`, regardless of how far into the future it reaches.
  3. Introduced a leak isolated to `low` only (f7's `r_lo` read `h1["low"][:i+6]` instead of the truncated `lo`), leaving `high`/`close`/`open`/`atr` correctly truncated. **Not caught** — all 9 tests passed. Root cause: `test_mutating_bars_after_the_signal_changes_no_feature` only tampers `close` and `high` (`tampered["close"][IDX+1:] += 5.0`, `tampered["high"][IDX+1:] += 5.0`); `low` is left byte-identical between `before`/`after`, so a leak that only reads future `low` values produces the same output both times. `test_appending_future_bars_changes_no_feature` doesn't help either — it appends 50 *new* rows past the end of the original 400-bar array, which is invisible to a leak of only a few bars past `bar_idx=300` (indices 301–305 already existed, unchanged, before and after the append).
- Checked the actual (non-mutated) implementation by inspection: all five arrays are truncated exactly once, at the top of `build_features`, to local variables `hi/lo/close/open_/atr`, and every feature computation reads only from those truncated locals — never from `h1[...]` directly. So **the shipped code is causally sound today**; the finding below is about the test suite's ability to catch a *future* regression in this frozen module, not a live bug.
- Checked degenerate-input guards: `r_hi == r_lo` → `0.5` (f7, tested implicitly via non-degenerate fixture but the branch itself isn't exercised by any test); `path == 0` → `0.0` (f3); `sd == 0` → `0.0` (f8); empty `prev_day` slice → `0.0` (f4). All four present and correct. `f2`'s `atr[-50:].mean()` and `f4`'s division by `risk` have **no** zero-guard, unlike the other four — see Minor finding below.
- Checked small-`bar_idx` behavior (window larger than available history): traced through f1–f8 by hand for `bar_idx` near 0. None crash — negative-slicing beyond array length silently returns the whole (short) array, and f4's explicit `len(...) == 0` guard covers the one case that would otherwise divide by nothing. No test exercises this region (the brief's own fixture only uses `bar_idx=300` against a 400-bar array). Traced upstream: `population.py` (Task 1, unmodified here) imposes no minimum-`bar_idx` floor before a signal enters the population, so this path is reachable in practice for signals very early in a symbol's H1 history, though real backtests are unlikely to have meaningfully-sized SilverBullet histories start at bar 0.
- Checked the placebo hash inputs (`f"{seed}:{salt}:{sig['symbol']}:{sig['bar_idx']}:{sig['time']}"`): none of these are price/outcome-derived, only signal-identity fields, and SHA256's avalanche property destroys any residual structure (e.g. `time` weakly encoding hour-of-day/session) — genuinely decorrelated from anything price-based, and deterministic per signal as required. No finding here.
- Checked `f4`'s `day_len = 24` "previous completed day" window against the 24/5 forex reality this universe trades in (`UNIVERSE_11`/`UNIVERSE_LIVE_9` in `__init__.py` — mostly forex pairs, plus symbols like `BTCUSD` that do trade weekends). A fixed 24-bar offset only aligns with an actual calendar day when every day in the window has exactly 24 H1 bars. Forex feeds typically have a short Friday session (closing hours before the weekend) and zero bars for the weekend itself; a fixed 24-bar lookback taken from a Monday or Tuesday signal will therefore not cleanly bound "Friday's" (or whichever day's) high/low — it silently blends partial-day boundaries rather than raising or falling back to a time-derived boundary, even though `h1["time"]` is available and unused for this purpose.

## A) SPEC COMPLIANCE — PASS

- `build_features(sig, h1, seed=SEED)` signature present (with the additional `h4_bias=None` keyword the brief's own interface section requires); returns a dict keyed by `FEATURE_SPECS` names plus the two placebo names.
- `FEATURE_SPECS`/`PLACEBO_NAMES` frozen at exactly 8/2 entries, test-enforced.
- Strict causality by construction: full arrays passed in, truncated internally at `sig["bar_idx"]` — verified both by inspection and by the (initially failing-to-fail, see below) look-ahead tests.
- `f6_h4_agree` takes injected `h4_bias=None`, returns `0` when `None`, imports neither `BiasEngine` nor `pandas`.
- Sign orientation: `f7_range_pos` matches the brief's exact formula (`1 - raw` BUY / `raw` SELL, test-verified via `buy + sell == 1.0`); `f8_ret_vol` flips sign with direction (test-verified); `f4_prev_day_dist` is direction-oriented (`raw`/`-raw`) though not test-verified for orientation specifically (see Minor below).
- `NY_SHIFT`/`SEED` imported, not redefined.
- Nothing under `src/` touched; no Task 1–3 file touched.
- stdlib `unittest` only.

## B) TASK QUALITY — Not approved

### Critical — the look-ahead tests cannot catch a leak through `atr`, `low`, or `open`

Per the brief's own stated bar for this: "would they catch a feature that indexes with a positive offset past `bar_idx`? … If the tests cannot catch that, say so — it is a Critical finding." I built exactly that mutation twice (isolated `atr` leak, isolated `low` leak) and both passed the full 9-test suite untouched. Two independent, compounding causes:

1. **The `atr` fixture is a constant array** (`np.full(n, 0.0010)`). No test in this module — nor any conceivably added under the current fixture — can distinguish a causal read of `atr` from a leaking one, because every element is identical. `f1_atr_pct` and `f2_atr_ratio` (2 of the 8 frozen features) are structurally untestable for look-ahead safety as written.
2. **The mutation test only tampers `close` and `high`**, not `low`, `atr`, `open`, or `time`. `f4_prev_day_dist` and `f7_range_pos` both read `low` (via `pdl`/`r_lo`); `f8_ret_vol` reads `open`. A leak confined to any of those fields is invisible to `test_mutating_bars_after_the_signal_changes_no_feature`, and the appended-future-bars test doesn't compensate — it only detects a *complete absence* of truncation (reading far past the array end), not an off-by-a-few read of data that already existed just past `bar_idx` in the original array.

The shipped implementation is causally correct today (single truncation point, all features read from the truncated locals) — this is a test-robustness gap, not a live bug. But it is exactly the failure mode the brief warned about: a future edit to this frozen, high-stakes module (e.g. Task 5 touching `f6`, or any later maintenance) could reintroduce a leak in `atr`/`low`/`open` and the suite would report green. Given this module's whole purpose is to prove the features can't leak, and the brief explicitly pre-registered this exact check, this should be fixed before the task is considered done: vary `atr` across bars in the fixture (not a constant), and extend the mutation test to tamper `low` and `open` as well as `close`/`high`.

### Important — `f4`'s fixed `day_len = 24` doesn't reliably bound an actual calendar day on a 24/5 forex feed

The universe (`UNIVERSE_11`) is mostly forex pairs with a short Friday close and no weekend bars; a fixed 24-bar lookback silently drifts against real day boundaries near the weekly gap (and after any holiday or feed gap that shortens a session), rather than deriving the boundary from `h1["time"]`, which is passed in and available. This doesn't break causality (still strictly backward-looking) and doesn't crash, so it doesn't corrupt the strict-causality property the module exists to guarantee — but it does mean `f4_prev_day_dist` is measuring an approximate, silently-inaccurate window for a meaningful fraction of signals (anything near a weekly boundary), with no comment flagging the approximation and no test exercising a week-boundary `bar_idx`. Worth fixing (derive the window from `time` deltas) or at minimum documenting as a known limitation before this candidate feature is scored in the screen.

### Minor findings

- `f2_atr_ratio` (`atr[-10:].mean() / atr[-50:].mean()`) and `f4`'s `raw = … / risk` have no zero-guard, unlike `f3`/`f7`/`f8`, which all guard their respective denominators. Real ATR/risk should never legitimately be zero, but the inconsistency (three guarded, two not) suggests it wasn't a deliberate risk assessment. `population.py` validates `sig["atr"] > 0` for the *signal's own* ATR but not the historical `h1["atr"]` window values consumed here.
- No test exercises `bar_idx` small enough to invoke any of the short-window fallback branches (f1/f2/f3/f7/f8 silently using fewer bars than their nominal window when history is short). Not necessarily wrong, but untested and undocumented as intentional.
- No test verifies `f4_prev_day_dist`'s direction-orientation the way `f7`/`f8` are explicitly tested (`buy == -sell` or `buy + sell == 1`); only `f7`/`f8` have that coverage even though the brief lists all three (4, 7, 8) as requiring sign orientation.

## Recommendation

Fix the Critical finding (vary `atr` in the fixture; extend the tamper test to `low`/`open`) before landing. The Important `day_len` finding should at minimum be logged as a follow-up/known-limitation if not fixed now, since it affects a shipped candidate feature's validity in the actual screen. The implementation itself (as opposed to its test coverage) is causally sound and spec-compliant.

MIG-VERDICT: CHANGES
