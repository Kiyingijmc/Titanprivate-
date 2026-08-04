# Confidence–Skew Screen — design

**Date:** 2026-08-04
**Status:** design approved; preregistration + implementation not started
**Branch (when execution starts):** `research/confidence-skew-screen`
**Origin:** a proposed "Hierarchical Market State Scalper / Market Intent Engine (MIE)"
programme — a Tier-0 inference layer above every strategy, estimated by its author at
70–90% of Titan's decision layer. This spec does **not** design that programme. It designs
the cheapest experiment capable of falsifying its central premise.

---

## 1 · Why this exists

The MIE proposal rests on one load-bearing assumption:

> Finer confidence estimates buy better sizing, therefore higher expectancy.

Titan already ships a confidence estimate — `SignalGrader`'s 0–100 score. If that score
carries no exploitable information above its floor, the premise is false for the estimate we
have, and the burden shifts to demonstrating that a *new* estimate would do better. This
screen tests both halves: the shipped grader, and a frozen panel of candidate market-state
features standing in for the MIE's proposed "intent dimensions".

### 1.1 What the repository already says

| Finding | Source | Bearing on the premise |
|---|---|---|
| `≥B` floor helps (+0.194R → +0.222R); **`≥A` over-filters — fewer trades, no expectancy gain** | `docs/research/2026-07-11-silverbullet-h1-stop-study.md` §4, n=1,327 | The bottom cut carries information; **monotonicity above it was never demonstrated** |
| Base rate ≈ **1 survivor in 9** gated candidates | `docs/strategies/ARSENAL.md` | Prior strongly favours a null |
| Median round-trip cost gate ≤ **0.25R** | ibid. | Sets the economic floor below which a confidence signal is not worth acting on |
| Entries must earn their own edge; candidates screened on **skew potential, not on inheriting the exit engine** | EXP-0, 2026-07-31 | Determines the estimand (§3) |
| **STRAT-01:** live exit engine (`trade_manager.sync_positions`) is not the validated one (`poc_sb_stops.replay_managed`); every replay number is an upper bound | `docs/strategies/IMPROVEMENTS.md` Tier 1 §1 | Any managed-R estimand would be invalidated by the eventual fix |

### 1.2 Measured before designing: the score is far coarser than assumed

Recomputing `SignalGrader` over the live-stop signal population
(`data/history/sb_stops_trades_H1.csv`, model `ATR10`, n=2,217, 11 symbols, 2023-06 → 2026-06):

| Factor | Range on paper | Actual range on live SilverBullet signals |
|---|---|---|
| Risk:Reward | 20 | **constant 15** — `silver_bullet.py:29` pins `rr = 2.0`; RR is 2.0 on all 2,217 |
| Displacement | 20 | **binary 15/20** — the strategy's entry rule already requires displacement |
| PD array | 15 | **binary 0/15** — `liq_status` is only ever PREMIUM or DISCOUNT, never EQ |
| HTF bias | 30 | 0/10/30 (aligned 674, neutral 936, counter 607) |
| Killzone | 15 | 0/15 |

The score takes **13 distinct values** (30…95). Grade buckets:

```
C 592 · B 939 · A 499 · A+ 138 · A++ 49
```

Two consequences established **before any outcome was examined**:

1. **The proposal's 4-tier risk ladder is unbuildable on this evidence base.** Tiers at
   A+ (n=138) and A++ (n=49) span three years and eleven symbols — ~16 A++ signals/year for
   the entire book. At per-trade R sd ≈ 1.3 the standard error on an A++ mean is ≈ ±0.19R.
   Those tiers cannot be estimated now, nor after any plausible additional soak.
2. **It mechanically explains "≥A over-filters."** Above the B floor the score is moved by
   two binary factors and a killzone flag. It is a 3-bit signal presented as a 100-point scale.

Accordingly the score is analysed as an **ordinal trend**, never as five buckets, and the real
effort goes to whether any finer-resolution confidence feature exists at all.

### 1.3 Scope boundary

This is a **screen**, the first stage of the repo's standing funnel (screen → gate →
demo-forward). **No outcome of this screen authorizes building the MIE as proposed.** The best
possible result authorizes one named feature and one confirmation gate.

Explicitly out of scope: the Tier-0 architecture, the strategy selector, the narrative engine,
per-bucket A+/A++ expectancy (§2.4), and conviction-scaled sizing (§6.2).

---

## 2 · Population, anchoring, estimand

### 2.1 Population

All SilverBullet H1 signals in `data/history/sb_stops_trades_H1.csv` where `model == "ATR10"`
(the live stop model): **n = 2,217**, 11 symbols, 2023-06 → 2026-06 — **regenerated per §2.7**,
which adds the expired signals the source file dropped, so the final n will exceed 2,217 and is
reported rather than assumed.

IS/OOS split at 0.70, **cut at the calendar date before which 70% of signals fall — not at a row
index**, so symbols with denser signal counts cannot dominate the training period. Purge and
embargo per §4.3.

**Primary universe = all 11 symbols**, chosen because n is the binding constraint. The **live
9-symbol cost-viable set** (the frozen-lake universe: AUDUSD, BTCUSD, EURUSD, GBPJPY, GBPUSD,
US30, USDCAD, USDJPY, XAUUSD) is a **mandatory robustness cell that must agree in sign** — a
survivor that works only on the two symbols Titan does not trade (GBPCAD, XBRUSD) is worthless.

### 2.2 Anchoring — the load-bearing choice

Excursions are measured **from the signal bar, relative to the nominal entry level, over a
fixed forward horizon** — never from a modelled fill, never to a modelled exit.

This removes the **exit-engine** confound: no ratchet, partial, runner or time-stop enters the
measurement, so STRAT-01 cannot invalidate the result. What remains is a property of the entry
alone — exactly what EXP-0's doctrine requires.

**It does not remove the fill-model confound, and an earlier draft of this spec wrongly claimed
it did.** Anchoring at the signal bar governs *how* an outcome is measured; it has no bearing on
*which signals are in the sample*. Measured fill waits in the source file run 1…12 bars with a
**100% fill rate and a hard maximum of exactly 12** — the rig applied a 12-bar expiry and
**discarded every expired signal**. The population is therefore already conditioned on filling,
under the pre-correction resolver that admitted BUY LIMITs one spread too easily,
**direction-asymmetrically**. Because `bias_class` is a Family A test and correlates with
direction mix, that selection lands squarely on a hypothesis under test. Resolution: §2.7.

### 2.3 Estimands

In R units, where 1R = the ATR10 stop distance recorded per signal:

| Symbol | Definition | Role |
|---|---|---|
| `MFE_H` | max favourable excursion from entry level within H, **signed positive**, floored at 0 | descriptive |
| `MAE_H` | max adverse excursion within H, **as a positive magnitude**, floored at 0 | descriptive |
| **`skew_H`** | **`MFE_H − MAE_H`** | **sole primary** |
| `P(MFE ≥ 2R before MAE ≥ 1R)` | path-ordered hit proxy at the live 2R target | descriptive |

Both excursions are positive magnitudes floored at 0, so `skew_H` is a signed quantity where
positive means the trade's favourable path dominated.

**`MFE_H` is truncated at the first 1R adverse touch — this is not optional.** An untruncated
MFE credits favourable movement that occurs *after* the position would already have been
stopped out, which is unrealizable by construction. A signal reaching MFE 3R only after first
printing MAE 2R scores `skew_H = +1.0` while being a dead trade. Truncation makes the primary
estimand "how much did this entry give me before it killed me," which is what a confidence
estimate is supposed to rank.

Truncating at 1R does **not** reintroduce the exit engine: 1R *is* the entry's own stop, the
same ATR10 distance that defines the R unit. No ratchet, partial, runner, or time-stop enters
the measurement, so STRAT-01 remains irrelevant to the result. The untruncated variant is
retained as a descriptive companion, never as the promotion criterion.

**Window construction.** The excursion window opens at the **first touch of the nominal entry
level** (a LIMIT does not exist as a position before then) and runs H H1-bars forward from that
touch. The entry must be touched within **W = 12 H1 bars** of the signal bar — the same expiry
the source rig applied, adopted rather than invented so the population is not re-cut on a new
parameter. Measured fill waits: median 3, p90 9, p99 12, max 12.

**A signal that never touches within W scores `skew_H = 0`**, retained in the sample rather than
dropped. Zero is the literal realizable outcome of a signal that never becomes a position, and
dropping such signals would select on a post-signal event. Two consequences are pre-registered:
the fraction at exactly 0 is reported (it is a tie mass that Spearman must handle by mid-ranks),
and a feature that predicts *non-filling* rather than *bad filling* is reported as such rather
than conflated with a skew result.

**Estimand shopping is closed off.** The descriptive companions may inform interpretation and
may **never** be substituted as the promotion criterion.

**Horizon: H = 12 H1 bars primary** — covers p90 of realised holding periods (median 1,
p75 5, p90 12, p95 16). **H = 24 confirms only**; a feature significant at H=24 alone is
**not** a survivor.

**Excursions are computed on M5 bars, not H1** — same source data, 12× the path resolution.
This makes the ordering test (`MFE ≥ 2R` *before* `MAE ≥ 1R`) accurate rather than an intrabar
coin-flip, and directly addresses the stop study's own caveat that H1 bar-path replay cannot
order intrabar events.

### 2.4 Declared out of scope by power

Per-bucket expectancy for A+ (n=138) and A++ (n=49). At SE ≈ ±0.19R these tiers cannot be
estimated, and the study will not report them as though they could.

### 2.5 Pre-registered caveats on the source data

- **Retired by §2.7** (kept here so the reasoning survives): `sb_stops_trades_H1.csv` was
  generated 2026-07-11, predating the 2026-07-30 fill-model correction, and contains **only
  signals that filled within 12 bars** — a sampling frame chosen by a direction-asymmetric bug.
  Regeneration removes this rather than caveating it. An earlier draft claimed §2.2's anchoring
  neutralised it; that claim was wrong.
- 2026 covers **Jan–Jun only**. BTCUSD includes **weekend sessions**.
- Broker→NY offset is a fixed **−7h** with ±1h DST wobble (`poc_sb_stops.py:42`).
- M5 CSVs carry **OHLC only — no volume, no spread**. Tick-volume and live-spread candidate
  features are therefore unavailable to this screen and are not in the panel.

### 2.6 Fill-conditional secondary cell

As a **secondary read only**: re-resolve fills with the corrected direction-aware resolver and
repeat the primary test on filled-only signals. If primary and secondary disagree, **that
disagreement is the finding** and is reported rather than reconciled away.

### 2.7 Population regeneration — resolving the selection confound

**Decision: regenerate the signal set rather than inherit it.** The screen re-runs signal
collection from the frozen lake with the **corrected direction-aware resolver**, emitting
**every signal including expired ones**, and uses that as its population.

This is a deliberate scope increase (≈ +0.5–1 day) taken because the alternative is unsound:
inheriting `sb_stops_trades_H1.csv` means testing `bias_class` on a sample whose membership was
decided by a known direction-asymmetric bug. No amount of downstream statistical care repairs a
biased sampling frame, and a "flat" verdict drawn from one would be the *right conclusion for
the wrong reason* — the worst possible outcome for a study whose entire value is that its null
is trustworthy.

Regeneration also retires the §2.5 provenance caveats wholesale, and pairs naturally with the
`skew_H = 0` treatment of unfilled signals (§2.3), which is inert on the inherited file (100%
filled) and only becomes meaningful once expired signals exist in the sample.

**The inherited file is retained** as a fixed, hash-frozen cross-check: the regenerated
population must reproduce the inherited one's 2,217 filled signals to within the fill-model
correction's expected direction-asymmetric difference. A larger or oppositely-signed
discrepancy means the regeneration is wrong, not the original, and blocks the run.

---

## 3 · The panel

Frozen and committed **before any outcome is computed**.

### 3.1 Family A — the shipped grader, decomposed (5 tests)

`bias_class` (3 levels) · `displacement_bucket` (binary) · `pd_array` (binary) ·
`killzone` (binary) · `composite_score` (13 ordinal levels).

**RR is excluded from the panel because it has zero variance** (§1.2). That is a reported
finding, not a test.

### 3.2 Family B — candidate confidence features (8 tests)

Each is the cheapest OHLC-computable proxy for one of the MIE proposal's "intent dimensions",
so a null is a null *for that dimension's cheapest form*, not merely for one arbitrary
indicator.

| # | Feature | Intent dimension proxied |
|---|---|---|
| 1 | ATR percentile of `atr` within the trailing 250 closed H1 bars | Volatility Intent — stored vs released |
| 2 | ATR(10)/ATR(50) at signal | Volatility Intent — compression vs expansion |
| 3 | Kaufman efficiency ratio over 20 closed H1 bars: `abs(c_t − c_{t−20}) / Σ abs(c_i − c_{i−1})` | Auction Intent — discovery vs balance |
| 4 | Signed distance from entry to the nearer of the **previous completed** day's high/low, in R | Liquidity Intent — proximity to the pool |
| 5 | Session-of-day, 4 levels by NY hour (§2.5 offset): Asia `[17,02)`, London `[02,07)`, NY-AM `[07,12)`, NY-PM `[12,17)` | Time Intent — finer than the binary killzone |
| 6 | Agreement between H1 bias and the bias of the **last closed** H4 bar (resampled), 2 levels | the nested-timeframe claim, cheapest testable form |
| 7 | **Continuous** position of entry in the trailing 20 closed H1 bars' range, `(entry − lo)/(hi − lo)` | Directional Intent + **binarization test** |
| 8 | **Continuous** signal-bar return / trailing 20-bar realized vol | Directional Intent + **binarization test** |

Direction handling: features 4, 7 and 8 are **sign-oriented to the signal direction** (a SELL's
value is negated) so that "higher = more favourable to this trade" holds uniformly and a
monotone test is meaningful. Features 1, 2, 3, 5, 6 are direction-agnostic by construction.

Feature 6 computes the H4 bias with the **shipped `BiasEngine`** (`src/analysis/bias_engine.py`)
applied to resampled H4 bars — not a second, hand-rolled definition of bias. Same reasoning as
§5.4: an offline reimplementation is exactly how the existing grader mirror drifted, and a null
on a bias definition Titan does not use would answer the wrong question.

**Feature 6 fails silently by design and must be instrumented.** `BiasEngine.get_bias_context`
returns `"NEUTRAL"` both when it genuinely sees a range *and* when it catches any exception
(`bias_engine.py:66`) or has fewer than 50 bars (`:38`). A broken H4 resample would therefore
present as a legitimate constant, and the feature would be reported as a null when it was never
computed. **Mandatory instrumentation:** record the H4 NEUTRAL rate and the exception count
separately, and if NEUTRAL exceeds the H1 bias's own NEUTRAL rate (42%, from §1.2's
936/2,217) by more than 15 points, feature 6 is reported as **not computed** rather than as a
null. The ≥50-bar warmup also means the earliest signals per symbol are legitimately NEUTRAL;
those are excluded from feature 6's test and the excluded count is reported.

**Interpretation caveat on features 1 and 2 — normalization circularity.** `skew_H` is
denominated in R, and R *is* the ATR10 stop distance, so the outcome is already ATR-normalized.
Features 1 and 2 are functions of ATR. If ATR systematically mis-scales true move size at
volatility extremes — which is exactly what a fat-tailed regime does — these features will
correlate with ATR-normalized skew **mechanically**, with no confidence information involved.
A hit on 1 or 2 is therefore reported as **"volatility normalization or confidence — not
separable by this design"**, and its promotion requires a follow-up gate measuring skew in
absolute price units. A null on 1 or 2 is unaffected by this and remains a clean null.

Features **7 and 8 are continuous versions of factors the grader currently binarizes** and are
the highest-value cells in the panel: if continuous forms carry signal where binary ones do
not, the finding is that the grader discards information at its thresholds — a config-scale
fix with a measured basis, and the cheapest actionable outcome this study can produce.

### 3.3 Frozen placebos (2)

Deterministic pseudo-random values seeded from the signal timestamp, indistinguishable from
real features to the pipeline. **If either placebo survives, the run is void (§5.1).**

### 3.4 Strict causality

Every feature is computed **only from bars closed at or before the signal bar** — trailing ATR
percentile, not centered; *previous completed* day's high/low, not the in-progress day.
Enforced by the look-ahead test in §7.

---

## 4 · Inference

### 4.1 Clustered inference (not naive p-values)

Signals are **not independent**. The eleven symbols carry shared factors — GBPUSD, GBPCAD and
GBPJPY load on a common GBP factor; EURUSD, GBPUSD and AUDUSD on a common USD factor; XAUUSD
and XBRUSD co-move through the dollar and the risk cycle — and signals cluster within sessions
and days on top of that. Naive Spearman p-values
would assume 2,217 independent observations against a far lower effective count — the standard
way a panel study manufactures a false positive.

**Method:** a **cluster bootstrap over calendar-week blocks** — whole weeks resampled with
replacement, all symbols moved together (~157 blocks), preserving serial and cross-sectional
dependence in one operation. (Named precisely: the blocks are non-overlapping calendar units,
not the randomly-placed variable-length blocks of a *stationary* bootstrap. The distinction
matters because the two have different implementations and different edge behaviour.)

**Concretely:** the bootstrapped statistic is the within-symbol-rank Spearman ρ between feature
and `skew_H`. The null distribution is built by resampling weeks **with the feature column
permuted across weeks** (so dependence structure is retained while the feature–outcome link is
broken); the two-sided p-value is the fraction of null draws at least as extreme as the
observed ρ. 10,000 draws, seeded and recorded.

**Intracluster correlation is measured, not assumed:** ICC is computed on `skew_H` residuals
after within-symbol rank-normalization, with the calendar week as the grouping unit. The design
effect follows from it, and **every power statement in the results doc is reported against the
measured value**, not against the projection below.

**Honest projection** (ICC ≈ 0.05, ~14 signals/week ⇒ design effect ≈ 1.65, effective IS
n ≈ 940): detectable |ρ| ≈ **0.09** at α=0.05, ≈ **0.115** after BH, OOS confirmation needs
|ρ| ≥ ≈ **0.14**.

### 4.2 Within-symbol normalization

BTCUSD and EURUSD have structurally different R-multiple distributions, so a feature merely
correlated with symbol identity (ATR percentile being the obvious candidate) could score
without carrying confidence information. Features **and** outcomes are rank-normalized
**within symbol** before pooling.

### 4.3 Purge and embargo

A signal near the 0.70 boundary has a forward window running into OOS. **H + 4 bars are purged
and embargoed at the boundary, per symbol**, so no training signal's outcome window overlaps
any test signal.

### 4.4 Multiplicity

**15 tests** — 5 (Family A) + 8 (Family B) + **2 placebos** — against the single primary
estimand, **Benjamini–Hochberg at q = 0.10 applied jointly across all 15**. No separate family
budgets: splitting the panel would let a weak Family B result borrow significance.

The placebos are **inside** the BH family rather than monitored alongside it. This makes the
void condition (§5.1, §5.3) well-defined — "a placebo appears in the rejected set" — and is
slightly conservative, which is the correct direction to err.

**Dependence structure, stated rather than glossed.** `composite_score` is a deterministic
function of the four other Family A factors, so those five tests are strongly positively
dependent. Benjamini–Hochberg controls FDR under positive regression dependence, so the
procedure remains valid — but it is *conservative* here, which means **a Family A null is more
trustworthy than a Family A hit**. The redundant component tests are kept deliberately: without
them, an individual factor scoring backwards (the inverted-direction row in §6) is undetectable,
and that is the only outcome of this study that would identify a live defect rather than a
missed opportunity.

**If more than one feature survives all of §4.5**, exactly one is promoted, ranked by
**economic-floor magnitude, not by p-value** — p-values under clustered inference are the
noisier quantity and ranking on them invites selection on sampling error. Remaining survivors
are recorded as secondary candidates, each requiring its own future gate. Pre-registering the
tie-break removes the opportunity to choose a favourite after seeing the results.

Robustness cells (H=24, fill-conditional, live-9 subset, per-symbol and per-year sign) apply
only to survivors and are excluded from the FDR count: they confirm an already-selected
hypothesis rather than offering new chances to find one.

### 4.5 Promotion criteria — all must hold

1. Survives **BH at q = 0.10** on IS under clustered inference.
2. Clears the **economic floor of 0.25R**, pegged to the repo's median round-trip cost gate
   because a confidence signal thinner than the cost of trading on it is not a confidence
   signal. Defined per feature type so it applies to the whole panel:
   - **Continuous** (1,2,3,4,7,8) — top-vs-bottom quintile `skew_H` spread. Quintiles are cut on
     **within-symbol ranks**, ties assigned to the lower group.
   - **Binary** (`displacement_bucket`, `pd_array`, `killzone`, feature 6) — difference between
     the two group means.
   - **Categorical / ordinal >2 levels** (`bias_class`, `composite_score`, feature 5) —
     **max-minus-min group mean**, with any group holding <30 signals excluded from the contrast
     so a thin cell cannot manufacture a spread.
3. **Confirms OOS** in the same direction.
4. **Sign consistency: ≥ 8/11 symbols and ≥ 3/4 years.** Matches this repo's existing gate
   standards. Note 2023 (n=399) and 2026 (n=278) are **partial years** — 2023 starts in June,
   2026 ends in June — so a year cell failing on either is reported with its n rather than
   treated as equivalent evidence to a full year. For **categorical** features, "sign" means the
   direction of the max-vs-min group contrast identified on IS, held fixed across cells.
5. **Agrees in sign on the live 9-symbol subset.**

---

## 5 · Calibration and validity controls

### 5.1 Permuted-outcome dry run (mandatory, runs first)

The entire pipeline runs on **outcomes shuffled within symbol**, before any real outcome is
touched. The observed false-positive rate must match nominal q. This validates calibration
**without consuming a look at the real data**.

### 5.2 Injected-signal recovery (replaces the circular positive control)

A **synthetic feature constructed as a known noisy function of the realised `skew_H`** is
injected as a 16th column: the within-symbol rank of `skew_H` blended with seeded noise so its
population Spearman ρ with `skew_H` is **0.15** — deliberately just above the ≈0.115 post-BH
detection threshold projected in §4.1. The pipeline must **reject its null under the same BH
procedure**, and its recovered ρ must fall inside the bootstrap CI around 0.15. Failure means
the pipeline cannot see an effect it was built to detect, and the run is void.

The injected column is excluded from the 15-test BH family (it is a diagnostic, not a
hypothesis) and is dropped before the real run's p-values are computed.

This replaces an earlier proposal to use the stop study's C/B cut as a positive control. That
control was **circular**: the C/B result was measured on *managed R* via `replay_managed`,
while this study's estimand is `skew_H`. Its absence could mean a broken pipeline **or** that
the stop study's §4 result was an exit-engine artifact — a substantive finding that would be
misread as a bug. The C/B comparison is retained as a **descriptive cross-check with no gate
authority**.

### 5.3 Void handling — bounded

A void (placebo survives, or injected signal not recovered) permits **exactly one**
re-specification. It must cite a **named procedural defect**, and both attempts appear in the
results document. **A second void ends the study as inconclusive.** Without this bound, "void →
re-specify" is unlimited re-looking at the same data.

### 5.4 No reimplementation of the grader

The screen **imports and calls `SignalGrader` from `src/analysis/signal_grader.py` directly**,
adapting each trade row into its `(decision, context, candle)` shape.

This is not a style preference. The existing offline mirror at `scripts/poc_sb_stops.py:549`
**has already drifted from the shipped grader** — it hardcodes the RR factor at 15 and omits
the epsilon tolerances and the degenerate-risk guard. Every conclusion in the stop study's §4
rests on that mirror. Calling the real class makes this a test of the code that actually runs;
a unit test pins the adapter so the drift cannot recur.

### 5.5 Adversarial review

The results document receives an **adversarial review before the verdict is recorded**. This
repo's repeated lesson is that a clean run and a green suite cannot falsify a claim, and that
review — not tests — caught the real defects on S004, S013, and the Aftershock kill-screen.

---

## 6 · Decision table

| Outcome | Meaning | Authorizes |
|---|---|---|
| **Void** — placebo survives or injected signal not recovered | Procedure miscalibrated | One bounded re-spec (§5.3). **No result reported.** Not patchable after the fact |
| **Flat** — nothing clears all of §4.5 | No exploitable confidence information at actionable resolution | Conviction-scaled risk **not built**. MIE programme closed with evidence; verdict recorded in `docs/research/` and ARSENAL. `SignalGrader` redesignated a **floor filter, not a confidence estimate**, and its 100-point presentation flagged as misleading |
| **PARTIAL** — clears BH + floor + OOS but **fails sign consistency** | Unstable | **Nothing. Recorded inconclusive; may not be re-tested on this data** |
| **Family A survives, positive direction** | Grader has real information, wrongly weighted | Reweight/retune the grader — config-scale, **its own confirmation gate** |
| **Family A survives, inverted direction** | A shipped factor is scoring **backwards** — it currently *rewards* the worse setup | Propose removing or inverting that factor. Higher-value than the positive case (it is a live defect, not a missed gain) and held to the same confirmation gate |
| **Feature 7 or 8 survives** | Grader destroys information at its thresholds | Replace those buckets with continuous scores — **its own confirmation gate** |
| **Family B survives** | Genuine confidence information exists, and the survivor **names the dimension** | Promote *that one feature* to a full gate: instrument `research_run.py`, fresh preregistered run on the 9-symbol frozen universe |

### 6.1 The ceiling is deliberate

No row authorizes building the MIE as proposed. The best result authorizes **one feature and
one confirmation gate** — the repo's standing funnel discipline (one candidate per research
cycle), not an extra hurdle invented here.

### 6.2 Conviction-scaled sizing is downstream and separate

This screen measures **entry skew**; sizing is a **portfolio-R** question. Even a surviving
feature must clear a distinct later gate: it must support ≥ 2 tiers each with adequate n, and a
tiered-sizing policy must beat flat sizing on a bootstrap 5% lower bound over the same signal
stream. Given §2.4, any viable ladder is **two tiers, not four**.

---

## 7 · Tests (`tests/unit`, stdlib unittest, TDD)

| Test | Why it has teeth |
|---|---|
| Adapter ↔ real `SignalGrader` equivalence over generated rows | Prevents recurrence of the mirror drift this study uncovered (§5.4) |
| **Look-ahead, features:** appending arbitrary future bars changes **no** feature value | A leaking feature otherwise surfaces only as an impossibly good result nobody questions |
| **Look-ahead, outcomes:** appending bars beyond the H-window changes **no** `skew_H` value | The horizon is as leakable as the features, and an unbounded window would silently import future information into the outcome |
| `MFE_H` truncation: a fixture that prints MAE 1R **then** MFE 3R scores `skew_H = −1.0`, not `+2.0` | This is the single defect most likely to be "simplified away" during implementation, and it inverts the ranking of exactly the trades a confidence score exists to separate |
| An unfilled signal (level never touched within W) scores exactly `0.0` and **remains in the sample** | Dropping it is the natural implementation, and it silently selects on a post-signal event |
| MFE/MAE on hand-built M5 fixtures, including a bar where both 2R-favourable and 1R-adverse occur | Path ordering is the entire reason for measuring on M5; only an order-sensitive fixture proves it |
| Purge/embargo — a signal whose window crosses the split appears in **neither** set | Leakage is silent and would inflate OOS |
| BH procedure against a known-answer fixture | An off-by-one in the BH rank is invisible in output |
| Within-symbol rank normalization invariant to symbol-level rescaling | Directly tests the confound it exists to remove (§4.2) |
| Seeded block bootstrap and placebo features reproduce bit-identically | A preregistered result must be re-derivable |

---

## 8 · Deliverables

- `docs/research/2026-08-04-confidence-skew-screen.md` — §§1–3 (hypothesis, panel, criteria)
  **committed before the run**; §§4–6 filled from results. Follows the fill-model-correction
  doc's structure, including its "run set fixed, measurement pending" status marker.
- `scripts/confidence_skew_screen.py` — the analysis, **hash-recorded in the prereg doc**.
- The regenerated population per §2.7 (corrected resolver, expired signals included), plus the
  reconciliation report against the inherited `sb_stops_trades_H1.csv`.
- Dataset frozen via `scripts/freeze_gate_dataset.py`; artifacts under
  `data/results/confidence_screen/`.
- `tests/unit/test_confidence_skew_screen.py`.
- `ARSENAL.md` and `IMPROVEMENTS.md` updated with the verdict either way.

**Effort:** ~3–4 days. Revised twice during design, both times upward and both times for
substantive reasons rather than padding: first for the §4–§5 hardening (cluster bootstrap,
permuted-outcome dry run, injected-signal recovery, look-ahead tests), then for the §2.7
population regeneration. The original ~2-day estimate assumed an inherited dataset that turned
out to have a biased sampling frame.

**Most likely outcome: Flat** — and that is the outcome with the highest value per unit cost,
because it retires a proposed rewrite of 70–90% of the decision layer for a few days of work.

---

## Appendix A · Reality check on the originating proposal

Recorded so the programme is not re-proposed on the same premises.

- **`Intent` is already taken, and means the opposite thing.** `src/arbiter/intent.py` defines
  `Intent` as *a strategy's request to trade*, resolved by a five-rule `Arbiter` with
  `IntentEmitted`/`IntentBlocked` events. A "Market Intent Engine" meaning *inferred market
  state* would collide with the execution path's vocabulary. Any future version needs a
  different name.
- **Several proposed components already exist under other names.** There is no
  `Indicators → Strategy` layer to replace: there is a memoized DAG (`FeatureBus`), a
  manifest/registry already carrying capability metadata (`family`, `timeframe`, `requires`,
  `priority`, `honors_htf_bias`, `status`), a deterministic arbiter, and a replay kernel. The
  proposed "Strategy Selection Layer" is largely the Arbiter plus fields that already exist.
- **"Refactor every strategy" is four files, one of which trades live.** A selector routing
  intent→strategy would arbitrate a portfolio of one.
- **Half the proposal is already decomposed in ARSENAL.md as individually-gateable
  candidates:** Trinity (HMM regime allocator, overlay only), Rubicon (BOCPD regime break),
  Shannon Gate (entropy deficit — explicitly *"architect as a FeatureBus filter, not a
  strategy"*), Walclock (tick-volume effort). That decomposition was deliberate, so each piece
  can be falsified alone.
- **Three hard blockers make parts unbuildable today, not merely expensive.** Weekly/Monthly
  layers: D1 history is 775 bars/symbol and `collect_signals` raises `KeyError` on H4/D1 (P10
  unstarted). Participant Intent / delta / "aggressive buying": FBS MT5 supplies tick volume
  only — no real volume, no delta, no book — and the tick volume is itself unaudited, while the
  ask price is transmitted and discarded (RISK-07). STRAT-01: the exit engine producing the
  sign of the edge has never been executed by a research harness, so a NO-GO on a layer built
  above it would not identify which layer failed.
- **The proposal contained no falsifiable claim, baseline, cost screen, or kill criterion**,
  and stated its success metric only after the rewrite. Against a measured base rate of ≈1
  survivor in 9, and with every H1 directional model this repo has gated returning NO-GO
  (Gyroscope v1, MaSlopeBaseline, Unicorn, CRT, ICT_OTE, MTF-PB v2, Aftershock), that ordering
  is backwards. This spec inverts it: falsify the premise first, in a few days.
