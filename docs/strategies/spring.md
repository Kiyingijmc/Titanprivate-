# SPRING — Ornstein-Uhlenbeck half-life mean reversion

> **Status:** candidate (Wave 3, pre-registration pending) · **Family:** stat-arb / mean reversion ·
> **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §5 (SPRING) ·
> **Doc version:** 2026-08-01

## 1. Thesis and return source

Not "is price stretched?" — every band-fade system asks that — but "does a measured spring
currently exist, and how stiff is it?" Spring rolling-fits an Ornstein-Uhlenbeck process
(`dx = θ(μ − x)dt + σdW`) on H1 log price and trades reversion *only* inside episodes where θ is
statistically significant, the half-life (ln2/θ) is short and stable, and the reversion distance
clears costs. The claimed return source is harvesting genuine equilibrium episodes (post-repricing,
pre-event lulls, session ranges) while the θ-significance gate structurally refuses to trade the
majority of the time when no measurable spring exists — which the brainstorm frames as the actual
edge over naive fade systems, not the fades themselves (brainstorm §5.3).

## 2. Evidence base

Spring has **no dedicated backtest, gate doc, or cost-screen result yet** — this is an architecture
document, not a validated study. All figures below are priors from adjacent, already-adjudicated
research; none are Spring-specific measurements.

| Source | Finding | Relevance to Spring |
|---|---|---|
| `docs/research/2026-07-11-ote-canonical-results.md` | OTE canonical NO-GO, −0.158R pooled gross-negative | The repo's cost bar is brutal; any new mean-reversion concept inherits the same FBS spread wall |
| `docs/research/2026-07-14-gyroscope-gate-results.md` | Gyroscope H1-momentum NO-GO, −0.067R pooled, 27.1% realized false-entry vs 5% designed α | The one prior "statistically-gated H1 stat process" candidate in this arsenal failed net of cost — Spring is the same estimator family (rolling H1 process fit + significance gate) applied to reversion instead of drift, so this is the closest adverse precedent available |
| `docs/research/2026-07-11-silverbullet-h1-stop-study.md` | Only validated edge needed H1 granularity + wide ATR stops + low frequency to survive FBS spreads | Sets the bar Spring's reversion amplitude must clear |
| Brainstorm §5.12 (self-rated) | Cost survival **2/5**, existence risk **3/5** (comparative matrix §12, row 5) | Spring rates itself among the worse cost-survival candidates on the shortlist — below Gyroscope (4/5) and well below Aftershock/Gumbel Fade (5/5) |

**Adverse evidence, stated plainly:** short-horizon single-asset FX reversion is one of the most
heavily fished trades in retail quant (brainstorm §5.12). H1 amplitude may simply not clear FBS
spreads — "prior research says respect this risk" (brainstorm §5.12, verbatim framing). The strategy
has negative skew by construction (small consistent wins, occasional large stop-outs at z_stop).
Estimation lag means the OU fit degrades exactly when trends begin, i.e. exactly when reversion
trading is most dangerous.

**EXP-0 implication:** the EXP-0 coin-flip (2026-07-31) showed the live exit engine amplifies a
real entry's edge (+0.231R) but does not subsidise a placebo one (+0.075R on random entries,
−0.249R for the full placebo vs +0.109R real). Spring's θ-significance gate is exactly the kind of
selective-entry discipline EXP-0 says is required — but the gate must be shown to select real
reversion episodes, not just plausible-looking ones, before any exit-engine benefit can be assumed
to transfer.

## 3. Signal specification

As specified in the brainstorm (§5.6–§5.10), not yet implemented:

- **Setup:** rolling OU fit on H1 log price (lag-1 regression, ≤300 bars) producing θ̂ (with
  t-stat), μ̂, σ̂, and half-life ln2/θ̂. State machine: `NO-SPRING → SPRING DETECTED (θ̂ t-stat > 2,
  half-life ∈ [4, 48] bars, stable across sub-windows) → ARMED`.
- **Trigger:** `STRETCHED` when equilibrium displacement `z = (price − μ̂)/σ_eq` exceeds
  `z_entry ≈ 2`, subject to a `VALIDATION` step: expected reversion distance (μ̂ − price) must clear
  n× spread.
- **Entry:** LIMIT order at the stretch, fading toward μ̂ (LIMIT order type already exists
  end-to-end).
- **Stop:** hard SL at `z_stop ≈ 3.5` — beyond this the OU model is considered rejected, not merely
  losing.
- **Target:** TP at μ̂ (not through it — the physics only claims pull to equilibrium).
- **Time stop:** 2 half-lives elapsed without reversion → flatten ("the spring broke").
- **Regime exit:** θ̂ loses significance mid-trade → flatten.
- **Risk model:** expected R:R ≈ z_entry/(z_stop − z_entry) ≈ 1.3:1, win-rate-dependent; fixed
  fractional R sized off z_stop distance; no martingale/grid/adds — one unit per episode; a
  portfolio cap on simultaneous fades is required because reversion trades correlate in risk-off
  conditions (brainstorm §5.9).
- **Universe:** not yet chosen. Session lulls (Asia) are the natural habitat, but Asia spreads are
  wider — session-conditional spread stats are a prerequisite (see §5).

## 4. Architecture integration

- **Manifest (sketch, not yet created):**
  ```yaml
  # config/manifests/spring.yaml
  id: spring
  version: "0.1.0"
  class_path: "src.strategies.models.spring:SpringStrategy"
  family: stat
  timeframe: H1
  requires: []          # raw OHLC only; no SMC pack needed
  status: research
  priority: 70           # placeholder, below live/validated strategies
  honors_htf_bias: false  # the OU fit is its own regime signal, per Gyroscope precedent
  ```
- **Class placement:** `src/strategies/models/spring.py` — `SpringStrategy(BaseStrategy)`, mirroring
  `gyroscope.py`'s pattern of a thin strategy class over a pure math module
  (`src/analysis/ou_reversion.py`, analogous to `src/analysis/kalman_drift.py`). Uses
  `validate_data(df, min_length=warmup, check_smc=False)` — raw OHLC only, no FeatureBus SMC pack
  dependency.
- **Config block (sketch):**
  ```yaml
  strategies:
    spring:
      enabled: false
      timeframe: H1
      warmup_bars: 300
      z_entry: 2.0
      z_stop: 3.5
      half_life_min_bars: 4
      half_life_max_bars: 48
      theta_tstat_min: 2.0
      max_half_lives_hold: 2
      pairs: []            # TBD post cost-screen
  ```
- **FeatureBus resources:** none required for v1 (raw OHLC + a self-contained OU estimator, same
  posture as Gyroscope's `KalmanDrift`). If session-conditional spread stats (see §5) are built as a
  shared resource, it would register as e.g. `spread.session_stats` (scope `symbol`), reusable by
  other candidates.
- **Order types:** LIMIT for entry (already supported end-to-end); no OCO needed since Spring is
  single-sided per episode.
- **Grading path (P8 statement):** Spring is a non-SMC signal — like Gyroscope, it will lose the
  displacement/premium-discount/killzone points (65 of 100 possible) in `SignalGrader.grade()`
  (`src/analysis/signal_grader.py`), leaving at most HTF-alignment (30, moot since
  `honors_htf_bias: false`) + R:R (20) = 35/100, structurally below `min_grade: B`. Spring needs the
  same grading accommodation Gyroscope needs (a non-SMC grading lane or exemption), not yet
  designed at repo level.
- **HTF-bias stance:** `honors_htf_bias: false` — the OU fit is Spring's own regime read, analogous
  to Gyroscope's own-drift-is-its-own-bias framing (brainstorm §14.1).
- **Exit profile:** Spring's trade thesis is TP-at-equilibrium, hard z_stop, and a time stop at 2
  half-lives — this does **not** match the default ratchet/runner (which assumes SilverBullet-style
  positive-skew continuation and progressively bags a winning trend). Spring is explicitly
  negative-skew by construction (brainstorm §5.12), so it needs a **per-strategy exit profile (P7)**
  with no runner — a flat TP/SL/time-stop exit, not the default ratchet ladder. This is a named
  infrastructure prerequisite (§5) and the strategy must not go live on the default exit profile.
- **Risk interaction:** standard broker-spec sizing off z_stop distance; the correlated-fades
  portfolio cap described in §3 is not present in `ExposureManager` today and would need to be
  added or approximated via the existing per-symbol/currency caps.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| P7 | Per-strategy exit profile (flat TP/SL/time-stop, no ratchet/runner) | Spring's negative-skew, TP-at-equilibrium thesis is incompatible with the default ratchet built for positive-skew continuation trades | Not yet designed; medium — `TradeManager` currently assumes one ratchet policy for all strategies |
| P6 / RISK-07 | `context['spread']` does not exist today; ask-price/spread capture | Stage-(b) cost screen (median episode reversion amplitude vs 3× spread) is the expected kill point and needs real spread data, not an ATR proxy | Medium |
| — (new) | Session-conditional spread-history feed | Asia (Spring's natural habitat per §5.13) has wider spreads than London/NY; a single blended spread stat will misprice the cost screen for exactly the sessions Spring wants to trade. No such feed exists today. | Medium-large — likely needs new bridge/history capture, not just a config value |
| P8 | Grader accommodation for non-SMC signals | Spring loses 65/100 grading points structurally (see §4); without a fix it cannot clear `min_grade: B` regardless of edge quality | Medium (shared with Gyroscope) |
| News calendar / lockout | Hard news lockout | Fading news is explicitly named the "classic account-killer" (brainstorm §5.13); no news-lockout mechanism is referenced elsewhere in this repo's contract | Unclear — not confirmed to exist; treat as a prerequisite until verified |

## 6. Validation plan

TVP (`docs/research/2026-07-12-novel-arsenal-brainstorm.md` §0) applies, with stage (b) load-bearing
and decisive per the brainstorm's own framing (§5.17):

- **Stage (b), run before any backtest:** measure the distribution of `|reversion amplitude| / spread`
  during detected (θ-significant) episodes. If the median episode does not clear 3× spread, **NO-GO
  at the screen** — no backtest is warranted.
- **Existence-gate discriminative power test:** compare forward reversion statistics inside vs
  outside gated (θ-significant) episodes — the gate must demonstrably separate real reversion from
  noise, not just correlate with it.
- **Session-conditional cost screen:** stage (b) must be run per-session once session-conditional
  spread stats exist (see §5); a pooled-session screen would understate Asia-specific cost risk.
- **Data:** 3-yr H1 history (available, `data/history/`), session-conditional spread stats (does
  **not** exist yet — this blocks a correct stage-(b) run, though a coarse pooled-spread version
  could run first as a preliminary filter).
- **Baseline:** must beat a naive band-fade (z-score-only, no θ-significance gate) on the same data —
  this is the direct test of whether the existence gate is adding value over "every reversion system"
  (brainstorm §5.3).
- **Kill criteria:** stage-(b) median-amplitude-vs-3×-spread failure; θ-significance gate showing no
  discriminative power vs the naive baseline; pooled net expectancy negative or sign-unstable across
  ±30% sweeps of (z_entry, z_stop, theta_tstat_min).
- **What cannot be validated with current data:** session-conditional cost survival (needs the
  session-conditional spread feed, §5); anything involving `context['spread']` (does not exist,
  audit P6/RISK-07) — the stage-(b) screen would run on an ATR-proxied spread until that lands,
  which understates true cost risk for wide-spread sessions.

## 7. Failure modes and monitoring

- **The fat tail:** a "stretch" that is actually a regime break, not an equilibrium excursion.
  Mitigated by z_stop, the time stop, and the θ̂-significance kill switch — but a live self-audit
  metric (realized loss rate on z_stop-triggered exits vs the OU model's implied tail probability)
  should be tracked, mirroring Gyroscope's realized-false-entry-rate self-check (brainstorm §14.6).
- **Estimation lag:** OU fit quality degrades exactly when trends begin. Monitor: θ̂ variance across
  sub-windows (the fit-stability metric) trending up should suppress new entries before the naive
  significance test alone would.
- **Cost regime drift:** if realized spreads widen (esp. in Asia), the 3× cost screen's safety
  margin erodes silently. Monitor realized round-trip cost per episode vs the pre-registered 3×
  threshold, not just at gate time but on a rolling basis in demo/live.
- **News:** hard lockout is a hard requirement, not a nice-to-have — fading a news-driven excursion
  is the textbook failure mode named explicitly in the source material.
- **Ops:** like all strategies, fails safe to lot=0 if specs are missing; no strategy-specific ops
  risk beyond the shared portfolio-cap and Sync Guard behaviour already documented for the platform.

## 8. Verdict and sequencing

Candidate, not yet gated. Spring's differentiator — a genuine θ-significance existence gate rather
than an indicator-fade threshold — is real, but its own self-rating (cost survival 2/5, the worst on
the comparative matrix's cost-survival column) sets a low prior for standalone survival. The
recommended sequence: (1) build the session-conditional spread-stat prerequisite (or, if that is
judged too large a lift near-term, run a coarse pooled-spread stage-(b) screen as a fast NO-GO
check); (2) run stage-(b) before writing a single line of backtest code — this is the expected kill
point and is cheap; (3) only if stage-(b) survives, pre-register the full gate (mirroring the
Gyroscope gate-doc format) and design the P7 flat exit profile; (4) do not build the strategy class
until the gate doc exists. Sequencing relative to the rest of Wave 3: Spring is not on the critical
path for Gumbel Fade (H4/D1, independent) or Walclock (independent data-quality probe); it competes
for research-cycle slots with Shannon Gate, whose honest expected outcome is similarly NO-GO
standalone.
