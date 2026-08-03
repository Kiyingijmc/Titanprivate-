# Gyroscope v2 gate — results: NO-GO (criterion 7 flip-rate; 6/7 pass)

**Date:** 2026-08-01 · **Pre-registration:** `2026-08-01-gyroscope2-gate.md` (committed
e656d8e, before the run) · **Run card:** `data/results/gyro2_gate/20260801T111005Z_gyroscope2_POOLED6_H1/`
(root checkout) · **Harness:** `scripts/gyro2_gate.py` @ e7cfaac · **One pass; no re-runs.**

## Verdict

**NO-GO as registered.** All six economic/robustness criteria pass; the calibration
criterion (7) fails on its flip-rate sub-metric (52.0% vs ≤25%). Per the pre-registration's
all-7 rule the verdict is NO-GO, and the innovation-SPRT configuration does not change
status on this run.

## Scorecard

| # | Criterion | Registered bar | Result | |
|---|---|---|---|---|
| 1 | Economics | pooled net > 0 and OOS > 0 | **+0.057R** pooled (IS +0.068 / OOS **+0.033**) | PASS |
| 2 | Cost screen | median RT cost ≤ 0.25R | **0.033R** | PASS |
| 3 | Stress | ≥ 0 at ×1.5 spread | **+0.040R** | PASS |
| 4 | Breadth | ≥ 4/6 symbols non-negative | 4/6 (BTC +25.5R, US100 +20.9R, US30 +13.9R, ETH +10.7R; XAU −3.2R, XTI −4.3R) | PASS (at the bar) |
| 5 | Sweeps | ≤ 1 of 4 flips pooled sign | 1 of 4 (δ−30% → −11.3R; other three +52.8…+66.1R) | PASS (at the bar) |
| 6 | Confidence | bootstrap 5% LB > −0.05R | **+0.003R** (LB is positive) | PASS |
| 7 | Calibration | ≤ 2.0 signals/day AND flip ≤ 25% | 1.03/day ✓ · **flip 52.0% ✗** | **FAIL** |

Pooled: n=1,112 trades, PF 1.13, max DD 23.6R, win rate 38%, median hold 4 bars,
time-stop exits 4, skipped-busy 16. Fixed-SL/TP secondary accounting (v1-comparable):
gross +0.035R, PF 1.05, DD 45.5R — the managed engine amplifies the stream, consistent
with EXP-0.

## What the run proves about the redesign (vs the v1 audit)

The F1/F3 pathology is fixed, measured on the registered metrics' own terms:

| | v1 (2026-07-14) | v2 (this run) |
|---|---|---|
| Signals/day (pooled) | 10.7 (9 syms) | **1.03** (6 syms) |
| Median same-symbol gap | 11 h | **118 h (~5 days)** |
| Pooled net /trade | −0.067R (fixed exits) | **+0.057R** (managed) / +0.035R gross fixed |
| Max drawdown | 241.7R | **23.6R** |
| Bootstrap 5% LB | −0.0997R | **+0.003R** |

This is the first stat-family gate in this repo with a positive OOS net and a positive
bootstrap lower bound under full measured costs.

## Why criterion 7's flip-rate failed — and why that sub-metric was mis-specified

The flip metric counts direction changes between *consecutive same-symbol signals*. With
episodes a median 5 days apart, ~50% flips is the signature of **independent** episodes —
the exact property the redesign targeted. v1 scored "better" (42%) only because it
re-fired the *same* direction every 11 h inside one trend: serial correlation, i.e. the
pathology itself. A threshold of ≤25% therefore demands cross-episode autocorrelation and
punishes the fix. The signals/day sub-metric (the actual F1 measure) passed with 2×
margin. The mis-specification is the registrant's error (mine), documented here; the
registered verdict is still honoured.

## Caveats

- XTIUSD sensitivity: at a 5-pt spread (vs measured 2) its expectancy is −0.075R/trade;
  it is net-negative in this run regardless (−4.3R).
- Breadth and sweeps pass exactly at their bars (4/6, 1-of-4) — no margin.
- Same model caveats as the parent harness family: same-bar SL-first pessimistic,
  partials-at-level optimistic, slippage beyond spread not modeled.
- Data spans differ slightly (incumbent symbols → 2026-06-24, screen cohort → 2026-07-28).

## Disposition (owner's call — no further runs without a decision)

1. **Accept the NO-GO** and shelve Gyroscope v2 (status stays `research`); or
2. **Ratify a corrected calibration criterion** — e.g. keep signals/day ≤ 2.0 and replace
   flip-rate with "median same-symbol inter-signal gap ≥ 48 h" — in a **new pre-registered
   gate doc**, all parameters and the other six criteria byte-identical, and accept that
   its run is a second pass whose motivation is this documented mis-specification. Under
   option 2's metrics this run's data would read 1.03/day and 118 h, but the point of
   registering first is that the owner ratifies the metric *before* it is scored.

No config, manifest, or live-code enablement changes on this NO-GO: `sprt_on` defaults to
`velocity`, the manifest stays `status: research`, and the live book is untouched.
