# Missing tools, resources and elements — the performance-improvement bill

> **Doc version:** 2026-08-01 · Companion to [ARSENAL.md](ARSENAL.md). Every item here is
> grounded in a measured result or a verified audit finding — no speculative machinery. Items are
> ranked by expected impact on realized performance per unit of effort. Backlog status notes
> whether a mig row already exists (the 101 audit findings and 5 arsenal-delta rows are already
> loaded in the inbox — do not double-add).

## Tier 1 — measurement integrity (these change whether the numbers are true)

### 1. One ratchet, two callers — extract the exit engine (STRAT-01 / roadmap B2)
The single highest-value engineering item in the repo. Evidence: fixed exits −0.122R vs
ratchet+runner +0.109R on identical entries — the sign of the edge is produced by
`trade_manager.sync_positions`, which no research harness has ever executed; the validated
figures come from a parallel implementation (`poc_sb_stops.replay_managed`). Every known
difference (unverified fire-and-forget MODIFYs, 5s-stale volumes, dust guard, stop-level
rejections) biases live *downward*. Fix: extract the ratchet stage logic into one pure function
(state in, commands out), have both `TradeManager` and `research_run.py` call it, delete
`replay_managed`, re-run the study. Effort 2 d. Backlog: `strat-01-validated-exit-engine-is`
(inbox). **Everything else in this file is second-order until this is done.**

### 2. Journal schema that can validate the ratchet (OBS-01 — deadline-sensitive)
The demo soak is accruing data *right now* that cannot answer the STRAT-01 closure question
(no exit reason, no ratchet level at exit, no modification history, no slippage, no
submit/fill timestamps). Every soak day before this lands is unrecoverable evidence lost.
Effort 1 d. Backlog: `obs-01-journal-schema-cannot-validate` (inbox).

### 3. Exit-verification loop (EXIT-01/02/03 / roadmap B5)
The ratchet advances its own state before the broker confirms, and never verifies or retries.
A believed-but-absent breakeven stop converts the edge's core mechanism into silent risk. Fix:
heartbeat-verification for MODIFY/partial/cancel with `r_level` rollback on mismatch. Effort
2 d. Backlog rows exist (inbox).

### 4. Live spread/ask capture (RISK-07 + STRAT-03 / P6) — the cost gate, live
The EA already transmits the ask; Python discards it. Without it: no live spread ceiling on
entries, a systematic long-side bias in fills, no realized-cost monitoring against the 0.25R
gate, and three candidates (Coil's spread filter, Spring's session-conditional cost screen,
Bell's slippage measurement) are unbuildable. Also record a rolling per-symbol/per-session
spread history table — a new, cheap data asset no current tool provides. Effort: capture is a
5-minute change — the TICK handler stores `msg.get('b', 0)` and drops `msg['a']`, at
`system_controller.py:787` in the current tree (the audit cites the pre-RISK-01 line `:690`);
the gate + history table ~1 d. Backlog:
`risk-07-ask-price-is-transmitted`, `strat-03-spread-is-charged-as` (inbox).

## Tier 2 — capability unlocks (new strategies become possible)

### 5. Per-strategy exit profiles (P7) — match exit shape to signal skew
EXP-0's central lesson operationalized: the ratchet is an amplifier calibrated on a
positive-skew continuation signal. Negative-skew candidates (Tide, Spring) need
bank-earlier/trail-tighter/no-runner variants; TSMOM (Anchor) needs signal-flip exits with no
fixed target. Today `TradeManager` applies one global profile keyed off nothing. Design: a
`trade_management.profiles.<name>` config block + a `profile` field on the manifest, resolved
per-ticket at registration; the pure ratchet function (item 1) takes the profile as a
parameter, so research and live stay in lockstep. Effort ~1 d after item 1. Backlog: **new row
needed**.

### 6. D1/H4 data unlock (P10) — one afternoon, three strategies
`collect_signals` supports only M15/H1 (H4/D1 raise KeyError); D1 history is 775 bars/symbol.
MT5 serves 15–25 y of D1 via the existing GET_HISTORY path. Unlocks Anchor (TSMOM), Gumbel
Fade (EVT), and turns Almanac from n=36 to n≈240. Also enables the first real
drawdown-duration statistics. Effort: one afternoon + rig support. Backlog: **new row needed**.

### 7. OCO pending-order pairs (P2)
Coil and Bell enter with two-sided STOP brackets; nothing pairs pending orders today — the
arbiter *blocks* the sibling instead of cancelling it. `sibling_ticket` column + cancel-on-fill
in the EXECUTION:OPENED handler. Effort 1 d. Backlog: `oco-pending-order-pairs-arsenal-p2`
(inbox, arsenal-delta).

### 8. Grading path for non-SMC signals (P8)
`SignalGrader` awards up to 50 of 100 points to SMC-shaped evidence (displacement,
premium/discount, killzone). A Coil/Aftershock/Anchor signal structurally caps near the B
floor. Policy options: per-family factor sets, or grade-exempt manifests with their own
quality gates. Effort 1 d. Backlog: `grading-policy-for-non-smc-signals` (inbox).

### 9. Cross-strategy arbitration (P9) + HTF-bias exemption policy
`max_positions_per_symbol: 1` makes two concurrent strategies on one symbol impossible;
direction-agnostic candidates (Coil brackets, Tide fades) need the manifest
`honors_htf_bias: false` exemption policy formalized (Gyroscope precedent exists). Effort 2 d.
Backlog: `bias-filter-exemption-policy-arsenal-review` (inbox); P9 **new row needed**.

### 10. Portfolio-level backtest + Monte Carlo (P12 / STRAT-05)
No current rig can simulate the count cap, aggregate risk cap, correlation gate and daily
breaker together — the study's 14R maxDD ignores them, and any multi-strategy expectancy claim
is uncomputable without it. Non-negotiable before a second live strategy. Effort 3 d. Backlog:
`strat-05-no-portfolio-simulation-the` (inbox).

## Tier 3 — shared signal infrastructure (FeatureBus resources any strategy can consume)

The FeatureBus is the platform's under-used asset: exactly one pack exists (`smc_pack`). The
arsenal designs repeatedly invent per-strategy state that should be shared, cached, journaled
resources. Proposed library (each lands with its own tests; strategies declare them in manifest
`requires`):

| Resource | Source design | Consumers |
|---|---|---|
| `spread.session_stats` (per-symbol rolling spread by session) | item 4 | Spring, Coil, Bell, grader, cost monitoring |
| `regime.run_length_posterior` (BOCPD) | Rubicon §11 — "valuable as infrastructure even under NO-GO" | SilverBullet filter, Trinity, any candidate |
| `vol.hawkes_intensity` (λ excitation gauge) | Aftershock | Aftershock, Antibody v2, portfolio brake |
| `info.entropy_deficit` (LZ/block-entropy z) | Shannon Gate — expected to mature into a filter | arsenal-wide "don't trade now" gate |
| `anomaly.score` (Antibody self-model) | Antibody v1 (scorer already works; 0.05% alert rate) | entry lockouts, ops telemetry |
| `swap.nightly_rates` | Ledger Step-0 survey (underway on `feat/swap-survey`) | cost model (STRAT-06), Ledger gate |

Build rule: a resource ships only when its first consumer's pre-registration needs it — no
speculative platform work. But design each candidate's state as a bus resource from day one
(the Gyroscope postmortem: its Kalman state lived privately in the strategy; as a bus resource
it would have been reusable and journal-visible).

## Tier 4 — research-rig honesty upgrades

- **Ratchet parameter sensitivity sweep (STRAT-02):** the load-bearing constants (0.382/0.618/
  0.886, 30%/50% banks, 0.268 trail) have never been varied. After item 1, sweep them in the
  shared function. Backlog row exists.
- **Walk-forward + Sharpe/Sortino + drawdown-duration + MAE/MFE (STRAT-07):** required for
  Anchor-class strategies and for the drawdown-tolerance decision the audit flags as the human
  kill factor. Backlog row exists.
- **Swap/financing model (STRAT-06):** the survey producing the table is already running;
  wire results into `trade_dollars`. Backlog rows exist (`strat-06`, `ledger-step-0`).
- **Slippage attribution (roadmap C2):** a stated go-live condition with no tooling; Bell's
  kill criterion depends on it.
- **Almanac as standing complexity baseline:** add to the pre-registration template — every
  candidate must beat the zero-parameter calendar rule on the same data (once built).

## Deliberately absent (agreed with the audit's "no stage" list)

Kelly sizing, ML direction prediction, RL position management, LLM-in-the-loop signal
generation (Vibe-Trading assessment: REJECT), smart order routing — inapplicable at this scale
or harmful given the evidence base. Regime detection enters only as measured FeatureBus
resources gated by their own studies (Tier 3), not as a discretionary switch.

## Sequencing summary

Week 1 (with remediation Stage A): items 2, 4-capture, then 1. Weeks 2–4 (Stage B): items 3,
1-rerun, 6, 8; Almanac build. Then per the arsenal staging: Coil (item 7), Tide (item 5),
Anchor (items 6+10). The backlog additions this analysis owes are: P7 exit profiles, P9
cross-strategy arbitration, P10 D1/H4 extension, plus per-candidate pre-registration rows —
see the backlog update accompanying this doc set.
