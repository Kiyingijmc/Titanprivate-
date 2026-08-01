# Rubicon — Bayesian online change-point (BOCPD) regime trader

> **Status:** candidate (Wave 2) · **Family:** Bayesian change-point / regime-turn ·
> **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §3 (lines 155-213), §12 comparative
> matrix (row 3), §13 ranked shortlist (#3) · **Doc version:** 2026-08-01

## 1. Thesis and return source

Bayesian Online Change-Point Detection (Adams & MacKay 2007) maintains, at every H1 bar, a full
posterior over "run length" — how many bars have elapsed since the generating distribution of returns
last reset (brainstorm §3.3, lines 163-165). A collapsing run-length posterior is a probabilistic
statement that the market regime that existed until now no longer exists — and it discards stale
old-regime statistics **immediately** rather than averaging them away over a fixed lookback window,
which the brainstorm calls out as "the structural flaw of every rolling-window indicator" (line 164).

Return source: the hypothesis is that genuine change-points are followed by a short window of drift
persistence — positioning adjusts over hours, not instantly — and trading that direction, sized to the
*new* regime's volatility, front-runs systems that only catch up once enough new data has diluted their
rolling window (brainstorm §3.4, lines 166-167).

This document treats Rubicon as two things at once, per the brainstorm's own framing (§3.11, line 195)
and the explicit instruction behind this document: a **candidate trading strategy** (uncertain,
possibly NO-GO) and a piece of **reusable regime infrastructure** — the run-length posterior itself —
whose salvage value is real even if the trading hypothesis fails. That dual framing shapes §5 and §8.

## 2. Evidence base

**Supporting (design-level; the underlying statistical method is well established outside this repo,
its application here is untested):**
- Ranked #3 in the brainstorm shortlist, specifically flagged as having **the highest salvage value on
  the list**: "its detection layer is reusable infrastructure (a regime clock for SilverBullet, Trinity,
  and the others) even under a trading NO-GO" (`…brainstorm.md:637`).
- BOCPD directly attacks a documented weakness of every other component in this repo's arsenal —
  rolling-window contamination by stale data (`…brainstorm.md:195`).
- Comparative matrix: complexity 7/10, expected robustness 3/5, cost survival 4/5, existence risk 3/5
  (`…brainstorm.md:619`) — a middling-to-cautious profile, not a strong one.

**Adverse (stated plainly, per house rule):**
- The graveyard: OTE −0.158R pooled, MTF-PB v2 −0.274R pooled, original SilverBullet M5 −4.27R, and
  **Gyroscope** — this arsenal's own #1-ranked pick — NO-GO at −0.067R pooled with only 4/9 symbols
  non-negative (`docs/research/2026-07-14-gyroscope-gate-results.md`).
- **The Gyroscope lesson applies to Rubicon's decision layer directly and specifically.** Gyroscope's
  designed 5% false-entry rate realized at 27.1% because the SPRT's error-rate theory assumed i.i.d.
  observations while consecutive velocity z-scores shared filter state
  (`…gate-results.md:38,40,44`). BOCPD has its own analogous, independently-flagged risk: **"false
  change-points in heavy-tailed noise — BOCPD with Normal likelihood over-fires on fat tails"**
  (`…brainstorm.md:190`), which is exactly the same species of failure — nominal sequential-decision
  error rates breaking down under real market autocorrelation/fat-tailedness rather than the idealized
  distribution the math assumes. The brainstorm's own prescribed mitigation (Student-t likelihood,
  monitor false-break rate) is treated in this document as **mandatory, not optional**, precisely
  because the sister strategy in the same arsenal failed for the nominal-vs-realized-error-rate reason.
- **The honest existence risk, stated by the brainstorm itself:** "Post-break drift persistence at H1
  in FX is a hypothesis, not a documented fact — could simply be false" (`…brainstorm.md:198`). This is
  the central uncertainty this document is required to name plainly: unlike volatility clustering
  (Aftershock's basis, "the most-replicated stylized fact in finance") or mean reversion, post-break
  drift persistence at H1 in retail FX/metals has no citation in this repo's research corpus. It is an
  untested hypothesis, not an established fact being re-implemented.
- No Rubicon-specific event study, detection study, or backtest has been run. Every quantitative claim
  about Rubicon's own performance is **not yet measured**.
- **EXP-0 implication:** placebo entries through the live exit engine net −0.249R (0/20 reps positive)
  vs SilverBullet's real +0.109R (`docs/research/2026-07-31-exp0-coinflip-preregistration.md`); the
  exit engine amplifies real edges (+0.231R) but does not subsidise random ones (+0.075R). Rubicon's
  entries — sized to a freshly-estimated, high-uncertainty regime — must independently demonstrate a
  monetisable directional edge in the post-break window; the ratchet cannot manufacture one from noise.

## 3. Signal specification

**State model:** H1 log returns drawn from a Normal (or, per the mandatory mitigation, Student-t) with
unknown (μ, σ) that occasionally resets. BOCPD maintains `P(r_t)`, the posterior over run length r_t
(bars since the last reset), updated online each bar (brainstorm §3.5-3.6, lines 169-178).

**State machine** (`…brainstorm.md:172-178`):
```
STABLE (long run length) → BREAK DETECTED (P(r<3) > p_crit) → CHARACTERIZATION
 (2-3 bars: estimate new-regime μ̂, σ̂ from the young run) → SIGNAL (|μ̂| significant vs σ̂)
 → VALIDATION (cost screen, vol sanity) → ENTRY → MANAGEMENT → EXIT
 → COOLDOWN (no re-entry until run length matures or next break)
```

**Entry:** when change-point probability spikes above `p_crit` and the young run's estimated drift is
significant (`|μ̂|·√n / σ̂ > z`), enter in the drift direction. Pure vol-shift breaks with no
significant drift are explicitly **not traded** — the characterization stage filters these out, and the
brainstorm notes that's most breaks, and skipping them is the point (brainstorm §3.7, lines 180-181).

**Stop:** `k·σ̂` — the new regime's estimated volatility, not a fixed ATR multiple; sizing self-adapts
to the break's violence (brainstorm §3.8-3.9, lines 183, 187).

**Target / management:** TP and trailing via the existing ratchet pipeline once armed.

**Structural exit — "next-break-flattens":** the **next** detected change-point unconditionally
flattens the position, independent of P&L, because the thesis ("this regime is still live") has
expired by definition (brainstorm §3.8, line 184). This is the new exit primitive named in this
document's brief; see §4 for how it would actually wire through the platform, since no such hook
exists today.

**Time stop:** at N bars if no change-point has fired and the position hasn't reached target.

**Risk shaping:** half size on the first trade after a **vol-expansion** break specifically — the
widest-estimation-error case (brainstorm §3.9, line 187).

**Universe:** H1, frozen 9-symbol gate set as the default screening universe
(`data/lake/frozen/`), consistent with the other Wave 2 candidates.

## 4. Architecture integration

**Class placement** (mirrors the Gyroscope precedent — `src/strategies/models/gyroscope.py` +
`src/analysis/kalman_drift.py`):
```
src/strategies/models/rubicon.py         # RubiconStrategy(BaseStrategy)
src/analysis/bocpd.py                    # BOCPD: run-length posterior + hazard model + likelihood
tests/unit/test_bocpd.py                 # posterior math on synthetic piecewise-stationary series
tests/unit/test_rubicon_strategy.py      # decision-dict contract, gating, next-break-flatten
```

**Manifest sketch** (`config/manifests/rubicon.yaml`, format verified against the live
`config/manifests/gyroscope.yaml`):
```yaml
id: rubicon
version: "0.1.0"
class_path: "src.strategies.models.rubicon:RubiconStrategy"
family: bayesian_changepoint
timeframe: H1
requires: []
status: research
priority: 70          # illustrative placeholder; final value set at spec time
honors_htf_bias: false
```
`honors_htf_bias: false` — Rubicon's direction comes from the young run's own estimated drift, which by
construction *is* a claim about the current bias; it should not additionally be filtered by the
controller's separately-computed HTF bias signal. Same exemption mechanism as `gyroscope` and
`ma_slope_baseline` (`src/strategies/manifest.py:33`, `src/strategies/registry.py:75`,
`src/core/system_controller.py:962`).

**Config block sketch:**
```yaml
strategies:
  rubicon:
    enabled: false
    timeframe: H1
    pairs: []
    likelihood: student_t        # NOT normal — mandatory per §2's Gyroscope-lesson mitigation
    hazard_rate: 1/250           # prior expected run length in bars; consequential, not obvious
    p_crit: 0.5                  # change-point probability threshold
    characterization_bars: 3
    z_significance: 2.0
    k_sl: 2.5                    # stop = k_sl * sigma_hat
    vol_expansion_half_size: true
    time_stop_bars: 48
```

**FeatureBus resource — the salvage-value path.** The run-length posterior is explicitly named as
reusable infrastructure even under a trading NO-GO (`…brainstorm.md:637`). Concretely, this means
registering it as a FeatureBus resource so other strategies (or a future Trinity-style allocator, not
in Wave 2) can consume it as a regime filter, mirroring the pattern in
`src/features/packs/smc_pack.py` (`ResourceSpec(name="smc.enriched_df", scope="symbol_tf",
compute=...)`):
```python
# src/features/packs/regime_pack.py (new)
bus.register(ResourceSpec(
    name="regime.run_length_posterior",
    scope="symbol",
    compute=_compute_run_length_posterior,   # wraps BOCPD.posterior(ctx.window)
))
```
This is infrastructure that ships regardless of Rubicon's own gate outcome, exactly as
`KalmanDrift` was retained after Gyroscope's NO-GO (`src/analysis/kalman_drift.py`,
`…gate-results.md:49`). `validate_data(df, min_length=warmup, check_smc=False)` — raw OHLC only for
the strategy itself.

**Grading path (P8):** as with Aftershock, verified directly against `signal_grader.py` rather than
assumed. Displacement (≤20) is computed from `enriched_df.iloc[-1]`'s ATR/open/close regardless of
strategy family (`system_controller.py:969`), so a genuine break bar (elevated range by construction of
the characterization stage) should score reasonably. Premium/discount defaults to `+5` (no liquidity
concept). Killzone (`+15`) is time-based and unrelated to the regime signal. HTF bias scores 10
(neutral) unless coincidentally aligned. Net: plausibly clears `min_grade: B` (55) without a grader
change, to be confirmed empirically once real decisions exist — narrower than a blanket "SMC-shaped
grader structurally caps this."

**HTF-bias stance:** exempted (`honors_htf_bias: false`).

**Exit profile — the concrete plumbing gap.** "Next-break-flattens" needs a strategy to *initiate* a
close outside its normal entry-signal turn, which today's `on_new_candle(df, context) →
decision-dict-or-None` contract does not support — it can only propose new entries, never manage
existing ones. Strategy-initiated flatten does **not exist as a hook today**, but the *routing
mechanism it would use* already exists and is well-understood: `SystemController._dispatch_mgmt_command`
(`src/core/system_controller.py:648`) already routes `TradeManager`-originated commands — `MODIFY`,
`CLOSE_PARTIAL` (translated to `CLOSE_POS` with a volume), and plain `CLOSE_POS` — onto the EA's
fire-and-forget PUSH protocol, with outcomes verified from the next HEARTBEAT rather than a REQ
round-trip (per this repo's standing rule that slow trade calls must never sit on the REQ path). The
missing piece is entirely on the *producer* side: Rubicon needs a way to say "flatten ticket N" when it
detects the next change-point, and no current call site invites that from a strategy instance. The
concrete addition would be a new controller call — e.g. `strategy.check_exits(open_orders_for_me,
context)` invoked once per H1 close alongside `_run_strategies`, returning a list of `{"action":
"CLOSE_POS", "ticket": …}` dicts that flow into the *same* `_dispatch_mgmt_command` `TradeManager`
output already uses today. No new EA change and no new socket are required — only a new call site and
a way for the strategy to know which open tickets are its own (the state-DB rows already carry a
`strategy` column per the TTL-cleanup code at `system_controller.py`'s `_cleanup_ghost_orders`, so this
is available data, not a new schema).

**Risk interaction:** unchanged `RiskManager.calculate_lot_size`; stop distance is regime-derived so
sizing adapts. The book-wide portfolio cap already aggregates risk across strategies with no new work.
The vol-expansion half-size rule is new strategy-internal logic, not a RiskManager change.

## 5. Infrastructure prerequisites

| Gap | Description | Effort |
|---|---|---|
| Strategy-initiated flatten hook | No mechanism today for a strategy to emit a management command outside `on_new_candle`'s single-decision contract. The routing target (`_dispatch_mgmt_command` → fire-and-forget `CLOSE_POS`) already exists; only the producer-side call site is missing. This is the single largest concrete piece of new controller plumbing any Wave-2 candidate in this batch needs. | Medium — new controller hook + tests |
| P8 (grading) | Likely not a hard structural cap (see §4) but must be confirmed empirically once decision dicts exist, especially since Rubicon's signal frequency is expected to be very low (few observations to check against). | Low |
| P6/RISK-07 | `context['spread']` does not exist live; any cost-screen filter in the entry logic is inert on the live path exactly as Gyroscope's `max_spread_atr_frac` is. Backtest cost modeling via `scripts/poc_sb_stops.py:43` is unaffected. | Medium — EA/bridge change |
| STRAT-01 | `poc_sb_stops.py`'s `replay_managed` models the ratchet as an upper bound but has no concept of "next-break-flattens" — that state-based exit is entirely unmodeled by any existing harness. Backtest-engine FIXED-R resolution is the only currently-trustable number, and it doesn't test the exit primitive that is this strategy's most distinctive feature. | Medium-High — new replay logic |
| Regime-pack FeatureBus registration | `regime.run_length_posterior` does not exist yet; needs a new pack file mirroring `smc_pack.py`. Worth building even on a Rubicon NO-GO, per the brainstorm's salvage-value framing. | Low-Medium |
| Likelihood choice / hazard prior | Both are "consequential and not obvious" per the brainstorm itself (`…brainstorm.md:198`) — this is a research decision, not an engineering task, and belongs in the pre-registered gate document, not this architecture doc. | N/A (research, not infra) |

## 6. Validation plan

TVP instantiated with BOCPD's own three-stage sequencing (brainstorm §3.17, lines 210-211), which is
stricter than the standard TVP because the existence risk is explicitly unresolved:

1. **Stage 1 — pure detection study, label-free.** Do BOCPD-detected break points visually and
   statistically align with known regime shifts across the 3-yr H1 history? This is a sanity check on
   the detector itself, independent of any trading claim.
2. **Stage 2 — event study.** Forward H1 returns conditioned on the drift z-score of the young run,
   post-break. **This is the decisive test of the central hypothesis** ("post-break drift persistence
   is real"). If the event study shows no post-break persistence, **record NO-GO at this stage** and
   retain BOCPD purely as the regime-filter library described in §4 — exactly the disposition the
   brainstorm itself prescribes (`…brainstorm.md:211`).
3. **Stage 3 — backtest, only if stage 2 passes.** Pre-registered gate mirroring
   `docs/research/2026-07-14-gyroscope-gate.md`'s format: frozen 9-symbol H1 dataset, 70/30
   chronological IS/OOS, ±30% sweeps on (p_crit, z_significance, hazard_rate, k_sl), ×1.5/×2 spread
   stress, bootstrap 95% CI, ≥6/9 symbols non-negative (the criterion Gyroscope failed at 4/9), beat
   `MaSlopeBaseline`. Given expected low trade frequency, the ≥150-trade minimum criterion
   (Gyroscope's own bar) may take materially longer to accumulate — state this honestly in the gate
   doc rather than lowering the bar.
4. **Cannot currently be validated:** the next-break-flatten exit rule (no harness models it — see §5
   STRAT-01); live spread filtering (P6/RISK-07 inert); the Student-t vs Normal likelihood choice's
   effect on realized false-break rate cannot be checked against a designed error budget the way
   Gyroscope's SPRT could, because BOCPD has no equivalent single α parameter — a bespoke diagnostic
   would need to be designed for this, not assumed to transfer from Gyroscope's blueprint.

## 7. Failure modes and monitoring

- **False change-points in heavy-tailed noise** — the primary named risk (brainstorm §3.10, line 190).
  Mitigation: Student-t likelihood (mandatory in this design, not optional per §2/§4); monitor realized
  false-break rate live, mirroring Gyroscope's self-audit discipline (`…gate-results.md:38`) even
  though BOCPD has no single designed-α to compare against — the monitoring metric itself needs
  definition during the gate-doc write-up, not assumed transferable.
- **Noisy 2-3 bar drift estimate** — the z-gate is expected to leave most detected breaks untraded;
  accept low frequency as the honest cost of the significance filter (brainstorm §3.10, line 191).
- **Slow regime drift with no sharp break is invisible by design** — not a bug, other arsenal members
  (Spring, Gyroscope) are meant to cover that case; Rubicon should not be judged against slow-drift
  regimes it was never meant to trade.
- **Whipsaw news days producing multiple false breaks** — needs a news lockout (shared prerequisite
  across the arsenal, not built yet) plus the Student-t likelihood.
- **Live self-audit:** realized win-rate and R-multiple of trades taken immediately after a
  characterization stage, tracked separately from trades where the position survived a subsequent
  false-break scare — the two populations should differ if the thesis is real; if they don't, that's
  live evidence the event-study result (however positive) didn't transfer.

## 8. Verdict and sequencing

**Recommendation:** run stage 1 (detection sanity) and stage 2 (event study) before writing
`RubiconStrategy` itself — only `BOCPD`'s posterior math needs to exist for those two stages, and it
should be built and unit-tested against synthetic piecewise-stationary series first (TDD, no market
data), mirroring the Gyroscope build sequence. Do **not** build the strategy-initiated-flatten
controller hook (§4/§5) until stage 2 passes — it is real engineering effort with no payoff if the
central hypothesis (post-break drift persistence at H1) is false, which is a live, undocumented
possibility this document does not paper over.

Ranked #3 in the brainstorm's shortlist, behind Gyroscope (NO-GO) and Aftershock
(`docs/strategies/aftershock.md`, also pre-registration pending) — specifically because its tradable
hypothesis is the least documented of the top three (`…brainstorm.md:637`). Regardless of the trading
verdict, the `regime.run_length_posterior` FeatureBus resource should ship as infrastructure once
`BOCPD` exists and passes its unit tests — this is the one Wave-2 concept in this batch with a clear
value path even on a NO-GO, and that path should not be blocked on the trading gate's outcome. As with
the other candidates, the EXP-0 finding governs: Rubicon's post-break entries must earn their own
directional edge; the exit engine will amplify a real one and cannot manufacture one from noise.
