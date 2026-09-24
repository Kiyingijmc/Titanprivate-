# SilverBullet hardening and independent execution verification

## Outcome

The first hardening pass rejects malformed SilverBullet inputs and confirms
that the older profitability estimate cannot be used as the optimization
baseline. No strategy thresholds, enabled flags, risk settings or running
broker processes were changed. No deployment or live orders were performed.

The primary [execution diagnostic](2026-09-16-silverbullet-execution-diagnostic.md)
was independently rerun with:

```bash
.venv/bin/python scripts/sb_execution_diagnostic.py \
  --out data/results/sb_execution_validation_20260916
```

All twelve source hashes and all nine history-file hashes matched the original
run card before measurement. The rerun reproduced orders.csv, summary.csv and
run.json byte for byte. The summary SHA-256 is
`f955bd017ce4affc87c91059cc4182ad68f4734fee4944c90d2fbb7747ea20a9`.

All 32 pooled filter/exit/path combinations are negative. Raw runner returns
are -0.1189R / -0.0933R per fill; bias+grade+tight runner returns are
-0.1398R / -0.1025R. The two values represent O-H-L-C and O-L-H-C paths,
not confidence bounds or actual tick execution. Nine historical symbols were
tested; this is neither a fresh holdout nor the full current twelve-symbol
configuration.

Raw tight-runner mean before commission is -0.0690R / -0.0458R. Spread remains
embedded in those prices: this is not a zero-cost test. No symbol has positive
tight-runner net mean in both paths, with either raw or combined-filter entries.
Post-hoc symbol selection is not justified by these results.

## Changes made in this pass

- SilverBullet rejects nonfinite/nonpositive OHLC, ATR and entry prices,
  missing price columns, malformed candle extremes, missing/ambiguous FVG
  flags, and non-executable SL/TP geometry. Risk multipliers must be finite
  and positive at construction. Only the selected FVG edge is required.
- Corrected misleading strategy comments: the implemented default is H1,
  all-hour configured windows, with no first-gap-per-session restriction.
- Added hand-calculated regression examples showing that the actual legacy
  management replay can credit pre-fill highs and miss a same-bar reversal
  through a newly raised stop. Historical replay code is preserved.
- Updated the stale TTL test fixture to expect a cancellation request retained
  until broker confirmation, matching the existing controller behavior.

The input checks are a safety change, not a claim of improved expectancy.
The frozen real-controller signal parity test passes unchanged.

## Verification

71 tests passed across these two commands:

```bash
.venv/bin/python -m unittest tests.unit.test_sb_execution \
  tests.unit.test_sb_component_diagnostic tests.unit.test_management_confirmation \
  tests.unit.test_partial_lifecycle tests.unit.test_gateway_close_guard
.venv/bin/python -m unittest tests.unit.test_silverbullet_inputs \
  tests.unit.test_silverbullet_timing tests.unit.test_strategy_timeframe \
  tests.unit.test_sb_legacy_execution_difference tests.unit.test_signal_parity
```

The existing timeframe test helper emits an unclosed-event-loop resource warning;
the tests pass. The gateway tests use a C++ stub harness, not MetaEditor.

## What remains before a stronger performance claim

The research simulator does not execute TradeManager.sync_positions. Live
management waits for broker confirmation, applies cooldowns and volume rounding,
and can advance directly to L2 after a price jump. The simulator assumes
instantaneous management. Its rejected-BE branch advances its stage; live keeps
the desired intent until reconciled. No such simulated rejections occurred in
this historical run. The live runner's high-water and tightened flags remain
in memory, so restart continuity is another parity requirement.

Next work must reconcile known fills against execution/tick data, cover broker
acknowledgments and constraints, and align closed-bar context, clock, news and
portfolio admission. The updated gateway still requires MetaEditor compilation
and a demo lifecycle check. Parameter tuning and increased deployment should
wait for a credible baseline and an untouched evaluation period.

The two synthetic legacy counterexamples prove possible optimism; they do not
attribute the entire historical return difference to those defects. Several
execution assumptions changed together. The negative diagnostic weakens the
case for tuning SilverBullet first; Gyroscope's older managed-replay evidence
also needs execution review before it can be treated as a replacement.
