# BELL — index session opening-range breakout

> **Status:** candidate (pre-registration pending) · **Family:** session liquidity / opening-range
> breakout · **Timeframe:** M15 · **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §6 ·
> **Doc version:** 2026-08-01

## 1. Thesis and return source

Opening-range breakout (ORB) has a genuine, recently re-documented empirical basis — the source
document cites Zarattini & Aziz's 2023 work on ORB in liquid equity instruments as having revived a
strategy family previously written off. The mechanism: overnight information accumulates and
resolves into directional flow in the first period of liquid trading, and that flow exhibits
short-horizon continuation (05-STRATEGY-ARSENAL.md §6, "Thesis").

Bell is restricted to **US30, US100, XAUUSD, BTCUSD only**. This is not an arbitrary universe
choice — it follows directly from the cost-gate analysis in the source document: on a
high-volatility index/metal/crypto instrument, an opening range of tens to hundreds of points is
cheap relative to a spread of a few points, whereas an FX major's opening range is too narrow
relative to its spread to clear the cost gate at M15. The document's worked example: "On US30 an
opening 30-minute range is routinely 60–150 index points against a 200-tick (≈2 point) spread — a
cost fraction of ~0.03R. This is your cheapest R in the entire universe" (05-STRATEGY-ARSENAL.md
§6, "Why M15 works here and nowhere else in the set"). This is also the *only* M15 strategy judged
viable in the arsenal — M15/M5 ATR-multiple stops are dead by the platform's general cost analysis
(brief §"Hard constraints"), and Bell survives that only because its stop is the opening-range
width, not an ATR multiple.

**EXP-0 implication:** placebo entries through the full ratchet+runner exit engine produced
−0.249R (0/20 reps positive); real entries produced +0.109R, with the exit engine amplifying a
genuine signal (+0.231R) but not subsidising a random one (+0.075R) (EXP-0 outcome 1, 2026-07-31;
brief §"Hard constraints"). Bell's entry — a directional breakout of a measured range — has to
independently select for continuation; a high trade frequency and wide structural stop are
necessary but, per EXP-0, not sufficient on their own.

## 2. Evidence base

**No Bell-specific backtest exists yet.** What follows is design basis and adverse context.

| Source | What it establishes | Citation |
|---|---|---|
| Cost table | US30 200, BTCUSD 1000, XAUUSD 20 (points, Bell's non-FX universe); XTIUSD not in Bell's universe. Commission $7/lot | `scripts/poc_sb_stops.py:43` |
| Cost-ratio analysis | "US30, US100, XAUUSD and BTCUSD have the best volatility-to-cost ratios in your universe and are your only realistic intraday candidates" | brief §"Hard constraints"; 05-STRATEGY-ARSENAL.md §1.1 |
| The graveyard | Original SilverBullet on M5 at 0.2×ATR: −4.27R — the general lesson that small/ATR-relative stops die at short timeframes, which Bell avoids by using range width instead | brief §"Hard constraints" |
| The graveyard | OTE −0.158R, MTF-PB v2 −0.274R, Gyroscope −0.067R (three ICT/momentum NO-GOs); none is a direct analogue of ORB, but all three confirm pattern-entry ideas on this data have a poor base rate | brief §"Hard constraints" |
| EXP-0 coin-flip | Placebo −0.249R vs real +0.109R through the identical exit engine | brief §"Hard constraints" |

**Adverse framing, stated plainly:** Bell is explicitly flagged by the source document as "highest
variance in the arsenal; also the highest ceiling" (05-STRATEGY-ARSENAL.md §6, "Expected profile")
and carries a **higher validation bar than the other candidates** for exactly that reason — its own
kill criterion (§6 below) requires +0.10R OOS, versus +0.05R for Coil and Tide. No M15 strategy has
ever run on this platform (M15 CandleMaker does not exist, §5), so there is zero live or backtested
precedent for M15 execution mechanics specifically, independent of the entry thesis.

## 3. Signal specification

As drafted in the pre-registration sketch (05-STRATEGY-ARSENAL.md §6, "Mechanics"):

```
Universe: US30, US100, XAUUSD, BTCUSD ONLY.
          FX majors excluded — opening ranges too narrow relative to spread.
Setup:    OR = high/low of the first 2 × M15 bars after the NY equity open
          (US/Eastern, DST-aware — get_current_ny_string is already correct)
Trigger:  STOP at OR_high + 0.1 × OR_width  /  OR_low − 0.1 × OR_width
Stop:     opposite OR extreme   ← structural, wide, cost-friendly
Filter:   OR_width between 0.5× and 2.0× the 20-day median OR
          (skip both dead opens and news-gap opens)
          AND no high-impact release within 30 min
          (news_manager exists but is USD-only — extend it, see §5)
Expiry:   unfilled 90 min after open → cancel. Time-stop at session close.
OCO:      required (shared with Coil, see §5)
```

Bell uses STOP orders on both sides of an opening range in the same paired-bracket pattern as Coil
(§3 of `docs/strategies/coil.md`), so it inherits the identical OCO dependency. It is the second
(and, in current staging order, last) strategy to require paired pending orders.

## 4. Architecture integration

**Manifest sketch** (`config/manifests/bell.yaml`):

```yaml
id: bell
version: 0.1.0
class_path: src.strategies.models.bell.Bell
family: session_orb
timeframe: M15
requires: [smc.enriched_df]   # OHLC + ATR-equivalent range stats; no FVG/PD/killzone dependency
status: research
priority: 70
honors_htf_bias: false          # an ORB breakout is direction-agnostic at signal time (see below)
```

**Class placement:** `src/strategies/models/bell.py`, subclassing `BaseStrategy`
(`src/strategies/base_strategy.py`), `on_new_candle` returning `{'signal', 'type': 'STOP', 'price',
'sl', 'tp'}` — Bell's `self.timeframe` would be `'M15'`, which today receives **no candle-close
routing at all**: `data_store.py:25` (per the audit's `entry-03-m15-strategies-silently-never`
backlog row) only builds M5 and H1 CandleMakers. A Bell manifest deployed today would silently
never fire — the single most consequential prerequisite gap for this strategy (§5).

**Config block sketch** (`config/config.yaml`, under `strategies:`):

```yaml
strategies:
  bell:
    enabled: false
    pairs: [US30, US100, XAUUSD, BTCUSD]
```

**FeatureBus resources:** `smc.enriched_df` for raw OHLC and range statistics on the M15 series
(once the M15 CandleMaker exists); needs a 20-day median opening-range statistic and a session-open
bar-index anchor, neither of which exist today.

**Order type:** STOP, both sides — same paired-bracket pattern as Coil; the two strategies should
share the OCO implementation rather than each build their own.

**HTF-bias stance:** `honors_htf_bias: false`. An opening-range breakout has no directional read
until one side triggers, the same architectural reasoning as Coil (`docs/strategies/coil.md` §4).
Bell needs the same bias-filter exemption policy resolved (backlog row
`bias-filter-exemption-policy-arsenal-review`) even though that row's description names only "Coil
brackets, Tide fades" explicitly — Bell's two-sided STOP bracket has the identical exemption need
and should be included in that policy decision, not treated as a separate gap.

**Grading path (P8 statement):** same SMC-shaped grader gap as Coil and Tide
(`src/analysis/signal_grader.py`, HTF alignment/R:R/displacement/premium-discount/killzone). Bell's
range-breakout-strength signal has no natural displacement or premium/discount mapping. Backlog row
`grading-policy-for-non-smc-signals` applies identically here; the policy, once decided, should
cover all three non-SMC candidates (Coil, Tide, Bell) rather than being re-litigated per strategy.

**Exit profile:** default ratchet + runner. The source document explicitly calls Bell's expected
payoff shape "excellent n, excellent skew, ideal runner input" (05-STRATEGY-ARSENAL.md §6) — unlike
Tide, there is no stated rationale for a P7 per-strategy exit variant here; the design assumption is
that Bell's breakout profile resembles Coil's and SilverBullet's fat-right-tail shape, and should
use the same ratchet/runner the platform already has. This assumption should be checked, not
asserted, once trade data exists.

**Risk interaction:** standard broker-spec sizing. Both STOP legs, while pending, count against the
portfolio risk cap per their state-DB rows (brief §"Risk") — same double-counting-until-cancel
consideration as Coil (`docs/strategies/coil.md` §4), and the same reason OCO is a hard, not
optional, prerequisite. Bell's universe (US30, US100, XAUUSD, BTCUSD) already carries the
platform's largest per-tick cost figures (200/1000-point spreads), so accurate sizing against
broker specs is unusually load-bearing here — a specs-load failure fails safe to lot=0 (brief
§"Risk"), which for Bell means a silent no-trade on exactly the instruments the strategy is built
for.

## 5. Infrastructure prerequisites

| # | Prerequisite | Backlog / audit row | Effort | Why Bell needs it |
|---|---|---|---|---|
| P1 / ENTRY-03 | M15 CandleMaker from configured TFs | `entry-03-m15-strategies-silently-never` (inbox); `data_store.py:25`, `candle_maker.py:118` | 4 h | Without it, a Bell manifest produces zero signals with no error — `data_store.py` only creates M5 and H1 makers today; the fix also repairs H4-bucketing for tf ≥ 60 |
| P5 / ENTRY-02 | Bar-time (not wall-clock) session gating | `entry-02-session-gate-keyed-to` (inbox); `system_controller.py:842` | 4 h | Bell's entire setup is anchored to "the first 2×M15 bars after NY open" — a wall-clock gate diverges between live and backtest and is inert/wrong exactly where Bell depends on it most |
| P2 | OCO pending-order pairs | `oco-pending-order-pairs-arsenal-p2` (inbox) | 1 day | Shared with Coil — Bell's two-sided STOP bracket has the identical fill-one-leg-orphan-the-other failure mode |
| — | Bias-filter exemption policy | `bias-filter-exemption-policy-arsenal-review` (inbox) | S | Same direction-agnostic-bracket exemption need as Coil (row names Coil/Tide explicitly; Bell should be added to the same decision) |
| P8 | Grading policy for non-SMC signals | `grading-policy-for-non-smc-signals` (inbox) | S | Same SMC-shaped grader gap |
| — | Extend `news_manager` beyond USD | 05-STRATEGY-ARSENAL.md §6 | not sized in source docs | Bell's "no high-impact release within 30 min" filter needs non-USD event coverage for XAUUSD/US30/US100/BTCUSD-relevant releases; `news_manager` today is USD-only |
| STRAT-03 | Slippage on STOP entries unmodelled; spread charged post-hoc rather than adjusting fill/trigger prices | `strat-03-spread-is-charged-as` (inbox); `backtest_engine.py:68-73,168` | 1 day (per backlog) | Bell's entries are STOP orders that trigger on a break — exactly the order type most exposed to slippage, and the current backtester models none of it. "Measure this on demo before believing any backtest of Bell" (05-STRATEGY-ARSENAL.md §6) |

Bell has the largest prerequisite bill of the three candidates in this batch — P1 and P5 are hard
correctness blockers (the strategy literally cannot fire without P1; its session anchor is wrong
without P5), not risk hygiene like most of Coil's and Tide's list.

## 6. Validation plan

- **Pre-registered gate**, committed to `docs/research/` before any run: mechanics as in §3,
  universe fixed to the four named instruments, kill criteria fixed in advance including the
  slippage measurement (below), one-pass rule.
- **Data:** M15 resampling from the existing M5 CSVs (`data/history/<SYM>_M5.csv`) is available in
  principle (~50,000 bars/symbol over 3y, "n ✓, costs marginal" per brief §"Data") — this is a
  larger sample than H1 gives Coil/Tide, consistent with Bell's ~750 trades/instrument/3y design
  estimate (05-STRATEGY-ARSENAL.md §6). Requires P1 before the live/demo path can produce this
  signal at all; the offline backtest can in principle resample M15 independent of P1, but the
  research harness's entry-parity property (brief §"Research harness") only holds once the live
  M15 routing exists — a backtest run before P1 ships is not entry-parity-equivalent to what would
  eventually run live.
- **Baselines:** MaSlopeBaseline (exists); Almanac zero-parameter yardstick once built.
- **Cost stress:** ×1.5/×2 spread on the four-instrument cost table (`scripts/poc_sb_stops.py:43`).
- **Higher bar than the other candidates:** per 05-STRATEGY-ARSENAL.md §6, Bell's kill criterion is
  OOS < +0.10R (vs +0.05R for Coil/Tide) — explicitly because its variance is higher.
- **Slippage measurement is a validation-plan requirement, not an optional monitor:** the backtester
  models none of it (STRAT-03); before any backtest result is trusted, median realised slippage on
  STOP entries must be measured on the demo soak. This is stated as a kill criterion below because
  the source document treats it as a precondition for believing any other number for this strategy.
- **What CANNOT be validated with current data:** cannot validate live M15 session-open bar timing
  before P5 lands — a backtest using wall-clock timing today would not match live behaviour once P5
  changes it. Cannot validate non-USD news-gap filtering before `news_manager` is extended — any
  gate run before that extension implicitly assumes USD-relevant news is the only relevant calendar
  risk for US30/US100/XAUUSD/BTCUSD, which is not defensible for index/metal/crypto instruments.
  STRAT-01 applies identically: any managed-exit number is an upper bound from the offline replay,
  not a live number.

## 7. Failure modes and monitoring

- **Silent non-firing:** without P1, the manifest loads and the strategy never produces a signal —
  no error, no log distinguishable from "no setups occurred." Monitor: non-zero Bell signal count
  per week once deployed, alerting on an unexpected zero-streak.
- **Session-anchor drift:** without P5, live session timing can diverge from the backtest's bar-time
  anchor, especially around DST transitions — even though `get_current_ny_string` is itself already
  DST-aware (05-STRATEGY-ARSENAL.md §6), the *gate that consumes it* is wall-clock keyed at
  `system_controller.py:842`.
- **Slippage erosion:** the single highest-risk unknown for this strategy. Monitor realised fill
  price vs signalled STOP price per trade; the kill criterion (below) is explicit and should be
  checked continuously on demo, not just at a validation checkpoint.
- **News-gap false positives/negatives:** until `news_manager` covers non-USD events, Bell may take
  a signal into an index/metal/crypto-relevant release its filter cannot see. Monitor: manual cross-
  reference of large losses against an external calendar during the demo phase.
- **OCO race condition:** identical to Coil's — monitor count of simultaneous same-symbol pending
  orders per Bell signal.
- **Self-audit metrics for live/demo:** median realised slippage vs the 0.1R kill threshold;
  per-instrument trade count vs the ~750/instrument/3y design estimate; win rate vs the 33–40%
  design band; grade distribution once P8 policy is decided.

## 8. Verdict and sequencing

**Stage 5** in the audit staging (05-STRATEGY-ARSENAL.md §13) — described as "The aggression"
stage, the last real candidate before Tether, gated behind P9 (cross-strategy arbitration) and P12
(portfolio-level backtest), because "Only after the portfolio machinery can measure what adding it
does." This document adds: Bell is also gated behind P1 and P5 specifically, which are hard
correctness blockers unique to it among the three candidates covered here (Coil and Tide need
policy decisions and shared infrastructure; Bell needs its data path built before it can produce a
signal at all).

**Sequencing dependencies:** Stage 2 (Coil) and Stage 3 (Tide) precede Bell in the staging order and
share several of its prerequisites (OCO/P2, the bias-filter exemption policy, the P8 grading
policy) — landing those for Coil first de-risks Bell's identical dependencies. Bell additionally
needs P1 (M15 CandleMaker, 4h) and P5 (bar-time session gating, 4h) before it, and P9+P12 (audit
§12: cross-strategy arbitration, portfolio-level backtest) are staged ahead of it specifically
because Bell is the first candidate the arsenal document expects to run *concurrently* with
survivors from earlier stages, and the portfolio machinery to measure that does not exist yet
(05-STRATEGY-ARSENAL.md §13, Stage 5 gating). Recommendation: do not begin Bell's pre-registered
gate until P1 and P5 are both landed (an ungated run cannot be trusted to reflect live mechanics),
and do not deploy it even on a passing gate until P9/P12 exist, per the staging order — Bell is
explicitly the strategy the source document says needs portfolio-level measurement most, given its
"highest variance in the arsenal; also the highest ceiling" profile.

**Kill criteria** (05-STRATEGY-ARSENAL.md §6): OOS < +0.10R — a higher bar than the other
candidates because of its higher variance; or median realised slippage on stop entries exceeding
0.1R, measured on demo before any backtest result is trusted (STRAT-03).
