# SilverBullet 3-Year Stop-Model & Timeframe Study — VALIDATED EDGE (H1)

**Date:** 2026-07-11 · **Rig:** `scripts/poc_sb_stops.py` (+ offline managed-exit replay)
**Data:** 3 years M5 (2023-06 → 2026-06), 11 instruments, FBS specs (`data/specs.json`),
costs charged in R per trade: indicative FBS spread (×1/×1.5/×2 stress) + $7/lot commission.
**Raw outputs:** `data/history/sb_stops_{M5,M15,H1}.log`, `data/history/sb_stops_trades_*.csv`.

## Question

The 2026-05-30 study killed SilverBullet's frictionless London-open edge: the live
stop is a fixed **0.2×ATR** buffer past the FVG edge (risk ≈ 1 pip on M5), so spread
alone costs ~1R+. The flagged-but-untested fix was **widening the stop**. This study
tests that, across timeframes, with the entry logic frozen (limit at the FVG edge of
a displacement candle, RR 2.0, TTL 12 bars, one open trade per symbol).

## Design

- **Stop models:** LIVE (0.2×ATR) · ATR05 (0.5×ATR) · ATR10 (1.0×ATR) · STRUCT
  (beyond the displacement structure +0.2×ATR).
- **Timeframes:** M5 (n≈31k trades), M15 (n≈10k), H1 (n≈2.2k) — same data, resampled.
- **Exits:** fixed 2R vs the v14.4 ratchet (BE @38.2%, bank 30% @61.8%, bank 50%
  @88.6%) vs ratchet+runner (TP dropped at 88.6%, trail 0.268×range). Replay is
  same-bar-SL-first (pessimistic); partials fill at the fib level (mildly optimistic).
- **Validation:** 70/30 chronological OOS split, per-year, per-symbol, spread ×1.5/×2,
  Wilson CIs. Grading-gate impact via an offline mirror of `SignalGrader`.

## Results

### 1. M5 and M15 are cost-dead at any stop width (confirms 05-30 finding at scale)

| TF | best model | gross exp | net 1× exp |
|----|-----------|-----------|------------|
| M5 | ATR05 | +0.415R (n=31,714) | **−1.318R** |
| M5 | LIVE (current live logic) | +0.067R | **−4.271R** |
| M15 | ATR05 | +0.392R (n=9,987) | −0.539R |
| H1 | ATR05 | +0.316R (n=2,280) | −0.094R (fixed exits) |

The gross edge is real and stable (+0.3…+0.45R for ATR05 on every TF) — the signal
concept works; intraday-scalp cost ratios kill it. **The live M5 config trades a
~1-pip-risk scalp paying ~1.5 pips of costs: −4.3R/trade expectation. It must not
go live as-is.**

### 2. H1 + the v14.4 management engine flips it net-positive

Fixed exits on H1 are still slightly negative; the ratchet/runner is the difference
(pooled, all 11 symbols, net 1× costs):

| H1 stop | FIXED 2R | RATCHET | RATCHET+RUNNER |
|---------|----------|---------|----------------|
| ATR05 | −0.094R | −0.092R | +0.037R |
| **ATR10** | −0.122R | **+0.087R** | **+0.109R, PF 1.26, DD 24R** |
| STRUCT | −0.083R | +0.014R | +0.031R |

The sign of the result does not depend on picking exactly ATR10 or exactly the
runner variant — all three wider stops improve monotonically with management.

### 3. Final portfolio (a-priori cost screen, not performance selection)

Keep symbols whose **median round-trip cost ≤ 0.25R** at the ATR10 stop — an
economic viability rule: it excludes **GBPCAD (0.26R)** and **XBRUSD (1.00R)** only.
Universe: EURUSD GBPUSD USDJPY AUDUSD USDCAD GBPJPY XAUUSD US30 BTCUSD.

**H1 · ATR10 stop · ratchet+runner · 9 symbols (n=1,837, ~11.8 trades/week):**

| slice | n | win% | exp | PF | maxDD |
|-------|-----|------|------|-----|-------|
| pooled net 1.0× | 1,837 | 47.1 | **+0.194R** | 1.53 | 14R |
| net 1.5× spreads | 1,837 | 47.1 | +0.160R | 1.42 | 15R |
| net 2.0× spreads | 1,837 | 47.1 | +0.125R | 1.31 | 16R |
| TRAIN 70% | 1,285 | 47.2 | +0.198R | 1.53 | 14R |
| **TEST 30% OOS** | 552 | 46.7 | **+0.185R** | 1.53 | 11R |
| 2023 / 2024 / 2025 / 2026 | — | — | +0.27 / +0.17 / +0.18 / +0.20R | all ≥1.42 | ≤14R |
| grade ≥ B | 1,327 | 48.3 | +0.222R | 1.62 | 10R |
| grade ≥ B, OOS 30% | 399 | 49.4 | +0.262R | 1.85 | 8R |

Per-symbol (full 11-sym run): 10/11 positive; XAUUSD +0.35R, USDJPY +0.27R,
EURUSD +0.20R … only XBRUSD negative. Timing: positive broadly across the day
(H07-17 +0.114R); the old H05-07 window is the best hour block (+0.39R, n=66)
but is NOT required for viability — no timing gate is adopted.

### 4. Grading gate

On the cost-viable H1 portfolio the **≥B floor helps** (+0.194 → +0.222R, and the
OOS slice improves most). ≥A over-filters (fewer trades, no expectancy gain).
Keep `min_grade: B`.

## Integrity caveats

- Stop model and exit variant were selected on this data (4×3 grid) → selection
  bias. Mitigations: monotone/robust across neighbours, perfect train/test
  consistency, every-year positivity, 10/11 symbols, survives 2× spreads.
- H1 bar-path replay can't order intrabar events exactly (SL checked first =
  pessimistic; partials at level = optimistic). Slippage beyond spread not modeled.
- Killzone hour in grading uses a fixed broker−7h NY offset (±1h DST wobble).
- 2026 covers Jan–Jun only. BTCUSD weekend sessions included.
- Indicative spreads (same table as the harness); re-measure live spreads after
  the first supervised week and re-run the cost stress if materially different.

## VERDICT & adopted live changes

**GO (supervised demo first).** SilverBullet moves to **H1, stop = entry ± 1.0×ATR,
runner enabled, 9-symbol cost-viable universe, no session gate, min_grade B.**
Expected profile at 1% risk/trade: ≈ +0.19R × 12 trades/wk ≈ **+2%/week expectancy**,
historical maxDD ≈ 14R ≈ −14% (within the 3%/day breaker's envelope; ~12 trades/wk
means most days trade 1–3 times).

Rollout: demo-forward-test ≥ 2 weeks; compare realized spreads/slippage and the
journal's grade distribution against this study before any live-capital decision.
