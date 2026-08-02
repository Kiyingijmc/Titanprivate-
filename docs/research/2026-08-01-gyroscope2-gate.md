# Gyroscope v2 (innovation-SPRT) — design + pre-registered gate

**Date:** 2026-08-01 · **Status:** PRE-REGISTERED (committed before the gate run; one pass;
NO-GO is a valid outcome) · **Prereq:** `docs/research/2026-08-01-gyroscope-audit.md`
(findings F1–F10). The 2026-07-14 NO-GO configuration stays NO-GO; this is a new design
entering its own gate, not a re-tune.

## Hypothesis

The Kalman level+velocity filter is a sound drift estimator; v1 failed because the decision
layer tested an autocorrelated statistic (F1), guaranteeing whipsaw. Running the SPRT on the
filter's **standardized one-step innovations** `u = ε/√S` — approximately white when NIS≈1,
which is the filter's own calibration target — restores approximate validity of the Wald
α/β boundaries and makes participation **episodic by construction**: the detector fires on
drift *onset* and self-quiets once the filter absorbs the new velocity, so a sustained trend
does not re-trigger (kills F3 at the root). Traded on **trend-prone asset classes only**
(crypto / metals / indices / energy — the classes where even broken v1 was net positive,
F8), under the **managed exit engine the live book actually runs** (F4), the entry stream is
hypothesized to clear the same economic bar the SilverBullet universe screen used.

## Design deltas (each mapped to an audit finding)

| Δ | Change | Finding |
|---|---|---|
| 1 | SPRT input `u = ε/√S` (signed standardized innovation) instead of `z = v̂/√P_vel` | F1, F2 |
| 2 | Crossing requires velocity agreement: LONG needs `z ≥ +z_confirm`, SHORT needs `z ≤ −z_confirm` | F1 |
| 3 | `nis_persist` decoupled from `nis_window` (10 vs 50) so the integrity brake is reachable | F7 |
| 4 | Gate accounting = **managed exits** (v14.4.2 ratchet+runner replay, same harness family as the SilverBullet study and universe screen), fixed-SL/TP reported alongside as a non-binding secondary | F4 |
| 5 | `max_bars_in_trade` time-stop actually implemented in the replay (48 H1 bars); live TradeManager wiring only lands on GO | F5 |
| 6 | Universe = trend-prone classes, pre-registered by mechanism (FX excluded; USDJPY excluded despite being +20R in v1 — it is FX) | F8 |
| 7 | Offline spread model uses measured FBS spreads per symbol; ×1.5/×2 stress; no vacuous screen | F6 |
| 8 | `reentry_lockout` 5 → 12 H1 bars (belt-and-braces; the innovation-SPRT already self-quiets) | F3 |

### Design-phase synthetic evidence (2026-08-01, scratchpad `sprt_synth.py`, seeds 7/8)

5,000-bar synthetic log-price, real `KalmanDrift` filter equations, both decision layers:

| Metric | v1 velocity-SPRT | v2 innovation-SPRT + z_confirm=1.0 |
|---|---|---|
| Pure-noise fire rate | 49/1000 bars | 10.2/1000 bars |
| Fires inside one 2,000-bar sustained trend | 124 | 15 (0 wrong-direction) |
| Detection delay of onset | bar 1055 | bar 1055 (no penalty) |

Synthetic data only — no market data was touched in the design phase.

## Locked parameters (no tuning after this commit)

```
sprt_on: innovation          z_confirm: 1.0
alpha: 0.05  beta: 0.20  delta: 0.40      # unchanged from blueprint, now ~meaningful
warmup_bars: 200  q_atr_frac: 0.05  r_frac: 1.0
nis_window: 50  nis_persist: 10
k_sl: 3.0  sl_atr_floor: 0.8  rr_target: 2.0
reentry_lockout: 12          max_bars_in_trade: 48
timeframe: H1                entry: MARKET, filled at next bar open
```

Managed-exit rules: the adopted v14.4.2 ladder exactly as the harness implements it
(BE at 0.382 (+3 pips), bank 30% at 0.618 → SL to L1, bank 50% at 0.886 → SL to L2,
runner trail 0.268×range, arm C tighten-on-giveback ON — matching the live soak config).

## Universe, data, costs

| Symbol | Class | Data (M5 → H1 resample) | Spread (broker pts, measured) |
|---|---|---|---|
| BTCUSD | crypto | `data/history/BTCUSD_M5.csv` (3y → 2026-06-24) | 1000 |
| ETHUSD | crypto | `data/history/ETHUSD_M5.csv` (3y → 2026-07-28) | 193 |
| XAUUSD | metal | `data/history/XAUUSD_M5.csv` (3y → 2026-06-24) | 20 |
| US30 | index | `data/history/US30_M5.csv` (3y → 2026-06-24) | 200 |
| US100 | index | `data/history/US100_M5.csv` (3y → 2026-07-28) | 200 |
| XTIUSD | energy | `data/history/XTIUSD_M5.csv` (3y → 2026-07-28) | 2 (sensitivity at 5 reported) |

Commission $7/lot round-trip; tick specs from `data/specs.json` + the universe-screen
harness values for US100/ETHUSD/XTIUSD (measured over the bridge 2026-07-28).
Chronological 70/30 IS/OOS split per symbol. One open trade per symbol.

## Pre-registered pass criteria (ALL must hold on the single gate run)

1. **Economics:** pooled managed net expectancy > 0 at 1× spread, **and** OOS net > 0.
2. **Cost screen:** pooled median round-trip cost ≤ 0.25R.
3. **Stress:** pooled managed net ≥ 0 at ×1.5 spread.
4. **Breadth:** ≥ 4 of 6 symbols non-negative net (full period).
5. **Robustness:** one-at-a-time ±30% sweeps on `delta` and `q_atr_frac` (4 runs): at most
   1 of 4 flips the pooled-net sign.
6. **Confidence:** bootstrap 5% lower bound on per-trade net (seed 11, n=2000) > −0.05R.
7. **Calibration (the F1 fix, verified empirically):** pooled signal rate ≤ 2.0/day across
   the 6 symbols, **and** same-symbol consecutive-signal direction-flip rate ≤ 25%
   (v1: 10.7/day, 42%).

**Verdict rule:** all 7 → GO (propose a demo-status canary to the owner, alongside live
wiring of the time-stop and spread gate). Any failure → NO-GO, results recorded, no re-tune.
Early termination after a failed criterion 1 or 2 is permitted (record what ran).

Harness: `scripts/gyro2_gate.py` (this branch), run-carded to
`data/results/gyro2_gate/`. Detector code: `src/analysis/kalman_drift.py`
`sprt_on="innovation"` mode (default remains `"velocity"` — v1 behavior untouched).
