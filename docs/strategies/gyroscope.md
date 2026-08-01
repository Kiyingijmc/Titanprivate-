# GYROSCOPE — Kalman drift estimator + Wald SPRT decision gate (H1)

> **Status:** research NO-GO (2026-07-15) · **Family:** time-series momentum (H1, SPRT-gated
> velocity filter) · **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §1 (concept) and §14
> (architectural blueprint) · **Doc version:** 2026-08-01

## 1. Thesis and return source

FX/metals exhibit episodic persistent drift at H1–H4 horizons (time-series momentum). The
hypothesised inefficiency was not the drift itself — well documented, partially decayed — but the
*timing of participation*: most trend systems enter late (long lookbacks) or churn (short
lookbacks). Gyroscope modelled price as a noisy sensor reading of a latent state `x = [level,
velocity]` (log-price and its drift) via a two-state Kalman filter, then used Wald's Sequential
Probability Ratio Test (SPRT) as the decision layer — the provably fastest sequential test for a
given false-entry/miss error budget (α/β) — to decide when accumulated evidence for a real drift
episode justified an entry. The pitch: separate drift from noise optimally, participate in real
trend earlier, and stand down faster in chop than an MA-cross system, with the participation/churn
ratio being exactly what kills retail trend systems via costs
(`docs/research/2026-07-12-novel-arsenal-brainstorm.md:35`).

**EXP-0 implication:** irrelevant in retrospect — Gyroscope was gated and killed before EXP-0
(2026-07-31) existed. But it matters as a design lesson for the next momentum candidate: EXP-0
shows the ratchet/runner exit engine amplifies a real entry edge (+0.231R) but does not manufacture
one from noise (+0.075R on random entries) — Gyroscope's entry needed to carry its own edge, and
under the pre-registered gate it did not (pooled −0.067R, net of the same exit engine that turns
SilverBullet's entry into +0.109R).

## 2. Evidence base

**Adverse (the operative record) — pre-registered gate, `docs/research/2026-07-14-gyroscope-gate.md`
(registered before any run), results in `docs/research/2026-07-14-gyroscope-gate-results.md`:**

- 9 frozen symbols (the validated SilverBullet universe minus GBPCAD/XBRUSD), 3 years H1
  (2023-06→2026-06), `signal_grading.min_grade: C` floor (SMC grading disabled identically for
  Gyroscope and the MaSlopeBaseline control) — 8,365 signals → 4,914 trades, 4,911 resolved.
- **Pooled net expectancy: −0.067R.** IS (70%, n=3,439): −0.066R, PF 0.91. OOS (30%, n=1,472):
  **−0.071R**, PF 0.90.
- **4/9 symbols non-negative** (need ≥6/9): BTCUSD +32.2R, XAUUSD +35.7R, USDJPY +20.0R, US30
  +2.6R positive; EURUSD −106.1R, GBPJPY −124.1R, GBPUSD −77.5R, AUDUSD −71.8R, USDCAD −40.9R
  negative.
- **Bootstrap 95% lower bound on pooled net expectancy: −0.0997R** (OOS lower bound −0.131R) —
  negative, so the CI does not exclude zero from below; it excludes zero from *above* in the wrong
  direction.
- 4 of the 8 pre-registered ANDed GO criteria failed decisively (criteria 1, 3, 4, 8 — see §6);
  criteria 5–7 (parameter sweeps, baseline comparison, ×1.5 spread stress) were not run after a
  machine restart killed the detached run sequence, but the gate's own logic makes this moot: they
  exist to falsify a would-be positive headline, and the headline was already dead by a wide margin
  (the +0.10R threshold sits ~0.17R above the point estimate).
- **Realized false-entry rate: 27.1%** (1,330/4,911 resolved trades stopped within the 5-bar
  lockout) vs the designed α = 5% — ~2.7× the blueprint's own kill-switch band (2α = 10%,
  `docs/research/2026-07-12-novel-arsenal-brainstorm.md:729`). The strategy fails its own
  advertised error budget.
- **Signal frequency: ~10.7 signals/day pooled** across 9 symbols vs the designed "episodic drift
  participation" — the SPRT fired near-continuously rather than selectively.

**Supporting (mechanically, not economically):** the filter algebra was reviewer-verified, entries
are look-ahead-safe, and costs are applied per-symbol — the implementation is mechanically sound.
The positive tails (BTCUSD, XAUUSD, USDJPY, US30 — all trend-prone assets) were real but too thin
to carry the FX-major losses.

**Context vs the rest of the arsenal:** this is the **third H1-momentum NO-GO** on this rig, after
MTF-PB v2 (−0.274R pooled, `docs/research/2026-06-25-mtf-pb-v2-results.md`) and ICT_OTE canonical
(−0.158R pooled managed, `docs/research/2026-07-11-ote-canonical-results.md`). All three used the
same live cost model and the same (or a materially similar) ratchet/runner exit engine that turns
SilverBullet's +0.3…+0.45R gross edge into +0.109R net — none of them had a gross edge for that
engine to rescue.

## 3. Signal specification

As implemented (`src/strategies/models/gyroscope.py`, `src/analysis/kalman_drift.py`) — frozen at
the pre-registered gate defaults, config `strategies.gyroscope` in
`config/config.yaml`:

- **State:** `KalmanDrift` (`src/analysis/kalman_drift.py`, 183 LOC), one instance per symbol,
  2-state Kalman filter (level, velocity) on log-close, fed once per closed H1 bar.
  `R` (measurement noise) = 0.5 × rolling variance of 1-bar log returns × `r_frac`; `Q` (process
  noise) scaled to `(q_atr_frac × ATR/price)²` — both asset-agnostic, no per-symbol constants.
- **Decision layer:** SPRT on the filter's **standardized velocity** `z = v̂/√P_vel` (a deliberate,
  documented deviation from the blueprint's whitened-innovation design — see §7). Long/short LLR
  accumulate each bar; enter when `Λ ≥ A = ln((1−β)/α)` (α=0.05, β=0.20, δ=0.40 in
  z-units).
- **Integrity monitor (NIS):** rolling mean of `NIS = ε²/S` over a 50-bar window must sit inside a
  χ² band; sustained violation → `SUSPENDED` state, no new entries, filter re-warms.
- **Trigger:** `reading.state == "OBSERVE"` and `reading.crossed` on the newest bar only (bootstrap
  crossings during warmup are never traded); cooldown (`reentry_lockout: 5` bars) blocks re-entry.
- **Stop:** `k_sl × √S_price` (the filter's own price-space uncertainty, k_sl=3.0), floored at
  `sl_atr_floor × ATR` = 0.8×ATR so it never undercuts the SilverBullet-study finding that tight H1
  stops die.
- **Target:** `rr_target × risk` (2.0) — arms the existing partials ladder; the runner does the
  harvesting.
- **Filters:** optional `vol_floor`/`vol_ceil` ATR band (off by default); `max_spread_atr_frac`
  (0.10) — **inert today**, `context['spread']` does not exist on the live path (P6/RISK-07).
- **Universe:** the 9-symbol frozen gate set (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY,
  XAUUSD, US30, BTCUSD).

## 4. Architecture integration

- **Manifest:** `config/manifests/gyroscope.yaml` exists on disk — `id: gyroscope`,
  `version: "1.0.0"`, `class_path: src.strategies.models.gyroscope:GyroscopeStrategy`,
  `family: stat`, `timeframe: H1`, `requires: []` (raw OHLC only, no SMC columns),
  `status: research`, `priority: 60`, `honors_htf_bias: false` — its own drift estimate *is* its
  bias, so it sits in the controller's HTF bias-filter exemption set.
- **Class:** `GyroscopeStrategy(BaseStrategy)` at `src/strategies/models/gyroscope.py`,
  `timeframe: H1`; `validate_data(df, min_length=warmup_bars, check_smc=False)`.
- **Config block:** `strategies.gyroscope` in `config/config.yaml` — `enabled: true` today but
  **inert**: research-status strategies never activate in the FSM (REGISTERED→LOADED→ACTIVE); an
  operator `/enable` with `allow_research` is required, and none has been issued post-NO-GO.
- **FeatureBus:** consumes none — raw OHLC + carried per-symbol filter state (`_filters`,
  `_last_ts`, `_cooldown` dicts keyed by symbol).
- **Order type:** `MARKET` via the REQ handshake (existing path).
- **Grading (P8 statement):** graded with `signal_grading.min_grade: C` in the pre-registered gate
  — the SMC-shaped grader (HTF alignment, displacement, premium/discount, killzone) is meaningless
  for a non-SMC strategy, so the C-floor disabled selection identically for Gyroscope and the
  MaSlopeBaseline control. A live flip would require the still-unbuilt per-strategy grading policy
  (P8) first.
- **Exit profile:** default ratchet + partials + runner (`trade_manager.py`) — unchanged, arms
  normally once `initial_entry/initial_tp` are non-zero from send-time metadata.
- **Risk:** standard `RiskManager.calculate_lot_size`, broker-spec driven, fail-safe lot=0 if specs
  missing; NEUTRAL-bias sizing does not apply (bias-exempt).

## 5. Infrastructure prerequisites

| Item | What | Status |
|---|---|---|
| Arbiter per-tf bar aging (advisory C) | `_bar_index` single-counter ages H1 theses on M5 closes | **Required precondition before ANY live flip alongside an M5-timeframe strategy** — inert for Gyroscope alone since it is H1-only, and the gate is explicit that "a GO verdict here does NOT waive it" (`docs/research/2026-07-14-gyroscope-gate.md:101-108`) |
| P8 grading path for non-SMC signals | Per-strategy grading policy | Not built; the C-floor was a study-only workaround, not a live answer |
| P6/RISK-07 spread gate | `context['spread']` does not exist on the live path | Gyroscope's `max_spread_atr_frac` screen is inert live (and was vacuous offline too — the gate carries no live spread) |
| STRAT-01 | Live ratchet exit engine has no research-harness equivalent | Same caveat as every strategy on this rig — moot here since the entry failed before the exit-engine question mattered |

Moot given the NO-GO: none of the above is worth spending effort on for Gyroscope specifically.
They are listed because the transferable lesson (§7) implies a next momentum candidate will hit
the same list.

## 6. Validation plan (as executed — retained for the record)

Pre-registered gate (`docs/research/2026-07-14-gyroscope-gate.md`), 8 ANDed GO criteria evaluated
at the pre-registered defaults only (one-pass rule):

1. Pooled net expectancy ≥ +0.10R/trade — **FAIL** (−0.067R).
2. ≥150 pooled resolved trades — pass (4,911).
3. ≥6/9 symbols non-negative — **FAIL** (4/9).
4. OOS pooled net expectancy > 0 — **FAIL** (−0.071R).
5. ±30% one-at-a-time sweeps on (α, β, δ, q_atr_frac) don't flip pooled sign — not run (moot: see
   the disclosed protocol deviation in §2).
6. Beats MaSlopeBaseline — not run (moot).
7. ×1.5 spread stress keeps pooled net expectancy > 0 — not run (moot).
8. Bootstrap 95% lower bound on pooled net expectancy > 0 — **FAIL** (−0.0997R).

Baseline: `ma_slope_baseline` v1.0.0 (comparison run never executed — moot per the short-circuit
logic above, but the baseline itself remains a permanent control, see §7c). **Cannot be validated
further with current data or method** — the negative result is decisive enough (4/8 criteria fail,
2 of them by more than the CI width) that no additional sweep could plausibly flip the verdict; the
one-pass rule means any future re-test of this exact rule set is disallowed, only a fresh
pre-registered study with a mechanically distinct decision layer.

## 7. Failure modes and monitoring

Not applicable in production — Gyroscope never flipped live and the manifest stays `status:
research`. Retained as documented failure modes for anyone reviving the SPRT-momentum family:

- **Nominal vs. exact error rates under autocorrelation.** The SPRT ran on `z = v̂/√P_vel`
  (standardized velocity), not raw whitened innovations — a deliberate, documented deviation
  (`src/analysis/kalman_drift.py:1-18`) because the innovation-SPRT fought the NIS integrity
  monitor (both trip on exactly the drift transient). But `z` is autocorrelated bar-to-bar (a
  smoothed state estimate, not an i.i.d. sample), so the classical Wald α/β bounds are **nominal,
  not exact**: the LLR accumulates faster than i.i.d. theory assumes, collapsing the effective
  evidence threshold. The 27.1%-vs-5% realized false-entry rate is the empirical footprint of this.
- **NIS-suspend boundary caveat:** re-arm at the window boundary can, in rare cases, admit one
  extra bar of persistence past the nominal window edge (Task-3 review, Minor).
- **Live self-audit metric (if ever revived):** rolling 30-trade realized false-entry rate vs 2α —
  the blueprint's own kill-switch (`docs/research/2026-07-12-novel-arsenal-brainstorm.md:729`);
  Gyroscope breached this by ~2.7× in the gate itself, before ever reaching production monitoring.

## 8. Verdict and sequencing — transferable lessons

**Verdict: NO-GO, closed.** `gyroscope` manifest stays `status: research`, disabled by policy (the
`enabled: true` config flag is inert without an explicit research `/enable`). No further work is
scheduled on this exact design.

**Lessons for the next candidate, in priority order:**

**(a) Sequential-test error budgets are nominal under autocorrelated filter state.** Any future
SPRT/CUSUM-style decision layer built on a smoothed state estimate (Kalman velocity, EWMA, or
similar) must either test on **non-overlapping innovations** or use **block-decimated** input series
to restore the i.i.d. assumption the Wald bounds require — and this must be its own new
pre-registered study, not a parameter retune of Gyroscope's rule set (the one-pass rule forbids
in-place re-tuning on this data regardless).

**(b) This is the third H1-momentum NO-GO** (with MTF-PB v1/v2 and ICT_OTE canonical). Time-series
momentum at H1 in FX majors is cost-dead on this broker across three independent implementations
with different entry mechanics (trend-pullback, canonical MTF-OTE structure, Kalman-SPRT). Any
future momentum-family candidate — e.g. the `Anchor` candidate in
`docs/strategies/newbot-roster.md` / `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §7, which
targets a 3–12 month horizon rather than H1 — must differentiate on **horizon or breadth**, not
implementation quality; implementation quality has now been tested three ways and is not the
limiting factor.

**(c) Salvage — code stays, manifest stays `status: research`:**
- `KalmanDrift` (`src/analysis/kalman_drift.py`, 183 LOC, 11 passing unit tests) is retained as
  reusable filter/velocity infrastructure. It is already the proposed hedge-ratio estimator for the
  `Tether` candidate (cointegration spread reversion — `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md`
  §8: "A Kalman filter is the textbook estimator for a *time-varying* hedge ratio... you have
  already built the hardest component of this strategy for a different purpose").
- `MaSlopeBaseline` exists as a permanent research-only control for future gates — a zero/low-
  parameter yardstick every new candidate should be compared against, not a candidate itself.
- The Plan-07 platform deliverables (frozen 9-symbol dataset, pooled `research_run` with
  per-symbol costing + bootstrap CI + overrides, MARKET/one-open resolution correctness, manifest
  priority plumbing, bias-exemption generalization) stand regardless of this verdict and carry
  forward to every future gate.

**Sequencing:** the next candidate enters through the identical pre-registration → gate → verdict
pipeline. No dependency from this document blocks any other strategy doc in this set.
