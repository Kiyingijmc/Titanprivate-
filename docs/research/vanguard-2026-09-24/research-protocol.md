# N–O. Research protocol and conditional implementation roadmap

Status: proposed for owner approval. Numerical gate thresholds below are policy proposals to freeze **before** VANGUARD outcomes are measured, not thresholds derived from a successful backtest. This phase produced documents and inspected existing infrastructure; it did not implement or evaluate VANGUARD.

## N1. Hypotheses and experiment ledger

Primary null: conditional directional exposure does not produce positive net expectancy at the chosen broker universe/horizon after executable costs. Secondary nulls: local acquisition adds no value; evidence exits add no value versus simple exits; graduation adds no value versus a fixed slow horizon; scaling adds no value versus equal-budget aggregate exposure; native allocation adds no value versus shared risk at comparable exposure.

Before execution, record hypothesis ID, parent experiment, data hashes/time bounds/source clock/revision policy, eligibility universe and reasons, algorithm and config hashes, numerical choices, primary metric, effect size of practical interest, uncertainty method, family multiplicity rule, cost/stress scenarios, exclusion rules, stopping rule and allowed outcomes. Count prior related Titan MTF, Gyroscope and exit work as known development evidence; do not call the reused periods untouched.

All exploratory attempts, manual threshold changes, rejected settings, horizon choices, and interaction tests remain in the ledger. Any post-result rule change is a new hypothesis requiring genuinely fresh evidence, not a rerun under the original preregistration. An infrastructure correction requires a documented impact review and corrected rerun, with old results retained and any compromised holdout reclassified.

## N2. Data and execution gate comes first

Freeze a point-in-time universe based on broker availability, liquidity/cost feasibility, legal quantity and adequate synchronized history. Do not select winners by prior strategy returns. Include negative/unsizeable instruments in the feasibility report rather than silently removing them. Preserve delisting/contract changes, symbols and broker suffixes, session calendars and historical clock conventions. Specify whether observations are as originally available or corrected historical bars.

Audit at least:

- Native tick/quote, M1/M5/H1 availability and what is missing. M2 requires genuine finer observations.
- Closed-bar cutoff, duplicate/out-of-order/revision handling, source counts, market holidays and gaps.
- Spread by time, volatility and symbol; commission/account currency; swaps/financing for multi-day runners; tick value/size and legal volume history or disclosed approximations.
- Broker timestamps versus UTC/NY availability. No fixed clock string for a session-sensitive strategy.
- Tail bars and open trades at dataset end, missing observations, stale quotes, and pending orders at split boundaries.

Do not query a live execution venue as part of an offline experiment. Existing HTTP read-only history tools and lake freezing can be used after scope approval; no trading route is required.

**Gate E0:** complete causal state replay and deterministic command sequence for the tested scope; all critical adverse execution scenarios pass; documented sufficient data coverage. A missing quote history may permit exploratory research with cost/path sensitivities, but cannot support an execution-validated GO.

Model entries after decision availability and realistic latency. Existing stops act before new software decisions. Broker-rejected/late modifications retain the old stop. Count entry partial fills, canceled-yet-filled orders, ambiguous sends, legal volume constraints and reservation overlap. Do not treat intended stop profit as banked.

OHLC and OLHC paths are **sensitivity scenarios, not upper/lower bounds** on all possible tick paths. Require signal-bar exclusion and no pre-fill extrema. If the sign of incremental benefit depends on the assumed path, verdict is execution-sensitive/insufficient, not choose the favorable path. Seek real quote/deal reconciliation before promotion.

## N3. Baseline matrix and staged ablations

Run a deliberately limited set, not a full Cartesian product. Freeze the exit comparator for the direction screen, then isolate exits with matched entries. Report every scheduled arm, including stopped/insufficient results.

| Stage | Question / arms | Advancement condition |
|---|---|---|
| V0a direction existence | Cash/placebo; existing MA slope; stable MA trend; normalized momentum; simple close breakout; existing Gyroscope reference | A net viable slow directional baseline, with all execution/cost caveats resolved for scope |
| V0b horizon/acquisition | Single slow horizon; simple M15 trend + M5 entry; H1/M15/M5 versus H4/H1/M15; families separately | Incremental benefit or demonstrable cost/participation improvement; otherwise retain simplest baseline |
| V1 open trend | Identical entries with hard ATR SL + fixed 2R TP; hard SL + structural reversal; hard SL + fixed ATR trail/no TP | Establish payoff/cost tradeoff without added state scores |
| V2 thesis exit | V1 + one PnL-independent contradiction rule; controls: tighter fixed SL/trail and simple time exit | Paired incremental improvement or approved tail-risk improvement without unacceptable right-tail loss |
| V3 graduation | Fixed local, fixed tactical, age-only transition, evidence transition | Evidence transition beats fixed slow and age-only alternatives; not merely fewer exits |
| V4 acquisition refinement | One efficiency/pullback or contraction feature added to surviving family | Conditional incremental value after turnover/cost effects |
| V5 participation | Bounded REENTRY, then one added tranche; aggregate versus independent management | Portfolio/campaign gain at matched capital budget, not merely greater leverage |
| V6 native risk | Shared, fixed bounded allocation, then one discrete overlay | Better owner utility/tail outcome under matched exposure; global invariants maintained |
| V7 optional exits | Deterioration-aware giveback/partial or dynamic trail, each independently | Survives multiplicity and right-tail gate; no automatic admission |

This reorders the brainstorm: prove the executable baseline and isolate exit removal before adaptive features. Debt and an elaborate “full VANGUARD” are not mandatory destination stages. If a simple no-TP trend strategy wins, that is the final strategy.

Initial numerical choices: horizon span 24, trend activation 0.5 normalized units, dwell two closes, 2 ATR initial stop, 2.5 ATR trail. Thesis experiment uses span 8 and −0.5 adverse threshold with the same dwell. These are **unvalidated frozen candidates**, not a recommendation to trade them. A small prespecified sensitivity set changes one choice at a time around the center; it tests broad behavior, not selects a new optimum. Fixed-R target and tighter-stop values also must be registered before results.

## N4. Paired designs that answer the right question

**Exit-only cohort:** acquire identical quantities at identical executable entries. Each exit arm follows the same subsequent observed path with its own policy. First measure paired trade PnL differences and counterfactual continuation. Then run a separate deployment simulation with each arm's own occupancy, budget release and future admissions. Mixing these answers obscures whether a benefit comes from exits or more trading.

**Entry cohort:** use common causally defined trend episodes. Record enter/skip/expiry and missed exposure for each family. A pullback strategy with fewer high-quality fills must still account for the largest trends it never acquired. Include cash while waiting; do not compare only its favorable filled subset to all baseline trades.

**Same-market additions:** fixed initial capital, identical maximum campaign allocation and stress envelope. Compare no-add, a larger initial allocation within that same envelope, scheduled scaling, signal-based aggregate add and independent satellite. Report both incremental return and incremental downside/margin. Distinct tickets do not create independent observations.

**Native risk:** compare at actual unscaled account outcomes and at a development-fixed matched target volatility/exposure. Do not rescale using OOS realized volatility to manufacture equal-risk performance. Report the opportunity cost of drawdown halts and rebound misses.

## N5. Common-horizon MFE and false-invalidation measurement

Ordinary lifetime MFE is endogenous to the exit: closing early shortens the measured path. It cannot alone show that early exits preserved winners.

Define before testing a reference continuation policy and observation horizon per acquisition. Observe the counterfactual path until the reference exit or a fixed maximum horizon, whichever definition is registered. The horizon must not be chosen from realized future success. Continue recording after the experimental exit without placing hypothetical extra real trades.

For each matched acquisition, record experimental realized net PnL, reference realized net PnL, post-decision available path and terminal/censored flag. Early-exit saving is reference loss avoided net of exit costs; false invalidation includes exits followed by materially positive reference continuation. Report the **whole paired difference**, not only saved losses. The “winner that would have reached 8R” label is for evaluation only and never enters live state.

Bucket common-horizon favorable excursion into <1R, 1–2R, 2–4R, 4–8R and 8R+. Report counts, realized PnL, retained quantity, tail contribution and uncertainty per bucket. Also show position-lifetime MFE capture as a descriptive statistic, clearly distinct. Ratios near zero MFE are undefined/unstable; do not silently divide by a tiny epsilon. Capture ratios may be negative and are not optimized alone.

End-of-data trades are marked to executable liquidation value for equity reporting, with separate closed-only and censored outcome diagnostics. Do not drop open winners/losers or classify them as zero. Campaign return uses campaign monetary PnL divided by a fixed declared numeraire; summing differently sized ticket Rs is not campaign performance.

## N6. Required metrics

| Domain | Measures |
|---|---|
| Return | Net expectancy/R with immutable denominator, monetary and daily-equity returns, PF, total return/CAGR only with sufficient duration, Sharpe/Sortino with stated sampling/serial dependence, calendar-year/quarter outcomes |
| Distribution | Skew of trade and daily returns separately, median trade, 90/95/99th percentile winners with counts/intervals, largest losses, expected shortfall, drawdown/depth/duration, top-trend contribution |
| Entry | Fill/expiry/rejection/missed-trend rates, executable cost/R, MAE/MFE, time to causal confirmation, preregistered false acquisition definition |
| Exit | Paired net savings, false invalidation, common-horizon tail truncation, giveback, MFE capture by bucket, time in market, turnover, stop/exit reason attribution |
| Campaign | Initial/accretion trade expectancy, incremental added return, fixed-numeraire campaign R, peak entry/equity/stress risk, entries per trend, cumulative loss per failed trend, pending/unknown commitments |
| Risk | Requested/approved/deployed RU and monetary equivalent, peak open RU, confirmed released/credited amounts, gross issuance rate, factor/notional/margin concentration, drawdown-state exposure and recovery opportunity cost |
| Execution | Quote/spread/slippage distributions, rejected/late modifies, partials, legal-size failures, command/confirmation latency, gap loss, cancellation races, unknown-state duration |
| Operations | Bar/quote coverage, stale/revised/missed events, parity divergences, recovery time, critical persistence failures, decision explainability completeness |

PF and win rate are descriptive, not primary selection targets. The 99th percentile is particularly uncertain with few winners. Report insufficient tail evidence rather than turning a handful of extreme trends into a confident estimate.

## N7. Validation and statistical gates

Use development → validation → sealed chronological test → prospective shadow. Reserve contiguous recent data not previously inspected for VANGUARD selection, or collect a new prospective cohort if repository history is already heavily used. A calendar split alone does not make previously researched data independent.

Warm indicators causally with pre-test history, without training on test outcomes. Carry live-like positions/state across boundaries for the primary deployment test or separately register a flat-start evaluation; do not alternate opportunistically. Purge training labels/outcome intervals overlapping test episodes. Embargo when training samples after a test block contain dependent features/labels. Long and variable trend holdings make a fixed arbitrary embargo unsafe; derive it from the registered label/support interval. Pure chronological tests still need careful boundary state and outcome treatment.

Uncertainty: synchronized moving/stationary time-block bootstrap of daily portfolio returns and campaign-level paired outcomes, with block choices fixed on development information. Preserve cross-symbol co-movement. Never IID-bootstrap satellites as independent trades. Use leave-one-symbol/year/large-trend-out sensitivity; loss of profitability without the biggest outlier is descriptive concentration evidence, not automatically a reason to reject a legitimate skew strategy.

Apply multiplicity adjustment (for example Holm within the registered finite family) to primary incremental claims. Record raw and adjusted intervals. DSR/PBO are secondary diagnostics where their assumptions and trial matrix are available; no manufactured PBO from one chosen strategy. Effective sample size and minimum detectable economic effect determine whether the test is powered. No universal “150 trades proves it” rule.

Proposed gates to ratify before outcomes:

| Gate | Rule | Failure disposition |
|---|---|---|
| G0 correctness | No critical leakage, nondeterminism, exposure-accounting or protection invariant violation in tested scope | STOP; engineering correction, no economic verdict |
| G1 feasibility | Tradeable legal size and recorded costs; cost/R diagnostics acceptable under owner-approved envelope; no dependency on unavailable data | NO-GO for that habitat or insufficient data |
| G2 baseline economics | Positive net OOS mean portfolio/trade economics with a prespecified one-sided 95% block-based lower confidence bound above zero for the primary claim | NO-GO or INSUFFICIENT EVIDENCE; no retune |
| G3 incremental component | Multiplicity-adjusted paired lower bound for incremental objective above zero, or preregistered tail-risk benefit with return noninferiority | Delete component if not supported; baseline can survive |
| G4 execution/cost stress | Net expectancy nonnegative under registered 1.5× all-in variable-cost scenario; report 2×, delayed exits, failed modifies and adverse gaps without cherry-picking | Cost-sensitive NO-GO if primary stress fails |
| G5 right-tail preservation | For exits/graduation, paired common-horizon upper-tail participation/return is noninferior within owner-set tolerance; insufficient bucket N remains unresolved | No adaptive exit promotion |
| G6 capital survival | Drawdown/stress/margin outcomes stay within owner-set limits under simultaneous-factor, gap and outage scenarios | Risk NO-GO regardless of Sharpe |
| G7 portability/stability | Registered neighborhood does not depend on a narrow isolated optimum; report symbol/year/phase dispersion and full-calendar outcomes | Simplify or reject, not select favorable subperiod |
| G8 prospective operation | Frozen shadow cohort has verified coverage, reproducible decisions and broker-reconciled execution tests for relevant capabilities | No demo/live promotion while unresolved |

Positive economics are required for a trading recommendation. A risk policy may be retained for an explicitly approved safety benefit while lowering expected return, but must not be described as added alpha. Tail noninferiority and risk tolerance values remain owner decisions, so the gate contract is not ready to execute blindly.

## N8. Stress and falsification program

Deterministic synthetic paths: zero-drift random walk, persistent drift, drift with deep pullbacks, alternating chop, sudden reversal, jump/gap, parabolic rise/crash, slow grind, spread shock and synchronized factor collapse. Synthetic success is a correctness/property test, not evidence of market alpha. On zero-predictability processes, positive skew must not be mistaken for positive expectancy after costs.

Replay faults: duplicate/reordered bars and fills, future/forming HTF bars, delayed quotes, stale specs, crash before/after persistence/send/ack/fill, lost ack, partial fills, stop rejection, manual close, canceled order late fill, simultaneous anchor exit/satellite fill, account netting, illegal partial remainder and exhausted reservation capacity.

Cost stress: state-dependent spread and slippage, commissions, overnight/triple swap where applicable, stressed conversion, one or more bars of software delay, broker freeze/stop constraints and different minimum volumes. Test actual intended account equity; a continuous-volume backtest may be impossible to trade on a small account.

Attribution tests: local contradiction versus tightened stop; graduation versus fixed slow horizon; efficiency versus slope alone; compression versus breakout; fatigue versus fixed attempt limit; native risk versus simple exposure reduction; satellites versus aggregate equal-budget exposure. No interaction survives solely because the full bundle is profitable.

## N9. Innovations worth investigating

### Innovation 1: continuation comparator for every management decision

- **Problem:** saved early losses are visible; the lost future right tail is easily hidden.
- **Hypothesis:** a fixed continuation comparator exposes whether informational exits improve conditional future exposure value.
- **Mechanism:** at each eligible exit decision, record the immutable state and shadow continuation under the preregistered reference policy/common horizon.
- **Expected advantage:** directly falsifies exit stories and avoids exit-dependent MFE bias; also works prospectively.
- **Failure mode:** wrong counterfactual execution costs or outcome horizon exaggerate savings.
- **Simpler competitor:** same-entry paired realized PnL alone.
- **Test:** reconcile comparator on known quote paths; compare loss savings and missed 4–8R/8R+ outcomes out of sample.
- **Decision criterion:** retain the measurement mechanism if it reproduces and materially explains paired results; retain the exit only if G3/G5 pass.

### Innovation 2: dual loss ledger with stressed stop protection

- **Problem:** entry-positive stops hide large current-equity giveback and gap exposure.
- **Hypothesis:** entry-loss plus equity-loss/stress limits prevent unsafe late additions more effectively than “locked profit” credit.
- **Mechanism:** maintain separate immutable-entry attribution and current-equity/scenario exposure, including pending and unknown orders.
- **Expected advantage:** makes campaign financing understandable and prevents accounting-only risk release.
- **Failure mode:** overly conservative scenarios suppress all useful additions; weak scenarios miss common gaps.
- **Simpler competitor:** fixed gross campaign allocation with zero recycling.
- **Test:** common trend reversal/gap scenarios and equal-budget OOS addition arms.
- **Decision criterion:** no invariant failures; any added complexity must enable useful exposure within owner loss tolerances better than the fixed cap.

### Innovation 3: executable-cost hysteresis

- **Problem:** direction flips smaller than transaction costs create churn.
- **Hypothesis:** a no-action region scaled to observable costs reduces uneconomic switching without requiring multiple health scores.
- **Mechanism:** one bounded entry/exit separation based on current cost relative to lagged volatility, with no fitted multi-factor multiplier.
- **Expected advantage:** adapts to broker habitat and is easier to explain than vitality/debt.
- **Failure mode:** price-based exits occur too late during sudden reversal or spread spikes; costs cannot veto mandatory safety exits.
- **Simpler competitor:** fixed threshold and two-bar dwell.
- **Test:** paired turnover, net return and missed-tail analysis across cost states, all point-in-time.
- **Decision criterion:** adjusted incremental economics and capital/tail gates pass; otherwise retain fixed hysteresis.

### Innovation 4: commitment batch budget

- **Problem:** correlated opportunities arrive together while a sequential loop makes arbitrary first-arrival allocations.
- **Hypothesis:** a deterministic cap on gross commitments per closed-bar batch gives stable exposure without an opaque ranker.
- **Mechanism:** gather only simultaneously available eligible candidates at a declared watermark, order by fixed policy/cost eligibility, reserve against shared cluster budgets atomically.
- **Expected advantage:** eliminates arrival-order accidents and hidden net-risk churn.
- **Failure mode:** waiting for a batch delays entries or stale markets hold up the watermark.
- **Simpler competitor:** existing sequential ordering with conservative gross cap.
- **Test:** reorder identical simultaneous event sets and compare decisions; measure latency opportunity cost.
- **Decision criterion:** deterministic capacity compliance plus no unacceptable execution degradation. Defer if current controller scope cannot justify the added batching abstraction.

These are proposed mechanisms, not claims of academic novelty. Innovations 1 and 2 are primarily better measurement/safety, not new alpha.

## O. Roadmap — only after research/design approval

1. **Ratify the research contract.** Owner resolves runtime, universe, account constraints, tail/risk tolerances, finite experiment tree and untouched-data policy. No production change implied.
2. **Offline feasibility/correctness work.** Canonical bars/availability audit, executable cost data, independent baseline ledger, shared policy replay skeleton. Changes stay in approved research scope. Produce a reproducible run card before running performance gates.
3. **V0/V1 one-pass evaluation.** Stop if no feasible net baseline. Publish all results and unknowns. Do not build campaigns to rescue a failed baseline.
4. **Isolated exit/graduation experiments.** Only supported components advance. Collect prospective shadow decisions with complete coverage and immutable versions.
5. **Separately reviewed live integration prerequisites.** TP-independent management profile; durable entry identities and reservations; actual fill/partial handling; closed-bar routing and event clock; profile persistence; single stop ownership. Preserve existing strategies with regression tests. No automatic enablement.
6. **Broker demo capability tests.** Verify accounting mode, fills, stops, rejected modifies, crash/reconnect, target-volume retries and reconciliation against actual broker records. Requires explicit deployment/execution authorization.
7. **Campaign experiment if still justified.** At most one additional tranche initially, zero protected-profit credit, fixed lifetime attempt/loss caps. Compare independent versus aggregate management before introducing roles.
8. **Native risk last.** Explicit budget adapter and one bounded overlay, always under global risk. Complex covariance/competition/recycling only via new evidence and authorization.

Each stage ends with GO-for-next-research-stage, NO-GO, SIMPLIFY or INSUFFICIENT EVIDENCE. None is automatically GO-live.

## Verification performed in Phase 1

Read-only source/config/doc audit and current web research; source revision recorded in the package. Ran:

```text
.venv/bin/python -m unittest
  tests.unit.test_strategy_timeframe
  tests.unit.test_kernel_replay
  tests.unit.test_management_confirmation
  tests.unit.test_partial_lifecycle
  tests.unit.test_structure_management
  tests.unit.test_risk_manager_exposure_cap
  tests.unit.test_arbiter
  tests.unit.test_registry_guards
  tests.unit.test_candle_time_epoch
```

Result: **136 tests passed in 279.018 seconds.** Python emitted a ResourceWarning for an unclosed event loop during the run. This was not investigated or changed as part of the documentation-only assignment. The checks establish the existing covered behavior, not absence of all bugs or readiness for VANGUARD. The full unit suite, live broker checks and VANGUARD performance experiments were not run.
