# GUMBEL FADE — extreme value theory exhaustion model

> **Status:** candidate (Wave 3, slow-burner) · **Family:** extreme-value-theory exhaustion fade ·
> **Timeframe:** H4/D1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §7 (GUMBEL FADE) ·
> **Doc version:** 2026-08-01

## 1. Thesis and return source

Multi-day directional runs that reach *regime-adjusted* tail extremes with a thin tail shape revert
partially, driven by position-unwinding/profit-taking flows. The novel discipline is measuring
"extreme" correctly: rolling Generalized Pareto Distribution (GPD) fits on H4/D1 peaks-over-threshold
give an exceedance probability adapted to the current regime's actual tail shape (ξ), rather than a
fixed z-score that implicitly assumes Gaussian tails — exactly wrong where it matters (brainstorm
§7.3–§7.4). The ξ estimate is itself the regime gate: fade only when ξ̂ is low (thin-tailed), because
in fat-tail regimes extremes beget extremes and fading is statistically wrong. The return source is
this regime-conditional discipline, not "big moves revert" as a blanket rule.

## 2. Evidence base

Gumbel Fade has **no dedicated backtest or gate doc yet** — this is an architecture document only.
Figures below are priors and self-ratings from the brainstorm, not Gumbel-Fade-specific measurements.

| Source | Finding | Relevance |
|---|---|---|
| Brainstorm §12 comparative matrix, row 7 | Cost survival **5/5** (tied for best on the board, with Aftershock) | H4/D1 cadence makes spread-as-fraction-of-move small by construction — the brainstorm calls this "the opposite of our OTE problem" (§7.11) |
| Brainstorm §13 ranked shortlist | "Gumbel Fade is the best 'slow burner' (start collecting its H4/D1 event studies in the background)" — explicit honorable mention | Directly actionable now, independent of code |
| `docs/research/2026-07-11-ote-canonical-results.md` | OTE canonical NO-GO at −0.158R pooled, gross-negative at H1-and-below cadence | The cost-death mode that killed OTE is structurally absent at H4/D1 scale — this is the basis for the 5/5 cost-survival self-rating, not an independent Gumbel-Fade result |
| Brief §7 / §8 data constraint | D1 ≈ 775 bars/symbol; `collect_signals` (research harness) supports only M15/H1 resampling — **H4/D1 raise a `KeyError` today** | This is the identical infrastructure blocker Anchor-class H4/D1 candidates share; Gumbel Fade cannot be backtested on the live research harness until P10 lands |

**Adverse evidence, stated plainly:** trade count is very low by construction (multi-day tail events
are rare) — the brainstorm calls out that multi-year validation and slow live confirmation are
required (§7.12). The strategy is counter-trend by nature, "the hard side" psychologically and
statistically (§7.12). Rolling EVT fits are data-hungry; peaks-over-threshold (POT) needs "many
exceedances," which is in direct tension with D1's 775-bar sample depth (brief §8) — Gumbel Fade's
own data appetite and the repo's thinnest-available timeframe are in conflict. GPD threshold choice
(POT u) is a known sensitivity point requiring standard mean-residual-life diagnostics, done once
in-sample (§7.10).

**EXP-0 implication:** the exit engine amplifies real edge (+0.231R) but does not subsidise a
placebo entry (+0.075R on random entries; full placebo −0.249R vs real +0.109R, 2026-07-31). At
H4/D1 cadence Gumbel Fade's entries are rare and high-conviction by design (ξ-gated exceedance
events), which is the opposite profile from a high-frequency placebo — but the EXP-0 finding still
applies in kind: the ξ-gate and reversal trigger must be shown to select genuine exhaustion, not
merely large-looking moves, before assuming the exit engine's amplification transfers.

## 3. Signal specification

As specified in the brainstorm (§7.6–§7.9), not yet implemented:

- **Setup:** rolling GPD fit (peaks-over-threshold) on H4/D1 move magnitudes, producing ξ̂ (tail
  shape) and β̂ (scale), refit slowly on multi-year windows.
- **Trigger — `TAIL EVENT`:** current excursion's (e.g. a 3-day directional run) exceedance
  probability under the fitted GPD is `< p_tail` (candidate threshold ~1%) **and** ξ̂ is below a
  fat-tail cutoff `ξ_max` (thin-tailed regime only).
- **Confirmation — `WAIT FOR TRIGGER`:** first H4 reversal bar — close against the run direction,
  beyond the prior bar's midpoint.
- **Entry:** fade at the reversal bar, targeting a 38–50% retrace of the run.
- **Stop:** beyond the run's extreme + buffer — a new extreme falsifies the "exhaustion" read (model
  rejection, same design pattern as Spring's z_stop).
- **Target:** the 38–50% retrace level.
- **Time stop:** 10 H4 bars — if the retrace hasn't happened on schedule, the thesis expires.
  First-hit resolution order.
- **Risk model:** fixed fractional R; wide stops (tail events are violent) mean correspondingly
  small position size via `RiskManager`'s standard math. Never add to a losing fade. A per-symbol
  monthly cap on fade attempts is specified because tail events cluster — one thesis per cluster,
  not one per exceedance (§7.9).
- **Universe:** not yet chosen; brainstorm recommends cross-asset pooling for sample size (§7.17),
  which argues for running Gumbel Fade across the full symbol book rather than a narrow subset.

## 4. Architecture integration

- **Manifest (sketch, not yet created):**
  ```yaml
  # config/manifests/gumbel_fade.yaml
  id: gumbel_fade
  version: "0.1.0"
  class_path: "src.strategies.models.gumbel_fade:GumbelFadeStrategy"
  family: stat
  timeframe: H4          # or D1 — TBD pending P10 resolution, see §5
  requires: []            # raw OHLC only
  status: research
  priority: 75
  honors_htf_bias: false  # ξ-gated exhaustion is its own regime read
  ```
- **Class placement:** `src/strategies/models/gumbel_fade.py` — `GumbelFadeStrategy(BaseStrategy)`,
  with the GPD math in a pure module `src/analysis/evt_exhaustion.py` (mirrors the
  `kalman_drift.py`/strategy-shell split used by Gyroscope). **`self.timeframe: H4` (or `D1`) does
  not exist on the live path at all.** `DataStore` constructs CandleMakers for **M5 and H1 only**
  (`src/core/data_store.py:26-27`), so an H4 or D1 manifest would register and activate cleanly and
  then silently never receive a candle close — a fail-silent trap, not a routing gap that degrades
  loudly (audit ENTRY-03 / P1). Live H4/D1 routing is therefore a hard prerequisite alongside the
  P10 harness work in §5, and the two are separate items: P10 unblocks *backtesting*, the CandleMaker
  addition unblocks *running*.
- **Config block (sketch):**
  ```yaml
  strategies:
    gumbel_fade:
      enabled: false
      timeframe: H4
      gpd_refit_bars: 500       # slow refit cadence, TBD
      p_tail: 0.01
      xi_max: 0.20              # thin-tail cutoff, TBD via mean-residual-life diagnostic
      retrace_target_low: 0.38
      retrace_target_high: 0.50
      time_stop_bars: 10
      monthly_fade_cap: 1       # per symbol
      pairs: []                 # cross-asset pooled universe, TBD
  ```
- **FeatureBus resources:** none required for v1 — raw OHLC only, self-contained GPD estimator
  (same posture as Gyroscope's `KalmanDrift`, no SMC pack dependency).
- **Order types:** MARKET or LIMIT at the reversal bar close — TBD; MARKET is simpler and matches
  the "first reversal bar" trigger's immediacy.
- **Grading path (P8 statement):** non-SMC signal, but the cap is narrower than "loses the SMC
  points." Verified against `src/analysis/signal_grader.py`: displacement (≤20) is computed from the
  enriched candle for any strategy (`system_controller.py:969`) and a tail-event reversal bar is
  large by construction, so it should score; premium/discount awards **+5**, not 0, when
  `context['liquidity']['STATUS']` is unset or `"EQ"` (`signal_grader.py:95-97`); killzone (+15) is a
  pure NY-clock test (`signal_grader.py:101-110`); and HTF alignment still scores 30/10/0 from
  `context['bias']` — `honors_htf_bias: false` suppresses the controller's *filter*, not the grade.
  Gumbel Fade's specific exposure is that it is a **counter-trend fade after a multi-day run**, so
  `context['bias']` will usually oppose it → `bias_counter +0` on 30 points, and its 38–50% retrace
  target against an extreme-plus-buffer stop can fall short of the grader's 1.5 R:R floor
  (`signal_grader.py:66-69`). Plausible range ≈20–55, i.e. it will clear `min_grade: B` only
  intermittently. Needs the same non-SMC grading policy named for Spring
  (`grading-policy-for-non-smc-signals`, inbox), and the grade distribution must be journaled from
  the first backtest — with this strategy's low trade count, intermittent gating would badly distort
  an already thin sample.
- **HTF-bias stance:** `honors_htf_bias: false` — the ξ-gate and exceedance read are the strategy's
  own regime signal.
- **Exit profile:** fixed retrace-target TP, extreme-plus-buffer SL, 10-bar time stop — this is a
  flat, discrete exit thesis, not a continuation trade. Like Spring, it does not match the default
  ratchet/runner (built for SilverBullet-style positive-skew continuation) and needs the same
  **per-strategy exit profile (P7)** infrastructure. Unlike Spring, Gumbel Fade's low trade count
  means P7 design errors here would be slow and expensive to detect live — get the exit profile
  right in backtest.
- **Risk interaction:** standard broker-spec sizing off the wide extreme-plus-buffer stop; the
  monthly per-symbol fade cap is not an existing `ExposureManager` primitive and would need to be
  added (or tracked strategy-side via state).

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| P10 | H4/D1 data extension — `collect_signals` raises `KeyError` on H4/D1 today; D1 history is only ~775 bars/symbol vs H1's ~18,600 | **Hard blocker.** Gumbel Fade cannot be backtested on the live research harness until this lands — the same blocker Anchor-class H4/D1 candidates share (brief §8) | Unclear, likely significant — needs both harness resampling support and (for D1) an MT5 history-extension project (`GET_HISTORY` supports 15-25y per the brief, but it has not been pulled yet) |
| ENTRY-03 / P1 | Live H4/D1 candle routing — `DataStore` builds CandleMakers for **M5 and H1 only** (`src/core/data_store.py:26-27`) | **Second hard blocker, distinct from P10.** An H4/D1 manifest activates and then silently never fires; the strategy would look healthy and place no trades. P10 unblocks backtesting, this unblocks running | Not sized; a new CandleMaker plus routing/warmup plumbing |
| P7 | Per-strategy exit profile (flat TP/SL/time-stop, no ratchet/runner) | Gumbel Fade's retrace-target/extreme-stop/time-stop thesis is incompatible with the default continuation-shaped ratchet | Shared with Spring; not yet designed |
| P8 | Grading policy for non-SMC signals (`grading-policy-for-non-smc-signals`, inbox) | Not an absolute cap (§4): counter-trend bias scoring 0/30 and a sub-1.5 R:R target make grading *intermittent*, which on a low-trade-count strategy silently biases the sample | Shared with Spring/Gyroscope |
| — (new) | Cross-asset event-study infrastructure for pooling exceedance events across symbols | Brainstorm explicitly requires cross-asset pooling "essential for sample size" (§7.17) given how rare H4/D1 tail events are per symbol | Not scoped; likely a research-script-level addition, not a platform change |

## 6. Validation plan

TVP (`docs/research/2026-07-12-novel-arsenal-brainstorm.md` §0) applies, plus the brainstorm's
Gumbel-Fade-specific addition (§7.17):

- **Existence study before any backtest:** a forward-return event study conditioned on
  `(exceedance bucket × ξ bucket)` — a 2×2 that must show the predicted interaction (reversion
  concentrated in the thin-tail/extreme cell, not the fat-tail/extreme cell) before writing a
  backtest. This is a falsification test of the core thesis, not a tuning exercise.
- **Cross-asset pooling** is essential for sample size given rarity of qualifying events; this
  should run across the full available symbol book, not a narrow pre-selected universe.
- **Data:** H4 (~4,650 bars/symbol, brief §8 calls this "marginal") or D1 (~775 bars/symbol,
  brief §8 calls this "cannot validate — needs the P10 history-extension project"). **This doc
  recommends starting on H4 first** if the P10 harness fix lands for H4 sooner than D1 history can
  be extended, since H4 is at least nominally validatable per the brief's own timeframe guidance,
  while D1 explicitly is not yet.
- **Baseline:** not specified in the brainstorm for this strategy; the repo's standard baseline
  culture (MaSlopeBaseline, Almanac per the brief's audit note) should apply once H4/D1 backtesting
  is possible.
- **Kill criteria:** the 2×2 existence study failing to show the thin-tail/extreme interaction is
  the cleanest possible NO-GO — it falsifies the ξ-gate's premise directly, before any P&L
  backtest is run. Standard TVP net-of-cost, IS/OOS, and ±30% sweep criteria apply thereafter.
- **What cannot be validated with current data:** anything on D1 (775 bars is explicitly
  insufficient per the brief); H4/D1 backtesting at all until P10 resolves the `collect_signals`
  `KeyError`. **The brainstorm's own recommendation is to start the background event-study
  collection now** (§13 honorable mentions, §7.17) — this can proceed independent of P10 as a
  pure data-analysis exercise (computing GPD fits and the 2×2 existence table from raw OHLC does
  not require the research harness), even though a full backtest cannot run until P10 lands.

## 7. Failure modes and monitoring

- **Fading a genuine trend birth:** the primary failure mode. Mitigated by the ξ-gate (refuses to
  fade in fat-tail regimes) and the hard extreme-plus-buffer stop (a new extreme falsifies the
  thesis and exits). Monitor: realized win rate on ξ-gated entries vs the GPD's implied exceedance
  probability, mirroring Gyroscope's realized-false-entry-rate self-check.
- **GPD fitting instability:** POT threshold (u) sensitivity is a known EVT pitfall; the mean-
  residual-life diagnostic must be done once in-sample and the fit's stability validated, not
  re-tuned live.
- **Sample scarcity:** the lowest trade count of any Wave 3 candidate by construction — slow live
  confirmation is expected and should be planned for, not treated as a red flag on its own.
- **Cost drift:** self-rated 5/5 cost survival is a strong prior, not a guarantee — should still be
  monitored via realized round-trip cost per trade vs R, same as every strategy, even though the
  brainstorm expects this to be a "rounding error" at H4/D1 scale.
- **Ops:** standard fail-safe lot=0 on missing specs; no strategy-specific ops risk beyond the
  shared portfolio-cap and Sync Guard behaviour.

## 8. Verdict and sequencing

Candidate, slow-burner, currently **blocked on P10** for any real backtest. The ξ-gate is a
genuinely novel discipline transfer per the brainstorm's own assessment, and the H4/D1 cadence gives
it the best cost-survival self-rating on the shortlist — but low trade count and the P10 blocker
mean this cannot move at the pace of an H1 candidate. Recommended sequencing: (1) start the
background event-study collection now, independent of P10 — compute rolling GPD fits and the
2×2 (exceedance × ξ) existence table directly from `data/history/` OHLC, which needs no harness
change; (2) treat P10 resolution as a separate, shared infrastructure project (benefits Gumbel Fade
and any other H4/D1-scale candidate) rather than a Gumbel-Fade-specific task; (3) only pre-register
a formal gate once both the existence study is favourable and P10 unblocks a real backtest; (4) do
not build the strategy class or exit-profile plumbing until the existence study passes — this is
cheap to falsify early and expensive to build first. Not on the critical path for Spring, Walclock,
or Shannon Gate.
