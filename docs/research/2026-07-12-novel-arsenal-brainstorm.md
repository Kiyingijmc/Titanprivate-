# Novel Arsenal Research — Strategy Concepts Beyond SMC/ICT

**Date:** 2026-07-12
**Status:** Brainstorm / research deliverable (no code, no gate runs yet)
**Scope:** Greenfield strategy concepts from non-trading disciplines. Explicitly excludes ICT/SMC/Wyckoff/order-block/FVG/liquidity concepts and any renaming thereof.

---

## 0. Ground rules and honest framing

Three constraints from this repo's own research history bind everything below:

1. **The cost bar is brutal.** Our canonical 3-yr OTE study was NO-GO everywhere (−0.158R pooled, gross-negative). The only validated edge (SilverBullet H1, +0.19R/trade net) needed H1 granularity, wide ATR stops, and low frequency to survive FBS retail spreads. **Any new concept that fires many small-target trades intraday is presumptively dead on arrival.** Concepts below are biased toward H1+ holding periods, low trade frequency, or explicit cost screens.
2. **Data reality:** OHLC bars (M1–D1) + MT5 tick volume + spread via the bridge. No Level 2, no options, no real volume, no sentiment feeds. Every concept below runs on that.
3. **Intellectual honesty about "novelty":** most discipline-inspired ideas map onto known quant families (momentum, mean reversion, vol clustering, regime switching). Where that's true, it is said explicitly. The value of the scientific framing is not mystique — it's that it supplies *principled estimators, decision rules with controlled error rates, and self-diagnostics* instead of ad-hoc indicator thresholds. A strategy is admitted only if its core statistic is measurable from our data and its decision rule is deterministic.

**Shared validation protocol (referenced as "TVP" below):** every candidate goes through the same pipeline the OTE study used — (a) 3-yr M5/H1 history export for the 9 live symbols via the HTTP bridge; (b) event-study cost screen first (does the gross move even clear 2× spread?); (c) pre-registered gate written *before* the backtest (net expectancy in R after modeled FBS spread+slippage, minimum trade count, per-symbol consistency, IS/OOS split ~70/30 chronological); (d) parameter sensitivity: every threshold ±30% must not flip the sign of expectancy; (e) Monte Carlo trade-order bootstrap for drawdown envelope; (f) NO-GO is a valid, recordable outcome. Strategy-specific validation notes below are *additions* to TVP.

---

## 1. GYROSCOPE — Kalman state-space drift estimator with SPRT decision gate

### 1. Name
**Gyroscope** (aerospace attitude estimation: estimator + decision rule + integrity monitor).

### 2. Scientific inspiration
Aerospace/EE control systems: Kalman filtering (sensor fusion, Apollo guidance), plus Wald's Sequential Probability Ratio Test (WWII munitions QC) as the decision layer, plus flight-control integrity monitoring (innovation whiteness / NIS tests) as the supervisor.

### 3. Core principle
Price is a noisy sensor reading of a latent state. Model the state vector **x = [level, velocity]** (log-price and its drift) evolving under process noise; each closed H1 bar is a measurement. The Kalman filter yields, at every bar, an optimal estimate of *velocity* (local drift) **and its variance** — i.e., not just "trend" but "trend with an error bar." A moving average gives you a level; a Kalman filter gives you a level, a slope, and a covariance matrix telling you how much to believe each.

The decision layer is Wald's SPRT: accumulate the log-likelihood ratio between H₁ ("drift = +δ") and H₀ ("drift = 0") bar by bar; enter only when the cumulative evidence crosses a boundary set by chosen error rates (α = false-entry rate, β = miss rate). SPRT is *provably* the fastest sequential test for given error rates — it is the mathematically optimal answer to "how many bars of confirmation do I need?", replacing the arbitrary "wait for 2 closes above the MA."

### 4. Trading hypothesis
FX/metals exhibit episodic persistent drift at H1–H4 horizons (time-series momentum). The inefficiency is not the drift itself (well documented, partially decayed) but the *timing of participation*: most trend systems enter late (long lookbacks) or churn (short lookbacks). A filter that separates drift from noise optimally, with an entry rule that has an explicit false-positive budget, participates in real drift episodes earlier and stands down faster in chop — the edge is in the ratio of participation to churn, which is exactly what kills retail trend systems via costs.

### 5. Observable variables
- H1 log-close (measurement)
- Kalman state: level, velocity `v̂`, covariance `P`
- Innovation `ε_t` (measurement minus prediction) and innovation variance `S_t`
- Normalized Innovation Squared `NIS = ε²/S` (integrity metric)
- ATR / realized vol (for δ scaling and stops)
- Spread (cost screen at signal time)

### 6. State machine
```
IDLE → (filter warmed, NIS χ² test passing) → OBSERVATION
OBSERVATION → (SPRT statistic Λ drifting toward a boundary) → SIGNAL FORMATION
SIGNAL FORMATION → (Λ ≥ log((1−β)/α)) → VALIDATION
VALIDATION → (spread ≤ cost cap, vol within band, no news lock) → ENTRY
ENTRY → MANAGEMENT (existing trade_manager: BE/partials/ratchet)
MANAGEMENT → (reverse-SPRT triggers OR stop/TP/time-stop) → EXIT
EXIT → RECOVERY (Λ reset to 0; filter keeps running; re-entry lockout n bars)
Any state → SUSPENDED if NIS test fails (model no longer describes market) → re-warm.
```

### 7. Entry logic
Long when cumulative LLR for "drift = +δ·σ" vs "drift = 0" crosses the upper Wald boundary `A = ln((1−β)/α)` (symmetric short). δ is vol-scaled (e.g., 0.15·ATR per bar) so the test is asset-agnostic. Entry at next bar open, market order, subject to validation checks.

### 8. Exit logic
Deterministic, first-hit: (a) reverse SPRT (evidence for opposite drift crosses its own boundary) → close; (b) hard SL at k·√(innovation variance) — a stop derived from the filter's own uncertainty, not an arbitrary ATR multiple; (c) existing ratchet/runner management for profit-taking; (d) time stop at N bars if Λ has mean-reverted to ~0 (drift episode over, position is pure cost).

### 9. Risk model
Position sizing via existing `RiskManager.calculate_lot_size` (broker-spec driven, fixed fractional R). Stop = k·√S (filter uncertainty). Profit protection = existing BE-at-38.2%/partials pipeline. No scaling-in (SPRT gives one decision, not a ladder). Capital preservation: SUSPENDED state (integrity monitor) flattens new entries when the model is invalidated — a fail-safe borrowed directly from avionics.

### 10. Failure modes
- **Regime of pure chop:** SPRT boundaries rarely crossed → few trades (safe failure, costs nothing).
- **Vol regime jump:** Q/R miscalibrated → filter lags or overreacts. *Detected by* the NIS whiteness test (innovations should be χ²-distributed; sustained violation = suspend).
- **Slow bleed:** many boundary crossings that immediately reverse (whipsaw at boundary). *Detected by* rolling win-rate vs α budget — realized false-entry rate exceeding ~2α is a designed kill-switch.

### 11. Strengths
Principled early trend entry; explicit, tunable error-rate budget; self-diagnosing (NIS); O(1) per bar; asset-agnostic; every decision explainable ("cumulative evidence crossed the 95% boundary at bar t").

### 12. Weaknesses
Time-series momentum in FX majors has decayed since ~2010 — the *family* has headwinds even if the implementation is superior. Two-layer math (Kalman + SPRT) is harder to eyeball-debug than an MA cross. Boundary behavior near A is sensitive to the δ choice.

### 13. Market compatibility
Trending: excellent. Ranging: flat/near-flat (SPRT stays inside boundaries — this is the design win). High vol: good if Q adapts, guarded by NIS suspend. Low vol: few signals. News: velocity spikes can fake drift — needs the standard news lockout. Session transitions: neutral (H1 granularity blurs them).

### 14. Automation complexity: **5/10**
### 15. Computational cost
Trivial: 2×2 matrix ops per bar per symbol. Microseconds; negligible memory.

### 16. Data requirements
OHLC only (H1 primary). Spread at decision time.

### 17. Validation plan
TVP, plus: compare against a naive MA-slope baseline on identical data — Gyroscope must beat the *baseline*, not just zero, to justify its complexity; sweep (α, β, δ) on IS only; verify realized false-entry rate ≈ α on OOS (a distributional check no MA system can even offer).

---

## 2. AFTERSHOCK — Hawkes self-exciting volatility cascade trader

### 1. Name
**Aftershock** (seismology: Omori's law — big earthquakes raise the probability of subsequent quakes, decaying as a power law).

### 2. Scientific inspiration
Seismology + point-process theory. Hawkes processes (self-exciting counting processes) model events whose occurrence raises the short-term intensity of further events. Epps/Omori-style decay is one of the best-replicated facts in market microstructure: volatility events cluster.

### 3. Core principle
Define an "event" as an H1 bar whose true range exceeds q·(rolling median TR) (e.g., q≈2.5). Maintain a Hawkes intensity `λ(t) = μ + Σ α·exp(−β(t−tᵢ))` over recent events. λ is a real-time, decaying "market excitation" gauge: after a shock, elevated λ says more large moves are statistically due; as λ decays toward baseline μ, the episode is exhausting.

### 4. Trading hypothesis
Volatility clustering is a *fact*; directionality during clusters is the exploitable part: (a) **continuation leg** — the first large-range event with a directional close, arriving when λ was near baseline (fresh shock, not exhaustion), tends to be followed by same-direction range expansion (slow diffusion of information/positioning); (b) **exhaustion leg** — events arriving when λ is already very high (late in the cascade) mark over-extension; fading them targets the post-cascade compression. Costs are respected because entries only occur when ranges (and thus targets) are multiples of normal — target size scales with the event, so spread as a fraction of target collapses exactly when the strategy is active.

### 5. Observable variables
True range per bar, rolling median TR, event indicator, event direction (close vs open), Hawkes intensity λ (μ, α, β fit rolling by MLE or fixed from IS), ATR, spread.

### 6. State machine
```
IDLE (λ ≈ μ) → SHOCK DETECTED (fresh event, λ jump from baseline) → OBSERVATION (1–2 bars)
 → SIGNAL: CONTINUATION (directional follow-through bar) → VALIDATION (cost screen) → ENTRY
IDLE→…→ CASCADE (λ > λ_hi, multiple stacked events) → SIGNAL: EXHAUSTION (event against
 prevailing cascade direction OR λ peak-and-decay) → ENTRY (fade)
MANAGEMENT → EXIT (λ decay below λ_lo = episode over → flatten; plus stops/targets)
RECOVERY: no re-entry until λ returns near μ (one trade per cascade).
```

### 7. Entry logic
Continuation: fresh event (λ jumped from < λ_lo), event bar closes in its direction beyond its midpoint, next bar confirms (doesn't fully retrace) → enter with the event. Exhaustion: λ > λ_hi (top decile of IS λ distribution) and current event's close reverses off its extreme → fade toward the pre-cascade level. Both: skip if spread > x% of the event bar's range.

### 8. Exit logic
SL beyond the event bar's opposite extreme (structure of the shock itself). TP: continuation targets 1× event range projected; exhaustion targets 50% retrace of the cascade. Time/state exit: λ decays below λ_lo → episode over → flatten regardless of P&L. First-hit deterministic.

### 9. Risk model
Fixed fractional R via RiskManager; stop distance is event-scaled (large stops, large targets — few, chunky trades). One position per symbol per cascade. Optional portfolio brake: if λ is elevated on >half the book simultaneously (systemic shock), halve size — correlated cascades are one event, not nine.

### 10. Failure modes
- Slow grinding trends produce no events → inactive (safe).
- Parameter drift in (μ, α, β) across regimes → λ thresholds miscalibrated. *Detect:* rolling KS test of inter-event times against the fitted model.
- News spikes with instant full reversal (flash events) fake continuation signals → mitigate with the confirm bar + news lockout.
- Exhaustion leg is fading strength — the classically dangerous side; gate it harder (λ_hi very strict) or ship continuation-only first.

### 11. Strengths
Active precisely when ranges dwarf costs (structurally cost-robust — the property OTE lacked). Grounded in the single most-replicated stylized fact in finance. Naturally infrequent. Clear, physical narrative per trade.

### 12. Weaknesses
Few trades → slow statistical validation. MLE fitting of Hawkes on sparse events is noisy (may need fixed decay β from IS). Continuation vs exhaustion legs can conflict without the λ-band separation being cleanly tuned.

### 13. Market compatibility
Volatile/news-driven: excellent (its habitat). Trending: continuation leg fine. Ranging/low-vol: dormant. Session transitions: London/NY opens are natural event generators — fine, but verify the edge isn't *only* a session effect (control in validation).

### 14. Automation complexity: **6/10**
### 15. Computational cost
Low: exponential decay updates are O(events); rolling MLE refit weekly is a scipy call.

### 16. Data requirements
OHLC (H1 primary, M5 acceptable for event timing), spread.

### 17. Validation plan
TVP, plus: event-study first (distribution of forward returns conditioned on λ-band and event direction — if the conditional histograms don't separate, stop before backtesting); test continuation and exhaustion legs *separately* with separate gates; session-of-day control (re-run with session dummies to prove λ adds information beyond "it's the London open").

---

## 3. RUBICON — Bayesian online change-point regime trader

### 1. Name
**Rubicon** (the river you cross when the old regime is over).

### 2. Scientific inspiration
Statistics: Bayesian Online Change-Point Detection (Adams & MacKay 2007), from fields like DNA segmentation and industrial process monitoring — detecting, in real time and with a posterior probability, that the generating distribution of a stream has changed.

### 3. Core principle
Model H1 returns as drawn from a distribution (Normal with unknown μ, σ) that occasionally *resets*. BOCPD maintains, at every bar, a full posterior over "run length" — how many bars since the last change-point. A collapse of the run-length posterior toward zero is a probabilistic statement: "the market that existed until now no longer exists." Old-regime statistics are then discarded *immediately* instead of being averaged away over a lookback window — the structural flaw of every rolling-window indicator.

### 4. Trading hypothesis
Regime breaks (vol shifts, drift births/deaths) are recognized late by rolling-window methods because stale data pollutes the estimate. The exploitable inefficiency: the first bars *after* a genuine change-point carry abnormal drift persistence (positioning adjusts over hours, not instantly). Trading the direction of the post-break drift, sized to the *new* regime's vol, front-runs the crowd of lagging-lookback systems.

### 5. Observable variables
H1 log returns; run-length posterior P(r_t); change-point probability P(r_t < k); posterior predictive μ̂, σ̂ of the *current* run; ATR; spread.

### 6. State machine
```
STABLE (long run length) → BREAK DETECTED (P(r<3) > p_crit) → CHARACTERIZATION
 (2–3 bars: estimate new-regime μ̂, σ̂ from the young run) → SIGNAL (|μ̂| significant vs σ̂)
 → VALIDATION (cost screen, vol sanity) → ENTRY → MANAGEMENT → EXIT
 → COOLDOWN (no re-entry until run length matures or next break)
```

### 7. Entry logic
When change-point probability spikes above p_crit and the young run's estimated drift is significant (|μ̂|·√n / σ̂ > z), enter in the drift direction. No trade on pure vol-shift breaks with no drift (characterization stage filters these — that's most of them, and skipping them is the point).

### 8. Exit logic
SL at k·σ̂ (new-regime vol). TP/trail via existing management pipeline. Structural exit: the *next* detected change-point flattens the position unconditionally — the thesis ("this regime") has expired by definition. Time stop at N bars.

### 9. Risk model
Fixed fractional R; stops from new-regime σ̂ (so sizing self-adapts to the break's violence). Half size on the first trade after a vol-*expansion* break (widest estimation error). Next-break-flattens rule is the capital preserver.

### 10. Failure modes
- False change-points in heavy-tailed noise (BOCPD with Normal likelihood over-fires on fat tails) → use Student-t likelihood; monitor false-break rate.
- Drift estimate from 2–3 bars is noisy → the z-gate keeps most breaks untraded; accept low frequency.
- Slow regime *drift* (no sharp break) is invisible to it → by design; other arsenal members cover that.

### 11. Strengths
Attacks the one thing every rolling-window system does badly. Full posterior = principled confidence, not a binary flag. Also valuable as *infrastructure*: the run-length posterior is a regime clock any other strategy (SilverBullet included) can consume as a filter.

### 12. Weaknesses
Very low trade frequency (genuine drift-bearing breaks are rare) → slow to validate, slow to earn. Hazard-rate prior and likelihood choice are consequential and not obvious. Post-break drift persistence at H1 in FX is a hypothesis, not a documented fact — could simply be false.

### 13. Market compatibility
Best at regime turns (post-news repricing, trend births, vol crushes). Dormant in long stable regimes (safe). Vulnerable during whipsaw news days (multiple false breaks) → news lockout + t-likelihood.

### 14. Automation complexity: **7/10**
### 15. Computational cost
Moderate: run-length posterior is O(t) naive, O(1) amortized with pruning (keep top-K run lengths). Fine at H1.

### 16. Data requirements
OHLC (H1). Spread.

### 17. Validation plan
TVP, plus: *first* a pure detection study — do detected break points visually and statistically align with known regime shifts in our 3-yr data (label-free sanity)? Then event study of post-break forward returns conditioned on the drift z-score. Only then a backtest. If the event study shows no post-break persistence, record NO-GO at stage (b) and keep BOCPD as a regime-filter library instead.

---

## 4. RAINFLOW — fatigue-accumulation compression/breakout model

### 1. Name
**Rainflow** (rainflow cycle counting — the standard algorithm for metal fatigue analysis in mechanical engineering).

### 2. Scientific inspiration
Mechanical engineering: materials under repeated stress cycles accumulate fatigue damage (Miner's rule: damage = Σ cycles/cycles-to-failure at each amplitude) and fail suddenly, not gradually. Rainflow counting decomposes an irregular load history into discrete stress cycles.

### 3. Core principle
Run the *actual rainflow algorithm* on the H1 price series within a detected consolidation: extract oscillation cycles and their amplitudes. Compute a fatigue index: many cycles at *decreasing* amplitude against a static boundary = accumulating "damage" to that boundary (resting interest at the boundary is being consumed / the coil is tightening). Unlike a Bollinger squeeze (a point-in-time vol reading), fatigue is a *path integral* — it distinguishes "quiet because nothing is happening" from "quiet because a compressed spring has cycled 9 times with shrinking amplitude."

Honesty note: the *family* is volatility-compression breakout (known). The novel content is the path-dependent fatigue statistic replacing the memoryless vol reading, plus a directional bias from cycle asymmetry (which boundary is being hit harder/more often).

### 4. Trading hypothesis
Ranges that *cycle* with contracting amplitude break out more violently and more predictably than ranges identified by low vol alone, and the boundary absorbing more/late cycle touches breaks first. Costs respected: breakout targets scale with the pre-break range and fatigue level.

### 5. Observable variables
Turning points (zigzag on closed H1 bars), rainflow cycle set {amplitude, mean}, amplitude-contraction slope, cycle count per boundary, fatigue index D, range width, ATR, spread.

### 6. State machine
```
SCANNING → RANGE IDENTIFIED (≥4 alternating turning points within a band) →
FATIGUE ACCUMULATION (update D each new cycle; require amplitude contraction) →
ARMED (D > D_crit AND width/ATR still tradeable) → TRIGGER (close beyond boundary
with range expansion bar) → ENTRY → MANAGEMENT → EXIT → RESET (D := 0)
Invalidation: range widens beyond tolerance or D stale-decays → back to SCANNING.
```

### 7. Entry logic
Armed + H1 close beyond the fatigued boundary with bar range > median (expansion confirms failure, filters drips). Direction: the boundary with higher accumulated damage. Stop-order variant at boundary ± buffer is acceptable via the existing `STOP` command.

### 8. Exit logic
SL: inside the range (midpoint or opposite third — the structure that failed). TP1 at 1× range height projected, runner via ratchet. Failure exit: re-entry back inside the range for 2 closes = failed break → flatten immediately (deterministic false-break rule).

### 9. Risk model
Fixed fractional R; stop distance is range-derived (structurally meaningful). Skip if range height < n× spread (cost screen). One attempt per range; a failed break voids the range (no revenge re-entry) — false-break losses are the known killer of this family and are capped by construction.

### 10. Failure modes
False breakouts (the classic) → expansion-bar trigger + 2-close failure exit + one-attempt rule. Fatigue index miscalibration across assets → normalize amplitudes by ATR. Ranges that resolve by *drift* rather than break → time-decay D and stand down.

### 11. Strengths
Path-dependent information no vol indicator carries; deterministic and fully explainable; naturally infrequent; targets scale with structure (cost-robust).

### 12. Weaknesses
Known family with a known failure mode (false breaks); zigzag turning-point extraction has a look-back confirmation lag; several structural parameters (band tolerance, D_crit) to discipline.

### 13. Market compatibility
Ranging→trending transitions: its exact habitat. Established trends: dormant. High vol chop: ranges fail the contraction requirement (good). News: breakouts on news are its best trades *and* its worst fakes — take them, rely on the failure exit.

### 14. Automation complexity: **6/10**
### 15. Computational cost
Low: zigzag + rainflow on ≤200 bars per symbol per H1 close; milliseconds.

### 16. Data requirements
OHLC (H1). Spread.

### 17. Validation plan
TVP, plus: A/B the fatigue statistic against a plain Bollinger-squeeze breakout on identical trigger/exit scaffolding — Rainflow must beat the memoryless baseline, else the path-dependence adds nothing and we record that. Track false-break rate as a first-class metric.

---

## 5. SPRING — Ornstein-Uhlenbeck half-life mean reversion

### 1. Name
**Spring** (Hooke's law: restoring force proportional to displacement).

### 2. Scientific inspiration
Stochastic differential equations / physics: the OU process `dx = θ(μ − x)dt + σdW` — Brownian motion with a spring attached. The canonical model of mean reversion with *measurable* reversion speed θ and half-life ln2/θ.

### 3. Core principle
Don't ask "is price stretched?" (every reversion system does); ask "**does a spring currently exist, and how stiff is it?**" Rolling-fit OU on H1 log price (or price minus a slow Kalman level): estimate θ, μ, σ with confidence intervals. Trade *only* when θ is statistically significant and the half-life is short and stable — i.e., when mean reversion is a measured property of the current market, not a hope. Honesty note: this is classic stat-arb machinery; the discipline is the *existence gate* (most single-asset FX series, most of the time, will fail it — and refusing to trade then IS the edge over naive band-fade systems).

### 4. Trading hypothesis
FX pairs in identifiable equilibrium episodes (post-repricing, pre-event lulls, session ranges) exhibit temporary OU dynamics. Fading k·σ_eq displacements *only during measured episodes*, with time-boxed holding (2 half-lives), harvests reversion while avoiding the fat-tail blowups of always-on fading.

### 5. Observable variables
Rolling OU fit (θ̂ with t-stat, μ̂, σ̂), half-life, equilibrium displacement z = (price − μ̂)/σ_eq, fit-stability metric (θ̂ variance across sub-windows), ATR, spread.

### 6. State machine
```
NO-SPRING (θ not significant) → SPRING DETECTED (θ̂ t-stat > 2, half-life ∈ [4, 48] bars,
stable across sub-windows) → ARMED → STRETCHED (|z| > z_entry) → VALIDATION
(cost: expected reversion μ̂-distance > n× spread) → ENTRY (fade toward μ̂) →
MANAGEMENT → EXIT (μ̂ touched | 2 half-lives elapsed | θ̂ loses significance → flatten)
```

### 7. Entry logic
Armed + |z| ≥ z_entry (≈2) + reversion distance clears the cost screen → fade toward μ̂. Limit order at the stretch is acceptable (LIMIT command exists).

### 8. Exit logic
TP at μ̂ (the physics says the spring pulls to equilibrium, not through it). Hard SL at z_stop (≈3.5) — beyond it the OU model is rejected, not merely losing. Time stop at 2 half-lives (if it hasn't reverted on schedule, the spring broke). Regime exit: θ̂ significance lost → flatten. First-hit.

### 9. Risk model
Fixed fractional R with the z_stop distance; expected R:R is (z_entry)/(z_stop − z_entry) ≈ 1.3:1 with win rate doing the lifting — demands honest cost modeling (TVP stage b is decisive here). No martingale, no grid, no adds — one unit per episode. Portfolio cap on simultaneous fades (reversion trades correlate in risk-off).

### 10. Failure modes
The fat tail: a "stretch" that is actually a regime break → z_stop + time stop + the θ-significance kill. Estimation lag: OU fit degrades exactly when trends begin → fit-stability gate. Low reversion amplitude vs spread at H1 → likely the fatal issue; the cost screen will tell us fast.

### 11. Strengths
Fully deterministic; every parameter is an interpretable physical quantity; the existence gate is a genuine differentiator vs indicator-fade systems; complements the arsenal (SilverBullet/Gyroscope are long-vol/trend — Spring is the counter-cyclical leg).

### 12. Weaknesses
Short-horizon single-asset FX reversion is heavily fished and cost-fragile; H1 amplitude may simply not clear FBS spreads (prior research says respect this risk). Negative skew by construction.

### 13. Market compatibility
Ranging/low-vol: excellent. Trending: stands down (gate). News: must be locked out hard (fading news is the classic account-killer). Session lulls (Asia) are its natural habitat — but Asia spreads are wider; the cost screen must use session-conditional spread.

### 14. Automation complexity: **4/10**
### 15. Computational cost
Trivial: OU fit is a lag-1 regression on ≤300 bars.

### 16. Data requirements
OHLC (H1), session-conditional spread stats.

### 17. Validation plan
TVP with stage (b) emphasized: measure the distribution of |reversion amplitude|/spread during detected episodes *before any backtest*. If the median episode doesn't clear 3× spread, NO-GO at the screen. Also test the existence gate's discriminative power: forward reversion stats inside vs outside gated episodes.

---

## 6. SHANNON GATE — entropy-collapse persistence trader

### 1. Name
**Shannon Gate** (information theory's founder; the gate opens when the market becomes compressible).

### 2. Scientific inspiration
Information theory: entropy rate, Lempel-Ziv complexity, compression ratio. A maximally efficient market's return-sign sequence is incompressible (entropy ≈ 1 bit/symbol). Deviations from incompressibility = structure = exploitable predictability.

### 3. Core principle
Encode the last N H1 bars as a symbol stream (e.g., return sign + magnitude tercile → 6-symbol alphabet). Compute a rolling entropy-rate estimate (block entropy or LZ76 complexity, normalized against shuffled surrogates). Most of the time the market sits near max entropy → *stand down* (the gate's main output is "don't trade"). When measured entropy drops significantly below the surrogate distribution, structure exists; trade the dominant conditional pattern (e.g., P(up | recent context) from the empirical context tree) while the entropy deficit persists.

### 4. Trading hypothesis
Predictability is episodic. Systems that trade continuously pay costs during the (majority) incompressible periods. Conditioning *any* directional rule on a measured entropy deficit concentrates trading into the minority of hours where a pattern demonstrably exists, and the direction is read from the same context statistics that produced the deficit.

### 5. Observable variables
Symbolized return stream, block/LZ entropy vs surrogate mean±sd (a z-score: the "entropy deficit"), dominant context-conditional next-symbol probabilities, ATR, spread.

### 6. State machine
```
EFFICIENT (deficit z > −2) → STRUCTURE DETECTED (z ≤ −2 for 2 consecutive bars) →
PATTERN EXTRACTION (context tree: is there a conditional edge > p_min?) → ENTRY
(trade the conditional direction each time its context appears) → per-trade EXIT
(next-bar or fixed n-bar horizon) → GATE CLOSES (z recovers) → EFFICIENT
```

### 7. Entry logic
Gate open + current context's empirical continuation probability ≥ p_min (e.g., 0.62 with ≥30 observations) + expected move clears cost screen → enter that direction at bar open.

### 8. Exit logic
Fixed-horizon (the pattern's own horizon — typically next 1–3 bars), vol-scaled SL as disaster stop only. Gate close flattens. This is a short-holding, statistical-edge accumulator, not a runner system.

### 9. Risk model
Small fixed R per trade (edge is thin per event, harvested repeatedly during open-gate windows); daily loss cap per symbol; gate-close flatten. The whole risk architecture is "many small bets only while the meter says the casino is beatable."

### 10. Failure modes
**Cost death is the default expectation** — 1–3 bar H1 holds at retail spread is exactly the profile our OTE research killed. Multiple-comparisons overfitting in context selection → surrogate-based significance, contexts pre-registered. Entropy estimator variance at feasible N → block-length sensitivity study.

### 11. Strengths
Most honest self-limiting design possible (trades only under measured predictability); the entropy meter is a valuable *arsenal-wide filter* even if standalone trading fails; fully deterministic.

### 12. Weaknesses
Per-trade edge is thin → cost fragility (likely fatal standalone at our costs); needs many symbols/years for significance; symbolization choices are researcher degrees of freedom.

### 13. Market compatibility
Anywhere structure appears episodically; agnostic to trend/range labels. News: entropy spikes (gate closes) — naturally safe.

### 14. Automation complexity: **5/10**
### 15. Computational cost
Low-moderate: LZ76 on 200-symbol windows + surrogate ensemble (~100 shuffles, cached) per symbol per bar.

### 16. Data requirements
OHLC (H1/M15). Spread.

### 17. Validation plan
TVP with stage (b) as the expected kill point: measure gross conditional edge vs 2× spread first. Pre-register the symbolization and context set before looking at conditional stats (grader-mirror style, as in the OTE rig). Likely outcome to record: NO-GO standalone, ADOPT as a regime filter.

---

## 7. GUMBEL FADE — extreme value theory exhaustion model

### 1. Name
**Gumbel Fade** (Emil Gumbel, father of extreme value statistics).

### 2. Scientific inspiration
Extreme value theory (EVT): the tails of return distributions converge to a Generalized Pareto Distribution (GPD) above a high threshold — the same math that sets flood defenses and structural wind loads. It answers, rigorously: "how extreme is this move, really?"

### 3. Core principle
Maintain rolling GPD fits on H4/D1 move magnitudes (peaks-over-threshold). For any current excursion (e.g., 3-day directional run), compute its exceedance probability under the fitted tail. A move in the top ~1% of the *fitted current-regime tail* (not a fixed z-score — EVT adapts the tail shape ξ to the regime's fat-tailedness) is a candidate exhaustion. Fade it only with a reversal trigger and only when the tail is thin-shaped (ξ low — in fat-tail regimes, extremes beget extremes and fading is statistically wrong; the ξ estimate itself is the regime gate).

### 4. Trading hypothesis
Multi-day directional runs that reach regime-adjusted tail extremes with thin tail shape revert partially (position-unwinding / profit-taking flows), and EVT measures "extreme" correctly where z-scores systematically don't (they assume the wrong distribution exactly where it matters).

### 5. Observable variables
Run magnitude (H4/D1), rolling GPD fit (ξ, β) and exceedance probability of current run, reversal trigger bar, ATR, spread.

### 6. State machine
```
MONITOR → TAIL EVENT (run exceedance prob < p_tail AND ξ̂ < ξ_max) → WAIT FOR TRIGGER
(reversal bar: close against run direction beyond prior bar's midpoint) → ENTRY (fade)
→ MANAGEMENT → EXIT (retrace target | new extreme = stop | time stop) → COOLDOWN
```

### 7. Entry logic
Exceedance probability of current run < 1% under fitted GPD, ξ̂ below the fat-tail cutoff, then the first H4 reversal bar → fade, targeting a 38–50% retrace of the run.

### 8. Exit logic
SL beyond the run's extreme + buffer (a new extreme falsifies "exhaustion"). TP at the retrace target. Time stop: 10 H4 bars. First-hit.

### 9. Risk model
Fixed fractional R; wide stops (tail events are violent) → small size, per RiskManager math. Never add to a losing fade. Per-symbol monthly cap on fade attempts (tail events cluster; one thesis per cluster).

### 10. Failure modes
Fading a genuine break (trend birth) → the ξ gate + hard extreme-stop cap it. GPD fitting needs many exceedances → use multi-year windows, refit slowly; validate stability. Threshold choice (POT u) sensitivity → standard EVT mean-residual-life diagnostics, done once in IS.

### 11. Strengths
H4/D1 scale → costs are a rounding error (the opposite of our OTE problem); statistically principled definition of "overextended"; the ξ-gate is a genuinely novel discipline transfer (fade only thin-tailed regimes); low frequency, big per-trade R.

### 12. Weaknesses
Very low trade count → multi-year validation needed and slow live confirmation; counter-trend by nature (psychologically and statistically the hard side); rolling EVT fits are data-hungry.

### 13. Market compatibility
Best after extended one-way runs in otherwise orderly regimes. Wrong tool in crisis/fat-tail regimes — and it *knows* that via ξ (the self-awareness is the design). Ranging: dormant.

### 14. Automation complexity: **5/10**
### 15. Computational cost
Trivial at H4/D1 cadence.

### 16. Data requirements
OHLC (H4/D1, 3+ years — we have this). Spread (barely matters at this scale).

### 17. Validation plan
TVP, plus: forward-return event study conditioned on (exceedance bucket × ξ bucket) — the 2×2 must show the predicted interaction (reversion only in the thin-tail/extreme cell) before any backtest. Cross-asset pooling is essential for sample size.

---

## 8. CONSTELLATION — cross-asset lead-lag network model

### 1. Name
**Constellation** (positions read from the relative configuration of many stars, not one).

### 2. Scientific inspiration
Network science: rolling correlation/lead-lag graphs, centrality, information diffusion across networks (how activation spreads through connected nodes).

### 3. Core principle
Our book already streams 9 correlated symbols (majors, XAU, indices). Build a rolling lead-lag graph: edge weight = cross-correlation of H1 returns at lags 1–3 bars, kept only if stable across sub-windows. A significant move in a persistent *leader* node (e.g., DXY-proxy basket, XAU) implies a conditional expectation on its *laggard* neighbors that hasn't printed yet.

### 4. Trading hypothesis
Cross-asset information diffusion is not instantaneous at H1 granularity in retail-accessible instruments; stable lead-lag edges (where they exist) let us enter the laggard after the leader has moved, with the leader's move as pre-confirmation. Honesty note: lead-lag at H1 in majors is heavily arbitraged; the realistic hope is metals→related-FX or index→risk-FX edges, and the existence question is exactly what stage-(b) answers.

### 5. Observable variables
Per-symbol H1 returns; rolling lagged cross-correlation matrix; edge stability score; leader-move trigger (leader return > k·σ); laggard's own not-yet-moved check; spread.

### 6. State machine
```
GRAPH MAINTENANCE (weekly refit, daily stability check) → EDGE ARMED (stable edge exists)
→ LEADER FIRES (leader bar > k·σ in direction d) → LAGGARD CHECK (laggard hasn't already
moved > 0.5× its implied response) → ENTRY on laggard → EXIT (implied-move target |
n-bar time stop | leader reverses) 
```

### 7. Entry logic
Armed edge + leader fires + laggard still unmoved + cost screen → enter laggard in the implied direction at next bar open.

### 8. Exit logic
TP at β-implied response magnitude; time stop at the edge's fitted lag + 2 bars (diffusion has a deadline — if it hasn't happened on schedule, the signal is wrong); SL vol-scaled; leader full-reversal flattens.

### 9. Risk model
Fixed fractional R, but *correlation-aware*: a leader firing on multiple laggards is one macro bet — cap the summed R across simultaneous constellation trades (this portfolio brake is itself a network-science contribution to the whole arsenal).

### 10. Failure modes
Edges are regime-dependent and die silently → stability scoring + weekly refit + edge kill after n consecutive failures. Both assets gap together on news (no lag to exploit) → news lockout. Multiple-testing on 9×9×3 lag matrix → strict significance with FDR control, pre-registered.

### 11. Strengths
Uses information the rest of the arsenal ignores entirely (cross-sectional structure); diversifying by construction; the correlation-aware risk brake has arsenal-wide value regardless.

### 12. Weaknesses
The core inefficiency may simply not exist at H1 retail granularity (this is the most existence-risky concept on the list); needs simultaneous multi-symbol data hygiene; regime-fragile edges.

### 13. Market compatibility
Risk-on/risk-off macro days: best (clear leaders). Quiet idiosyncratic markets: dormant. News: leader/laggard gap together — locked out.

### 14. Automation complexity: **7/10** (multi-symbol synchronization in the controller is the real work)
### 15. Computational cost
Low: a 9×9×3 correlation tensor weekly + O(1) triggers.

### 16. Data requirements
Synchronized H1 OHLC across the book (have it), spread.

### 17. Validation plan
TVP, plus: pure existence study first — distribution of laggard forward returns conditioned on leader-fire, per candidate edge, FDR-corrected, IS only; only surviving edges proceed. Expect most to die; pre-commit to shipping nothing if none survive.

---

## 9. TRINITY — Hidden Markov regime allocator (meta-strategy)

### 1. Name
**Trinity** (three latent states: Trend, Range, Turbulence).

### 2. Scientific inspiration
Stochastic processes: Hidden Markov Models — inferring the unobservable generating state of a sequence from its emissions (speech recognition, genomics).

### 3. Core principle
Fit a 3-state Gaussian HMM on H1 (return, |return|, range/ATR) emissions. States empirically resolve into low-vol-drift (Trend), low-vol-no-drift (Range), high-vol (Turbulence). Output: the posterior state vector each bar. Trinity is primarily an **allocator**: it doesn't generate entries — it gates and sizes the *other* strategies (Gyroscope/Aftershock get Trend/Turbulence weight, Spring gets Range weight, everything derates in Turbulence-onset).

### 4. Trading hypothesis
Strategy edges are state-conditional (our own results say this: SilverBullet lives at specific hours/timeframes). Explicit state inference reallocates risk toward each strategy's habitat faster than each strategy's own internal gates can, and the *transition* probabilities add anticipation no single-strategy filter has.

### 5–8. Observables / state machine / entry / exit
Observables: HMM posterior P(state), transition matrix, per-state strategy weights. State machine: `FIT (quarterly, IS-only) → INFER (per bar) → ALLOCATE (map posterior → per-strategy risk multipliers 0–1.25×) → MONITOR (state-occupancy drift check)`. Entries/exits belong to member strategies; Trinity only scales their R.

### 9. Risk model
Multiplies member-strategy R by state-fitness weights; hard floor 0 (a strategy can be fully gated), soft cap 1.25×. Turbulence-onset (posterior swinging toward high-vol) triggers a global derate — the arsenal's circuit breaker.

### 10. Failure modes
Label switching / unstable fits → fix state ordering by vol ranking, quarterly refits on frozen IS. Posterior chatter at state boundaries → hysteresis (min dwell before weights move). The classic HMM sin — refitting on recent data until it "looks right" — is banned by protocol.

### 11–13. Strengths / weaknesses / compatibility
Strengths: force-multiplier for the whole arsenal; principled anticipation via transitions. Weaknesses: adds a layer of model risk *on top of* every strategy; wrong-state misallocation is correlated across the book. Compatibility: definitionally all-regime — its job is knowing which regime it is.

### 14. Automation complexity: **6/10** (hmmlearn or hand-rolled EM; the controller plumbing for risk multipliers is the real change)
### 15. Computational cost: trivial at inference; quarterly EM fit is seconds.
### 16. Data: OHLC H1, 3 yrs.
### 17. Validation
TVP adapted: validate as an *overlay* — member strategies' backtests re-run with Trinity weights vs without; adopt only if pooled net expectancy and drawdown both improve OOS. Also validate state economic meaning: per-state return/vol stats must differ significantly.

---

## 10. ANTIBODY — immune-system anomaly sentinel (defensive module)

### 1. Name
**Antibody** (negative selection: the immune system learns *self* and attacks what doesn't match).

### 2. Scientific inspiration
Immunology + cybersecurity intrusion detection: model the space of "normal" observations; flag and react to non-self, *without needing to have seen the attack before*.

### 3. Core principle
Learn the joint distribution of "normal market microbehavior" per symbol/session from history: bar-shape features (range/ATR, body/range, gap size, tick-volume z, spread z, bar-to-bar overlap). Maintain an anomaly score (Mahalanobis distance or isolation-forest score — deterministic once fit). Antibody is a **defensive sentinel**: sustained anomaly → derate/lock the arsenal (flash events, broker feed pathologies, liquidity holes — things our watchdogs currently catch only after they cost money). A secondary *offensive* mode (fading resolved single-bar anomalies) is testable but not the point.

### 4. Trading hypothesis (defensive form)
Most catastrophic strategy losses happen in market states absent from the training data. Detecting "we are off the map" in real time and cutting exposure is worth more expectancy (via avoided tail losses) than any entry signal of similar complexity.

### 5–8. Observables / state machine / entry / exit
Observables: per-bar feature vector, anomaly score, score persistence. State machine: `SELF-MODEL (quarterly fit) → PATROL (score each bar) → ALERT (score > q99 for 2+ bars) → RESPONSE (block new entries; optionally tighten stops on open trades) → ALL-CLEAR (score normal for n bars) → PATROL`. No entries of its own in v1.

### 9. Risk model
Purely protective: entry lockouts and derates. Interacts with telemetry (Telegram alert on ALERT state — a genuinely useful ops feature on day one).

### 10. Failure modes
False alarms during benign vol expansions → costs opportunity, not capital (asymmetrically safe). Feature drift → quarterly refit. Anomaly *after* the damage (single-bar flash) → can only protect subsequent bars; that's honest.

### 11–13. Strengths / weaknesses / compatibility
Strengths: protects every strategy at once; cheap; useful ops telemetry immediately. Weaknesses: no direct alpha; benefit is hard to measure (avoided losses are counterfactual). Compatibility: all regimes; most valuable in crisis.

### 14. Automation complexity: **3/10**
### 15. Computational cost: trivial.
### 16. Data: OHLC + tick volume + spread (all on the bridge).
### 17. Validation
Replay 3-yr history: catalog ALERT episodes; measure counterfactual P&L of member strategies inside vs outside alerts. Adopt if alerts are rare (<2% of bars) and member-strategy expectancy inside alerts is materially negative.

---

## 11. WALCLOCK — throughput/queue rhythm model (logistics)

### 1. Name
**Walclock** (queueing theory's Little's Law meets the market's service clock).

### 2. Scientific inspiration
Logistics/queueing theory: throughput, service-rate variation, and bottleneck dynamics. Markets process order flow like a service system; tick volume per unit price movement is a service-rate proxy.

### 3. Core principle
Define "effort per distance": tick volume required per unit of price progress (a bar-level proxy for the flow needed to move price — logistics' throughput-per-output). Rolling-normalize it. Rising effort-per-distance = the "conveyor" is jamming (absorption; movement is getting expensive); falling = frictionless flow. Divergences between effort trend and price trend are the signal: price grinding higher on exploding effort is a bottleneck about to back up.

Honesty note: this is the volume/price-efficiency family (related to classic effort-vs-result readings), made deterministic and normalized. Its existence risk is that MT5 *tick* volume is a noisy proxy — which is exactly what stage-(b) tests.

### 4. Trading hypothesis
Sustained effort-price divergence at H1 predicts stall-and-revert (bottleneck) or, when effort collapses while price holds, continuation (free flow). Deterministic thresholds on a normalized effort index time those transitions.

### 5–8. Observables / state machine / entry / exit
Observables: tick volume, |Δprice|, effort index E = vol/(|Δprice|/ATR) rolling-z, price trend sign, spread. State machine: `FLOW MONITOR → DIVERGENCE (E-z > 2 against 5-bar price trend, 3+ bars) → STALL CONFIRM (progress/bar < median) → ENTRY (fade the jammed direction) → EXIT (E normalizes | target | stop)`. Continuation mode mirrors on E-z < −1 with trend.

### 9. Risk model
Fixed fractional R, vol-scaled stops beyond the grind's extreme; only trades where the grind's height clears the cost screen.

### 10. Failure modes
Tick-volume unreliability per broker/session → per-session normalization; if stage-(b) shows tick volume carries no signal at FBS, NO-GO cleanly. Divergences that resolve by acceleration, not reversal → stall-confirm stage + stop above extreme.

### 11–13. Strengths / weaknesses / compatibility
Strengths: uses a data channel (tick volume) the rest of the arsenal ignores; cheap; deterministic. Weaknesses: proxy-quality risk is high; family adjacency to well-known volume divergence ideas. Compatibility: grinding trends and range edges; dormant in clean impulsive moves; news lockout required.

### 14. Automation complexity: **4/10**
### 15. Computational cost: trivial.
### 16. Data: OHLC + tick volume (bridge provides), spread.
### 17. Validation
TVP; stage (b) doubles as a data-quality audit of FBS tick volume (value regardless of outcome). A/B against the same rules driven by bar range instead of volume — volume must add information over range alone.

---

## 12. Comparative matrix

Scales 1–5 unless noted (5 = best). *Cost survival* = odds of clearing FBS retail costs given our prior research. *Existence risk* = risk the exploited inefficiency isn't there at all (5 = low risk).

| # | Strategy | Discipline | Originality | Complexity (1–10, lower easier) | Expected robustness | Cost survival | Existence risk | Adaptability | Compute | Titan feasibility | Role |
|---|----------|-----------|-------------|-----|-----|-----|-----|-----|-----|-----|------|
| 1 | Gyroscope | Control systems / sequential stats | 4 | 5 | 4 | 4 | 4 | 4 | 5 | 5 | Trend engine |
| 2 | Aftershock | Seismology / point processes | 4 | 6 | 4 | **5** | 4 | 3 | 5 | 4 | Vol-event engine |
| 3 | Rubicon | Bayesian change-point | 4 | 7 | 3 | 4 | 3 | 4 | 4 | 4 | Regime-turn engine + shared infra |
| 4 | Rainflow | Mechanical fatigue | 3 | 6 | 3 | 4 | 3 | 3 | 5 | 4 | Breakout engine |
| 5 | Spring | SDE / physics | 2 | 4 | 3 | 2 | 3 | 3 | 5 | 5 | Reversion engine |
| 6 | Shannon Gate | Information theory | 4 | 5 | 2 standalone / 4 as filter | 1 | 2 | 4 | 4 | 4 | Filter (likely) |
| 7 | Gumbel Fade | Extreme value theory | 4 | 5 | 3 | **5** | 3 | 3 | 5 | 4 | Exhaustion engine (H4/D1) |
| 8 | Constellation | Network science | 4 | 7 | 2 | 3 | 2 | 2 | 4 | 3 | Cross-asset engine |
| 9 | Trinity | Hidden Markov | 3 | 6 | 4 (as overlay) | n/a | 4 | 5 | 5 | 4 | Allocator overlay |
| 10 | Antibody | Immunology / IDS | 4 | 3 | 4 (defensive) | n/a | 5 | 5 | 5 | 5 | Defense sentinel |
| 11 | Walclock | Queueing/logistics | 3 | 4 | 2 | 3 | 2 | 3 | 5 | 5 | Volume-channel probe |

---

## 13. Ranked shortlist

**#1 — Gyroscope (Kalman + SPRT).** Best combined score on the axes that have historically decided our GO/NO-GO calls: H1 cadence and low churn (cost survival), an edge family (episodic drift) with documented existence, trivially cheap compute, drop-in fit to `BaseStrategy`/`on_new_candle`/existing trade management, and — uniquely — *falsifiable internal statistics* (realized false-entry rate vs α; NIS whiteness) that make live monitoring principled rather than vibes. Its main risk (momentum decay in majors) is precisely measurable by our existing rig at near-zero cost.

**#2 — Aftershock (Hawkes cascades).** Highest cost-survival on the board: it only trades when ranges are multiples of normal, so spread-as-fraction-of-target collapses exactly when it's active — the structural inverse of what killed OTE. Built on the most-replicated stylized fact in finance. Ranked below Gyroscope only because trade frequency is lower (slower validation) and Hawkes fitting on sparse events adds estimation risk.

**#3 — Rubicon (BOCPD).** Attacks a real structural weakness of all rolling-window systems, and its detection layer is reusable infrastructure (a regime clock for SilverBullet, Trinity, and the others) even under a trading NO-GO — the highest salvage value on the list. Ranked third because the tradable hypothesis (post-break drift persistence) is the least documented of the top three.

**Honorable mentions:** Antibody should probably be built *regardless of ranking* — it is 2–3 days of work, protects everything, and improves ops telemetry immediately. Gumbel Fade is the best "slow burner" (start collecting its H4/D1 event studies in the background).

---

## 14. Architectural blueprint — GYROSCOPE (production module)

### 14.1 Placement in Titan

```
src/strategies/models/gyroscope.py     # GyroscopeStrategy(BaseStrategy)
src/analysis/kalman_drift.py           # KalmanDrift: filter + SPRT + NIS (pure, stateless-in, state-out)
tests/unit/test_kalman_drift.py        # filter math on synthetic OU/drift series
tests/unit/test_gyroscope_strategy.py  # decision-dict contract, gating, suspend
config/config.yaml → strategies.gyroscope
docs/research/…-gyroscope-gate.md      # pre-registered gate BEFORE backtest (OTE-rig discipline)
```

- Subclasses `BaseStrategy`; `timeframe: 'H1'` so the controller routes H1 closes to it (mechanism already exists).
- `validate_data(df, min_length=warmup, check_smc=False)` — **needs no SMC columns**; it consumes raw OHLC only. It ignores HTF-bias context (its own drift estimate *is* its bias) — controller-side this means adding it to the bias-filter exemption set alongside CRT.
- Returns the standard decision dict `{signal, type: 'MARKET', price, sl, tp}`; `initial_entry/initial_tp` metadata flows through the existing send-time pipeline so `trade_manager` BE/partials/ratchet engage normally.
- Backtests on the existing rig (`tests/backtest/backtest_engine.py`) + the OTE study's cost model; no new harness needed.

### 14.2 Core math (`KalmanDrift`)

State: `x = [level, velocity]ᵀ` on log-price. Per H1 close `y = ln(close)`:

```
Predict:  x̂ = F x,  P = F P Fᵀ + Q          F = [[1,1],[0,1]]
Innovate: ε = y − H x̂,  S = H P Hᵀ + R       H = [1,0]
Update:   K = P Hᵀ / S;  x̂ += K ε;  P = (I−KH) P
```

- `R` (measurement noise): rolling variance of 1-bar log returns × r_frac.
- `Q` (process noise): scaled to ATR so the filter is asset-agnostic; both refreshed each bar from the same rolling window (no free constants per symbol).
- **Integrity monitor:** rolling mean of NIS = ε²/S over W bars must sit inside the χ²₁ confidence band; violation ⇒ `SUSPENDED` (no new entries) and re-warm.

**SPRT layer** on the innovation-whitened return stream `u_t = ε_t/√S_t` (unit-variance by construction — this is what makes the LLR clean):

```
Λ_t = Λ_{t−1} + [ ln f(u_t | drift=+δ) − ln f(u_t | drift=0) ]     (long test; short mirrors with −δ)
Enter long  when Λ_t ≥ A = ln((1−β)/α)
Reset lower at Λ_t ≤ B = ln(β/(1−α))   (evidence for H₀ → restart accumulation)
```

δ expressed in whitened units (default 0.4); α default 0.05, β default 0.2. Both tests (long and short) run concurrently; first boundary crossing wins; opposite test's crossing while in a trade is the reversal exit.

### 14.3 State machine → code mapping

| State | Where | Transition |
|---|---|---|
| WARMUP | strategy | `bars < warmup (200)` → filter/vol windows filling |
| OBSERVE | strategy | NIS band OK; update Λ_long, Λ_short each close |
| ENTRY | decision dict | Λ crosses A **and** validation: spread ≤ `max_spread_atr_frac`·ATR, no position, ATR within [vol_floor, vol_ceil], grader min-grade passes |
| IN_TRADE | trade_manager (existing) | BE 38.2%, partials 61.8/88.6, ratchet — config-driven, nothing new |
| EXIT | strategy + manager | reverse SPRT crossing → emit close intent; else SL/TP/time stop `max_bars_in_trade` (default 48) |
| COOLDOWN | strategy | `reentry_lockout` bars (default 5), Λ reset to 0 |
| SUSPENDED | strategy | NIS violation → block entries, log + Telegram notice; auto-resume after W clean bars |

Exit-by-signal uses the established mgmt path (`SystemController._dispatch_mgmt_command` → `CLOSE_POS` on PUSH, verified from HEARTBEAT) — never the REQ socket.

### 14.4 Orders and risk

- Entry: `MARKET` via REQ handshake (existing path).
- `sl = entry ∓ k_sl·√S_price` where √S is the filter's own price-space uncertainty (default k_sl = 3.0, floored at 0.8·ATR so it never undercuts the SilverBullet-study finding that tight H1 stops die).
- `tp = entry ± rr_target·(entry−sl)` (default 2.0) — present mainly to arm the partials ladder; the runner/ratchet does the harvesting.
- Sizing: unchanged `RiskManager.calculate_lot_size` (broker-spec driven, fail-safe on missing specs).

### 14.5 Config block (defaults = pre-registered values)

```yaml
strategies:
  gyroscope:
    enabled: false          # research first; flips only on a GO gate
    timeframe: H1
    warmup_bars: 200
    q_atr_frac: 0.05        # process noise scale
    r_frac: 1.0             # measurement noise scale
    sprt: { alpha: 0.05, beta: 0.20, delta: 0.40 }
    nis_window: 50
    k_sl: 3.0
    sl_atr_floor: 0.8
    rr_target: 2.0
    max_bars_in_trade: 48
    reentry_lockout: 5
    max_spread_atr_frac: 0.10
```

### 14.6 Failure detection in production (the avionics part)

1. **NIS χ² band** → SUSPENDED (model invalid).
2. **Realized false-entry rate** (entries stopped within `lockout` bars / total entries), rolling 30 trades: > 2α ⇒ auto-pause + Telegram alert. This is the strategy grading *itself* against its own advertised error budget — a check unavailable to any threshold-indicator system.
3. Standard watchdogs (bridge health, spec presence) unchanged.

### 14.7 Build & validation sequence (TVP instantiated)

1. `KalmanDrift` + unit tests on synthetic series (pure drift, pure noise, drift-with-break): filter must recover known velocity; SPRT must hit designed α/β on simulation. **TDD, no market data yet.**
2. Pre-register the gate doc (mirror the OTE gate format): 3-yr H1, 9 symbols, FBS cost model; GO requires pooled net ≥ +0.10R/trade, ≥ 150 trades, ≥ 6/9 symbols non-negative, OOS (final 30%) sign-consistent; ±30% sweeps on (α, β, δ, q_atr_frac) must not flip pooled sign; **must beat an MA-slope baseline on identical exits**.
3. Cost screen: distribution of favorable excursion after boundary crossings vs 2× spread.
4. Backtest on the existing rig; grader-mirror journaling as in the OTE study.
5. GO → demo-forward on FBS-Demo (same bar as SilverBullet: demo before live). NO-GO → record canonically in `docs/research/`, keep `KalmanDrift` as reusable analysis infra.

**Estimated effort:** core math + tests ~1 day; strategy shell + config ~0.5 day; gate doc + backtest + writeup ~1–1.5 days. Compute cost in live loop: microseconds/bar — negligible next to existing SMC feature pipeline.

---

## 15. Portfolio view

The shortlist is deliberately anti-correlated in habitat: Gyroscope earns in drift episodes, Aftershock in vol cascades, Rubicon at regime turns — three orthogonal payoff profiles next to SilverBullet's session-timing edge. Trinity (allocator) and Antibody (defense) are overlays that raise the whole book's quality rather than adding correlated signal count. Shannon Gate most likely matures into a shared "don't trade now" filter. Recommended cadence: one candidate per research cycle through the OTE-style rig, Gyroscope first; Antibody built in parallel as an ops win regardless of any gate outcome.
