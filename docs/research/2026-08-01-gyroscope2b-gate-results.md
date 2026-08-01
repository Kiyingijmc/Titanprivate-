# Gyroscope v2b gate — results: GO (7/7)

**Date:** 2026-08-01 · **Pre-registration:** `2026-08-01-gyroscope2b-gate.md` (committed
23769b8 before the run; owner-ratified calibration metric, all else frozen at v2 values) ·
**Run card:** `data/results/gyro2_gate/20260801T111531Z_gyroscope2_POOLED6_H1/` (root
checkout) · **Harness:** `scripts/gyro2_gate.py` @ 23769b8 · **One pass.**

## Verdict: GO

All seven criteria pass. The run reproduced the v2 gate's economics digit-for-digit
(deterministic harness; the only change was the ratified criterion-7 metric), so the two
run cards corroborate each other.

| # | Criterion | Bar | Result |
|---|---|---|---|
| 1 | Economics | pooled > 0, OOS > 0 | +0.057R pooled · IS +0.068 · OOS +0.033 |
| 2 | Cost | median ≤ 0.25R | 0.033R |
| 3 | Stress ×1.5 | ≥ 0 | +0.040R |
| 4 | Breadth | ≥ 4/6 non-negative | 4/6 (BTC +25.5, US100 +20.9, US30 +13.9, ETH +10.7 / XAU −3.2, XTI −4.3) |
| 5 | Sweeps | ≤ 1/4 sign flips | 1/4 (δ−30% negative; others +52.8…+66.1R) |
| 6 | Bootstrap 5% LB | > −0.05R | **+0.003R** (positive) |
| 7 | Calibration (ratified) | ≤ 2.0 sig/day AND median gap ≥ 48h | **1.03/day · 114h** (flip-rate 52%, non-binding) |

n=1,112 trades over ~3y, PF 1.13, max DD 23.6R, win rate 38%, median hold 4 bars, 4
time-stop exits. Under the v1-comparable fixed-exit accounting the stream is +0.035R
gross (PF 1.05) — the managed engine amplifies it, consistent with EXP-0.

## Interpretation and honest caveats

- The evidential weight lives in the v2 run; 2b re-scored the same deterministic data
  under a metric ratified after that data was seen (documented in the 2b registration's
  transparency note). What protects this GO from being a re-tune artifact: zero
  parameters changed between the runs, the corrected metric is mechanism-motivated, and
  criteria 1–6 — untouched — passed on the first (blind) pass.
- Breadth and sweeps sit exactly at their bars; XAUUSD and XTIUSD are net-negative, and
  XTIUSD flips clearly negative (−0.075R/trade) if its true spread is 5pts rather than
  the measured 2.
- Same harness caveats as the study family: same-bar SL-first pessimistic,
  partials-at-level optimistic, no slippage beyond spread.
- Per-trade edge (+0.057R) is ~3× smaller than SilverBullet's validated +0.19R; the value
  is diversification (stat family, calendar-independent, honors_htf_bias false) at ~1
  signal/day pooled.

## GO consequences (per registration: a PROPOSAL, not an enablement)

Recommended path to a demo-status canary, in order, each its own reviewed change:

1. **Live time-stop:** generalize TradeManager `time_exits` with a `max_bars`/hours
   variant wired to the Almanac-built exit hook (the offline gate assumed it; audit F5).
2. **Live spread gate:** populate `context['spread']` from the latest TICK so the
   strategy's `max_spread_atr_frac` check stops being inert (audit F6).
3. **Grading:** add `signal_grading.per_strategy_min_grade: {Gyroscope: "C"}` (audit F10).
4. **Config:** add the locked v2 parameters to `strategies.gyroscope` (sprt_on:
   innovation, z_confirm: 1.0, nis_persist: 10, reentry_lockout: 12) with pairs
   = the 6-symbol trend universe minus any the owner excludes (XAUUSD/XTIUSD are the
   weak slots; BTCUSD/ETHUSD/US100/US30 carried the run).
5. **Manifest:** `status: research → demo`, version 1.0.0 → 2.0.0 — owner sign-off, then
   the standard demo-soak observation window alongside SilverBullet + Almanac.

The v1 velocity mode remains the default in code; nothing changes live until 1–5 land.
