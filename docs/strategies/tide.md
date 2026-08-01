# TIDE — intraday overextension reversal

> **Status:** candidate (pre-registration pending) · **Family:** short-horizon mean reversion ·
> **Timeframe:** H1 · **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §5 · **Doc
> version:** 2026-08-01

## 1. Thesis and return source

Short-horizon reversal — order-flow-driven overshoot followed by correction within a developing
session range — is a documented FX intraday effect, mechanically distinct from the multi-day
continuation SilverBullet trades. Tide's return source is deliberately statistical rather than
pattern-based: given the repo's ICT falsification record (four NO-GO'd variants, see §2), a signal
that fades a measured overextension rather than recognising a chart pattern is the more defensible
bet on this data (05-STRATEGY-ARSENAL.md §5, "Thesis").

**Tide's value proposition is not primarily its own expectancy.** It is the only candidate in the
arsenal expected to be *negatively correlated* with SilverBullet, Coil and Bell — all three of
which are continuation/expansion strategies that lose in mean-reverting chop. As a portfolio
component, a diversifier with a modest positive standalone expectancy and negative correlation to
the rest of the book can be worth more than a strategy with a better standalone number and positive
correlation (05-STRATEGY-ARSENAL.md §5, §11).

**EXP-0 implication:** the exit engine amplifies real entries (+0.231R on SilverBullet's real
entries) but does not subsidise random ones (net −0.249R on placebo through the full engine, brief
§"Hard constraints"). Tide's entry — a measured overextension with no H4 momentum agreement — must
independently earn its edge; unlike Coil's fat-tail breakout profile, Tide's reversal thesis has
*negative* skew (large winners are not the mechanism — see §4). **EXP-0 falsified the source
document's additive framing** — 05-STRATEGY-ARSENAL.md §1.3 asserts that "any entry meeting those
four constraints inherits +0.316R of proven machinery", but the coin-flip showed the management
layer contributes +0.231R on a real entry and only +0.075R on a random one. The exit engine's
contribution is a function of the entry it is given, not a constant a new strategy can bank in
advance; no strategy in this arsenal, Tide least of all, should be scoped on the assumption that
+0.316R comes free. The ratchet was calibrated on a continuation signal; it is not safe to assume
it transfers at all.

## 2. Evidence base

**No Tide-specific backtest exists yet.** As with Coil, what follows is design basis and adverse
context, not a result.

| Source | What it establishes | Citation |
|---|---|---|
| SilverBullet H1 stop study | H1 satisfies both the sample-size floor (~18,600 bars/symbol, 3y) and the cost gate — the timeframe Tide inherits | brief §"Data" |
| Cost table | EURUSD 8, GBPUSD 12, USDJPY 10, AUDUSD 10, USDCAD 12, GBPJPY 25, XAUUSD 20 (points, FX majors + gold — Tide's universe); commission $7/lot | `scripts/poc_sb_stops.py:43` |
| The graveyard | OTE canonical −0.158R pooled managed (2026-07-11); MTF-PB v2 −0.274R pooled (2026-06-25); Gyroscope −0.067R pooled, 27.1% realised false-entry (2026-07-15, third H1-momentum NO-GO) | brief §"Hard constraints" |
| The graveyard | Original SilverBullet M5 config −4.27R — the canonical too-tight-stop failure | brief §"Hard constraints" |
| EXP-0 coin-flip | Placebo entries through the full ratchet+runner: −0.249R (0/20 reps positive); real entries: +0.109R | brief §"Hard constraints" |

**Adverse framing, stated plainly:** four of the six prior falsifications on this rig were
pattern-recognition entries on this exact data; Tide is designed to be statistical instead, but
that is a design choice, not evidence it will succeed. No reversal-family strategy has been tested
on this repo's data. The negative-correlation prior in §11 of the source audit is explicitly a
prior, not a measurement — see the correlation caveat in §7.

## 3. Signal specification

As drafted in the pre-registration sketch (05-STRATEGY-ARSENAL.md §5, "Mechanics"):

```
Setup:    close in the top/bottom 5% of the developing session range
          AND session range ≥ 1.5 × ADR(20)
          AND no H4 momentum agreement (fade exhaustion, never trend)
Trigger:  LIMIT at close ± 0.3 × ATR(14,H1), retracing INTO the range
Stop:     session extreme ± 0.5 × ATR(14,H1)   ← structural
Target:   session mid-range as anchor; ratchet manages the path
Session:  exclude the first 2 bars after any major open (reserved for Bell)
Universe: FX majors + XAUUSD.
          EXCLUDE indices and crypto — they trend intraday, and reversal
          signals there are on the wrong side of a real drift.
```

The "no H4 momentum agreement" filter is the mechanism that keeps this a fade-exhaustion signal
rather than a counter-trend gamble against a real trend — and it requires H4 candle data, which the
platform does not currently produce on either path. The research rig resamples only two
timeframes: `collect_signals` (`scripts/poc_sb_stops.py:54`) does `rule = {"M15": "15min",
"H1": "1h"}[tf]` at `poc_sb_stops.py:66`, so `tf="H4"` raises `KeyError`. The live path is
narrower still: `DataStore` builds CandleMakers for M5 and H1 only
(`src/core/data_store.py:25-28`). Neither is a hard blocker — a Tide strategy class can resample
H4 from the M5/H1 frame it is handed, or an H4 momentum resource can be registered on the
FeatureBus — but "compute it inline" is a design decision that must be made and tested before this
ships, not assumed.

## 4. Architecture integration

**Manifest sketch** (`config/manifests/tide.yaml`):

```yaml
id: tide
version: 0.1.0
class_path: src.strategies.models.tide.Tide
family: intraday_reversal
timeframe: H1
requires: [smc.enriched_df]   # ATR, ADR-equivalent range stats; no FVG/PD/killzone dependency
status: research
priority: 65
honors_htf_bias: false          # a fade is, by construction, counter to the prevailing HTF read
```

**Class placement:** `src/strategies/models/tide.py`, subclassing `BaseStrategy`
(`src/strategies/base_strategy.py`), `on_new_candle` returning `{'signal', 'type': 'LIMIT', 'price',
'sl', 'tp'}`. LIMIT is already a fully-supported order type end-to-end (brief item 9), so — unlike
Coil and Bell — Tide needs no new order-type plumbing.

**Config block sketch** (`config/config.yaml`, under `strategies:`):

```yaml
strategies:
  tide:
    enabled: false
    pairs: [EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD]   # FX majors + XAUUSD only
```

**FeatureBus resources:** `smc.enriched_df` for `ATR`; needs a session-developing-range /
ADR(20) computation and an H4-momentum-agreement check, neither of which exist in the FeatureBus
today — both would need to be added as new resources or computed inline from raw OHLC via
`validate_data(df, check_smc=False)` plus the strategy's own H4 resample.

**Order type:** LIMIT, retracing into the range (the opposite geometry from SilverBullet's
FVG-edge LIMIT, but the same order type).

**HTF-bias stance:** `honors_htf_bias: false` — a fade signal is definitionally opposed to
continuation, so the controller's HTF bias filter would filter out every Tide signal by
construction if applied. The mechanism itself already exists and is manifest-driven —
`system_controller.py:961-963` skips the counter-bias drop when the strategy's `honors_htf_bias` is
false (Gyroscope precedent) — so what Tide needs is the *policy* governing who may claim it:
backlog row `bias-filter-exemption-policy-arsenal-review`, which names "Coil brackets, **Tide
fades**" explicitly. Until that is settled, a Tide registered as bias-honouring would have every
signal silently dropped by the filter.

**Grading path (P8 statement):** same shared gap as Coil, but Tide is the worst case in the
arsenal. `SignalGrader.grade()` (`src/analysis/signal_grader.py`) scores HTF alignment (30 aligned
/ 10 neutral / **0 counter**), R:R (20/15/8), displacement (20/15/10 on body ÷ ATR),
premium/discount (15 aligned / 5 unknown / 0 opposed) and killzone (15), with the B floor at 55
(`signal_grader.py:21`). Every factor is computed from the controller context and the signal
candle, so the grader never errors — the audit's "a non-SMC signal has no grade" shorthand is not
literally true. But a *fade* is scored counter-bias by construction (0, not 10) and will frequently
sit on the wrong side of the PD array (0, not 5), because taking the top 5% of the session range
short is definitionally selling into what `BiasEngine` may call a bullish premium. That leaves a
realistic ceiling of 0 + 20 (R:R) + 20 (displacement) + 0 + 15 (killzone) = **55, exactly the floor
— and 40, a hard C, outside killzone hours.** Tide is therefore the one candidate that plausibly is
structurally gated out most of the time, and the same policy decision that gates Coil
(exempt-by-manifest vs a per-strategy grade profile, backlog row
`grading-policy-for-non-smc-signals`) should be resolved once for both.

**Exit profile — needs P7, not the default:** this is Tide's most consequential architecture point.
The default ratchet (BE at 38.2%, partials at 61.8%/88.6%, runner trail 0.268×range — see
`docs/strategies/silver-bullet.md` §4) is calibrated on SilverBullet's continuation profile, where
the runner's job is to let a small number of large winners run. Tide's thesis is reversal to a
session mid-range anchor — the expected payoff shape has **negative skew relative to SilverBullet**:
smaller, more consistent winners (design target win rate 55–65%, average winner 1.0–1.5R, per
05-STRATEGY-ARSENAL.md §5) rather than a fat right tail. Per audit prerequisite P7
(05-STRATEGY-ARSENAL.md §12, "per-strategy exit profiles … Tide needs no runner"), Tide needs its
own exit variant — bank earlier, trail tighter,
no runner mode — and **both the default ratchet and the bank-early/trail-tight variant must be
tested**, not assumed. This directly extends the EXP-0 finding: EXP-0 showed the exit engine
amplifies a genuine positive-skew entry but does not manufacture edge from a random one; Tide is a
third case the experiment did not test — a genuine but *negative-skew* entry — and there is no
existing evidence for how the ratchet behaves there. Testing both variants is part of the
pre-registered gate, not a post-hoc tuning step.

**Risk interaction:** standard broker-spec sizing. **RISK-01 status update, superseding the source
audit's blocker:** 05-STRATEGY-ARSENAL.md §5 states "Given RISK-01 (drawdown anchor resets on
restart) is still open, do not run Tide live until that is fixed. It is the strategy most exposed
to that specific bug." **RISK-01 is now fixed** — the daily-drawdown anchor was merged to main
2026-08-01 (`RiskManager.restore_daily_anchor`; the 3% breaker now survives restarts, keyed to a
23:45 EAT trading day). The audit's stated live-deployment blocker for Tide is therefore **cleared**
at the infrastructure level. This does not change Tide's validation status — it remains an
unvalidated candidate — but the specific reason the audit named for treating it as *more* dangerous
than the other candidates no longer applies. Reversal strategies remain, on general principle, the
shape of strategy most exposed to a broken drawdown breaker (a regime break plus an unenforced stop
compounds fastest against a mean-reversion book), so RISK-01's fix should be explicitly cited in
Tide's own pre-registration as a go/no-go precondition that is now satisfied, not skipped over.

## 5. Infrastructure prerequisites

| # | Prerequisite | Backlog / audit row | Effort | Why Tide needs it |
|---|---|---|---|---|
| — | Bias-filter exemption policy for non-SMC/direction-agnostic strategies | `bias-filter-exemption-policy-arsenal-review` (inbox) | S | Named explicitly for "Tide fades". The mechanism exists (`system_controller.py:961-963`); absent a policy, a bias-honouring Tide has every signal filtered as counter-bias |
| P1 / ENTRY-03 | H4 candle availability for the momentum-agreement filter | `entry-03-m15-strategies-silently-never` (inbox); `data_store.py:25-28`, `poc_sb_stops.py:66` | 4 h (shared with Bell) | Neither the live DataStore (M5/H1 only) nor `collect_signals` (M15/H1 only) produces H4; Tide must either resample inline or wait on P1 — decide before the gate, not after |
| P7 | Per-strategy exit profiles (Tide needs no runner) | audit §12 row P7 | 1 day | The default ratchet/runner is calibrated on continuation; Tide's negative-skew reversal profile needs a bank-early/trail-tight variant tested against the default before either is adopted |
| P8 | Grading policy for non-SMC signals | `grading-policy-for-non-smc-signals` (inbox) | S | Sharper for Tide than for Coil: a fade scores 0 on HTF alignment and often 0 on PD array, leaving a realistic ceiling of 55 (the floor itself) in killzone hours and 40 outside them |
| RISK-01 | Daily drawdown anchor survives restart | **DONE** — merged to main 2026-08-01, `RiskManager.restore_daily_anchor` | — | Audit's stated Tide-specific live blocker; now cleared |

## 6. Validation plan

- **Pre-registered gate**, committed to `docs/research/` before any run: mechanics as in §3, universe
  FX majors + XAUUSD only, both exit variants (default ratchet vs P7 bank-early/trail-tight) run
  as a paired comparison, kill criteria fixed in advance (one-pass rule).
- **Data:** existing ~3y H1 frame, same source as SilverBullet (`data/lake/frozen/PROVENANCE.md`) —
  no data extension needed.
- **Baselines:** MaSlopeBaseline (exists); Almanac as zero-parameter yardstick once built (brief
  §"Validation culture").
- **Cost stress:** ×1.5/×2 spread on the FX-majors+XAUUSD cost table (`scripts/poc_sb_stops.py:43`).
- **Correlation measurement, explicitly a prior today:** 05-STRATEGY-ARSENAL.md §11 states a
  SilverBullet↔Tide prior of **−0.2**, labelled "priors to be measured, not results" in the source
  table's own heading. This document does not adopt that number as a result — it is cited here
  only as the design rationale for building Tide at all, and it must be *measured* against real
  paired monthly P&L once both strategies have trade histories, not assumed.
- **What CANNOT be validated with current data:** the H4-momentum-agreement filter cannot be
  exercised through `collect_signals` at all — `poc_sb_stops.py:66` maps only `M15`/`H1`, so
  `tf="H4"` raises `KeyError`, and the live `DataStore` builds no H4 CandleMaker either
  (`data_store.py:25-28`). This needs a strategy-side or FeatureBus-side H4 resample, or the
  P1/P10 timeframe-rule fixes, resolved and tested *before* the gate run rather than assumed.
  Nor does grading have replay/live parity: `src/research/kernel_replay.py:42-50,66,92` stubs the
  time engine with a fixed NY-time string (default `"10:00:00 EST"`), so every replayed signal
  banks the grader's +15 killzone point that live Tide will usually miss. Given that Tide's
  realistic ceiling is 55 *with* that point and 40 without it (§4), a replay would systematically
  overstate how many Tide signals survive the `min_grade` gate live.
  STRAT-01 applies identically: any managed-exit number from `poc_sb_stops.replay_managed` is an
  upper bound, not a live number (brief §"Research harness").

## 7. Failure modes and monitoring

- **Regime break:** reversal strategies are, per the source document, "how accounts die when a
  regime breaks" (05-STRATEGY-ARSENAL.md §5, "Honest risk") — a sustained trend defeats every fade
  simultaneously. The stop must be absolute and position size must never scale up after a loss.
- **Correlation drift:** if Tide's realised correlation to SilverBullet's monthly P&L rises toward
  or past +0.3, it has stopped functioning as a diversifier and is instead adding correlated risk —
  this is one of the kill criteria below, not merely a monitoring note.
- **Exit-profile mismatch:** if the P7 variant is skipped and Tide runs on the default runner, watch
  for a low realised win rate combined with a low average winner (i.e., the reversal thesis paying
  off in small pieces that the runner logic delays banking on) — a signature that the exit engine is
  mismatched to the entry's skew.
- **Grade starvation is a live risk for Tide specifically, not a theoretical one:** with the
  current grader a fade tops out at 55 in killzone hours and 40 outside them (§4), so an unresolved
  P8 policy means Tide trades only during killzones and silently produces nothing the rest of the
  day — indistinguishable from "no overextensions occurred" without grade-distribution logging by
  NY hour. Instrument this before the first demo bar, not after a quiet week.
- **H4 filter degradation:** if the H4-momentum-agreement check is silently unavailable (e.g. an
  H4 resample failure), the fallback behaviour must be fail-closed (no trade), not fail-open
  (trade without the trend filter) — an unfiltered fade is explicitly the dangerous case per §"Honest
  risk" above.
- **Self-audit metrics for live/demo:** realised win rate vs the 55–65% design band; average winner
  vs the 1.0–1.5R design band; rolling correlation of Tide's monthly P&L to SilverBullet's; largest
  single realised loss as a multiple of planned R.

## 8. Verdict and sequencing

**Stage 3** in the audit staging (05-STRATEGY-ARSENAL.md §13) — "The diversifier," gated behind P4
(signed, fail-closed correlation + asset-class groups) and P7 (per-strategy exit profiles), which
are the two prerequisites specific to Tide's role in a multi-strategy book.

**Sequencing dependencies:** Stage 2 (Coil) is the pipeline dress rehearsal that precedes Tide in
the staging order; Tide additionally depends on the bias-filter exemption policy and the P8 grading
policy shared with Coil (resolve once, apply to both). RISK-01, the audit's named Tide-specific
live blocker, is now cleared (§4) — this removes a hard stop on eventual live deployment but does
not accelerate validation, which still requires the pre-registered gate and both exit-profile arms
to run. Recommendation: sequence Tide's gate run after Coil's (shared policy dependencies, and
Coil's dress-rehearsal purpose de-risks the process before a portfolio-role strategy uses it), and
explicitly budget the P7 exit-profile comparison as part of Tide's gate rather than a follow-up
study — a reversal strategy validated only against the continuation-calibrated ratchet has not
actually been validated.

**Kill criteria** (05-STRATEGY-ARSENAL.md §5): any single realised loss exceeding 1.5R (stops are
not holding); or OOS expectancy < +0.05R; or correlation to SilverBullet's monthly P&L above +0.3
(defeats the entire diversification purpose).
