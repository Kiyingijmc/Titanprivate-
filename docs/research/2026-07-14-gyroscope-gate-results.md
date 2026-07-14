# Gyroscope gate — RESULTS: NO-GO

**Date:** 2026-07-15 (run executed 2026-07-14 18:15 UTC)
**Pre-registration:** `docs/research/2026-07-14-gyroscope-gate.md`, committed at `30ee17e`/`342820f` BEFORE any run.
**Verdict: NO-GO.** Four of the eight ANDed GO criteria fail decisively at the pre-registered defaults. Gyroscope stays `status: research`, disabled; `KalmanDrift` is retained as reusable analysis infrastructure.

## Headline run (defaults, run 1 of the pre-registered 11)

- Run-card: `data/results/gyro_gate/20260714T181505Z_gyroscope_POOLED9_H1/run.json`
  (sha256 `f6c18ee878146273…`), git_sha `342820f8`, overrides `{signal_grading.min_grade: C}` as pre-registered.
- 9 frozen symbols, 3 yr H1, 8,365 signals → 4,914 trades (3,451 skipped busy under one-open-per-symbol), 4,911 resolved.

| Split | n | expectancy | PF | total R | maxDD |
|---|---|---|---|---|---|
| IS (70%) | 3,439 | **−0.066 R** | 0.91 | −225.6 R | 241.7 R |
| OOS (30%) | 1,472 | **−0.071 R** | 0.90 | −104.2 R | 128.5 R |
| Pooled | 4,911 | **−0.067 R** | — | −329.8 R | — |

Per-symbol net: BTCUSD +32.2R, XAUUSD +35.7R, USDJPY +20.0R, US30 +2.6R positive; EURUSD −106.1R, GBPJPY −124.1R, GBPUSD −77.5R, AUDUSD −71.8R, USDCAD −40.9R negative → **4/9 non-negative**.

## The 8 pre-registered criteria

| # | Criterion | Result | Verdict |
|---|---|---|---|
| 1 | Pooled net ≥ +0.10 R/trade | −0.067 R | **FAIL** |
| 2 | ≥ 150 pooled trades | 4,911 | pass |
| 3 | ≥ 6/9 symbols non-negative | 4/9 | **FAIL** |
| 4 | OOS pooled net > 0 | −0.071 R | **FAIL** |
| 5 | ±30% sweeps don't flip sign | not run | moot (see below) |
| 6 | Beats MaSlopeBaseline | not run | moot |
| 7 | ×1.5 spread stress > 0 | not run | moot |
| 8 | Bootstrap 95% lower bound > 0 | −0.0997 R (OOS −0.131 R) | **FAIL** |

**Protocol deviation, disclosed:** a machine restart during run 2 (×1.5 stress, started 18:53 UTC) killed the detached run sequence; runs 2–11 were **not re-executed**. Under the gate's AND-logic this cannot affect the verdict: criteria 5–7 exist to guard a would-be GO (falsification of a positive headline), and the headline already fails criteria 1, 3, 4 and 8 by wide margins (the +0.10R threshold sits ~0.17R above the point estimate; the CI lower bound is negative by ~0.10R). Re-running ~27h of compute could not change NO-GO. Process note for future gates: pre-register this short-circuit rule explicitly.

## Pre-registered diagnostics (reported, not gating)

- **Realized false-entry rate: 27.1%** (1,330/4,911 resolved trades stopped within the 5-bar lockout) vs designed α = 5%. This exceeds the blueprint §14.6 self-audit kill-switch (2α = 10%) by ~2.7× — the strategy fails its own advertised error budget.
- **Signal frequency: ~10.7 signals/day pooled** across 9 symbols vs the designed "episodic drift participation." The SPRT fires near-continuously.
- Both confirm the caveat pinned in the Task-3 amendment and the gate doc: **α/β are nominal under autocorrelated velocity z-scores** — consecutive z values share filter state, so the LLR accumulates far faster than the iid theory assumes, collapsing the effective evidence threshold.

## Interpretation

The velocity-SPRT implementation is mechanically sound (filter algebra reviewer-verified; entries look-ahead-safe; costs per-symbol) — the *edge* isn't there: time-series momentum at H1 in FX majors is cost-dead here (consistent with this repo's MTF-PB v1/v2 and OTE NO-GOs), and the positive tails (XAUUSD/BTCUSD/USDJPY/US30, all trend-prone assets) are too thin to carry the FX losses. The distributional self-audit (false-entry rate ≫ α) independently indicts the decision layer's calibration under autocorrelation — fixing THAT (e.g., SPRT on non-overlapping velocity innovations, or block-decimated z) would be a new pre-registered study, not a tweak.

## Disposition

- `gyroscope` manifest stays `status: research`; config `enabled: true` is inert (research never activates; promote-gate guards `/enable`).
- `KalmanDrift` retained (`src/analysis/kalman_drift.py`) — reusable filter/velocity infrastructure with 11 passing unit tests.
- The Plan-07 platform deliverables stand regardless of this verdict: frozen 9-symbol dataset + glob-fallback, pooled `research_run` with per-symbol costing + bootstrap CI + overrides, MARKET/one-open resolution correctness (which also corrected SB's historical double-counting), manifest priority plumbing, bias-exemption generalization.
- Arsenal cadence: next candidate enters through the identical pipeline (Antibody study already spec'd on `feat/antibody-study`; Wave 2 after).
