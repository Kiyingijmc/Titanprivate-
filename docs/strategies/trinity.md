# TRINITY — Hidden-Markov 3-state regime allocator

> **Status:** candidate (Wave 4, overlay — NOT an entry generator) · **Family:** stochastic
> process / regime inference (meta-strategy) · **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §9 · **Doc version:** 2026-08-01

## 1. Thesis and return source

Trinity is not a source of new trades. It is an allocator: fit a 3-state Gaussian Hidden Markov
Model on H1 (return, |return|, range/ATR) emissions per the brainstorm design; the states
empirically resolve into low-vol-drift ("Trend"), low-vol-no-drift ("Range"), and high-vol
("Turbulence"). Its output — a posterior state vector, updated every closed H1 bar — is consumed
by *other* strategies as a risk multiplier (0–1.25×) rather than generating entries of its own.

The claimed return source is not a new inefficiency; it is a claim that strategy edges are
state-conditional (the repo's own evidence for this: SilverBullet's edge is measured specifically
at H1 with session-timing structure — its performance is not asserted to be uniform across all
market states) and that explicit state inference reallocates risk toward each member strategy's
habitat faster, and with anticipation via transition probabilities, than each strategy's own
internal gates could alone. This is a claim about *risk-adjusted portfolio quality*, not raw
expectancy — Trinity can only be evaluated by its effect on member strategies' performance with
and without its weights applied, never in isolation.

## 2. Evidence base

No implementation, fit, or validation run exists for Trinity. There is no supporting evidence.
Relevant adverse and contextual evidence:

| Source | Finding | Relevance to Trinity |
|---|---|---|
| Brainstorm §9 | "The classic HMM sin — refitting on recent data until it 'looks right' — is banned by protocol"; quarterly refits on frozen IS only | Trinity's own source document pre-registers against the most common failure mode of regime-switching overlays: silent look-ahead via refit-until-plausible |
| Brainstorm §9, §12 | Existence risk 4/5 (better than most of the arsenal) but "n/a" cost-survival and "adds a layer of model risk *on top of* every strategy"; "wrong-state misallocation is correlated across the book" | An overlay's failure mode is not "loses money on its own trades" (it has none) — it is silently degrading every member strategy's sizing at once, in a way a per-strategy P&L review would not isolate |
| The graveyard (brief) | OTE, MTF-PB v2, Gyroscope, original SilverBullet M5 config — four independent pre-registered NO-GOs on this rig | Establishes that this rig's base rate for novel hypotheses, even well-motivated ones, is failure; Trinity should not be assumed to work by default |
| EXP-0 coin-flip, Outcome 1 (brief) | Placebo entries through the full exit engine average −0.249R vs SilverBullet's +0.109R real; exit engine amplifies real edge (+0.231R), does not subsidise random entries (+0.075R) | **Direct implication for Trinity:** an overlay that mis-sizes trades toward a wrong-state estimate does not get bailed out by the exit engine — it amplifies whatever the entry (member strategy) delivered, correctly or not. Trinity's weighting must track *real* state-conditional edge, not a plausible-looking correlation, or it degrades a strategy that would otherwise have earned its own edge |

## 3. Signal specification

Trinity generates no `{signal, type, price, sl, tp}` decision dict — it is explicitly not an entry
generator (per the brief and brainstorm §9: "Trinity is primarily an allocator: it doesn't generate
entries — it gates and sizes the *other* strategies"). Its "signal" is a per-bar state posterior
and a resulting risk multiplier:

- **Fit:** 3-state Gaussian HMM on H1 (return, |return|, range/ATR) emissions, quarterly, on
  frozen in-sample data only (no rolling refit — the brainstorm's explicit anti-overfitting
  discipline, §9 item 10).
- **Inference:** per closed H1 bar, compute the posterior state vector `P(state)` given the fitted
  model and the bar's emissions.
- **State labelling:** fixed by vol ranking at fit time (not by inspection) — Trend (low-vol,
  drift), Range (low-vol, no drift), Turbulence (high-vol) — to avoid label-switching between
  refits.
- **Allocation:** map the posterior to per-strategy risk multipliers, hard floor 0 (a strategy can
  be fully gated in an unfavourable state), soft cap 1.25×. Example habitat mapping per the source
  doc: trend-following strategies (Gyroscope, Aftershock per the brainstorm's own arsenal) weight
  toward Trend/Turbulence; mean-reversion strategies (Spring) weight toward Range.
- **Hysteresis:** minimum dwell time before a weight change takes effect, to suppress posterior
  chatter at state boundaries (brainstorm §9 failure-mode #2) — not yet parameterized.
- **Global derate:** a posterior swinging toward Turbulence triggers a book-wide risk reduction
  across all member strategies simultaneously — described in the source doc as "the arsenal's
  circuit breaker."
- **No entries, no stops, no targets of its own.** All trade mechanics remain the member
  strategy's; Trinity only scales the resulting position size.

## 4. Architecture integration

**This is new infrastructure, described honestly, not a config flag.** Titan today has no plumbing
for a meta-strategy to scale a specific member strategy's risk. What exists, verified in this repo
at `main @ c16e537`-equivalent code:

- `SystemController._execute_signal` (src/core/system_controller.py:490) computes a single scalar
  `risk_mult` from `self.risk_manager.throttle_factor()` (line ~509–510) — a **v15.2 drawdown
  throttle**, book-wide, unkeyed by strategy, defaulting to 1.0 (no-op) — and passes it into
  `RiskManager.calculate_lot_size(p, sl, symbol, htf_bias, risk_mult=risk_mult)`
  (src/risk/risk_manager.py:224). That function already multiplies the risk amount by `risk_mult`
  before the lot-size math (risk_manager.py:230–241).
- This means a `risk_mult` **seam exists**, but it is presently a single global scalar sourced from
  one thing (drawdown throttle) — it is not keyed by `strategy_id`, and nothing upstream of
  `_execute_signal` currently carries a per-strategy multiplier into it. `Intent`
  (src/arbiter/intent.py) — the object each strategy actually submits — has no `risk_mult` or
  equivalent field today (its numeric fields are `price`, `sl`, `tp`, `confidence` [unused for
  sizing], `priority`). `_run_strategies` (system_controller.py:917) builds the `Intent`, submits it
  to the arbiter, and on approval passes only `(decision, name, grade)` — reconstructed from a
  `pending_meta` dict keyed by `id(intent)` — into `_execute_signal`; the `Intent` object itself is
  discarded after `arb.resolve()`, so no `Intent` field survives to `_execute_signal` today.
- **The needed seam:** add a `risk_mult` (or `regime_mult`) field to `Intent`, populated either (a)
  by the strategy itself reading a FeatureBus resource, or (b) by the arbiter/controller layer
  consuming a new `global`-scope FeatureBus resource (e.g. `regime.state_posterior`, following the
  `symbol_tf | symbol | global` scoping already defined in `src/features/feature_bus.py`) and
  looking up the submitting strategy's habitat weight at approval time. Either way, that value must
  survive from `Intent` submission through `pending_meta` (system_controller.py ~line 999) to
  `_execute_signal`, and be **composed multiplicatively** with the existing drawdown-throttle
  `risk_mult` — `calculate_lot_size`'s single `risk_mult` parameter is the natural multiplication
  point (`risk_amount *= risk_mult`, risk_manager.py:241), not a second independent gate.
- **Manifest sketch** — Trinity is not a `StrategyManifest` entry in the conventional sense (it
  submits no `Intent`s of its own), so it does not fit the `status: research|demo|live` FSM the
  registry drives for entry-generating strategies. It is closer to a controller-level service (like
  `feature_bus`/`arbiter` themselves) than a `BaseStrategy` subclass. If forced into the existing
  registry shape for consistency, a non-trading manifest would need a new `family: overlay` and a
  registry carve-out that never routes it an `on_new_candle` call — this is itself new registry
  work, not existing behaviour.
- **Class placement (if built):** `src/analysis/trinity_hmm.py` (pure HMM fit/infer, mirroring the
  `src/analysis/kalman_drift.py` split the brainstorm used for Gyroscope — math isolated from
  strategy/controller wiring) plus a thin controller-level consumer, not a `BaseStrategy` subclass.
- **FeatureBus resource to register:** `regime.state_posterior`, `global` scope (book-wide, not
  per-symbol — the HMM per the brainstorm design fits on aggregate/representative emissions, though
  the source doc does not specify whether it is one HMM for the whole book or per-symbol; this is
  an open design question this document does not resolve).
- **Grading path (P8):** does not apply — Trinity submits no `Intent`, so it is never scored by
  `SignalGrader`.
- **HTF-bias stance:** not applicable — no entries.
- **Exit profile:** not applicable — Trinity does not manage positions; member strategies' exits
  (default ratchet/runner) are unaffected by Trinity except through the size Trinity assigned at
  entry.
- **Risk interaction:** this document's entire content *is* the risk interaction. Trinity's global
  Turbulence-derate is a second, independent lever from the existing drawdown throttle
  (`throttle_factor()`) and from the daily 3% drawdown breaker (RISK-01) — three separate
  size-reducing mechanisms would need to compose correctly (multiplicatively, per the existing
  pattern) rather than fight or double-count each other. This composition has not been designed.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| New: `Intent.risk_mult` field + threading | Extend `Intent` (src/arbiter/intent.py) and the `pending_meta` handoff in `_run_strategies` (system_controller.py:917) to carry a per-strategy multiplier into `_execute_signal` | This is the entire missing seam described in §4; without it Trinity has no way to act on any trade | Not sized; new pattern, small surface (a handful of lines) but touches the arbiter/controller boundary |
| New: `regime.state_posterior` FeatureBus resource | `global`-scope resource; no `global`-scope resource exists in `src/features/packs/` today (`smc_pack.py` is entirely `symbol_tf`) | Trinity's posterior must be computed once per bar and be readable by both the allocator logic and (for monitoring) telemetry | Not sized |
| New: registry carve-out for non-entry-generating overlays | Today `StrategyRegistry` activates manifests into an FSM that expects `on_new_candle` calls; Trinity has none | Needed if Trinity is to be operator-visible/toggleable the way other strategies are, rather than a hardcoded controller feature | Not sized |
| P12 / STRAT-05 | Portfolio-level backtest (count cap, aggregate cap, correlation gate, daily breaker) — `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:424` | **Binding prerequisite, not optional.** Trinity can only be validated as an overlay (§6) — member backtests re-run with vs without its weights. That comparison requires a portfolio-level backtest harness, which does not exist; the current rig (`tests/backtest/backtest_engine.py`) resolves single-strategy trade sequences, not a multi-strategy book with shared risk multipliers | 3 d (audit estimate) |
| Composition design for 3 size-reducing mechanisms | Trinity's Turbulence-derate vs the v15.2 drawdown throttle vs the RISK-01 daily 3% breaker | Undesigned interaction risk: three multiplicative (or worse, non-multiplicative) size reducers stacking unpredictably | Not sized |

## 6. Validation plan

**Trinity can be validated only as an overlay, never standalone** — it has no trades of its own to
score. Per the brainstorm's own instantiation (§9 item 17) and this document's binding
interpretation:

1. **Prerequisite:** the portfolio-level backtest (P12/STRAT-05, §5) must exist before step 2 is
   meaningful. Running Trinity's weights against the current single-strategy `backtest_engine.py`
   would silently ignore exactly the cross-strategy interaction Trinity claims to manage.
2. **Member-strategy re-run, with vs without.** Each member strategy's existing validated backtest
   (for SilverBullet: `docs/research/2026-07-11-silverbullet-h1-stop-study.md`, the reference TVP
   run) is re-run twice: once at its own baseline sizing, once with Trinity's state-conditional
   weights applied. Adopt only if pooled net expectancy **and** drawdown both improve
   out-of-sample — an improvement in one at the cost of the other is not a pass.
3. **State economic-meaning check.** Independent of the P&L comparison: per-state return/vol
   statistics must differ significantly (the states must correspond to something real in the data,
   not be an arbitrary 3-way split that happens to correlate with realized returns in-sample).
4. **Hysteresis/chatter check.** Realized state-dwell times vs the designed minimum dwell; a model
   that flips state every few bars despite the hysteresis parameter has failed its own design intent
   regardless of P&L.
5. **Refit discipline audit.** Quarterly refits must be on frozen IS data only, per the brainstorm's
   explicit ban on refit-until-plausible (§9 item 10) — this needs to be a checked constraint in the
   validation harness, not a promise.
6. **What cannot be validated with current data:** nothing about Trinity's HMM fit itself is
   data-blocked (H1, 3 years, per brief item 8) — the blocker is entirely the missing portfolio
   backtest (P12/STRAT-05) and the missing risk-mult plumbing (§4, §5), both infrastructure, not
   data.
7. **EXP-0 implication:** Trinity does not, and by construction cannot, add entry-side edge — it
   only reweights sizing on entries member strategies already generate. EXP-0's finding that the
   exit engine amplifies real entry edge (+0.231R) but does not subsidise random entries (+0.075R)
   means Trinity's weighting is only valuable if it correctly identifies *when* a member strategy's
   entries are in their true edge-bearing regime; a Trinity that misjudges state adds model risk on
   top of a real edge without adding any edge of its own. The bar for adoption (§6.2: expectancy AND
   drawdown both improve OOS) is deliberately strict for exactly this reason.

## 7. Failure modes and monitoring

- **Wrong-state misallocation is correlated across the book** (brainstorm §9 weakness) — unlike a
  single strategy's bad trade, a Trinity misjudgement degrades every member strategy simultaneously
  in the same direction. This is the single most important thing to monitor if Trinity ever ships.
- **Label switching between refits** — mitigated by fixing state order via vol ranking at fit time
  (§3); a refit that silently reorders "Trend" and "Turbulence" would misapply weights entirely
  invisibly. Needs an assertion at refit time, not just a design intent.
- **Posterior chatter at state boundaries** — mitigated by hysteresis/min-dwell (§3, §6.4); monitor
  realized weight-change frequency vs the dwell floor.
- **Refit-until-plausible** — the classic HMM sin the source doc explicitly bans (§9 item 10); the
  only defence is protocol discipline (frozen IS, quarterly cadence) enforced by the validation
  harness, since nothing in the code itself prevents a re-fit on demand.
- **Interaction with the other two size-reducing mechanisms** (drawdown throttle, RISK-01 daily
  breaker) — undesigned as of this document (§5); if all three can independently reduce size, a
  combination of a bad regime call plus a real drawdown could compound into near-zero sizing at
  exactly the moment a member strategy's real edge is trying to recover, or conversely the layers
  could double-apply and the aggregate effect could be invisible from any single mechanism's logs.
- **Live self-audit metrics (if built):** realized per-state return/vol vs the fitted state's
  expected values (a live analogue of Gyroscope's NIS whiteness check); weight-change frequency vs
  hysteresis floor; per-member-strategy expectancy-with-Trinity vs expectancy-without, tracked
  continuously (not just at the one-time validation gate) so weighting drift is caught before it
  compounds across a quarter.

## 8. Verdict and sequencing

**Do not build Trinity before the portfolio-level backtest (P12/STRAT-05) exists.** This is not a
sequencing preference — it is a validity requirement: Trinity's only defined pass/fail test (§6.2)
is literally impossible to run without it. Building the HMM math and the `Intent.risk_mult` seam
(§4, §5) is comparatively cheap and could proceed in parallel as infrastructure, but the go/no-go
decision cannot be made until P12 lands.

Depends on: P12/STRAT-05 (shared prerequisite with `constellation.md`, which also wants a
portfolio-level backtest for the same underlying reason — its correlation-aware brake needs one to
validate its drawdown effect). If both Constellation and Trinity are pursued, build the portfolio
backtest once, not twice. Sequenced correctly, Trinity is a Wave 4 item behind at least one member
strategy candidate with a completed standalone validation (so there is something real to re-run
with weights) — reweighting an unvalidated or NO-GO'd strategy proves nothing.
