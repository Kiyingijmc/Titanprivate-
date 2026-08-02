# MaSlopeBaseline — audit + pre-registered gate (identical bar to Gyroscope v2b)

**Date:** 2026-08-01 · **Status:** PRE-REGISTERED (committed before the run; one pass;
NO-GO a valid outcome) · **Requested:** owner, in-session ("do the same for the
ma_slope_baseline strategy").

## Why gate the control at all

MaSlopeBaseline exists as the naive competitor for the Gyroscope family (novel-arsenal
§14.7 step 2); the v1 gyroscope gate's criterion 6 (baseline comparison) was **never run**
— the gate aborted after the headline NO-GO — so no baseline number has ever existed.
Gating it under the **byte-identical** harness, universe, costs, exits, and criteria as
`2026-08-01-gyroscope2b-gate.md` answers two questions at once:

1. Does the dumbest defensible trend timer clear the same economic bar on the trend
   universe? (If yes, that recontextualizes what the Kalman/SPRT machinery buys.)
2. Does Gyroscope v2 beat its own baseline — the comparison v1's gate promised and never
   delivered?

**Doctrine note, carried honestly:** `config/config.yaml` marks this strategy *"Never a
live candidate; stays research forever."* This gate does not overturn that by itself — a
GO here produces a *comparison record and an owner decision*, not an automatic canary.

## Audit (code review — there are no prior results to audit)

- `src/strategies/models/ma_slope_baseline.py` (48 lines): SMA(24) slope sign flip →
  MARKET; stop `1.0×ATR(14)` (consistent with the validated "H1 1.0×ATR" stop finding);
  TP 2R. The slope sign reduces to `sign(close[t] − close[t−24])` — a 24-bar momentum
  sign detector. Deliberately memoryless (only `_prev_sign` per symbol).
- **A1 — warmup-entry artifact:** on the first evaluated bar `_prev_sign` is 0, so any
  non-zero slope "flips" and the strategy enters immediately at warmup completion,
  regardless of whether any flip occurred. One spurious trade per symbol per cold start.
  The gate replays this faithfully (it is live behavior); left unfixed — the baseline's
  value is being untouched and dumb.
- **A2 — no participation control:** no cooldown, no spread screen, no time-stop of its
  own. Sign flips are frequent in chop, so the episodic-calibration criterion is expected
  to be its hardest bar. That is the point of a shared bar.
- **A3 — never wired live:** manifest `status: research`, priority 90, no `pairs` key
  (post-scoping it would be unscoped if ever activated — moot at research status).
- Tests exist (`tests/unit/test_ma_slope_baseline.py`); the class is exercised.

## Locked gate spec (everything shared is byte-identical to gyroscope2b)

- **Parameters (from the long-standing config; no tuning):** `ma_window 24, stop_atr 1.0,
  rr_target 2.0`, H1, MARKET filled next bar open.
- **Universe/data/costs/exits/split:** the 6-symbol trend universe, same M5→H1 CSVs,
  same measured spreads + $7/lot, managed arm-C ladder + 48-bar time-stop, 70/30 split,
  one open trade per symbol. Fixed-SL/TP reported as non-binding secondary.
- **Criteria 1–7:** identical to gyroscope2b, including the ratified calibration metric
  (≤2.0 signals/day pooled AND median same-symbol inter-signal gap ≥48 h; flip-rate
  reported non-binding).
- **Sweeps (criterion 5):** one-at-a-time ±30% on the strategy's two core parameters —
  `ma_window` 17/31 (rounded), `stop_atr` 0.7/1.3; ≤1 of 4 may flip the pooled sign.
- **Harness:** `scripts/gyro2_gate.py --strategy ma_slope` (this branch), fast path
  parity-checked in-run against the real `MaSlopeBaseline` class; run card to
  `data/results/gyro2_gate/` with strategy-tagged naming.

**Verdict rule:** all 7 → GO, meaning the baseline record stands and the owner decides
whether anything changes (doctrine above). Any failure → NO-GO, recorded, no re-tune.
Either way the results doc reports the side-by-side against Gyroscope v2b.
