# SilverBullet lower-timeframe variants: first screen

Follow-up: [M15 session validation](2026-09-17-sb-session-validation-results.md)
tests the fixed UTC+2 assumption against fixed UTC+3 and source-supported
seasonal EET/EEST. The seasonal M15 sweep/reclaim result is stronger later,
but still fails the advance rules. The original screen below remains an
accurate record of its declared fixed-UTC+2 experiment.

## Outcome

Built and tested three research-only detectors across M5, M15, M30, H1 and
H2, with all-hours and New York 10–11 a.m. modes, fixed and runner exits,
two M5 execution paths, and normal/stressed costs. **Zero of the 60 model
combinations passed the frozen research-shortlist criteria.** This is an
exploratory historical result, not a live profitability forecast or a claim
that every possible lower-timeframe strategy must fail.

The rules and acceptance criteria were written before measuring this screen:
[design and hypotheses](2026-09-16-sb-variant-design.md).
Every model's early/late scenario ranges are preserved in the compact
[60-model results CSV](2026-09-17-sb-variant-screen.csv). “Best/worst” columns
are observed scenario extrema, not statistical confidence bounds.

## What was built

| Detector | Entry | Initial risk | Hypothesis |
|---|---|---|---|
| Edge control | Near edge of a three-candle gap; newest candle displaces >=1 ATR | 1 ATR | Comparator for existing gap/displacement idea |
| Middle retest | Midpoint of gap following middle-candle displacement >=1 ATR | Beyond three-candle extreme +0.1 ATR, minimum 1 ATR | Retracement after displacement offers better entry geometry |
| Sweep reclaim | Middle retest, with first candle sweeping and reclaiming preceding 12-bar range | Same structural stop | Rejection plus displacement selects better reversals |

ATR is a 14-bar simple true-range mean. Body direction must agree with the
gap. Setup bars must be contiguous; sweep lookback must also be contiguous.
Incomplete resampled candles are discarded. Only completed candles can signal.
The control differs from the production collector and is explicitly a research
comparator, not a duplicate production backtest.

All models reject cost/initial-risk above 0.25R without widening the stop.
Pending orders expire after three signal bars of wall-clock time. Filled
positions have a twelve-signal-bar wall-clock holding limit. Fixed targets are
2R; the alternative uses the existing idealized ratchet/runner. New York mode
uses the first cost-eligible signal each date. There is no live registry entry
and no production candle-routing or enabled-strategy change.

## What the screen found

For comparability, this table shows **all-hours, fixed 2R, normal-cost, later
period** results. Ranges span the two M5 path assumptions; fills can differ.
It is a declared slice, not a table of each timeframe's best configuration.

| Timeframe | Edge control mean R | Middle retest mean R | Sweep reclaim mean R |
|---|---:|---:|---:|
| M5 | -0.1351 to -0.1328 | -0.1461 to -0.1459 | -0.0988 |
| M15 | -0.0946 to -0.0857 | -0.1448 to -0.1425 | -0.0550 |
| M30 | -0.0894 to -0.0758 | -0.1387 to -0.1356 | -0.1057 |
| H1 | -0.1265 | -0.0740 to -0.0707 | -0.0928 |
| H2 | +0.0579 to +0.0842 | -0.0250 to -0.0212 | -0.4658 (only 9 fills) |

H2 control's positive later period does not survive the early-period check:
early normal-cost means are -0.2354R / -0.2165R. It does not advance.

**M5 costs remain a binding constraint.** Across the whole history, before
occupancy and date splitting, the normal-cost filter rejects 36,466/53,977
edge-control patterns (67.6%), 95,288/170,967 middle-retest patterns (55.7%),
and 7,006/13,586 sweep-reclaim patterns (51.6%). The surviving population is
still negative in the all-hours fixed-exit later-period slice.

**The New York window produces observations worth recording, not promotions:**

| Model | Early normal mean | Later normal mean | Later stressed mean | Fills early / later normal |
|---|---:|---:|---:|---:|
| M15 sweep reclaim, fixed | -0.0016R | +0.0553R | +0.0292R | 105 / 97 |
| M30 edge control, fixed | -0.2452 to -0.2202R | +0.1705R | +0.1265R | 120 / 78 |

Both miss the sample floors (150 early, 100 late); neither has positive
early economics. M30 also lacks the required later symbol breadth. M15's
runner alternative is also negative early and underpowered. A +0.591R
H2 sweep/session cell has just ONE later fill and is not meaningful evidence.

There were 20 positive later normal-cost cells among 120 path/model cells.
These are correlated scenario observations, not 20 independent discoveries.
No model passed all sample, early/later sign, stress and breadth requirements.
No thresholds were retuned after seeing the results.

## Dataset, accounting and verification

Nine symbols: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30,
BTCUSD. Local history spans approximately June 2023–June 2026; exact bounds
and hashes are in run.json. Early history ends before 2025-01-01, later
evaluation starts 2025-01-08, with independent occupancy and a seven-day gap.
These dates divide previously inspected data; the later period is not a
fresh holdout. Preceding data can supply indicator warmup.

Costs use recorded indicative spreads plus $7/lot round-turn commission.
Stress multiplies BOTH by 1.5 while keeping the candidate population fixed.
Spread is embedded in executable prices, never deducted twice. Each exit
arm schedules its own pending/open orders. Time exits act on the first
available opening quote at/after the deadline, with resting SL/TP precedence.

**58 tests passed.** Tests cover detector direction symmetry, causal prefix
invariance, sweep/reclaim, cost rejection, NY DST and first-signal rules,
incomplete/duplicate candles, correct M5/M30 signal availability, time exits,
gap priority, structural risk, and existing execution regressions.

The independent artifact audit verified:

- all recorded source/history hashes;
- 1,474,751 order rows across 4,048 nonempty independent schedules;
- no overlapping pending/open slots within a schedule;
- signal-close timestamps and fill/P&L correspondence;
- commission reconciliation and admission/outcome counts;
- per-symbol accounting and all 480 pooled model/path/cost/period cells.

The order count includes repeated scenarios and unfilled orders; it is NOT
1.47 million independent trades. Eighty-eight marked filled tails occur
across scenario/period cells; their returns are terminal marks, not realized
broker P&L. Summary values aggregate these marked tails with closed fills.

Backward compatibility: rerunning the previous EURUSD H1 diagnostic with
the generalized replay produced exactly the same 10,484 order rows across
its 32 arms. New durations and structural-risk inputs are opt-in; old
defaults retain their behavior.

## Limits and next research decision

M5 OHLC paths do not reconstruct ticks. No variable spread, partial-fill
latency, volume rounding, broker stop constraints, swap, news or portfolio
capital allocation is modeled. The runner is still an idealized research
implementation, not the broker-confirmed live manager. Pooled R is not an
account return and no portfolio drawdown/Sharpe claim is made.

Historical broker UTC+2 is an assumption. NY conversion handles US DST but
the broker's historical offset schedule is unverified. H2 close alignment
also means its 10–11 a.m. window has seasonal availability differences.
UTC+3/session-timestamp reconciliation remains required before trusting a
session candidate. No candidate earned promotion, so this sensitivity was
not used to search for a better result.

Intrabar fill time is represented by the M5 fill bar's open for holding
deadlines; actual holding time can be up to five minutes shorter. A market
closure delays a due exit until the next available quote. Stops can gap
beyond 1R. Pending/session selection and time exits are experimental design
choices and have not been established as optimal.

The next defensible step is independent data/session verification for the
M15 sweep/reclaim hypothesis if research continues. Its mixed evidence is
insufficient for trading. A genuinely different hypothesis such as H1-aligned
M5 continuation must get a new frozen design and evaluation, rather than
lowering this screen's thresholds or repeatedly tuning these same data.
M1/M3 execution requires finer history; it cannot be inferred from this run.

## Reproduction and artifacts

```bash
.venv/bin/python -m unittest tests.unit.test_sb_variants \
  tests.unit.test_sb_execution tests.unit.test_sb_legacy_execution_difference \
  tests.unit.test_sb_component_diagnostic tests.unit.test_exp0_coinflip \
  tests.unit.test_sb_overlay
.venv/bin/python scripts/sb_variant_study.py --out data/results/sb_variants_NEW
.venv/bin/python scripts/audit_sb_variant_run.py data/results/sb_variants_NEW
```

Primary output: `data/results/sb_variants_20260916/` (gitignored). Contains
orders.csv, by_symbol.csv, summary.csv, decisions.csv, run.json and audit.json.
Output directories must be new; the runner refuses overwrite.

Primary summary SHA-256:
`fa3221710eca5a2d86c5caab94cf0cd255fb793ce52f3b10d433f47f88cb7f83`.

Implementation: `src/research/sb_variants.py`, generalized
`src/research/sb_execution.py`, and `scripts/sb_variant_study.py`.
