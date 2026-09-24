# M15 structural exits: initial diagnostic

**Decision: implemented for opt-in evaluation; do not replace live management universally.** Results are mixed across instruments and negative in aggregate. No live configuration, running process, or broker position was changed.

## What changed

First partial eligibility moves to 50% of the original target distance. The closed fraction is 25%, 35%, or 50%, selected from recent M15 trend efficiency and relative ATR. A second 25% partial is volatility-spaced. After the first stage confirms, remaining volume follows confirmed post-entry M15 higher lows/lower highs, with ATR/spread/tick buffers. The original TP stays until a profitable structural stop is proposed. Details: [management runbook](../runbooks/structure-management.md).

This interpretation of “50%” means halfway to target; it does not mean an unconditional 50% volume close. Fractions, trigger thresholds, and buffers were set before measurement and were not tuned to these results.

## Experiment

Reused the legacy H1 SilverBullet collector and its bias-and-grade gate, unchanged between arms. Compared existing `tight_runner` against `structure` using executable bid/ask prices on two assumed M5 paths, OHLC and OLHC. Arms schedule their own one-pending-or-open occupancy. These paths are sensitivities, not price-path bounds.

Quick sample: last 30,000 local M5 bars per instrument. EURUSD spans January 29–June 24, 2026; USDJPY January 5–June 1; gold January 20–June 24. Instruments therefore do not share identical dates. There are 38 filled trades per arm/path (19 EURUSD, 9 USDJPY, 10 gold), 48 expired orders and one pending at data end. The two paths reuse the same history and must not be counted as independent samples.

Fixed synthetic spreads: EURUSD 0.00008, USDJPY 0.01, gold 0.20. Commission: $7 per lot round turn, converted through stored tick specifications. Spread is already included in executable prices. Legacy break-even buffer: three instrument-helper pips. M15 context sees closed source bars only; a pivot needs two closed subsequent M15 bars.

## Results

Mean net R per filled trade; R is planned entry-to-stop risk.

| Instrument | Fills | Existing OHLC | Structure OHLC | Existing OLHC | Structure OLHC |
|---|---:|---:|---:|---:|---:|
| EURUSD | 19 | -0.161 | -0.357 | -0.270 | -0.394 |
| USDJPY | 9 | +0.361 | +0.391 | +0.223 | +0.391 |
| XAUUSD | 10 | -0.233 | -0.067 | -0.214 | -0.067 |
| Pooled | 38 | -0.056 | -0.104 | -0.139 | -0.122 |

The new exits improved this USDJPY and gold sample, but worsened EURUSD. Aggregate performance is worse under OHLC and better under OLHC, with both models still negative. This does not establish superior profitability or reliable profit retention. No symbol-specific settings were selected from these observations.

## Limits and reproducibility

The sample is small, reused, and not a fresh holdout. The legacy collector retains its historical clock/context assumptions; this is an exit-only comparison, not validation of the latest strategy entries or Gyroscope. Software execution and confirmations are immediate, and volume is continuous. Live lot rounding, broker stop/freeze constraints, latency, variable spreads, swap, news filters, and portfolio effects are not modeled. Gap stops precede software management. Float threshold comparisons include a sub-tick numerical tolerance so exact crossings are not incorrectly postponed; final results below include that correction.

Final run:

```sh
.venv/bin/python scripts/structure_exit_study.py --quick --out data/research/structure-exits-20260922-verified
```

The directory already exists; use a new destination to repeat. Full local data can be tested by omitting `--quick`. [Summary CSV](2026-09-22-structure-exits-summary.csv) and [source/data hashes and assumptions](2026-09-22-structure-exits-run.json) are retained with this report. Detailed order records are in the run directory.

Implementation tests cover causal swing confirmation, forming/future data exclusion, buy/sell stops, dynamic partial sizes, one-time stages, restart recovery, partial-fill retries, existing-trade preservation, tiny-volume behavior, emergency exits, and candle updates while paused. Broker/demo execution and larger out-of-sample evaluation remain necessary before activation.
