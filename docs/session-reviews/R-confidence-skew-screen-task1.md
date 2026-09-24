# Review: Confidence–Skew Screen — Task 1 (Constants and population builder)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-c4e3af4..7fe3b55.diff` (commit `7fe3b55`)
**Files:** `scripts/confidence_screen/__init__.py`, `scripts/confidence_screen/population.py`, `tests/unit/test_confidence_screen_population.py`

## A) SPEC COMPLIANCE — PASS

Walked every brief requirement against the diff:

- **Files created exactly as specified**: the three files in the brief, and the diff is a byte-for-byte transcription of the brief's Step 1/Step 3 code blocks.
- **Frozen constants**: all 12 match the global constraint list exactly — H_BARS=12, W_BARS=12, RR=2.0, ATR10_MULT=1.0, NY_SHIFT=-7, Q_FDR=0.10, ECONOMIC_FLOOR_R=0.25, SPLIT_FRAC=0.70, EMBARGO_BUFFER_BARS=4, BOOTSTRAP_DRAWS=10000, SEED=20260804, INJECT_TARGET_RHO=0.15, MIN_CELL_N=30.
- **UNIVERSE_11 / UNIVERSE_LIVE_9**: exact match, including UNIVERSE_LIVE_9 = UNIVERSE_11 minus GBPCAD and XBRUSD, order preserved.
- **Interfaces**: `add_stop_and_target(sig) -> dict` and `build_population(symbols, collect=None, tf="H1", quick=False) -> list[dict]` match the brief exactly. `build_population`'s default lazily imports `scripts.poc_sb_stops.collect_signals`; its real signature/return `(signals, bars)` (or `(None, None)` on missing file) and the key set (`bar_idx, time, dir, entry, far_extreme, sig_high, sig_low, atr, body_atr, bias, liq_status, hour, year`, confirmed at `scripts/poc_sb_stops.py:105-116`) genuinely matches what `population.py` consumes — not just satisfied by the test's fake stub.
- **No `resolve()` call, no `busy_until`, no limit-fill filter, no expiry drop**: confirmed by inspection (`population.py` never references `resolve`) and by `test_overlapping_signals_are_all_retained`, which proves three signals one bar apart all survive.
- **ATR10 stop / 2R target math**: `sl = entry - 1.0*atr` (BUY) / `entry + 1.0*atr` (SELL); `tp = entry + 2*risk` (BUY) / `entry - 2*risk` (SELL) — matches the constraint.
- **`src/` untouched**: `git diff c4e3af4..7fe3b55 --stat` touches only `scripts/confidence_screen/*` and the new test file.
- **Tests are stdlib `unittest` under `tests/unit/`**: confirmed.

No scope creep — the diff is a faithful transcription of the brief, nothing more.

## B) TASK QUALITY — Approved

Re-ran only the new test module directly (not the full suite) to verify the implementer's claim independently:

```
Ran 7 tests in 0.002s — OK
```

All 7 named tests present and passing, matching the report.

Test-quality audit (would each test fail against a wrong implementation?):
- `test_buy_stop_is_one_atr_below_entry` / `test_sell_stop_is_one_atr_above_entry` / `test_target_is_exactly_two_r`: assert against literal hand-computed constants (1.0990, 1.1010, 1.1020/1.0980), not values re-derived from the code under test — not tautological. A sign flip or wrong multiplier fails these.
- `test_zero_atr_signal_is_rejected_not_silently_zero_risk`: guard is `if atr <= 0.0: raise ValueError` — correctly raises instead of producing a zero-risk trade; a naive implementation without the guard would fail this test.
- `test_overlapping_signals_are_all_retained`: asserts population length and exact `bar_idx` ordering against a fake `collect` — the key anti-regression test for the spec's central constraint (no `busy_until`); would fail if a one-open-per-symbol cursor were reintroduced.
- `test_symbol_is_stamped_on_every_signal`, `test_symbol_with_no_data_is_skipped_not_crashed`: non-tautological, would fail under a broken implementation (missing `symbol` key, or a crash on `(None, None)`).

## Findings

None. No Critical, Important, or Minor findings survive review.

One non-defect observation for the record: the guard `atr <= 0.0` also correctly covers negative ATR, but only the zero case is exercised by a test. The brief only required the zero case, so this is not a gap against spec — just worth noting if a later task needs negative-ATR coverage.

MIG-VERDICT: PASS
