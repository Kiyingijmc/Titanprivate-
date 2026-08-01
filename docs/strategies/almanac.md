# ALMANAC — Turn-of-Month Index Overlay (D1 decision, H1 execution)

> **Status:** candidate (canary role) · **Family:** calendar anomaly · **Timeframe:** D1 decision,
> H1 execution · **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §10 ·
> **Doc version:** 2026-08-01

## 1. Thesis and return source

The turn-of-month effect in equity indices — outperformance concentrated in the last trading day
of a calendar month through the first three of the next — is among the oldest documented calendar
anomalies (Ariel, 1987; Lakonishok & Smidt, 1988), commonly attributed to pension and payroll flow
into equities. Almanac is deliberately **not primarily a return-source bet** — the source document
is explicit that it is "not really a candidate. A yardstick"
(`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:346`). It exists for two epistemic reasons rather
than one economic one:

1. **A complexity baseline.** Almanac has **zero fitted parameters** — a calendar rule and a
   protective stop. Any future candidate with tunable parameters that cannot beat this rule, net of
   costs, on the same data has not earned its complexity (`05-STRATEGY-ARSENAL.md:363`).
2. **An end-to-end integration canary.** Because Almanac's signals are known months in advance,
   any live-vs-backtest divergence is unambiguously an infrastructure bug — a clock, session-logic,
   order-path or journal defect — not a strategy question (`05-STRATEGY-ARSENAL.md:365`).

The document is explicit that the effect has partially decayed since publication, as calendar
anomalies generally do, and that any honest treatment must say so
(`05-STRATEGY-ARSENAL.md:349`) — Almanac is not being proposed as a strong standalone edge.

**EXP-0 implication:** the coin-flip result (real entries +0.109R vs placebo −0.249R; exit engine
amplifies +0.231R on real signal, does not manufacture +0.075R of edge from noise alone) is
directly relevant to Almanac's yardstick role — a zero-parameter calendar rule is about as close to
a "matched-marginals random entry" as a real strategy gets. If Almanac's own net-of-cost result
lands near the EXP-0 placebo's −0.249R, that is consistent with the coin-flip finding that a bare
signal without the ratchet's amplification target (Almanac's exit is time-based, not TP-progress
based — see §4) does not manufacture edge on its own. Almanac beating the placebo baseline would be
informative; Almanac beating SilverBullet would not be expected and is not the point.

## 2. Evidence base

No backtest of Almanac exists in this repo. What exists is the calendar-anomaly literature (external,
not measured on Titan's data) and a hard sample-size ceiling:

| Item | Value | Source |
|---|---|---|
| Observations at current data depth | 12 signals/year × instrument × 3 years = **36 observations** | `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:358,367` |
| Observations after P10 (D1 history extension) | **≈240** (n scales with years of D1 history unlocked) | `05-STRATEGY-ARSENAL.md:367` |
| Effort to build | Half a day | `05-STRATEGY-ARSENAL.md:369` |
| Literature base (not measured on this repo's data) | Ariel (1987), Lakonishok & Smidt (1988) — turn-of-month outperformance in equity indices, effect partially decayed since publication | cited in `05-STRATEGY-ARSENAL.md:349,363` |

**Adverse evidence, stated plainly.** n=36 on current data is not a validatable sample by this
repo's own TVP discipline (300+ trades/symbol is the stated bar for the arsenal generally,
`05-STRATEGY-ARSENAL.md:75`) — Almanac cannot be validated, only built and observed, until the D1
history extension lands. The literature itself flags the effect as partially decayed. This is a
candidate built for its infrastructure value, not because the return source is expected to be
strong.

## 3. Signal specification

As designed (not implemented — no `src/strategies/models/almanac.py` exists):

- **Setup:** calendar date check — is today the last trading day of the month, or one of the first
  three trading days of the next.
- **Trigger:** D1 decision made at/after the D1 close of the qualifying day.
- **Entry:** MARKET at the H1 close (D1 decision, H1 execution — the only candidate with this
  split cadence).
- **Stop:** 2×ATR(20, D1) — explicitly protective only, not the exit mechanism
  (`05-STRATEGY-ARSENAL.md:356`).
- **Exit:** time-based — close of the third trading day of the new month, regardless of price.
- **Target:** none (protective stop only; exit is calendar-driven, not price-driven).
- **Universe:** US30 and US100 (both equity-index instruments with a documented flow mechanism).
- **Frequency:** 12 signals/year/instrument.

## 4. Architecture integration

- **Manifest sketch** (`config/manifests/almanac.yaml`, does not exist yet):
  ```yaml
  id: almanac
  version: "0.1"
  class_path: "src.strategies.models.almanac:Almanac"
  family: calendar
  timeframe: D1          # decision cadence; execution triggers on H1 close
  requires: [smc.enriched_df]   # raw OHLC/ATR path; no SMC dependency
  status: research
  priority: 10            # low-priority in arbiter tie-breaks; canary, not a capital-seeking strategy
  honors_htf_bias: false   # calendar signal is independent of H1 SMC directional bias
  ```
- **Class placement:** `src/strategies/models/almanac.py`, subclassing `BaseStrategy`. The D1
  decision / H1 execution split is unusual against the platform contract's single-`timeframe`
  routing model (`self.timeframe` decides which candle closes route to `on_new_candle`,
  `src/strategies/base_strategy.py`) — Almanac likely needs `timeframe: H1` with its own internal
  date-gate check inside `on_new_candle`, evaluating the calendar condition on every H1 close
  rather than being D1-routed, since the platform has no dual-timeframe routing mechanism today.
  This should be confirmed against `base_strategy.py`'s actual contract before implementation, not
  assumed.
- **Config block sketch** (`config/config.yaml`, under `strategies:`):
  ```yaml
  almanac:
    enabled: false
    timeframe: "H1"          # per the routing note above
    stop_atr: 2.0
    exit_trading_day: 3      # exit at close of 3rd trading day of the new month
    pairs: ["US30", "US100"]
  ```
- **FeatureBus resources:** none beyond ATR(20, D1), already available in the enrichment
  pipeline's OHLC/ATR path; no SMC-specific resource needed. A calendar/trading-day-index helper
  (last trading day of month, Nth trading day of month) does not currently exist in the repo and
  would need to be added — a small, self-contained utility.
- **Order types used:** MARKET only.
- **Grading path (P8 statement):** Almanac is not an SMC pattern — no displacement, no
  premium/discount, no killzone. Structurally under-graded by the current SMC-shaped grader exactly
  as Anchor/Tether/Ledger are (`05-STRATEGY-ARSENAL.md:420`, P8). For a canary strategy this may be
  acceptable to run at a low or explicitly carved-out grade floor rather than waiting on the full
  P8 fix, since Almanac's purpose is infrastructure verification, not capital-seeking — but that is
  a design choice to make explicitly, not a default.
- **HTF-bias stance:** `honors_htf_bias: false`. The calendar signal has no relationship to the H1
  SMC directional bias the controller filters against.
- **Exit profile:** needs a per-strategy exit profile (P7) — this is the strategy least compatible
  with the default ratchet of any candidate in the arsenal, since the exit is purely time-based
  with no TP-progress concept at all (not even a signal-flip condition, unlike Anchor/Ledger).
  `initial_tp` is never meaningfully set; the ratchet's ladder (38.2%/61.8%/88.6% of TP progress)
  has nothing to key off.
- **Risk interaction:** standard broker-spec sizing. Two symbols, short expected hold (a few
  trading days), 12 trades/year/symbol — low count, low urgency; a natural fit for the smallest
  risk-per-trade unit in any eventual multi-strategy budget.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| **P7** | Per-strategy exit profile (time-based exit, no TP-progress ratchet) | Almanac's exit has no fixed-target concept at all; the least ratchet-compatible design in the arsenal | 1 day (shared with Anchor/Ledger/Tether) |
| **P8** | Non-SMC grading path (or an explicit carve-out for a canary strategy) | Grader is SMC-shaped; Almanac structurally under-grades | 1 day (shared) |
| Calendar/trading-day utility | Last-trading-day-of-month and Nth-trading-day-of-month logic | Not present in the repo today; small, self-contained | not separately sized; part of the half-day build estimate |
| **P10** (only for validation, not for building) | 15-25y D1 history + `collect_signals` D1 rules | Needed to reach n≈240; **not needed to build or deploy Almanac as a canary** — the canary role works at n=36 | 1 afternoon |

Unlike Anchor/Tether/Ledger, Almanac's infrastructure bill for *deployment as a canary* is close to
nil — it needs P7 and P8 like every non-SMC candidate, plus a small calendar utility, but does
**not** need P10, P12, ARCH-01, or RISK-04 to serve its integration-test purpose. Effort to build:
half a day (`05-STRATEGY-ARSENAL.md:369`).

## 6. Validation plan

**What cannot be validated with current data:** genuine statistical validation. n=36 is far below
the 300+ trades/symbol bar the arsenal otherwise holds itself to
(`05-STRATEGY-ARSENAL.md:75`); Almanac "can never be validated on current data"
(`05-STRATEGY-ARSENAL.md:367`), full stop. This is not a caveat to work around — it is the reason
Almanac is framed as a yardstick and canary rather than a capital-seeking candidate at this data
depth.

**Pre-registered gate criteria (once meaningful, i.e. post-P10, n≈240):**
- Net-of-cost expectancy positive on 70/30 chronological IS/OOS.
- Must beat itself as its own baseline in one specific sense: every other candidate in the arsenal
  must be compared against Almanac, not the reverse — Almanac is the floor, not a target to clear
  (`05-STRATEGY-ARSENAL.md:363`).
- Spread ×1.5/×2 stress, bootstrap CI, one-pass rule — standard TVP discipline
  (`05-STRATEGY-ARSENAL.md:68-73`).

**Deployment before validation (the canary role):** Almanac is explicitly recommended to run on the
demo soak *before* it can be statistically validated, because its value there is architectural, not
statistical — live-vs-backtest divergence on a strategy whose signals are known months in advance
isolates infrastructure bugs from strategy questions (`05-STRATEGY-ARSENAL.md:365`). This is a
deliberate exception to the platform's validate-before-deploy culture, justified by the canary's
distinct purpose.

## 7. Failure modes and monitoring

- **The canary's entire value is divergence detection** — the primary "failure mode" worth watching
  for is actually a success condition: if live behaviour diverges from the pre-known backtest
  schedule, that is a caught infrastructure bug (clock, session logic, order path, or journal),
  not a strategy failure. Monitoring should explicitly diff live entry/exit timestamps against the
  precomputed calendar schedule every cycle.
- **Effect decay:** the turn-of-month anomaly is documented as partially decayed since original
  publication; a null or negative live result is a plausible honest outcome, not necessarily a bug.
  Distinguishing "the anomaly decayed" from "the infrastructure is broken" requires the divergence
  check above to rule out the latter first.
- **Grading silently blocking signals** (P8, or its carve-out) — same risk pattern as Anchor/
  Tether/Ledger: a live-enabled Almanac that never fires because of grade-floor gating would look
  identical to "no signal today" without explicit grade-distribution monitoring.
- **Portfolio correlation** is not populated in the audit's correlation-prior matrix for Almanac at
  all (`05-STRATEGY-ARSENAL.md:378-386` lists SilverBullet/Coil/Tide/Bell/Anchor/Tether/Ledger, not
  Almanac) — no prior exists to state, and none should be invented.
- **Ops:** fail-safe lot=0 on missing specs applies; low trade frequency (12/year/symbol) means a
  missed signal due to a data-load gap could go unnoticed far longer than on a higher-frequency
  strategy — worth an explicit "next expected signal date" monitor given the sparse cadence.

## 8. Verdict and sequencing

Build it, for reason 2 (integration canary) alone — the source document's own framing
(`05-STRATEGY-ARSENAL.md:369`). At half a day of effort and near-zero infrastructure dependency
beyond the shared P7/P8 non-SMC gaps, Almanac is the cheapest item in the arsenal to ship and the
only one recommended to deploy on the demo soak *before* validation is possible. **Sequencing per
the audit's staging plan: Stage 1**, built alongside the shared audit-debt prerequisites (P1, P3,
P5, P6, P8, P10, P11) and run on the demo soak alongside SilverBullet as the integration canary
(`05-STRATEGY-ARSENAL.md:438`). Its statistical validation is deferred to post-P10 (n≈240) and is
explicitly not a blocker for its canary deployment. Depends on: P7/P8 (shared with every non-SMC
candidate); P10 only for eventual statistical validation, not for the canary build. Every other
candidate in this arsenal (`docs/strategies/anchor.md`, `docs/strategies/tether.md`,
`docs/strategies/ledger.md`) should ultimately be reported against Almanac's net-of-cost result as
the standing complexity baseline.
