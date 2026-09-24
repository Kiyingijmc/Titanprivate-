# VANGUARD Phase 1 — research and architecture review

Date: 2026-09-24. Repository inspected at `8d6ab8d2863d294125df89243ca2a384c8c815fe`.
Status: **RESEARCH FIRST / SIMPLIFY. No implementation or deployment approval.**

The entire supplied conversation is treated as a collection of hypotheses. This package is a proposed research contract, not a claim of measured VANGUARD performance. No VANGUARD backtest was run; no production code, configuration, running service, or broker position was changed.

## Package and coverage

| Deliverable | Location |
|---|---|
| A Executive assessment; D adversarial review; P owner decisions; final verdict | This document |
| B Actual repository integration audit and end-to-end trace | [Repository audit](repository-audit.md) |
| C Literature review, evidence strength, source verification | [External evidence](literature.md) |
| E Complete mechanism inventory, classifications, falsification tests | [Concept inventory](concept-inventory.md) |
| F Architecture; G state models; H risk; I lifecycle; J acquisition; K configuration; L contracts | [Architecture](architecture.md) |
| M failure analysis; safety invariants; recovery | [Operations and failure analysis](operations.md) |
| N baselines, ablations, costs, metrics and gates; O conditional roadmap | [Research protocol](research-protocol.md) |

## A. Executive assessment

VANGUARD has a coherent **research question**, but the brainstorm does not establish an edge. The defensible question is whether a small amount of causal, multi-horizon information improves the allocation and retention of trend exposure after realistic costs. The least defensible claim is that naming more market and position states makes this information more predictive.

Proposed market hypothesis:

> On a prespecified broker universe and holding horizon, lagged directional evidence identifies episodes in which the conditional expected signed return exceeds implementation and financing costs. Conditional on the same directional evidence, a local acquisition event and a subsequent observable contradiction may respectively improve entry economics and continuation decisions. These incremental effects must survive chronological out-of-sample comparison against simpler rules at comparable capital exposure.

This formulation deliberately allows the local acquisition and thesis-exit hypotheses to fail while trend exposure survives. It also allows the entire intraday hypothesis to fail.

Separate four propositions:

1. **Alpha:** lagged information predicts future signed, executable returns. Slow information diffusion, persistent flows and delayed rebalancing are possible economic explanations, not proven causes in Titan's broker data.
2. **Entry timing:** delaying acquisition changes participation, price, costs and adverse selection. A better observed entry price is not automatically better expectancy.
3. **Risk:** sizing and caps control capital exposure. They do not establish directional predictability. A forecast-dependent sizing overlay is itself a predictive hypothesis and must be tested accordingly.
4. **Management:** an exit chooses continued exposure versus cash using information available now. Historical entry price and unrealized profit alone do not show which choice has higher forward value.

Trend literature supports persistence at some horizons and option-like payoff shapes. It does **not** establish H1/M15/M5 superiority, profitable hostile-pullback classification, winner graduation, protected-profit financing, or a seven-stage lifecycle. Positive skew can exist with zero gross expectancy and negative net expectancy. See [the evidence review](literature.md).

The recommended research V1 is one direction model, one acquisition rule, a real initial stop, no fixed TP in the principal arm, one monotonic volatility trail, one position per symbol, and shared Titan risk. Compare a single evidence-conditioned exit against both unchanged management and simple tightening. Defer campaigns and native allocation until that comparison has earned them.

## D. Strongest adversarial case

### 1. This may be the failed MTF pullback strategy renamed

Titan's [MTF-PB v2 three-year result](../2026-06-25-mtf-pb-v2-results.md) recorded NO-GO: no asset class passed its dual-model gate; pooled managed expectancy was −0.274R and FX was especially weak. Those historical simulations have their own limitations, but they are adverse prior evidence. A new name, debt variable or risk engine does not reset the research history. VANGUARD must identify a distinct incremental hypothesis and include prior attempts in its trial ledger.

### 2. Management sophistication can manufacture a backtest edge

The [September SilverBullet execution diagnostic](../2026-09-16-silverbullet-execution-diagnostic.md) reversed earlier positive headlines under a more detailed executable-price model. The [September structural-exit diagnostic](../2026-09-22-structure-exits.md) was small, mixed and negative in aggregate. Therefore the easiest way for VANGUARD to appear excellent is to obtain unrealistic stops, fills, partials or same-bar information—not to discover persistence.

### 3. The evidence vector counts the same price movement repeatedly

Slope, momentum and velocity mostly summarize displacement. Efficiency and path quality can be identical. Directional entropy is a deterministic transformation of the fraction of positive returns when calculated from binary signs. Vitality, health, confidence, debt and exit pressure are usually summaries of those same inputs. Multiplying their scores into sizing creates hidden leverage on duplicated evidence.

### 4. PnL-based graduation may select survivors rather than predict continuation

An entry at +4R has survived a favorable path. That does not establish greater future persistence than an otherwise identical market state at +0.4R. Entry-price anchoring can make economically equivalent exposures receive contradictory treatment. Test graduation against fixed slow management and age-only management, and stratify comparisons using information available before graduation.

### 5. A narrow thesis exit plus a wide disaster stop can hide real loss exposure

Expected early exits do not reduce contractual stop risk. A failed process, spread expansion, adverse gap or delayed close can realize the full stop loss or worse. Sizing must fund the broker stop and stress loss, not an assumed −0.2R average loss.

### 6. Profitable positions are not free options

From current equity, a runner at +8R with its stop at +2R can lose 6R plus costs/gap loss. Entry-relative protected profit does not erase current-equity risk. Funding new exposure from that profit may increase correlated tail risk precisely when a trend is crowded. Existing Titan accounting also does not implement the proposed credit.

### 7. More states do not reduce model complexity

Replacing a weighted score with seven named phases introduces transition thresholds, dwell periods and precedence rules. They count as parameters and model choices. The research budget must count the entire design tree, including rejected states and discretionary interpretation of results.

### 8. Campaign ticket structure is not economic diversification

Two EURUSD longs remain one market exposure. Independent local exits can be useful, but must outperform the same total exposure managed as a single position. Under MT5 netting they cannot simply be independent broker positions. Rotation that closes and reopens equivalent exposure changes accounting and costs, not the market opportunity.

### 9. Existing infrastructure is useful but incomplete

Titan already has manifests, feature caching, arbitration, broker sizing, persistent management intents and partial-deal accounting. It lacks a demonstrated end-to-end durable, idempotent campaign lifecycle. The separate `tradebot/` skeleton is not the active `src/` runtime. Adding another VANGUARD runtime would compound this split.

## P. Decisions for the owner

These decisions are needed **before experimental code or production changes**, not to complete this written review:

| Decision | Recommendation | Consequence |
|---|---|---|
| Target runtime | Existing `src/` Titan, as requested | Do not couple this work to migration into `tradebot/` |
| Next scope | Approve only data/execution audit and preregistered offline V0/V1 research | No strategy enablement, no broker writes |
| Universe | Freeze a broker-supported universe by data quality, costs and contract feasibility before examining VANGUARD outcomes | Do not select symbols from favorable historical VANGUARD results |
| Horizon candidates | One slow single-horizon baseline; then H4/H1/M15 versus H1/M15/M5 | M2/M10 require genuine finer data; no synthetic M2 from M5 |
| Account feasibility | Confirm intended account currency, equity envelope, hedging/netting mode and permitted overnight/weekend holdings | Determines legal volumes, swaps, stops and campaign feasibility |
| Risk tolerances | Owner sets maximum equity drawdown, margin/notional limits and permissible tail noninferiority loss | These are utility constraints, not performance-optimized thresholds |
| Research budget | Approve a finite registered experiment tree and reserve fresh data | No failed-hypothesis rescue by repeated holdout inspection |
| Native risk and campaigns | Design retained as conditional interfaces; implementation deferred | Shared risk remains the principal comparison |

## VANGUARD RESEARCH VERDICT

**Core hypothesis:** Coherent but unvalidated; intraday acquisition and lifecycle enhancements face adverse local evidence.

**Strongest feature:** Separating directional evidence, acquisition-specific invalidation and broker protection, with paired exit experiments.

**Most dangerous assumption:** That profitable/protected positions can safely finance more correlated exposure.

**Biggest overfitting risk:** Repeatedly transforming the same price evidence into phases, quality, debt, graduation and sizing multipliers.

**Most important simplification:** Three pure policies inside Titan; four trend states; two optional management horizons; no separate vitality/debt/exit-pressure engines.

**Most promising innovation:** A forward-recorded continuation comparator that measures whether each proposed early exit saves losses or destroys future tail winners on a common observation horizon.

**Infrastructure gap:** Durable command identity and reservation/reconciliation, complete causal multi-horizon data, and a TP-independent management path with one stop owner.

**Research blocker:** No verified VANGUARD edge, no full lifecycle execution parity, and no confirmed untouched dataset with adequate executable-price coverage.

**Recommended V1:** SINGLE_SHOT, SHARED risk, simple normalized trend plus one entry family, broker stop and no-TP monotonic trail; one isolated thesis-exit experiment.

**Explicitly deferred features:** Campaign additions, independent satellites, promotion, native allocation, recycled profit, dynamic covariance sizing, risk competition, adaptive horizons, partial harvesting and learned probabilities.

**Features rejected:** Guaranteed/“free” trend capital, rotation for entry-price cosmetics, duplicate health scores, separate exhaustion debt, age-implies-exhaustion rules, eight multiplicative confidence factors, magic aggressiveness profiles and HYBRID/HARVEST as distinct trading modes.

**Next decision required from owner:** Approve or revise this simplified research scope and its experiment/risk limits. Verdict remains **RESEARCH FIRST / SIMPLIFY**, not implementation GO.
