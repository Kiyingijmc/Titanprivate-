# LEDGER — Carry Harvest with a Momentum Overlay (D1 hold)

> **Status:** candidate — Step-0 falsification IN PROGRESS · **Family:** carry / momentum overlay
> · **Timeframe:** D1 hold ·
> **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §9 · **Doc version:** 2026-08-01

## 1. Thesis and return source

The carry premium — long high-yielders, short low-yielders, harvesting the interest-rate
differential and accepting periodic crash risk — is among the most robustly documented return
sources across asset classes (Koijen, Moskowitz, Pedersen & Vrugt, 2018; the FX carry literature
from Lustig & Verdelhan onward). In an MT5 CFD account the differential is expressed directly as
nightly swap, credited or debited per position held past rollover
(`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:307`). Ledger overlays a D1 momentum filter on top
of the carry direction, because carry without a trend filter is, in the source document's phrase,
"picking up pennies in front of a truck" — the difference between the documented academic premium
and a 2008-style carry unwind (`05-STRATEGY-ARSENAL.md:329`).

**EXP-0 implication:** the coin-flip result (real entries +0.109R, placebo −0.249R; exit engine
amplifies +0.231R on real signal but does not create +0.075R of edge from noise alone) means
Ledger's entry — MARKET on a carry-and-momentum-agree signal — has to be the source of whatever
edge it has. But Ledger's premise is explicitly not about entry timing skill; it is a structurally
different bet (get paid to hold, not to be right quickly, `05-STRATEGY-ARSENAL.md:331`) with a
4×ATR(20,D1) stop and a carry/momentum-flip exit that barely touches the ratchet machinery that
amplifies SilverBullet. Ledger's expectancy, if any, will not come from the exit engine's proven
skew-capture; it has to come from the carry differential itself surviving the broker markup — which
is precisely what Step-0 is designed to test before any of this is built.

## 2. Evidence base

**Step-0 is currently underway, not merely planned.** Branch `feat/swap-survey` in this repo
contains the commit "feat(research): Ledger Step-0 swap survey over the HTTP bridge" plus a bridge
version bump to 0.2.0 adding `SymbolInfo` swap fields (verified: `git log feat/swap-survey` shows
`da17d84 feat(research): Ledger Step-0 swap survey over the HTTP bridge` and
`6b4735e chore(bridge): version 0.2.0 — SymbolInfo swap fields`). A corresponding backlog row
(`ledger-step-0-swap-survey-log`) sits in the mig inbox. **No Step-0 results exist yet** — the
survey collects nightly swap data; the gate has not been evaluated.

| Item | Status | Source |
|---|---|---|
| Step-0 swap survey | IN PROGRESS — branch `feat/swap-survey`, bridge 0.2.0 SymbolInfo swap fields committed, backlog row open | this repo, `feat/swap-survey` branch |
| Carry strategy itself | No result — Step-0 gate not yet evaluated | — |
| Backtester swap modelling | **Confirmed gap (STRAT-06): the backtester models no swap at all.** Every current strategy holding overnight, including SilverBullet's runner, carries an unmodelled cost today | `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:337` |

**Adverse evidence, stated plainly — the author's own prior is that this fails.** The source
document states explicit skepticism: "the most diversifying idea here and the one I am most
skeptical of" (`05-STRATEGY-ARSENAL.md:304`), and the panel synthesis records an explicit bet —
"I would bet 80% it fails the 3% gate. Take that bet — it is two hours"
(`05-STRATEGY-ARSENAL.md:470`). The mechanism for doubting the retail implementation is specific:
FBS quotes swap on both sides with a markup, so the long-side credit is systematically smaller than
the short-side debit; brokers also revise swap rates without notice and apply triple swap on
Wednesdays (`05-STRATEGY-ARSENAL.md:310`). This is a case, per the source, where "a real academic
anomaly usually does not survive the retail wrapper."

## 3. Signal specification

As designed (not implemented — no `src/strategies/models/ledger.py` exists; contingent on Step-0):

- **Step-0 gate (already running):** log `SYMBOL_SWAP_LONG` and `SYMBOL_SWAP_SHORT` nightly for
  all 12 configured symbols via the bridge's `SymbolInfo` swap fields. Compute per symbol the
  annualised net carry if held long, and if held short.
  - **Gate:** does any symbol offer net positive carry exceeding 3% annualised after the broker's
    markup? If no — stop, delete the idea (cost: 2 hours of code, ~2 weeks of data collection). If
    yes — proceed to design (`05-STRATEGY-ARSENAL.md:317-323`).
- **If a symbol survives Step-0:**
  - **Setup:** net annualised carry > 3% AND D1 momentum agrees with the carry direction.
  - **Entry:** MARKET, small size.
  - **Stop:** 4×ATR(20, D1) — very wide; the premise is being paid to hold, not to be right
    quickly.
  - **Exit:** carry turns negative, or momentum flips.
  - **Hold:** weeks to months.
  - **Universe:** whichever symbols pass the Step-0 gate — not predetermined. XTIUSD, ETHUSD and
    BTCUSD are flagged as the longest-carry exposures worth watching
    (`05-STRATEGY-ARSENAL.md:337`).

## 4. Architecture integration

- **Manifest sketch** (`config/manifests/ledger.yaml`, does not exist yet, and should not be
  written before Step-0 resolves):
  ```yaml
  id: ledger
  version: "0.1"
  class_path: "src.strategies.models.ledger:Ledger"
  family: carry
  timeframe: D1
  requires: [smc.enriched_df]   # raw OHLC/ATR path, no SMC dependency
  status: research
  priority: 92
  honors_htf_bias: false   # carry direction is its own thesis, independent of H1 SMC bias
  ```
- **Class placement:** `src/strategies/models/ledger.py`, subclassing `BaseStrategy`,
  `timeframe: "D1"`. D1 candle-close routing needs `collect_signals`/CandleMaker support for D1,
  which does not exist today (see §5, shared with Anchor's P10 need).
- **Config block sketch** (`config/config.yaml`, under `strategies:`):
  ```yaml
  ledger:
    enabled: false
    timeframe: "D1"
    min_annualised_carry_pct: 3.0
    momentum_lookback_bars: 20   # D1; needs its own validation, not borrowed from Anchor's 126
    stop_atr: 4.0
    pairs: []   # populated only by symbols that pass the Step-0 gate
  ```
- **FeatureBus resources:** swap data is not currently a FeatureBus resource — it arrives via the
  bridge's `SymbolInfo` fields (feat/swap-survey work), not via the ZMQ `HISTORY` message the rest
  of the system uses for broker specs. Wiring swap into the live trading path (as opposed to the
  research survey) is unbuilt and is a distinct piece of work from the HTTP-bridge survey.
- **Order types used:** MARKET only.
- **Grading path (P8 statement):** Ledger is not an SMC pattern — no displacement, no
  premium/discount, no killzone. Structurally under-graded by the current SMC-shaped grader
  (`05-STRATEGY-ARSENAL.md:420`, P8) exactly as Anchor and Tether are; needs the same non-SMC
  grading path.
- **HTF-bias stance:** `honors_htf_bias: false`. Carry direction is a distinct, longer-horizon
  thesis from the H1-cached SMC bias the controller filters against.
- **Exit profile:** needs a per-strategy exit profile (P7) — exit is carry-turns-negative or
  momentum-flip, not TP-progress-based. Like Anchor, no `initial_tp` exists to anchor the default
  ratchet's ladder.
- **Risk interaction:** standard broker-spec sizing; "small size" per the design brief is a
  placeholder pending an actual risk-per-trade figure once Step-0 and any subsequent validation
  produce real numbers. STRAT-06 (unmodelled swap cost in the backtester) means Ledger's own
  backtest results, once built, would be systematically optimistic until the swap model (P11) is
  wired into `trade_dollars` — the same gap that currently understates the true cost of every
  overnight-holding strategy, including SilverBullet's runner.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| Step-0 gate resolution | Evaluate the swap survey already running on `feat/swap-survey` | Binary go/no-go; author's stated 80% prior is failure | 2 hours code (done) + ~2 weeks data collection (in progress) |
| **P10** | 15-25y D1/H4 history + `collect_signals` D1 resampling | D1 candle routing for the strategy itself needs this regardless of Step-0's outcome; also needed to validate the momentum-overlay component | 1 afternoon |
| **P11** | Swap model wired into `trade_dollars` | Fixes STRAT-06 for the whole system, not just Ledger; needed for any honest Ledger backtest | 4 hours |
| **P7** | Per-strategy exit profile (carry-flip / momentum-flip exit) | Default ratchet has no home for a non-TP exit condition | 1 day |
| **P8** | Non-SMC grading path | Grader is SMC-specific; Ledger structurally under-grades | 1 day |

**The swap survey is worth its cost regardless of Ledger's fate** — it produces the swap table the
backtester has been missing system-wide (STRAT-06), independent of whether Ledger ever ships
(`05-STRATEGY-ARSENAL.md:337,340`).

## 6. Validation plan

**What cannot be validated with current data:** the carry gate itself — Step-0 requires live nightly
swap observations, which by definition cannot be backfilled from historical price data; it is
running in real time on `feat/swap-survey` and needs its own data-collection window (~2 weeks
referenced in the source design). The momentum-overlay component, once a symbol clears Step-0,
faces the same D1 sample-size problem as Anchor (~775 bars/symbol pre-P10) — cannot validate a
weeks-to-months hold horizon on current data.

**Sequencing:**
1. **Step-0 gate (in progress):** any symbol with net positive carry > 3% annualised after markup.
   If none — stop; document the negative result; the swap table itself is still a deliverable.
2. **If a symbol survives:** pre-register a full TVP study — 70/30 IS/OOS, ±30% sweeps on the
   carry threshold and momentum lookback, spread stress, bootstrap CI, one-pass rule
   (`05-STRATEGY-ARSENAL.md:68-73`) — on D1 data, gated on P10 for adequate sample size, and on P11
   for honest cost modelling.
- **Baseline:** must beat Almanac's zero-parameter yardstick net of costs.
- **Kill criteria:** the Step-0 gate itself is the primary kill criterion — most likely outcome per
  the author's own prior is that it fails and the idea is deleted at negligible cost
  (`05-STRATEGY-ARSENAL.md:340`). If Step-0 passes, standard TVP kill criteria (OOS expectancy
  sign flip, drawdown breach, sub-threshold sample size) apply to the subsequent study.

## 7. Failure modes and monitoring

- **Broker markup asymmetry** is the central identified risk: FBS's long-side credit is
  systematically smaller than the short-side debit, and swap rates change without notice —
  including triple-swap Wednesdays (`05-STRATEGY-ARSENAL.md:310`). A pass on Step-0 today is not a
  guarantee the same symbol clears the gate in six months; ongoing swap-rate monitoring would be
  needed even after a live decision, not just at Step-0.
- **Carry-without-momentum-filter risk:** the design brief is explicit that carry alone is
  "picking up pennies in front of a truck" — the momentum overlay is not decoration, it is risk
  management against a sudden carry unwind (`05-STRATEGY-ARSENAL.md:329`).
- **Backtester blind spot (STRAT-06) understates cost for every overnight strategy today**, not
  just Ledger — this is a live, present-tense monitoring gap independent of whether Ledger ships.
- **Portfolio correlation to Anchor** is an audit prior of +0.4 — the highest cross-strategy prior
  in the matrix (`05-STRATEGY-ARSENAL.md:386`). **This is a prior, not a measurement.** If real,
  it would mean Ledger and Anchor have poor months together, undermining the diversification case
  for running both.
- **Ops:** fail-safe lot=0 on missing specs applies as everywhere; D1-hold strategies additionally
  need to survive multi-day reconciliation cycles without state drift, a scenario the existing
  Sync Guard has not been specifically exercised against for week-long holds.

## 8. Verdict and sequencing

Candidate, Step-0 falsification in progress. The correct sequencing is already happening: cheap
falsification before design investment, exactly as the audit recommends
(`05-STRATEGY-ARSENAL.md:340,469`). The author's own prior is 80% failure, and unanimous panel
agreement is to run Step-0 and not design past it until it passes
(`05-STRATEGY-ARSENAL.md:471`). Regardless of outcome, the swap survey is a net-positive
deliverable — it produces the missing swap table for STRAT-06. **Recommendation: let Step-0
resolve before writing `src/strategies/models/ledger.py` or a manifest.** Sequencing per the
audit's staging plan: **Stage 4**, run in parallel with Anchor once P10 lands
(`05-STRATEGY-ARSENAL.md:441`). Depends on: P10 (shared with Anchor/Almanac); P11 swap modelling
(this strategy's own prerequisite, but also a system-wide fix); no dependency on Tether's
infrastructure (ARCH-01/RISK-04/P13) — Ledger is single-leg.
