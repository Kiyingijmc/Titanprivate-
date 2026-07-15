# Antibody v1 — Counterfactual Study Results & Verdict

**Date:** 2026-07-15. **Verdict: RECORD ONLY — no adoption. Antibody v1 stays research.**
**Pre-registration:** docs/research/2026-07-14-antibody-study.md (criteria frozen before the run).
**Provenance:** SB run-card `20260715T003344Z_silver_bullet_POOLED9_H1` (git_sha `979dcda`);
study-card `20260715T055652Z_antibody_study/study.json`
(sha256 `550a77f2b8467c8d0fec2a62ef6152abde62a068d39b943a3535e4d4a344184f`, git_sha `979dcda`).
The SB run and the study both ran at the pre-registration commit (`979dcda`) — zero code
drift between registration and run.

## Mechanical verdict vs the 3 pre-registered criteria

| # | Criterion | Result | Pass? |
|---|-----------|--------|-------|
| 1 | Pooled alert rate < 2% of scored bars | **0.05%** (58 alert-bars / 116,856 scored) | ✅ PASS |
| 2 | n ≥ 30 SB trades entered inside alert windows | **n = 1** | ❌ FAIL |
| 3 | Inside expectancy negative AND ≥ 0.15R worse than outside | inside **+1.98R** (n=1), outside +0.044R; gap **−1.94R** (inside *better*) | ❌ FAIL (moot; n=1 is noise) |

**Criterion 2 fails decisively → pre-registered disposition: "insufficient sample — no
adoption, record only."** Only 1 of 1,386 filled SB trades entered inside any ALERT window,
so there is no powered sample to measure an inside-vs-outside expectancy difference. The
study is well-powered to measure the alert *rate* (criterion 1) but not the *overlap*.

## SB trade set (the run being overlaid)

Pooled `research_run`, 9 symbols, H1, split 0.7, live `min_grade B`, spread-mult 1.0:
3,319 signals → **1,386 filled trades** (681 skipped_busy). IS n=984 exp=+0.073R PF=1.11;
OOS n=402 exp=−0.021R PF=0.97 (SB's own edge is marginal here — expected; this study is
about the Antibody overlay, not SB's standalone edge).

## Alert windows (Antibody scoring)

Pooled alert rate **0.05%** — alerts are real but rare, and cluster in the most volatile
symbols. The 2-consecutive-bar ALERT entry rule (deliberately conservative, to reject
single-bar noise) makes sustained anomalies far rarer than the ~1% single-bar q99 rate.

| symbol | n_scored | alert-bars | alert_rate | windows | inside SB | outside SB |
|--------|---------:|-----------:|-----------:|--------:|----------:|-----------:|
| AUDUSD | 12,205 | 0 | 0.000% | 0 | 0 | 132 |
| BTCUSD | 19,723 | 28 | 0.142% | 9 | **1** | 178 |
| EURUSD | 12,631 | 3 | 0.024% | 1 | 0 | 143 |
| GBPJPY | 12,225 | 12 | 0.098% | 3 | 0 | 135 |
| GBPUSD | 12,631 | 3 | 0.024% | 1 | 0 | 170 |
| US30 | 11,286 | 0 | 0.000% | 0 | 0 | 186 |
| USDCAD | 12,225 | 3 | 0.025% | 1 | 0 | 158 |
| USDJPY | 12,205 | 9 | 0.074% | 3 | 0 | 137 |
| XAUUSD | 11,725 | 0 | 0.000% | 0 | 0 | 146 |
| **pooled** | **116,856** | **58** | **0.05%** | **18** | **1** | **1,385** |

## Degeneracy diagnostic (disclosure-C empirical check) — CLEAN

The Task-1 review flagged that the scale-blind ε=1e-9 covariance ridge could let a
near-constant feature dimension dominate the Mahalanobis distance on real data. The
per-symbol `fit_diag` refutes that here: every symbol's fit windows are well-conditioned.

| symbol | min feature variance | worst cov condition number |
|--------|---------------------:|---------------------------:|
| AUDUSD | 3.18e-03 | 1.7e+02 |
| BTCUSD | 1.60e-04 | 3.0e+03 |
| EURUSD | 3.06e-03 | 2.9e+02 |
| GBPJPY | 4.87e-03 | 1.4e+02 |
| GBPUSD | 3.48e-03 | 2.3e+02 |
| US30 | 5.90e-03 | 2.3e+02 |
| USDCAD | 3.35e-03 | 2.1e+02 |
| USDJPY | 3.89e-03 | 3.0e+02 |
| XAUUSD | 4.87e-03 | 1.4e+02 |

All min-variances are clearly nonzero and all condition numbers ≪ 1e4 (worst: BTCUSD
~3,000). No degenerate dimension; the ε=1e-9 ridge is never load-bearing on this data.
This confirms the prediction that M5→H1-resampled bars have real gap variance (f3 ≠ 0),
so the synthetic-fixture pathology from Task 1 does not reproduce on real market data.

## Top-10 alert episodes (descriptive sanity check) — real events

| symbol | start | end | dur (bars) | peak score |
|--------|-------|-----|-----------:|-----------:|
| BTCUSD | 2025-10-11 00:00 | 2025-10-11 02:00 | 3 | 17.61 |
| GBPJPY | 2026-04-30 11:00 | 2026-04-30 16:00 | 6 | 14.00 |
| USDJPY | 2024-10-28 00:00 | 2024-10-28 02:00 | 3 | 11.41 |
| BTCUSD | 2026-03-22 01:00 | 2026-03-22 03:00 | 3 | 10.25 |
| GBPJPY | 2025-04-03 00:00 | 2025-04-03 02:00 | 3 | 9.26 |
| BTCUSD | 2025-03-02 18:00 | 2025-03-02 21:00 | 4 | 8.54 |
| USDCAD | 2025-04-03 00:00 | 2025-04-03 02:00 | 3 | 7.59 |
| BTCUSD | 2024-10-15 17:00 | 2024-10-15 19:00 | 3 | 7.13 |
| BTCUSD | 2026-01-19 02:00 | 2026-01-19 04:00 | 3 | 7.11 |
| BTCUSD | 2024-04-13 23:00 | 2024-04-14 01:00 | 3 | 6.79 |

Episodes read as genuine outliers (crypto moves, GBPJPY/USDJPY volatility spikes) — short
(3–6 bars) and concentrated in the most volatile instruments. Not artifacts.

## Interpretation & disposition

- **The scorer works; the overlap doesn't exist.** Antibody flags real, rare geometric
  anomalies, but SilverBullet — a session-timing strategy — essentially never enters during
  them (1 of 1,386 trades). On this OHLC-only feature set + 3-yr dataset, an Antibody
  ALERT→block-SB-entry filter would have changed almost nothing, because there is nothing to
  block. This is a clean null result, not a failure of the machinery.
- **No adoption; no live wiring.** Per the pre-registered rule, insufficient inside-alert
  sample (n=1 ≪ 30) → RECORD ONLY. Antibody v1 stays research/disabled.
- **v2 is the honest next step (unchanged).** OHLC geometry alone rarely coincides with SB
  entries. The pre-registered v2 extension — tick-volume z + spread z, once live journaling
  accumulates them — targets feed pathologies (thin-book, spread blowouts) that are far more
  likely to overlap live entries than pure price-geometry outliers. This study neither
  supports nor refutes v2; it establishes that v1's feature set is inert *as an SB filter*.
- **Diagnostic dividend:** the degeneracy check came back clean, so the ε=1e-9 ridge and the
  four-feature construction are validated on real data for any future Antibody work.
