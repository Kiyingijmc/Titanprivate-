# Gyroscope Gate — Pre-Registered Study (Plan 07)

Registered BEFORE the first gate run (see this file's git commit vs the
run-cards' timestamps). Strategy: `gyroscope` v1.0.0 (Kalman drift + SPRT,
H1 MARKET), status research. Baseline: `ma_slope_baseline` v1.0.0.

## Dataset (frozen)

- 9 symbols (the validated SilverBullet universe; GBPCAD/XBRUSD stay
  cost-excluded): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD,
  US30, BTCUSD.
- `data/lake/frozen/fbs/<SYM>/H1/*.parquet`, ~3 years (2023-06..2026-06),
  M5→H1 via `load_h1_from_m5`. Provenance + source sha256:
  `data/lake/frozen/PROVENANCE.md` (commit 9fce074).

## Fixed inputs

- Parameters: the `strategies.gyroscope` block in `config/config.yaml` at
  this commit (α=0.05, β=0.20, δ=0.40, q_atr_frac=0.05, r_frac=1.0,
  warmup 200, nis_window 50, k_sl 3.0, sl_atr_floor 0.8, rr_target 2.0,
  reentry_lockout 5). These ARE the pre-registered values; the headline
  verdict is evaluated at these defaults ONLY.
- Cost model: `trade_dollars` (spread + $7/lot commission, broker tick
  specs), spread per symbol = `scripts/poc_sb_stops.SPREADS` ticks ×
  spread-mult. Baseline stress: spread-mult 1.5.
- Split: chronological pooled 70/30 (IS/OOS) by signal-bar timestamp.
- Grading floor: `--set signal_grading.min_grade=C` for BOTH gyroscope and
  the baseline. Rationale: the SignalGrader scores SMC confluence, which is
  meaningless-and-hostile for non-SMC strategies; C-floor disables that
  selection identically for both arms. Recorded in every run-card
  (overrides + widened config_hash). A live flip would require a
  per-strategy grading policy first (post-GO work item).
- Exit model: the rig's deterministic first-hit SL/TP resolution
  (`resolve_trade` via `simulate_signals`, one open per symbol, MARKET
  fills at next H1 open). Reverse-SPRT/time-stop live exits are built and
  unit-tested but are NOT part of this offline gate's accounting — the gate
  measures entry quality under a fixed exit, exactly like the SB/OTE
  studies.
- Spread-screen honesty: offline replay carries no live spread, so
  Gyroscope's max_spread_atr_frac entry screen passes vacuously (optimistic
  on selection); cost is applied per-symbol via trade_dollars (conservative
  on cost) and the ×1.5 stress (criterion 7) is the binding cost-robustness
  check.
- KalmanDrift design note: the strategy runs the AMENDED velocity-SPRT
  design (Task 3 amendment) — the SPRT test statistic is z = v̂/√P_vel, the
  standardized Kalman velocity estimate, not the raw filter output. Because
  z is autocorrelated bar-to-bar (it is a smoothed state estimate, not an
  i.i.d. sample), the SPRT's α/β error-rate guarantees are NOMINAL, not
  exact: the classical Wald bounds assume independent draws. This is why
  the diagnostics section below treats the realized-false-entry-rate ≈ α
  check as an EMPIRICAL observation to report, not a guaranteed property to
  assume. It also carries the nis_persist boundary caveat from the Task-3
  review (Minor): NIS-suspend re-arm at the window boundary can, in rare
  cases, admit one extra bar of persistence past the nominal window edge.
- Offline exit-model note: as above, the offline gate's accounting is the
  rig's first-hit SL/TP resolution only; Gyroscope's live reverse-SPRT and
  time-stop exits are excluded from every number in this study.

## GO criteria (ALL must hold, evaluated at the defaults)

1. Pooled net expectancy ≥ +0.10 R/trade.
2. ≥ 150 pooled resolved trades.
3. ≥ 6/9 symbols with non-negative net total R.
4. OOS (final 30%) pooled net expectancy > 0.
5. ±30% one-at-a-time sweeps on (α, β, δ, q_atr_frac) — 8 runs — none
   flips the pooled net sign. FALSIFICATION ONLY: a better-looking sweep
   cell is never adopted as the result.
6. Gyroscope pooled net > MaSlopeBaseline pooled net (identical exit model,
   cost, floor, dataset).
7. ×1.5 spread stress keeps pooled net expectancy > 0.
8. Bootstrap lower confidence bound on pooled net expectancy > 0
   (deterministic: seed 11, 2000 resamples, 5% quantile — the run-card's
   ci.expectancy_lower_bound).

Diagnostics (reported, not gating): realized false-entry rate vs α on OOS
(entries stopped within reentry_lockout bars / entries); NIS-suspend
frequency; per-symbol expectancy spread. The realized-false-entry-rate ≈ α
check is EMPIRICAL ONLY (see the KalmanDrift design note above — SPRT
guarantees are nominal, not exact, under autocorrelated z).

## Known offline-honesty gaps (recorded, not gating)

- SKIPPED_BUSY conflation wart (Task 7): the rig's SKIPPED_BUSY status does
  not currently distinguish "signal skipped because a position was already
  open" from a genuinely zero-risk/invalid signal; a zero-risk INVALID
  signal from Gyroscope's own filter-uncertainty stops could in principle
  be mislabeled SKIPPED_BUSY. This is THEORETICAL ONLY for this gate:
  Gyroscope's filter-uncertainty (NIS-suspend) stops cannot themselves
  equal an entry, so they cannot collide with the one-open-per-symbol
  busy check. Recorded here for completeness, not because it affects this
  study's numbers.

## Commands (exactly these, scripts/run_gyroscope_gate.sh)

Defaults, stress, baseline, then the 8 sweeps — 11 pooled runs total.
Run-cards land under data/results/gyro_gate/ (gitignored; the results doc
records their sha256s).

## Advisory C (arbiter timeframe aging)

Gyroscope is H1: the arbiter `_bar_index` single-counter (P05 advisory C —
M5 closes would age H1 theses in ~60 min) is INERT for this offline study
and for any H1-only roster. It is a REQUIRED precondition before ANY live
flip of an M5-timeframe strategy, and per-tf aging must land before
Gyroscope itself flips live alongside any M5 strategy. A GO verdict here
does NOT waive it.

## Outcome

Recorded in docs/research/2026-07-14-gyroscope-gate-results.md after the
runs. GO → recommend demo-forward (the flip is the operator's decision).
NO-GO → gyroscope stays research/disabled; KalmanDrift remains reusable
analysis infra; result stands in the record.
