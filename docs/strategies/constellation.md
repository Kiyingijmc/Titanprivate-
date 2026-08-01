# CONSTELLATION — cross-asset lead-lag network model

> **Status:** candidate (Wave 4) — pre-registration pending · **Family:** network science /
> cross-sectional information diffusion · **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §8 · **Doc version:** 2026-08-01

## 1. Thesis and return source

Titan's book already streams up to 12 correlated symbols (majors, XAU, indices, crypto) through
the same `SystemController` loop. Constellation's thesis is that a rolling lead-lag graph over
these H1 return series — edge weight = cross-correlation at lags 1–3 bars, retained only where
stable across sub-windows — captures cross-asset information diffusion that is not instantaneous
at H1 granularity in retail-accessible instruments. A significant move in a persistent *leader*
node (e.g. a DXY-proxy basket, XAU) would imply a conditional expectation on its *laggard*
neighbours that has not printed yet; entering the laggard after the leader fires, with the
leader's move as pre-confirmation, is the return source.

This is, by the brainstorm's own framing, the single highest existence-risk concept in the
arsenal (brainstorm §8, §12 "Existence risk" column: 2/5, the second-lowest score on the sheet;
§13 does not shortlist it). Lead-lag at H1 in major FX pairs is heavily arbitraged by
institutional participants with faster infrastructure than a retail MT5 bridge; the realistic
hope, stated in the source doc, is narrower relationships such as metals→related-FX or
index→risk-FX, not a general 9×9 web. Whether *any* exploitable edge survives at our granularity
and cost structure is the open question this document exists to gate, not to answer.

## 2. Evidence base

No backtest, event study, or existence study has been run for Constellation. There is no
supporting evidence to cite. The following is adverse or context-setting evidence that bears
directly on its prospects:

| Source | Finding | Relevance to Constellation |
|---|---|---|
| Brainstorm §0 (ground rules) | "Any new concept that fires many small-target trades intraday is presumptively dead on arrival"; the only validated edge needed H1 granularity, wide stops, low frequency | Constellation is H1 by design, which is necessary but not sufficient — it still needs each triggered laggard trade to clear the cost gate on its own |
| Brainstorm §8 | "lead-lag at H1 in majors is heavily arbitraged" (author's own honesty note); existence risk scored 2/5, the second-worst on the comparative matrix (§12) | This is the strategy's own source document pre-registering scepticism about itself |
| The graveyard (brief) | OTE canonical −0.158R pooled; MTF-PB v2 −0.274R pooled; Gyroscope −0.067R pooled (27.1% realized false-entry vs 5% designed α) — three independent H1/H4-class NO-GOs on this rig | Establishes the base rate: most H1-class hypotheses on this rig have failed pre-registered gates. Constellation should be assumed to share that base rate absent evidence otherwise |
| EXP-0 coin-flip, Outcome 1 (brief) | Placebo entries through the full exit engine average −0.249R (0/20 reps positive) vs SilverBullet's real +0.109R; the exit engine amplifies real edge (+0.231R) but does not subsidise random entries (+0.075R) | **Direct implication for Constellation:** if the lead-lag signal turns out to be noise (plausible per the existence-risk score above), routing it through the same ratchet/runner exit engine will not manufacture positive expectancy. The entry itself must demonstrate a real conditional edge in the pure existence study (§6) before any backtest is worth running |

## 3. Signal specification

As described in the source brainstorm (not yet implemented; this is the pre-registered design,
subject to revision by the existence study in §6):

- **Universe:** the live symbol set already carried by `market_data` (currently up to 12 pairs
  per `config/config.yaml` `strategies.*.pairs`); the correlation graph is computed over whichever
  subset has sufficient synchronized H1 history.
- **Graph maintenance:** weekly refit of a lagged (1–3 bar) H1 cross-correlation tensor across all
  symbol pairs; daily stability check (edge retained only if its sign and rough magnitude hold
  across sub-windows of the fit period).
- **Trigger (leader fires):** a "leader" node's H1 return exceeds `k·σ` in direction `d`, where the
  edge from that leader to a given "laggard" is currently armed (stable, above a significance
  threshold).
- **Laggard check:** the laggard has not already moved more than 0.5× its historically implied
  response — i.e. the diffusion has not already happened.
- **Entry:** laggard, in the implied direction, at next bar open, subject to the standard cost
  screen (spread vs the implied target).
- **Stop:** vol-scaled (ATR-derived, not yet parameterized).
- **Target:** the β-implied response magnitude from the fitted edge.
- **Exit (non-target):** time stop at the edge's fitted lag + 2 bars (if diffusion hasn't happened
  on schedule, the thesis is wrong); full reversal of the leader's move flattens the position.
- **Filters:** news lockout (leader and laggard can gap together on a shared news event, which is
  not lag to exploit); multiple-testing control (a 9×9×3 lag matrix is dozens of simultaneous
  hypothesis tests — FDR correction is mandatory, not optional, and must be pre-registered before
  any edge is looked at).

None of the above (thresholds, `k`, lag windows, FDR α) has been calibrated. This is a design
sketch, not tuned code.

## 4. Architecture integration

- **Manifest sketch** (`config/manifests/constellation.yaml`, not yet created):
  ```yaml
  id: constellation
  version: "0.1.0"
  class_path: "src.strategies.models.constellation:ConstellationStrategy"
  family: network
  timeframe: H1
  requires: [network.lead_lag_graph]   # new FeatureBus resource, not yet built
  status: research
  priority: 70
  honors_htf_bias: false   # the graph's own leader-move IS the directional thesis
  ```
- **Class placement:** `src/strategies/models/constellation.py` (`ConstellationStrategy(BaseStrategy)`),
  following the `GyroscopeStrategy` precedent (`src/strategies/models/gyroscope.py`,
  `config/manifests/gyroscope.yaml`) of a non-SMC strategy that ignores `context['smc_df']` and
  calls `validate_data(df, min_length=…, check_smc=False)`.
- **FeatureBus resource to register:** unlike every existing strategy (SilverBullet, Gyroscope),
  Constellation's core input is **cross-symbol**, not per-symbol. `FeatureBus` resources currently
  scope as `symbol_tf | symbol | global` (`src/features/feature_bus.py`); the lead-lag graph is a
  `global`-scope resource (the correlation tensor spans the whole book) that individual per-symbol
  `on_new_candle` calls would then query for "is my symbol currently an armed laggard, and did its
  leader fire this bar?" This is new FeatureBus surface — no `global`-scope resource exists in the
  live pack today (`src/features/packs/smc_pack.py` is entirely `symbol_tf`).
- **Multi-symbol synchronization — the real engineering work.** `SystemController._run_strategies`
  (src/core/system_controller.py:917) is invoked once per symbol per candle close; a leader firing
  on symbol A and a laggard check on symbol B in the same H1 bar requires either (a) the leader's
  fire to be recorded in the global-scope resource *before* the laggard's own `_run_strategies`
  call runs later in the same bar-close batch, which depends on the order symbols are drained from
  the HEARTBEAT/candle-close queue, or (b) a one-bar-delayed design (laggard checks the *previous*
  closed bar's leader state, sacrificing the fastest possible entry for determinism). Given the
  brainstorm's own automation-complexity rating (§12, 7/10, annotated "multi-symbol synchronization
  in the controller is the real work"), (b) is the honest starting design — it trades a fraction of
  the (already speculative) edge for not requiring a controller-loop-ordering guarantee that does
  not exist today.
- **Order types:** MARKET on laggard entry (matches the "diffusion window" thesis — a LIMIT order
  waiting for a pullback could miss the window entirely).
- **Grading path (P8 statement):** Constellation is not SMC-shaped. Per the audit's P8 finding
  (brief §4 point 4; `config/manifests/silver_bullet.yaml` vs `gyroscope.yaml` requires lists), the
  `signal_grader` scores HTF alignment (30 pts), R:R (20), displacement (20), premium/discount
  (15), and killzone (15) — all SMC-specific except R:R. A Constellation signal has no FVG, no
  premium/discount zone, and (with `honors_htf_bias: false`) no HTF-alignment points either; it
  would structurally cap near 20/100 (R:R only) and never clear `min_grade: B`. Constellation
  cannot execute live until either (a) it is added to a non-SMC grading exemption path (the same
  problem Gyroscope already carries, unresolved as of this writing), or (b) a network-specific
  grading factor (edge stability score, FDR-adjusted significance) is added to the grader. This is
  new work, not a config flag.
- **HTF-bias stance:** exempt (`honors_htf_bias: false`) — the leader's move is the strategy's own
  directional thesis; gating it against H1 SMC bias would be gating one directional signal against
  an unrelated one.
- **Exit profile:** default ratchet/runner (`TradeManager.sync_positions`) is the fallback; whether
  a bespoke exit (hard time-stop at fitted-lag+2, no runner) suits a diffusion trade better than the
  SilverBullet-tuned ratchet is unvalidated — flag as needing per-strategy exit profile work (P7).
- **Risk interaction — the correlation-aware portfolio brake.** This is the one piece of
  Constellation with arsenal-wide value independent of whether the strategy itself ever ships
  (brainstorm §8 point 9, §11 strengths): "a leader firing on multiple laggards is one macro bet —
  cap the summed R across simultaneous constellation trades." Titan's existing correlation gate
  (`src/risk/correlation.py:96` `check_correlation`, threshold `self.threshold = 0.8` at line 24)
  is **direction-blind** — it blocks any two positions above ρ=0.8 regardless of whether they are
  same-direction (correlated risk) or opposite-direction (partially hedged), a defect tracked as
  audit **RISK-04** (`docs/audit-2026-07-30/02-AUDIT-REPORT.md:368`, backlog row
  `risk-04-correlation-check-is-direction`) and infra item **P4** ("Signed, fail-closed correlation
  + asset-class groups", `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:416`). Constellation's
  design point — one leader firing across several correlated laggards must be capped as a single
  macro bet, not summed as N independent risk units — is exactly what a signed, direction-aware
  correlation gate (P4/RISK-04) would need to express. Building that gate has value today (it also
  fixes RISK-04's known Tether-blocking defect per the audit) regardless of whether Constellation
  itself ever passes its existence study.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort (per audit) |
|---|---|---|---|
| P4 / RISK-04 | Signed, fail-closed correlation gate + asset-class groups (`src/risk/correlation.py:128`) | Constellation's correlation-aware portfolio brake needs a direction-aware gate to sit on; also fixes today's direction-blind block | 2 d |
| New: `global`-scope FeatureBus resource | Lead-lag graph as a cross-symbol resource; no `global`-scope resource exists in `src/features/packs/` today | Constellation's entire signal depends on cross-symbol state, which no current strategy consumes | Not sized; new pattern |
| P8 | Grading path for non-SMC signals | Constellation structurally caps below `min_grade: B` on the current SMC-shaped grader | 1 d (per audit estimate, shared across all non-SMC strategies) |
| Controller-loop ordering (new) | Deterministic within-bar sequencing across symbols, or an accepted one-bar-delay design | `_run_strategies` runs per symbol independently (system_controller.py:917); no cross-symbol ordering guarantee exists | Not sized; scope depends on chosen design (a) vs (b) in §4 |
| P7 | Per-strategy exit profile | Whether the default ratchet suits a fitted-lag time-stop trade is unvalidated | 1 d |
| P12 / STRAT-05 | Portfolio-level backtest | Needed to validate the correlation-aware brake's actual effect on drawdown, not just Constellation's own P&L | 3 d |

## 6. Validation plan

**Stage order is non-negotiable and follows the brainstorm's own prescription (§8, item 17):**

1. **Pure existence study first, before any backtest scaffolding is built.** For each candidate
   leader→laggard edge in the fitted lag matrix: distribution of laggard forward returns
   conditioned on a leader-fire event, in-sample only, with **FDR correction across the full
   9×9×3 (or however many symbols are live) comparison set** — pre-registered before the study
   runs, exactly mirroring the OTE study's grader-mirror discipline.
2. **Pre-commitment: ship nothing if no edge survives FDR correction.** This is stated explicitly
   in the brainstorm (§8 item 17: "Expect most to die; pre-commit to shipping nothing if none
   survive") and is restated here as a binding constraint on this document, not just the source
   brainstorm. A single surviving edge after correction across dozens of tested pairs is still a
   thin reed — treat a marginal survival as grounds for a second confirmatory sample, not a GO.
3. Only edges that survive step 1–2 proceed to a cost screen (implied laggard response vs 2×
   spread) and then a full TVP backtest (3-yr H1, pre-registered gate, ±30% parameter sweeps,
   70/30 chronological IS/OOS, bootstrap CI, per-symbol consistency).
4. **What cannot be validated with current data:** the existence study needs synchronized H1 OHLC
   across the book, which the repo has (`data/history/`, per-symbol M5→resampled). It does *not*
   need new data collection. What it does need that doesn't exist yet is the FDR-correction
   tooling and the multi-symbol synchronization harness described in §4 — building the *research*
   version of that harness (offline, not live-loop) is a prerequisite the existence study cannot
   skip.
5. **EXP-0 implication:** even a statistically surviving lead-lag edge is not automatically
   tradeable. EXP-0 established that the exit engine amplifies real entry edge (+0.231R) but adds
   nothing to random entries (+0.075R); a Constellation edge that survives FDR correction but is
   economically thin will not be rescued by ratchet/runner management. The existence study's bar is
   "does this predict direction," but the eventual GO bar is "does this predict direction with
   enough magnitude, net of costs, to be worth the exit engine amplifying it" — the same standard
   SilverBullet cleared and OTE/MTF-PB/Gyroscope did not.

## 7. Failure modes and monitoring

- **The core inefficiency may simply not exist at H1 retail granularity** (brainstorm §8 weakness,
  §12 existence-risk score 2/5) — the most likely single outcome is a clean NO-GO at the existence
  study stage, before any code beyond the study script is written.
- **Edges are regime-dependent and can die silently** — mitigated in design by stability scoring
  and weekly refit; live monitoring would need an edge-kill rule (n consecutive failed
  predictions → auto-suspend that edge) mirroring Gyroscope's NIS-suspend pattern
  (`docs/research/2026-07-12-novel-arsenal-brainstorm.md` §14.6).
- **Both assets gap together on news** — no lag to exploit, false leader-fire; requires the
  existing news lockout.
- **Multiple-testing self-deception** — a 9×9×3 lag matrix has enough simultaneous tests that
  spurious "edges" are expected by chance alone; the FDR correction in §6 is the control, and any
  live monitoring must track realized hit-rate per edge against its designed rate, the same
  self-audit discipline Gyroscope uses for its SPRT α budget.
- **Live self-audit metrics (if ever built):** per-edge realized directional hit-rate vs its
  in-sample rate; correlation-brake activation frequency (how often multiple laggards fire off one
  leader, and whether the summed-R cap actually binds); FeatureBus `global`-scope resource
  staleness (a weekly-refit graph running against a broken symbol feed should be detectable, not
  silent).

## 8. Verdict and sequencing

**Do not build the entry strategy yet.** Constellation is correctly staged as Wave 4 and correctly
carries the brainstorm's own "highest existence-risk concept" label. The right next action is the
pure existence study (§6 step 1) — cheap (it needs no new data, no live-loop code, just an offline
analysis script against `data/history/` with FDR correction) — run *before* any manifest, class, or
FeatureBus resource is written. If it fails, record NO-GO exactly as the OTE/MTF-PB/Gyroscope
studies did and stop.

The correlation-aware portfolio brake (§4, §5 P4/RISK-04) has value independent of that verdict and
should be sequenced as general risk infrastructure, not gated behind Constellation's own existence
study — it fixes a live audit finding (RISK-04) today. Depends on nothing else in this document set;
Trinity (`trinity.md`) and this document both eventually want a portfolio-level backtest (P12/
STRAT-05), so that infra item should be shared, not duplicated, if both proceed.
