# COIL — volatility-compression expansion breakout

> **Status:** candidate (pre-registration pending) · **Family:** volatility clustering / breakout ·
> **Timeframe:** H1 · **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §4 · **Doc
> version:** 2026-08-01

## 1. Thesis and return source

Volatility clusters: periods of unusually compressed range are statistically followed by
expansion, and the direction of that expansion is not predicted in advance — it is declared by
which side of the compressed range breaks first. Coil is a two-sided bracket: a STOP order resting
above the range and a STOP order resting below it, so the strategy is positioned for the expansion
without taking a directional view. The return source is the compression→expansion regularity
itself, not a directional read of the market (05-STRATEGY-ARSENAL.md §4, "Thesis").

This makes Coil structurally different from SilverBullet, which is a directional, HTF-bias-filtered
continuation entry. Coil's edge, if real, comes from *catching the expansion move itself* — the
stop is the compressed-range width, which is wide by construction, and the payoff distribution is
expected to have a fat right tail that the ratchet/runner exit engine is well suited to monetise
(05-STRATEGY-ARSENAL.md §4, "Why it fits this bot specifically").

**EXP-0 implication:** the exit engine amplifies genuine entries (+0.231R on SilverBullet's real
entries) but does not subsidise random ones (+0.075R on placebo, net −0.249R after full engine)
(EXP-0 outcome 1, 2026-07-31; brief §"Hard constraints"). Coil's entry must therefore do its own
work — a compression breakout has to actually select for expansion, not merely produce a
trade-frequency and stop-geometry pattern the ratchet can ride regardless of signal quality. This
is untested for Coil specifically; it is the reason a pre-registered gate is mandatory before any
capital is risked.

## 2. Evidence base

**No Coil-specific backtest exists yet.** Nothing below is a result; it is the design basis and the
adverse context that bounds expectations.

| Source | What it establishes | Citation |
|---|---|---|
| SilverBullet H1 stop study | H1 is the only timeframe simultaneously satisfying sample size (~18,600 bars/symbol over 3y) and the cost gate; validates the *timeframe* choice Coil inherits | brief §"Data"; `data/lake/frozen/PROVENANCE.md` |
| Cost table | EURUSD 8, GBPUSD 12, USDJPY 10, AUDUSD 10, USDCAD 12, GBPJPY 25, XAUUSD 20, US30 200, BTCUSD 1000, XBRUSD 30 (points); commission $7/lot | `scripts/poc_sb_stops.py:43` |
| The graveyard | Gyroscope (H1-momentum family, direction-predictive) NO-GO'd three times, most recently −0.067R pooled, 27.1% realised false-entry vs 5% designed α (2026-07-15) | brief §"Hard constraints" |
| The graveyard | Original SilverBullet on M5 with a 0.2×ATR stop: −4.27R — the canonical example of a stop too tight for the cost structure | brief §"Hard constraints" |
| EXP-0 coin-flip | Placebo entries through the full ratchet+runner exit engine: −0.249R (0/20 reps positive); the exit engine does not manufacture edge from arbitrary entries | brief §"Hard constraints" |

**Adverse framing, stated plainly:** Coil has never been run. Its expected profile (win rate
35–42%, average winner 2.5–4R, expectancy target ≥+0.15R net, 250–400 trades/symbol over 3y;
05-STRATEGY-ARSENAL.md §4 "Expected profile") is a design target, not a measured result. Gyroscope
is the closest analogue in the graveyard — also H1, also structural-stop, also expansion-flavoured
— and it failed three times. Coil differs by being direction-agnostic rather than
direction-predictive, which removes Gyroscope's specific failure mode (predicting the wrong side)
but does not by itself prove an edge exists. Losses are expected to cluster in range-bound regimes;
"long flat stretches punctuated by good months" is the explicit trade-off to accept before funding
it (05-STRATEGY-ARSENAL.md §4).

## 3. Signal specification

As drafted in the pre-registration sketch (05-STRATEGY-ARSENAL.md §4, "Mechanics"):

```
Setup:    ATR(14,H1) in its bottom 25th percentile of the trailing 200 bars
          AND max(high) − min(low) over the last 4 bars < 1.2 × ATR(14)
Trigger:  BUY  STOP at range_high + 0.15 × range_width
          SELL STOP at range_low  − 0.15 × range_width
Stop:     opposite side of the range, floored at 0.8 × ATR(14,H1)
Target:   ratchet + runner (inherited)
OCO:      on one fill, cancel the other        ← does not exist today (see §5)
Expiry:   4 bars unfilled → cancel
Filter:   spread ≤ 0.15 × planned stop distance ← needs ask-price capture (see §5)
Universe: all 12 live pairs (all pass the H1 cost gate)
```

Both legs are STOP orders bracketing the compressed range. Filling one leg without cancelling the
other is a known-open failure mode until OCO exists (§5). Nothing about this trigger references
HTF bias, SMC structure (FVGs, displacement), premium/discount, or killzones — it is a pure
range/volatility signal, which has direct consequences for grading (§4) and for the HTF bias filter
(§4).

## 4. Architecture integration

**Manifest sketch** (`config/manifests/coil.yaml`):

```yaml
id: coil
version: 0.1.0
class_path: src.strategies.models.coil.Coil
family: volatility_compression
timeframe: H1
requires: [smc.enriched_df]   # for ATR; does not need FVG/bias/PD columns
status: research               # promote to demo only after pre-registered gate passes
priority: 60                   # lower rank than SilverBullet (50) at the arbiter tie-break
honors_htf_bias: false          # see bias-filter stance below
```

**Class placement:** `src/strategies/models/coil.py`, subclassing `BaseStrategy`
(`src/strategies/base_strategy.py`), implementing `async def on_new_candle(self, df, context=None)`
returning `{'signal': 'BUY'|'SELL', 'type': 'STOP', 'price': …, 'sl': …, 'tp': …}` — this would be
the **first strategy to use `type: STOP`** in the live decision dict; the field is already threaded
end-to-end (`Titan_Gateway.mq5:139–145`, `system_controller.py:637–640`) but currently unexercised
by any strategy (backlog row `oco-pending-order-pairs-arsenal-p2`).

**Config block sketch** (`config/config.yaml`, under `strategies:`):

```yaml
strategies:
  coil:
    enabled: false   # flip after pre-registered gate + operator /enable with allow_research
    pairs: [EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, US100, BTCUSD, ETHUSD, XTIUSD]
```

**FeatureBus resources:** consumes `smc.enriched_df` for `ATR` only; does not need
`is_fvg_bull/bear`, `fvg_top/bottom`, or `smc.bias_context`. Because a two-sided bracket is
direction-agnostic by design, it does not need the HTF bias filter that gates SilverBullet.

**Order types:** BUY STOP + SELL STOP, both legs live simultaneously — this is the platform's first
real use of paired pending orders, which is why OCO (P2) is a hard architecture prerequisite rather
than a nice-to-have.

**HTF-bias stance:** Coil should run with `honors_htf_bias: false` in the manifest, and needs the
controller's HTF-bias filter to actually respect that flag for a two-sided bracket — today the
filter's per-strategy exemption semantics for a direction-agnostic signal are not policy-defined
(backlog row `bias-filter-exemption-policy-arsenal-review`: per-strategy exemption from the H1 HTF
bias filter at `system_controller.py:828,842`, precedent = the Gyroscope exemption set). Without
this, a legitimate two-sided bracket could have one leg silently filtered by bias while the other
survives, breaking the OCO symmetry the strategy depends on.

**Grading path (P8 statement):** `SignalGrader.grade()` (`src/analysis/signal_grader.py`) scores
HTF alignment (30), R:R (20), displacement (20), premium/discount (15), killzone (15) — all five
factors either assume SMC structure or a directional read Coil does not produce. Per backlog row
`grading-policy-for-non-smc-signals`, the grader degrades gracefully rather than erroring (neutral
bias +10, unknown premium/discount +5) but caps around 70–75 without SMC context — below a
`min_grade: B` gate on some scoring scales. This is a **policy decision, not a blocker**: either
exempt Coil by manifest from grading, or define a per-strategy grade profile that scores R:R and
displacement-equivalent (breakout strength) without penalising the absent SMC fields. Coil cannot
go live until this policy is decided.

**Exit profile:** default ratchet + runner (no per-strategy exit variant proposed for Coil — unlike
Tide, its fat-tail breakout profile is exactly what the runner was built for; see
`docs/strategies/silver-bullet.md` §4 for the mechanism).

**Risk interaction:** standard broker-spec sizing via `RiskManager.calculate_lot_size`. Both STOP
legs, while pending, are Titan-placed resting orders and are counted in the portfolio risk cap
(`risk.account.max_total_open_risk_pct`) per their state-DB rows — this is already true of the
existing cap design (brief §"Risk"), but Coil is the first strategy to exercise it with two
simultaneous pending legs on one symbol, which will double-count risk against the cap until one
leg cancels (further reason OCO is a hard prerequisite, not an optimisation).

## 5. Infrastructure prerequisites

| # | Prerequisite | Backlog / audit row | Effort | Why Coil needs it |
|---|---|---|---|---|
| P2 | OCO pending-order pairs: `sibling_ticket` column in `state_manager` `active_orders` + cancel-on-fill in the `EXECUTION:OPENED` handler + paired TTL/CANCEL | `oco-pending-order-pairs-arsenal-p2` (inbox) | 1 day | Without it, filling one leg leaves the other resting; `max_positions_per_symbol: 1` then *blocks* (does not cancel) the sibling, which parks it until TTL expiry — a silent risk and exposure-accounting bug |
| — | Bias-filter exemption policy for non-SMC/direction-agnostic strategies | `bias-filter-exemption-policy-arsenal-review` (inbox) | S (small) | A two-sided bracket has no direction to filter; `honors_htf_bias: false` needs defined semantics at `system_controller.py:828,842` before Coil's brackets behave symmetrically |
| P8 | Grading policy for non-SMC signals | `grading-policy-for-non-smc-signals` (inbox) | S (small) | `signal_grader` caps ~70–75 without SMC context; decide exempt-by-manifest vs a per-strategy grade profile before `min_grade` gates every Coil signal out |
| P6 / RISK-07 | Ask-price capture; live spread gate | brief §"platform contract" item 1 (`context['spread']` does not exist today) | ~1 h (per audit) | Coil's `spread ≤ 0.15 × planned stop distance` filter is inert without it — the same gap that makes Gyroscope's spread gate inert today |

All four are pre-existing audit debt, not Coil-specific work — Coil is the first strategy that
makes them load-bearing rather than optional.

## 6. Validation plan

TVP instantiation, following the culture in brief §"Validation culture (TVP)":

- **Pre-registered gate**, committed to `docs/research/` before any run, specifying the exact
  mechanics in §3, the universe (all 12 live pairs), and the kill criteria below — fixed in
  advance, one-pass (no in-place re-tuning on the same data).
- **Data:** the existing ~3y H1 frame (resampled from `data/history/<SYM>_M5.csv`,
  `data/lake/frozen/PROVENANCE.md`) — no data extension required; this is Coil's chief
  infrastructure advantage over Anchor/Ledger/Almanac.
- **Baselines:** compare against MaSlopeBaseline (exists) and, per the audit's standing
  recommendation, Almanac as a zero-parameter yardstick once Almanac exists (brief §"Validation
  culture"; 05-STRATEGY-ARSENAL.md §10).
- **Cost stress:** ×1.5 and ×2 spread, using the same table as SilverBullet
  (`scripts/poc_sb_stops.py:43`).
- **Sample size:** target 300+ trades per symbol over 3 years per the brief's minimum-n rule; the
  expected 250–400 trades/symbol design estimate is close to that floor and should be checked
  early rather than assumed.
- **What CANNOT be validated with current data:** cannot validate a mechanical OCO failure mode in
  offline replay — the offline replay (`poc_sb_stops.replay_managed`) has no concept of two
  simultaneous pending orders, so the P2 dependency's *correctness* can only be checked live/demo,
  not in the research harness. Cannot validate realised spread on the STOP-order entries — the
  research harness has no ask-price / slippage model (same STRAT-03 gap that affects Bell).
- **STRAT-01 caveat applies identically to Coil:** whatever managed-exit number the offline replay
  produces is an upper bound, not a live number, because the research harness never drives the live
  `TradeManager` ratchet (brief §"Research harness").

## 7. Failure modes and monitoring

- **Chop regime:** the design explicitly expects long flat-to-negative stretches in range-bound
  markets — this is a *by-construction* property, not a bug, per 05-STRATEGY-ARSENAL.md §15. Decide
  the tolerable drawdown duration before funding, not during.
- **OCO race condition:** if P2 ships with a bug, both legs could fill (a hedge on one symbol) or
  neither could cancel (stale pendings accumulating exposure against the portfolio cap). Monitor:
  count of simultaneous same-symbol pending orders per Coil signal; alert if > 1 persists past one
  bar after a fill.
- **Grading starvation:** if the P8 policy under-scores Coil signals, the strategy could silently
  never clear `min_grade` and produce zero trades — indistinguishable from "no compression setups
  occurred" without explicit grade-distribution logging.
- **Spread-gate inertness:** until P6 lands, the `spread ≤ 0.15×stop` filter is a no-op; monitor
  realised cost per trade against the 0.25R gate manually until it is live.
- **Self-audit metrics for the live/demo phase:** per-symbol trade count vs the 250–400/3y design
  band; realised win rate vs the 35–42% band; fraction of P&L from one symbol (>60% is a kill
  criterion below); OCO sibling-cancel latency.

## 8. Verdict and sequencing

**Stage 2** in the audit staging (05-STRATEGY-ARSENAL.md §13) — "First real candidate," described
as "your pipeline dress rehearsal" whose purpose is a trustworthy validation process as much as a
surviving strategy; a pre-registered NO-GO is an explicitly successful outcome of this stage.

**Sequencing dependencies:** Stage 0 (EXP-0) is complete (2026-07-31, Outcome 1: entries do real
work). Stage 1 audit debt items P1/P3/P5/P6/P8/P10/P11 are the stated Stage-1 prerequisite bundle
for the arsenal broadly; Coil specifically hard-requires P2 (OCO), the bias-filter exemption
policy, the P8 grading policy, and P6 (ask-price/spread gate) before it can go from `research` to a
funded pre-registration run. None of P2, the bias-filter policy, or the grading policy are started
— all three are `inbox` rows in the mig backlog as of this writing. Recommendation: land P2 first
(it is the hard blocker with no workaround — pending both legs without it is unsafe), settle the
grading and bias-filter policy decisions in parallel (they are decisions, not builds, and can be
made before P2 lands), then run the pre-registered gate. Do not promote the manifest past
`status: research` until the gate is scored against the kill criteria below.

**Kill criteria** (05-STRATEGY-ARSENAL.md §4): OOS expectancy < +0.05R net; or fails at 1.5× spread
stress; or fewer than 3 of 4 calendar years positive; or more than 60% of P&L concentrated in one
symbol.
