# WALCLOCK — throughput/queue rhythm model

> **Status:** candidate (Wave 3, data-quality probe first) · **Family:** queueing-theory
> effort-per-distance divergence · **Timeframe:** H1 (tick volume) ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §11 (WALCLOCK) ·
> **Doc version:** 2026-08-01

## 1. Thesis and return source

Markets process order flow like a service system; tick volume per unit of price progress is a
service-rate proxy borrowed from queueing/logistics theory (throughput-per-output, Little's Law
framing). Walclock defines an "effort-per-distance" index — tick volume required per unit of price
progress, rolling-normalized — and reads divergences between that effort trend and the price trend:
sustained rising effort while price grinds in one direction (the "conveyor jamming," absorption) is
read as a stall-and-revert signal; effort collapsing while price holds is read as continuation
(frictionless flow). The brainstorm is explicit this is a made-deterministic, normalized version of
the classic volume/price-efficiency family (§11.3), not a wholly new phenomenon — the honest novelty
is the queueing-theory framing and the deterministic normalization, not the underlying inefficiency
claim.

## 2. Evidence base

Walclock has **no dedicated backtest, gate doc, or existence study yet** — this is an architecture
document only. No Walclock-specific numbers exist to cite.

| Source | Finding | Relevance |
|---|---|---|
| Brainstorm §11.2, §11.10 | "Its existence risk is that MT5 *tick* volume is a noisy proxy — which is exactly what stage-(b) tests" | Names the central open question up front: whether the data channel itself carries signal, independent of any strategy logic built on top |
| Brainstorm §12 comparative matrix, row 11 | Cost survival **2/5**, existence risk **2/5** — among the lowest-rated candidates on both axes | Sets a low prior; only Constellation and Shannon Gate score as low or lower on existence risk |
| Brainstorm §11.13 | "Family adjacency to well-known volume divergence ideas" listed as a named weakness | Signals this is not a defensibly unique inefficiency — success depends on execution/normalization quality, not novelty |
| Brief §7 hard constraints | The cost bar is brutal: FBS spreads mean M5/M15 ATR-multiple stops are dead; only the H1-and-above, wide-stop, low-frequency profile has ever validated in this repo (SilverBullet) | Walclock runs at H1 — inside the validatable envelope by cadence, but its self-rated 2/5 cost survival suggests the amplitude of its signal, not the timeframe, is the risk |

**Adverse evidence, stated plainly:** tick-volume unreliability per broker/session is named as the
primary failure mode (§11.10) — if stage-(b) shows tick volume carries no signal at FBS, the
brainstorm calls for a clean NO-GO, not further tuning. Divergences can resolve by acceleration
rather than reversal, which the state machine partially handles (a stall-confirm stage before entry)
but does not eliminate. There is no existing repo precedent — validated or NO-GO'd — for any
volume-based strategy; Walclock would be the first test of whether MT5 tick volume carries usable
signal at all in this system.

**EXP-0 implication:** the exit engine amplifies real entry edge (+0.231R) but does not subsidise a
placebo entry (+0.075R on random entries; full placebo −0.249R vs real +0.109R, 2026-07-31). Given
Walclock's low existence-risk rating and unproven data channel, the A/B-against-bar-range
requirement in §6 below is the direct analogue of EXP-0's discipline: a real entry must be shown to
add information over a naive baseline (bar range) before any exit-engine benefit can be assumed to
transfer to it, exactly as EXP-0 required real entries to beat marginal-matched random entries by
their own selectivity, not by the exit engine's help.

## 3. Signal specification

As specified in the brainstorm (§11.5–§11.9), not yet implemented:

- **Observables:** tick volume, `|Δprice|`, effort index `E = vol / (|Δprice| / ATR)`, rolling
  z-scored, price trend sign (5-bar), spread.
- **State machine:** `FLOW MONITOR → DIVERGENCE (E-z > 2 against 5-bar price trend, sustained 3+
  bars) → STALL CONFIRM (progress/bar drops below its median) → ENTRY (fade the jammed direction) →
  EXIT (E normalizes | target hit | stop hit)`. A mirrored `CONTINUATION` mode triggers on `E-z <
  −1` with the trend (effort collapsing while price holds).
- **Entry:** fade mode — enter against the jammed price direction once STALL CONFIRM validates
  (progress/bar below median) following a sustained 3+ bar effort divergence. Continuation mode
  enters with the trend on effort collapse.
- **Stop:** vol-scaled, placed beyond the grind's extreme.
- **Target / exit:** effort index normalizing back toward baseline, a fixed target, or a stop —
  first-hit; exact target formula not specified in the source and needs to be defined during
  strategy design (not invented here).
- **Filter:** only trades where the grind's height clears the cost screen; news lockout required
  (§11.13 — dormant in clean impulsive moves, needs a lockout around news to avoid misreading
  news-driven volume spikes as "effort").
- **Universe:** not yet chosen.

## 4. Architecture integration

- **Manifest (sketch, not yet created):**
  ```yaml
  # config/manifests/walclock.yaml
  id: walclock
  version: "0.1.0"
  class_path: "src.strategies.models.walclock:WalclockStrategy"
  family: stat
  timeframe: H1
  requires: []           # raw OHLC + tick volume only
  status: research
  priority: 80
  honors_htf_bias: false  # effort-price divergence is its own regime read
  ```
- **Class placement:** `src/strategies/models/walclock.py` — `WalclockStrategy(BaseStrategy)`, with
  the effort-index math in a pure module, e.g. `src/analysis/effort_index.py` (mirrors the
  Gyroscope shell/math split). `validate_data(df, min_length=warmup, check_smc=False)` — raw OHLC +
  tick volume only, no SMC pack dependency. **Data availability check needed before build:** the
  brief confirms MT5 tick volume is available via the bridge, but its presence/format in the live
  FeatureBus-enriched `df` used by `on_new_candle` has not been verified in this document — must be
  confirmed against `HEARTBEAT`/`HISTORY` message fields before assuming a column exists.
- **Config block (sketch):**
  ```yaml
  strategies:
    walclock:
      enabled: false
      timeframe: H1
      effort_z_window: 100        # TBD, rolling normalization window
      divergence_z_threshold: 2.0
      continuation_z_threshold: -1.0
      divergence_min_bars: 3
      pairs: []                    # TBD post cost-screen
  ```
- **FeatureBus resources:** none required for v1 (raw OHLC + tick volume, self-contained effort-
  index estimator). If proven useful, the effort index itself could later register as a shared
  FeatureBus resource (e.g. `flow.effort_index`, scope `symbol_tf`) for other strategies/the grader
  to consume — analogous to how the brief frames Shannon Gate's `info.entropy_deficit` — but that is
  a post-validation extension, not part of the v1 build.
- **Order types:** MARKET, consistent with a divergence-confirmation entry (not a resting-limit
  thesis like Spring's stretch-fade).
- **Grading path (P8 statement):** non-SMC signal — loses the same 65/100 displacement/
  premium-discount/killzone points as the other Wave 3 stat candidates, capped at 35/100 under
  `honors_htf_bias: false`. Needs the same grader accommodation named across this batch (Spring,
  Gumbel Fade) before it can clear `min_grade: B`.
- **HTF-bias stance:** `honors_htf_bias: false`.
- **Exit profile:** not fully specified by the source (target formula undefined) — this is a gap
  that must be closed during strategy design, not assumed to default to the standard ratchet. Given
  the fade/continuation dual-mode design and effort-normalization exit condition, this likely also
  needs a **per-strategy exit profile (P7)**, shared infrastructure with Spring and Gumbel Fade,
  rather than the default continuation-shaped ratchet.
- **Risk interaction:** standard broker-spec sizing off the vol-scaled stop; no additional
  portfolio-cap requirement identified in the source (unlike Spring's correlated-fades cap or Gumbel
  Fade's cluster cap).

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| — (new) | Tick-volume data-quality audit at FBS (per-session normalization, reliability check) | The brainstorm frames this as the central open question — "if stage-(b) shows tick volume carries no signal at FBS, NO-GO cleanly" (§11.10) — and notes stage-(b) "doubles as" this audit, i.e. it is worth doing regardless of Walclock's fate | Low-medium — largely a data-analysis task against existing `data/history/` tick-volume columns, no platform change needed |
| P8 | Grader accommodation for non-SMC signals | Structurally capped at 35/100 without it | Shared with Spring/Gumbel Fade |
| P7 | Per-strategy exit profile | Exit thesis (effort-normalization / target / stop) undefined against the default ratchet | Shared with Spring/Gumbel Fade; additionally needs the target formula itself defined, which is Walclock-specific work |
| News calendar / lockout | Hard news lockout for effort-index misreads around news | Named explicitly as required (§11.13); no confirmed lockout mechanism exists elsewhere in the repo — treat as unverified until confirmed | Unclear |
| — (verify) | Confirm tick-volume column reaches `on_new_candle`'s `df` in the live FeatureBus-enriched frame | Not confirmed in this document; the bridge provides tick volume per the brief, but live-frame availability is a separate question from raw data availability | Low — verification, not build |

## 6. Validation plan

TVP (`docs/research/2026-07-12-novel-arsenal-brainstorm.md` §0) applies, with the brainstorm's
Walclock-specific addition (§11.17):

- **Stage (b) doubles as a data-quality audit** of FBS tick volume — this has value independent of
  Walclock's eventual GO/NO-GO and is recommended regardless of whether the strategy proceeds
  further.
- **A/B against bar-range is mandatory:** the identical rule set (divergence thresholds, stall
  confirm, entry/exit logic) must be re-run driven by bar range instead of tick volume. Volume must
  demonstrably add information over range alone, or the strategy contributes nothing distinct from
  a simpler range-based rule — this is not optional and should be treated as a kill criterion on its
  own, not a nice-to-have comparison.
- **Data:** 3-yr H1 history with tick volume (available per brief §8/§9, `data/history/`); spread
  data for the cost screen (subject to the same `context['spread']` non-existence caveat as Spring —
  P6/RISK-07).
- **Baseline:** the bar-range A/B *is* the baseline requirement here, in addition to the repo's
  standard baseline culture (MaSlopeBaseline / Almanac).
- **Kill criteria:** tick volume showing no signal in the stage-(b) data-quality audit; the A/B test
  failing to show volume adding information over range; pooled net expectancy negative or
  sign-unstable across ±30% sweeps of the divergence/continuation thresholds.
- **What cannot be validated with current data:** nothing structurally blocks a first-pass stage-(b)
  audit — H1 tick volume for 3 years is available today, unlike Gumbel Fade's H4/D1 blocker. The one
  open unknown is whether tick volume survives from the bridge into the live `on_new_candle` frame
  unchanged (§5) — that must be confirmed before assuming a backtest and a live run would see the
  same feature.

## 7. Failure modes and monitoring

- **Proxy failure (primary risk):** MT5 tick volume may simply not carry the claimed signal, or may
  be broker/session-specific noise. This is the headline existence risk and is explicitly what
  stage-(b) is designed to catch early and cheaply.
- **Divergence resolving by acceleration, not reversal:** partially mitigated by the stall-confirm
  stage and a stop placed beyond the grind's extreme, but not eliminated — monitor realized win rate
  on divergence-triggered fades specifically, separate from continuation-mode entries, since they
  have opposite failure profiles.
- **News-driven volume spikes misread as "effort":** requires a hard lockout; without it, news bars
  would systematically trigger false divergence signals.
- **Session-normalization drift:** effort-per-distance must be normalized per session/broker; a
  pooled normalization would misprice sessions with structurally different tick-volume levels.
- **Ops:** standard fail-safe lot=0 on missing specs; no strategy-specific ops risk beyond the
  shared portfolio-cap and Sync Guard behaviour.

## 8. Verdict and sequencing

Candidate, but positioned explicitly as a **data-quality probe first**, not a strategy build. Given
the 2/5 cost-survival and 2/5 existence-risk self-ratings — among the lowest on the Wave 3
shortlist — the responsible sequencing is to run the tick-volume data-quality audit (stage-b) before
any commitment to strategy design work, since that audit is valuable on its own regardless of
Walclock's fate (it tells the whole arsenal whether tick volume is a usable data channel at all).
Recommended sequence: (1) run the stage-(b) tick-volume audit + the mandatory bar-range A/B as a
single combined study — both are cheap, need only existing H1 history, and together answer the
existence question directly; (2) if tick volume shows no incremental information over bar range,
NO-GO cleanly and do not proceed to a strategy build; (3) only if the A/B favours volume, design the
target/exit formula (currently unspecified) and the P7 exit profile, then pre-register a full gate.
Not on the critical path for Spring, Gumbel Fade, or Shannon Gate; its main shared value if it
survives stage (b) is confirming (or ruling out) tick volume as a usable FeatureBus data channel for
the rest of the arsenal.
