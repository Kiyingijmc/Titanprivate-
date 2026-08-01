# SHANNON GATE — entropy-collapse persistence detector

> **Status:** candidate — expected NO-GO standalone / ADOPT as arsenal-wide filter ·
> **Family:** information-theory predictability detector (primarily a FeatureBus filter, secondarily
> a trading arm) · **Timeframe:** H1/M15 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §6 (SHANNON GATE) ·
> **Doc version:** 2026-08-01

## 1. Thesis and return source

Most of the time a market's return-sign sequence is close to maximally entropic (incompressible) —
predictability is episodic, not constant. Shannon Gate encodes recent H1 bars as a symbol stream
(return sign + magnitude tercile → a 6-symbol alphabet) and computes a rolling entropy-rate estimate
(block entropy or LZ76 complexity), normalized against a surrogate (shuffled) distribution. When
measured entropy drops significantly below the surrogate baseline, structure demonstrably exists;
the "entropy deficit" (a z-score against the surrogate mean/sd) is the signal, and the direction
traded is read from the same empirical context-tree statistics that produced the deficit. The
brainstorm's own framing is decisive here: "the gate's main output is 'don't trade'" (§6.3) — the
return source, if any exists at all, is concentrating the *decision to act* into the minority of
hours where predictability is measured to exist, not a novel directional edge.

**This document treats the standalone trading arm as a cheap falsification study, and architects the
entropy-deficit meter primarily as a FeatureBus resource** — per the brief's explicit framing —
because the brainstorm's own honest assessment (§6.10–§6.12, §13) is that the trading arm is the
least likely of the four Wave 3 candidates in this batch to survive on its own, while the meter
itself has standing value to the rest of the arsenal regardless of that outcome.

## 2. Evidence base

Shannon Gate has **no dedicated backtest, gate doc, or entropy-deficit measurement yet** — this is
an architecture document only. No Shannon-Gate-specific numbers exist to cite.

| Source | Finding | Relevance |
|---|---|---|
| Brainstorm §12 comparative matrix, row 6 | Cost survival **1/5 standalone** (the single worst rating of any candidate on the entire matrix, across all 11 concepts, including the graveyard-adjacent ones), rising to **4/5 as a filter**; existence risk **2/5** | The self-rating is the most pessimistic on the board for standalone trading — this is not a hedge, it is the concept's own designer-assigned worst case |
| Brainstorm §6.10 | "**Cost death is the default expectation** — 1–3 bar H1 holds at retail spread is exactly the profile our OTE research killed" | Direct citation to the repo's own adjudicated NO-GO precedent as the expected outcome, not a hypothetical risk |
| `docs/research/2026-07-11-ote-canonical-results.md` | OTE canonical NO-GO, −0.158R pooled gross-negative, at similar short-hold H1 cadence | The concrete precedent Shannon Gate's own documentation points to as its likely fate |
| Brainstorm §6.17, §13 | "Likely outcome to record: NO-GO standalone, ADOPT as a regime filter" (explicit pre-registered expected outcome); §13: "Shannon Gate most likely matures into a shared 'don't trade now' filter" | The source material itself pre-commits to this framing before any data has been collected — this document follows that framing rather than treating standalone viability as an open question |

**Adverse evidence, stated plainly:** per-trade edge is thin by construction (an entropy deficit is
a statistical tilt, not a large directional move), which is cost-fragile and "likely fatal
standalone at our costs" (§6.12, verbatim). Symbolization choices (alphabet size, tercile
boundaries, block length) are researcher degrees of freedom that create real multiple-comparisons
risk in context selection — the brainstorm requires surrogate-based significance and pre-registered
contexts specifically to guard against this (§6.10). The entropy estimator's variance at feasible
sample sizes needs a block-length sensitivity study before any results can be trusted (§6.10).

**EXP-0 implication:** the exit engine amplifies real entry edge (+0.231R) but does not subsidise a
placebo entry (+0.075R on random entries; full placebo −0.249R vs real +0.109R, 2026-07-31). Shannon
Gate's 1–3 bar holding profile is explicitly the profile EXP-0's predecessor research (OTE) already
killed — a thin per-trade edge held for 1–3 bars is close to the least favourable shape for the exit
engine to amplify (the ratchet/runner needs room to work; a fixed-horizon 1–3 bar exit gives it
almost none). This is the single strongest reason to expect standalone NO-GO, independent of whether
the entropy deficit itself is real.

## 3. Signal specification

As specified in the brainstorm (§6.5–§6.9), not yet implemented. This section covers the
**standalone trading arm** (the falsification study); §4 covers the FeatureBus resource, which is
architecturally primary.

- **Encoding:** last N H1 bars as a symbol stream — return sign + magnitude tercile → a 6-symbol
  alphabet.
- **Entropy estimate:** rolling block entropy or LZ76 complexity, normalized against a shuffled-
  surrogate ensemble (~100 shuffles per the production-blueprint-adjacent estimate in §6.15).
  Output: "entropy deficit" — a z-score of measured entropy vs the surrogate mean/sd.
- **State machine:** `EFFICIENT (deficit z > −2) → STRUCTURE DETECTED (z ≤ −2 for 2 consecutive
  bars) → PATTERN EXTRACTION (context tree: is there a conditional edge > p_min?) → ENTRY (trade the
  conditional direction each time its context appears) → per-trade EXIT (next-bar or fixed n-bar
  horizon) → GATE CLOSES (z recovers) → EFFICIENT`.
- **Entry:** gate open (structure detected) + current context's empirical continuation probability
  ≥ `p_min` (candidate 0.62 with ≥30 observations) + expected move clears the cost screen → enter
  that direction at bar open.
- **Exit:** fixed-horizon (the pattern's own horizon, typically next 1–3 bars); vol-scaled SL as a
  disaster stop only, not the primary exit mechanism. Gate closing (entropy recovering) flattens
  immediately. This is explicitly "a short-holding, statistical-edge accumulator, not a runner
  system" (§6.8).
- **Risk model:** small fixed R per trade (the edge is thin per event, harvested repeatedly across
  open-gate windows); a daily loss cap per symbol; gate-close flatten. The brainstorm's own summary:
  "the whole risk architecture is 'many small bets only while the meter says the casino is
  beatable'" (§6.9).
- **Universe:** not specified; would need a per-symbol context tree, so likely starts on a small
  subset for the falsification study rather than the full book.

## 4. Architecture integration

The primary deliverable is the **FeatureBus resource**, per the brief's explicit direction. The
standalone strategy class is secondary and exists mainly to falsify (or, less likely, validate) the
trading-arm hypothesis cheaply.

- **FeatureBus resource (primary):**
  ```python
  # src/features/packs/entropy_pack.py (sketch — does not exist yet)
  ResourceSpec(
      name="info.entropy_deficit",
      deps=(),                 # raw OHLC only; no dependency on the SMC pack
      scope="symbol_tf",
      compute=compute_entropy_deficit,   # pure function: symbolize → block/LZ entropy → surrogate z-score
      version="1",
  )
  ```
  Registering `info.entropy_deficit` (and, if useful, the underlying dominant context-conditional
  probability as a second resource, e.g. `info.context_edge_prob`) makes the gate consumable by
  **other strategies and the grader**, not just a standalone strategy class — e.g. SilverBullet or
  Gyroscope could gate entries on `info.entropy_deficit` clearing a threshold, and
  `SignalGrader.grade()` could eventually incorporate it as a scoring factor (subject to the P8
  grader-redesign discussion below). This reuse is the actual point of building Shannon Gate at all,
  per the brainstorm's own strengths assessment (§6.11): "the entropy meter is a valuable
  *arsenal-wide filter* even if standalone trading fails."
- **Class placement (secondary, falsification-study arm):** `src/strategies/models/shannon_gate.py`
  — `ShannonGateStrategy(BaseStrategy)`, consuming `info.entropy_deficit` (and the context-edge
  resource) from the FeatureBus rather than recomputing entropy itself — this is the correct
  dependency direction: the resource is primary infrastructure, the strategy is one consumer of it.
  Pure entropy/LZ76/surrogate math lives in `src/analysis/entropy_persistence.py`, matching the
  Gyroscope shell/math split.
- **Manifest (sketch, standalone arm only):**
  ```yaml
  # config/manifests/shannon_gate.yaml
  id: shannon_gate
  version: "0.1.0"
  class_path: "src.strategies.models.shannon_gate:ShannonGateStrategy"
  family: stat
  timeframe: H1            # or M15 — TBD, brainstorm names H1/M15 as the timeframe
  requires: [info.entropy_deficit]
  status: research
  priority: 85              # lowest priority of this Wave 3 batch, reflecting expected NO-GO
  honors_htf_bias: false     # entropy structure is regime-orthogonal per the brainstorm (§6.13)
  ```
- **Config block (sketch):**
  ```yaml
  strategies:
    shannon_gate:
      enabled: false
      timeframe: H1
      alphabet_size: 6           # return sign x magnitude tercile
      block_length: 200          # symbol window for entropy estimate
      surrogate_count: 100
      deficit_z_threshold: -2.0
      deficit_confirm_bars: 2
      p_min: 0.62
      p_min_min_obs: 30
      exit_horizon_bars: 3       # 1-3 bar fixed horizon
      pairs: []                  # small subset for the falsification study
  ```
- **Order types:** MARKET, matching the fixed-horizon short-hold thesis (no time for a resting
  LIMIT to matter at a 1–3 bar horizon).
- **Grading path (P8 statement):** as a standalone strategy, non-SMC — capped at 35/100 like the
  other Wave 3 candidates, structurally below `min_grade: B`, shared grader-accommodation
  prerequisite. **As a FeatureBus resource**, Shannon Gate has a second, more consequential grading
  interaction: if `info.entropy_deficit` is later wired into `SignalGrader.grade()` as a scoring
  factor for *other* strategies, that is a grader redesign beyond the current
  displacement/premium-discount/killzone/HTF-alignment/R:R factor set (`src/analysis/
  signal_grader.py`) — a larger, arsenal-wide change, out of scope for this document but worth
  flagging as the natural next step if the resource proves useful.
- **HTF-bias stance:** `honors_htf_bias: false` for the standalone arm — entropy structure is
  framed as regime-agnostic (predictability is episodic across trend/range labels alike, §6.13).
- **Exit profile:** fixed 1–3 bar horizon, vol-scaled disaster-stop only, gate-close flatten. This
  is the shortest, most rigid exit thesis of any Wave 3 candidate and is maximally distant from the
  default ratchet/runner (which needs room and time to harvest a continuation move) — needs the
  **per-strategy exit profile (P7)**, and is arguably the strongest single argument in this whole
  batch for why P7 must exist before any of these four candidates can go live, since a 1–3 bar hold
  under the default ratchet ladder would not even reach the 38.2% BE trigger in most cases.
- **Risk interaction:** small fixed R, daily per-symbol loss cap — a risk shape not currently
  expressed in `RiskManager`/`ExposureManager` (which caps total open risk and position counts, not
  a rolling daily per-symbol loss budget per strategy); would need new plumbing if this ever reaches
  a live build.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| — (new) | `info.entropy_deficit` FeatureBus resource (`src/features/packs/entropy_pack.py`) | The primary deliverable of this doc — makes the entropy meter consumable arsenal-wide, independent of the standalone strategy's fate | Low-moderate: block/LZ76 entropy + surrogate ensemble on a 200-symbol window is "low-moderate" per the brainstorm's own compute estimate (§6.15) |
| P7 | Per-strategy exit profile (flat, 1–3 bar horizon, disaster-stop only) | The most extreme exit-profile mismatch with the default ratchet in this batch of four docs | Shared with Spring/Gumbel Fade/Walclock |
| P8 | Grader accommodation for non-SMC signals (standalone arm); separately, a possible grader-factor extension to consume `info.entropy_deficit` | Standalone arm capped at 35/100 without the first; the second is a larger, unscoped arsenal-wide change | Shared (first item); unscoped (second item) |
| Multiple-comparisons controls | Surrogate-based significance testing + pre-registered symbolization/context set, done grader-mirror style as in the OTE rig | Named explicitly as required by the brainstorm (§6.10) to prevent context-selection overfitting | Low — methodology discipline, not new platform infrastructure |
| Symbolization/block-length sensitivity study | Confirm entropy estimator variance is acceptable at feasible sample sizes | Named explicitly as a failure mode (§6.10) | Low — analysis task |

## 6. Validation plan

TVP (`docs/research/2026-07-12-novel-arsenal-brainstorm.md` §0) applies, with the brainstorm's
Shannon-Gate-specific addition (§6.17):

- **Stage (b) is the expected kill point:** measure the gross conditional edge (context-tree
  continuation probability's implied move) vs 2× spread *before* any backtest of the standalone
  trading arm. Given the 1/5 self-rated cost survival and the direct OTE-precedent citation (§6.10),
  this is expected to fail — that expectation should be stated in the pre-registered gate itself,
  not discovered after the fact.
- **Pre-registration discipline:** symbolization scheme (alphabet, tercile boundaries, block length)
  and the context set must be pre-registered *before* looking at conditional statistics — mirroring
  the grader-mirror discipline used in the OTE rig — specifically to prevent researcher degrees of
  freedom in symbolization from manufacturing an apparent edge.
- **Surrogate-based significance:** the entropy-deficit z-score itself, and the context-tree
  conditional probabilities, must be validated against a shuffled-surrogate null, not just an
  in-sample threshold.
- **Data:** OHLC H1/M15 (available, `data/history/`); spread (subject to the same
  `context['spread']` non-existence caveat as the rest of this batch — P6/RISK-07).
- **Baseline:** standard repo baseline culture (MaSlopeBaseline / Almanac) applies to the standalone
  arm if it proceeds past stage (b); for the FeatureBus resource itself, the relevant "baseline" is
  whether it adds discriminative power over strategies' existing filters when used as a gate — a
  separate, resource-level validation from the standalone-strategy backtest.
- **Kill criteria (standalone arm):** stage-(b) gross-edge-vs-2×-spread failure (expected); failure
  of the pre-registered surrogate significance test; multiple-comparisons-adjusted context edges not
  surviving out-of-sample.
- **Resource-level validation (the actually-expected path):** replay history, catalogue `STRUCTURE
  DETECTED` episodes, and measure whether *other* strategies' (e.g. SilverBullet's) forward
  performance differs materially inside vs outside those episodes — this is the direct test of the
  filter's arsenal-wide value and does not require the standalone strategy class to exist at all.
- **What cannot be validated with current data:** nothing structurally blocks stage (b) — H1/M15
  history is available today. The open question is entirely about whether the entropy-deficit
  signal is real, not about data availability.

## 7. Failure modes and monitoring

- **Cost death (expected, primary):** 1–3 bar H1 holds at retail spread is named directly as the
  profile the OTE research already killed. If stage (b) confirms this, the standalone arm should be
  recorded as NO-GO and not carried forward — the brainstorm pre-commits to this outcome.
- **Multiple-comparisons overfitting:** symbolization and context-selection choices are researcher
  degrees of freedom; guarded by pre-registration and surrogate significance, but this remains the
  most likely source of a false-positive "edge" if discipline lapses.
- **Entropy estimator variance:** block-length and window-size choices trade estimator variance
  against responsiveness; needs its own sensitivity study before any result is trusted.
- **Resource-level failure mode:** even if the standalone arm is NO-GO, the FeatureBus resource
  could still fail to show discriminative power when tested as a filter on other strategies — that
  is a distinct, separately falsifiable outcome and should not be assumed to succeed just because
  the standalone arm failed for cost reasons rather than existence reasons.
- **Ops:** standard fail-safe lot=0 on missing specs; no strategy-specific ops risk beyond the
  shared portfolio-cap and Sync Guard behaviour, if the standalone arm is ever built.

## 8. Verdict and sequencing

The honest expected outcome, stated plainly per the brief's own direction: **NO-GO standalone,
ADOPT as an arsenal-wide filter.** This is not a hedge — it is the brainstorm's own pre-registered
expectation (§6.17, §13), reinforced by the worst standalone cost-survival self-rating on the entire
comparative matrix (1/5) and a direct citation to the repo's own OTE NO-GO as the expected fate.
Recommended sequencing: (1) build `info.entropy_deficit` as a FeatureBus resource first — this is
the primary deliverable, is low-moderate effort, and has value independent of any strategy's
fate; (2) run the resource-level validation (catalogue `STRUCTURE DETECTED` episodes, compare other
strategies' forward performance inside vs outside them) — this is the test that actually matters;
(3) run the standalone-arm stage-(b) cost screen as a cheap, fast falsification study in parallel —
expect it to fail and record it cleanly as NO-GO rather than iterating on it; (4) only pursue a
grader-level integration (`SignalGrader` consuming `info.entropy_deficit`) if the resource-level
validation in step 2 shows real discriminative power — that is a separate, larger, unscoped
arsenal-wide change and should not be bundled into this candidate's own gate. Sequencing relative to
the rest of Wave 3: Shannon Gate's resource-first framing makes it structurally different from
Spring, Gumbel Fade, and Walclock (all pure strategy candidates) — it is closer in kind to Antibody
(defensive/infrastructure module) than to the three trading candidates in this batch, and should be
resourced accordingly.
