# Aftershock — Hawkes self-exciting volatility-cascade trader

> **Status:** candidate (Wave 2, pre-registration pending) · **Family:** point-process / volatility-event ·
> **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §2 (lines 92-153), §12 comparative
> matrix (row 2), §13 ranked shortlist (#2) · **Doc version:** 2026-08-01

## 1. Thesis and return source

Volatility clustering — large moves raise the near-term probability of further large moves, decaying
roughly as a power law (the seismology Omori-law analogy the strategy is named for) — is one of the
best-replicated stylized facts in market microstructure (brainstorm §2.2/§2.11, lines 97-98, 135). Aftershock
models this directly with a Hawkes self-exciting intensity `λ(t) = μ + Σ α·exp(−β(t−tᵢ))` over H1
"event" bars (true range exceeding `q×` rolling median TR, q≈2.5), then trades a *directional* leg
conditioned on where the current excitation sits relative to that intensity.

Two distinct legs share the same intensity infrastructure but are tested, gated and go-live'd
**separately** (brainstorm §2.17, line 151, and §2.10 line 132):

- **Continuation leg** (recommended first): a fresh event arriving when λ is near baseline μ, closing
  directionally beyond its own midpoint, confirmed by a non-retracing next bar — trades with the shock
  on the theory that information/positioning diffuses over subsequent bars, not instantly.
- **Exhaustion leg** (deferred): a reversal bar arriving late in a cascade, when λ is already in its
  top decile — fades the over-extension. Brainstorm §2.10 calls this "the classically dangerous side"
  and explicitly recommends shipping continuation-only first; this document follows that
  recommendation and scopes exhaustion out of v1.

Return source: unlike prior NO-GO strategies, Aftershock only fires when the *target* is a multiple of
the normal bar range, so spread-as-a-fraction-of-target shrinks exactly when the strategy is active —
the structural inverse of what killed the OTE study (brainstorm §2.11, line 135; §13, line 635). This
is a design property, not yet a measured one.

## 2. Evidence base

**Supporting (design-level, not yet empirical):**
- Highest cost-survival score on the board (5/5) in the brainstorm's comparative matrix, tied only
  with Gumbel Fade — `docs/research/2026-07-12-novel-arsenal-brainstorm.md:618,623`.
- Ranked #2 in the shortlist, immediately behind Gyroscope, specifically for cost-robustness — "the
  structural inverse of what killed OTE" (`…brainstorm.md:635`).
- Volatility clustering itself is described as "the single most-replicated stylized fact in finance"
  (`…brainstorm.md:135`) — the underlying phenomenon, not Aftershock's specific parameterisation of it,
  is well documented outside this repo.

**Adverse (from this repo's own record — stated plainly per house rule):**
- The graveyard: OTE canonical −0.158R pooled (2026-07-11), MTF-PB v2 −0.274R pooled (2026-06-25),
  original SilverBullet M5 −4.27R, and most directly relevant — **Gyroscope NO-GO** (−0.067R pooled,
  4/9 symbols non-negative, `docs/research/2026-07-14-gyroscope-gate-results.md`). Gyroscope was this
  arsenal's #1-ranked pick and still failed on 4 of the 8 ANDed GO criteria.
- **Gyroscope's calibration lesson applies directly to Aftershock's own statistical machinery.**
  Gyroscope's SPRT realized a 27.1% false-entry rate against a designed 5% α (`…gate-results.md:38`)
  because its sequential-test error rates were derived under an i.i.d. assumption while consecutive
  velocity z-scores share filter state — the LLR accumulated far faster than the theory assumed
  (`…gate-results.md:40,44`). Aftershock's rolling MLE fit of Hawkes parameters (μ, α, β) on a sparse,
  by-construction-autocorrelated event stream carries the same class of risk: the fitted λ thresholds
  (λ_lo, λ_hi) could be miscalibrated in exactly the same "nominal-but-not-real" way. The brainstorm's
  own failure-mode list independently names this: "MLE fitting of Hawkes on sparse events is noisy —
  may need fixed decay β from IS" (`…brainstorm.md:138`).
- No Aftershock-specific backtest, event study, or gate has been run. Every quantitative claim about
  Aftershock's own performance in this document is **not yet measured** — pre-registration is pending
  and this is stated as candidate status, not validated-not-live.
- **EXP-0 implication:** the coin-flip pre-registration (`docs/research/2026-07-31-exp0-coinflip-preregistration.md`,
  outcome dated 2026-07-31) showed placebo entries through the full live exit engine net −0.249R
  (0/20 reps positive) versus SilverBullet's real +0.109R; the exit engine is an amplifier
  (+0.231R on real entries) not a subsidy (+0.075R on random entries). A new entry inherits only
  ~+0.08R of cost-drag mitigation from the ratchet — **Aftershock's entry logic must catch a
  monetisable move on its own merits**; the event-study screen below exists precisely to test that
  before any capital-weighted backtest is run.

## 3. Signal specification

**Event definition:** an H1 bar is an "event" when `TR > q × rolling_median(TR, window)`, default
q ≈ 2.5 (brainstorm §2.3, line 101).

**Intensity:** `λ(t) = μ + Σ α·exp(−β(t−tᵢ))` summed over recent events; (μ, α, β) fit by rolling MLE
or held fixed from the IS split per the calibration caution above (brainstorm §2.15, line 145).

**Continuation entry (v1 scope):**
1. A fresh event fires while λ was below `λ_lo` immediately prior (a jump from near-baseline, not
   mid-cascade).
2. The event bar closes beyond its own midpoint in the direction it moved.
3. The next bar confirms — does not fully retrace the event bar's range.
4. Cost screen: skip if spread exceeds `x%` of the event bar's own range (see §5 — this filter is
   currently inert live, see P6/RISK-07).
5. Enter `MARKET` with the confirming bar's close (or next bar open).

**Exhaustion entry:** deliberately **not implemented in v1** per the brainstorm's own risk framing —
λ > λ_hi (top IS decile) plus a reversal bar fading toward the pre-cascade level. Deferred to a
follow-on study if the continuation gate passes.

**Stop:** beyond the event bar's opposite extreme — the shock's own structure, not an ATR multiple
(consistent with this repo's standing finding that ATR-multiple stops are cost-dead at fine
granularity; brief hard-constraint: M5/M15 ATR stops are dead, stops must be structural/wide).

**Target:** 1× the event bar's range projected from entry; the ratchet/runner pipeline (§4) handles
partial-taking beyond that.

**Time/state exit:** λ decaying below `λ_lo` — the cascade is exhausted — flattens the position
regardless of P&L (brainstorm §2.8, line 123). This is a *new* exit primitive; see §5/§6.

**Universe:** H1, reused frozen 9-symbol gate set as the default screening universe
(`data/lake/frozen/`, see brief item 8); the brief's cost table (FBS spread points: EURUSD 8, GBPUSD
12, USDJPY 10, AUDUSD 10, USDCAD 12, GBPJPY 25, XAUUSD 20, US30 200, BTCUSD 1000, XBRUSD 30,
commission $7/lot) suggests the high-vol instruments (US30, XAUUSD, BTCUSD) are the natural
first-priority subset given the best vol-to-cost ratios — this is a prior, not yet a measured
per-symbol result for Aftershock.

**Order type:** MARKET only, per the brainstorm design and the confirming-bar entry rule (no LIMIT/STOP
variant proposed for this concept).

## 4. Architecture integration

**Class placement** (mirrors Gyroscope's precedent exactly — `src/strategies/models/gyroscope.py` +
`src/analysis/kalman_drift.py`):
```
src/strategies/models/aftershock.py     # AftershockStrategy(BaseStrategy)
src/analysis/hawkes_intensity.py        # HawkesIntensity: event detect + λ recursion + MLE/fixed-β fit
tests/unit/test_hawkes_intensity.py     # filter/recursion math on synthetic event streams
tests/unit/test_aftershock_strategy.py  # decision-dict contract, gating, cascade-exhaustion flatten
```

**Manifest sketch** (`config/manifests/aftershock.yaml`, format verified against the live
`config/manifests/gyroscope.yaml`):
```yaml
id: aftershock
version: "0.1.0"
class_path: "src.strategies.models.aftershock:AftershockStrategy"
family: point_process
timeframe: H1
requires: []
status: research
priority: 65          # illustrative placeholder, below gyroscope's 60; final value set at spec time
honors_htf_bias: false
```
`honors_htf_bias: false` because Aftershock's direction comes from the event/cascade structure itself,
not HTF bias — the same exemption pattern already used by `gyroscope` and `ma_slope_baseline`
(`src/strategies/manifest.py:33`, `src/strategies/registry.py:75`, controller check at
`src/core/system_controller.py:962`).

**Config block sketch** under `strategies:` in `config/config.yaml`:
```yaml
strategies:
  aftershock:
    enabled: false
    timeframe: H1
    pairs: []             # per-strategy symbol universe, set at spec time
    event_q: 2.5
    lambda_fit: fixed      # fixed | rolling_mle (default fixed per the calibration caution in §2)
    lambda_lo_pctile: 20
    lambda_hi_pctile: 90   # exhaustion leg only — inert in v1 (continuation-only)
    confirm_bar_required: true
    max_spread_frac_of_range: 0.10   # inert live until P6/RISK-07, see §5
    tp_range_multiple: 1.0
    continuation_only: true
```

**FeatureBus:** no resource required to consume for v1. `validate_data(df, min_length=warmup,
check_smc=False)` — raw OHLC only, same as Gyroscope. If the intensity proves useful arsenal-wide
(e.g. as a shared "cascade active" flag for other strategies' portfolio brakes), it could later be
registered as `vol.hawkes_intensity` (the name already reserved for it in
`docs/strategies/IMPROVEMENTS.md`'s Tier 3 resource table) mirroring the pack pattern in
`src/features/packs/smc_pack.py`
(`register(ResourceSpec(name=…, scope=…, compute=…))`) — not required to ship v1.

**Grading path (P8):** verified directly against `src/analysis/signal_grader.py:1-119`, not assumed.
The controller always passes `enriched_df.iloc[-1]` as the `candle` argument to `grade()`
(`src/core/system_controller.py:969`), and that frame carries `ATR`/`open`/`close` regardless of
which strategy is active — so the **displacement factor (≤20 pts) is not structurally lost** for
Aftershock: event bars are large by construction (`TR > 2.5× median`), so body/ATR should score well.
The **premium/discount factor** defaults to `+5` (not 0) when `context['liquidity']['STATUS']` is
unset/`"EQ"` (`signal_grader.py:95-97`) — Aftershock has no liquidity concept, so it structurally gets
this partial credit, not a hard loss. **Killzone** (`+15`) is time-based and generic — London/NY opens
are natural event generators per the brainstorm (line 141), so Aftershock signals plausibly land in
killzone hours often, but this is not guaranteed by design. **HTF bias** scores 10 (neutral) unless the
event direction happens to coincide with the controller's independently-computed HTF bias, in which
case 30. Net: achievable score range is roughly 40–90 depending on RR and bias coincidence; clearing
`min_grade: B` (55) looks plausible without a `SignalGrader` change, but this must be checked
empirically once real decision dicts exist — it is a narrower, more specific claim than a blanket "the
grader is SMC-shaped and this strategy will be capped."

**HTF-bias stance:** exempted (`honors_htf_bias: false`), per §4 manifest above.

**Exit profile:** the default ratchet (BE 38.2%, partials 61.8%/88.6%, optional runner trail) engages
normally once `initial_entry`/`initial_tp` are non-zero, same as any strategy. But the λ-decay flatten
rule (§3) is **not** something `TradeManager.sync_positions` can compute — it only knows ratchet
percentages against `initial_tp`, not a strategy's internal intensity state. This needs a
**per-strategy exit profile (P7)** — see §5.

**Risk interaction:** unchanged `RiskManager.calculate_lot_size` (broker-spec driven, fail-safe lot=0
on missing specs); stop distance is event-derived so sizing adapts automatically. The book-wide
portfolio cap (`risk.account.max_total_open_risk_pct`) already sums risk across all strategies with no
new plumbing required. Brainstorm §2.9 (line 126) proposes an additional brake — halve size when λ is
elevated on more than half the book (a systemic shock is one event, not nine) — not modeled by any
existing component; would be new logic inside Aftershock itself (portfolio-wide λ read, not a
FeatureBus resource in v1).

## 5. Infrastructure prerequisites

| Gap | Description | Effort |
|---|---|---|
| P8 (grading) | Verified NOT a hard structural cap for Aftershock (see §4) — but the strategy's actual grade distribution should be journaled and checked against `min_grade` empirically before any gate run. | Low — journaling only, existing pipeline |
| P7 (per-strategy exit profile) | `TradeManager` has one global ratchet; the λ-decay "flatten regardless of P&L" rule needs a hook for a strategy to emit a management command outside its single-decision `on_new_candle` contract. No such hook exists today. Concretely: either extend the return contract, or add a controller call `strategy.check_exits(open_orders, context)` per H1 close, whose output routes through the existing `_dispatch_mgmt_command` (`system_controller.py:648`) exactly like `TradeManager` output does — the *routing* target (fire-and-forget `CLOSE_POS` on PUSH, outcome verified via HEARTBEAT) already exists; only the strategy→command producer side is missing. | Medium — new controller hook + tests |
| P6/RISK-07 | `context['spread']` does not exist on the live path (brief item 1; audit P6/RISK-07). The "skip if spread > x% of event range" filter in §3 is **inert live** exactly like Gyroscope's `max_spread_atr_frac`. Backtesting can still model spread via the FBS table in `scripts/poc_sb_stops.py:43`; going live without this fixed is a real gap. | Medium — EA/bridge change to surface spread |
| STRAT-01 | The research harness (`scripts/research_run.py` + `kernel_replay.py`) runs live entry logic but resolves trades with `backtest_engine.py`'s FIXED-R exits — it does not model the ratchet, let alone the λ-decay flatten this strategy needs. `scripts/poc_sb_stops.py`'s `replay_managed` models the ratchet (upper bound) but has **no concept of a strategy-initiated flatten either** — it would need extension before Aftershock's validation numbers can be trusted as anything but a FIXED-R lower bound / ratchet-only upper bound with the flatten rule entirely unmodeled. | Medium-High — new replay logic for state-based flatten |
| P2 (no OCO) | Not applicable — Aftershock only ever places one directional MARKET order per cascade, never paired pending orders. | None |
| Swap costs | Cascades could plausibly hold across a session/day boundary; the TVP cost gate currently prices spread+commission only. Ledger's swap-field survey (`feat/swap-survey`, underway) is not yet integrated into any strategy's cost model. | Not yet scoped |

## 6. Validation plan

TVP instantiated, with the brainstorm's event-study-first sequencing treated as a **hard gate before
any backtest** (brainstorm §2.17, line 151):

1. **Stage (b), first and mandatory:** event study — distribution of forward H1 returns conditioned on
   (λ-band × event direction). If the conditional histograms for continuation don't separate from the
   unconditional distribution, **stop here and record NO-GO** without running a backtest at all. This
   is a stronger kill-switch than the OTE/Gyroscope studies used, applied deliberately given the
   Gyroscope lesson that a mechanically sound implementation can still front an absent edge.
2. Session-of-day control: re-run the event study with session dummies to confirm λ adds information
   beyond "it's the London/NY open" (brainstorm §2.17).
3. Continuation and exhaustion legs are **never pooled** — this document scopes exhaustion out of v1
   entirely; if a future study revisits it, it gets its own independent gate.
4. If stage (b) survives: pre-register a gate document (mirroring
   `docs/research/2026-07-14-gyroscope-gate.md`'s format) on the frozen 9-symbol H1 dataset
   (`data/lake/frozen/`, ~18,600 bars/symbol), 70/30 chronological IS/OOS, ±30% sweeps on (q, λ_lo,
   λ_hi, tp_range_multiple), ×1.5/×2 spread stress, bootstrap 95% CI, per-symbol consistency
   (≥6/9 non-negative, mirroring the criterion Gyroscope failed at 4/9), beat the
   `MaSlopeBaseline` manifest.
5. Backtest on the existing `backtest_engine.py` rig for the FIXED-R lower bound; separately run
   `poc_sb_stops.py replay_managed` (once extended for the flatten rule, see §5) for the ratchet-aware
   upper bound. Quote both, label the replay number as an upper bound per STRAT-01.
6. **Cannot currently be validated:** the λ-decay flatten rule's effect on realized R (no harness
   models it yet); live spread-based entry filtering (P6/RISK-07 inert); any multi-day swap cost drag.

## 7. Failure modes and monitoring

- **Slow grinding trends with no events → inactive.** Safe failure (brainstorm §2.10).
- **Parameter drift in (μ, α, β) across regimes → λ thresholds miscalibrated.** Monitor via a rolling
  KS test of inter-event times against the fitted model (brainstorm §2.10); if `lambda_fit: rolling_mle`
  is ever enabled, this check becomes mandatory, not advisory, given the Gyroscope calibration lesson.
- **News spikes with instant full reversal fake continuation signals.** Mitigated by the confirm-bar
  requirement plus the **existing** news lockout: `src/analysis/news/` (NewsManager façade,
  ForexFactory CSV source, fail-closed policy when the feed is down and the cache is stale). It blocks
  on HIGH-importance events only, with configurable pre/post windows (60/30 min) and currency
  inference across USD/EUR/GBP/JPY/AUD/CAD/CHF/NZD plus the `news.symbol_currencies` config map. The
  gate is consulted in `_execute_signal` via `SystemController._news_blocks_symbol`
  (`src/core/system_controller.py:480,491`), so Aftershock inherits it with no new work — what would
  need checking at spec time is whether the 60/30-minute windows are the right shape for a
  cascade-triggered entry, not whether a lockout exists.
- **Self-audit metric (live):** realized false-entry rate (event confirmed → next-bar stop hit before
  1× range target) tracked rolling, compared against the IS-measured base rate from the gate. A
  material excess — mirroring Gyroscope's 27.1%-vs-5% gap — should auto-pause the strategy and alert,
  the same discipline Gyroscope's blueprint specified (`…brainstorm.md:729`) even though Gyroscope
  itself never reached live to prove the alert fires correctly.
- **Cascade λ elevated on >half the book simultaneously:** correlated-shock detector, not yet built;
  flagged in §4 as new logic, not existing infrastructure.

## 8. Verdict and sequencing

**Recommendation:** proceed to stage (b) — the event-study screen — before writing any code beyond
`HawkesIntensity` and its unit tests (TDD on synthetic event streams, no market data, mirroring
Gyroscope's build sequence in `…brainstorm.md:734`). Do not build the exhaustion leg or the λ-decay
flatten controller hook until continuation clears the event study; both are wasted effort if stage (b)
kills the concept, which is exactly the point of gating there.

This is Wave 2's #2-ranked candidate by the brainstorm's own scoring (`…brainstorm.md:635`), but ranked
below Gyroscope specifically because of lower trade frequency (slower statistical validation) and
Hawkes MLE fragility on sparse data — and Gyroscope, the #1 pick, was NO-GO. No portfolio-sequencing
dependency on Rubicon or Rainflow (`docs/strategies/rubicon.md`, `docs/strategies/rainflow.md`) — all
three can run their event-study/detection-study gates independently and in parallel, per the
brainstorm's portfolio view (`…brainstorm.md:746`: "one candidate per research cycle... Gyroscope
first" — Gyroscope has already run; these three are the next cycle). The EXP-0 finding stands as the
governing caveat for all of them: this strategy's entries must earn their own edge before the exit
engine's amplification (not subsidy) can be credited to it.
