# MaSlopeBaseline gate — results: NO-GO (1/7), and the Gyroscope comparison it existed for

**Date:** 2026-08-01 · **Pre-registration:** `2026-08-01-ma-slope-baseline-gate.md`
(committed 94e61e1 before the run) · **Run card:**
`data/results/gyro2_gate/20260801T123856Z_ma_slope_baseline_POOLED6_H1/` (root checkout) ·
**Harness:** `scripts/gyro2_gate.py --strategy ma_slope` @ 94e61e1 · **One pass.**

## Verdict: NO-GO — decisively

| # | Criterion | Bar | Result | |
|---|---|---|---|---|
| 1 | Economics | pooled > 0, OOS > 0 | −0.027R pooled (IS −0.044 / OOS +0.010) | FAIL |
| 2 | Cost | median ≤ 0.25R | 0.056R | PASS |
| 3 | Stress ×1.5 | ≥ 0 | −0.056R | FAIL |
| 4 | Breadth | ≥ 4/6 non-negative | 2/6 (ETHUSD −152.2R alone) | FAIL |
| 5 | Sweeps | ≤ 1/4 sign flips | 4/4 negative (−130 … −371R) | FAIL |
| 6 | Bootstrap 5% LB | > −0.05R | −0.052R | FAIL |
| 7 | Calibration | ≤ 2 sig/day, gap ≥ 48h | **9.9/day · 4h gap** · flip 99.7% | FAIL |

n=6,046 trades from 10,855 signals (4,700+ skipped-busy), PF 0.95. The A2 audit
prediction held exactly: an SMA-slope sign is a coin that re-flips every few hours of
chop; 99.7% of consecutive signals reverse direction — the detector is pure whipsaw with
occasional trend rides that don't pay for it, even under the managed exit ladder.

## The comparison this strategy exists for (identical harness, universe, costs, exits)

| | MaSlopeBaseline | Gyroscope v2 (innovation-SPRT) |
|---|---|---|
| Pooled net /trade | **−0.027R** | **+0.057R** |
| OOS net | +0.010R | +0.033R |
| PF | 0.95 | 1.13 |
| Bootstrap 5% LB | −0.052R | +0.003R |
| Signals/day (pooled) | 9.91 | 1.03 |
| Median same-symbol gap | 4 h | 114 h |
| Direction flip rate | 99.7% | 52% |
| Trades (3y) | 6,046 | 1,112 |
| Sweep robustness | 0/4 positive | 3/4 positive |

Same bars, same replay engine, same costs: the Kalman filter + innovation-SPRT is worth
**+0.084R/trade over the dumbest defensible trend timer**, while trading 5× less often.
This is the criterion-6 baseline evidence the aborted 2026-07-14 gyroscope gate never
produced, and it directly answers "does the machinery add value over a naive rule": yes.

## Disposition

- **NO-GO recorded; no re-tune.** The config doctrine stands confirmed rather than
  assumed: *"Never a live candidate; stays research forever"* — now with numbers.
- Manifest stays `research`, config untouched, nothing wired live.
- Continued role: the mandatory trend-baseline comparator for any future stat-family
  gate on this harness (`--strategy ma_slope` reruns it deterministically).
