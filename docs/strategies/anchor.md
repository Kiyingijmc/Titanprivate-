# ANCHOR — Diversified Time-Series Momentum (H4 now, D1 later)

> **Status:** candidate (pre-registration pending) — blocked on data · **Family:** time-series
> momentum (TSMOM) · **Timeframe:** H4 now, D1 target ·
> **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §7 · **Doc version:** 2026-08-01

## 1. Thesis and return source

Time-series momentum — going long instruments with positive trailing returns and short those with
negative trailing returns, sized so each contributes equal risk — is one of the most documented
anomalies in finance (Moskowitz, Ooi & Pedersen 2012, 58 instruments across four asset classes;
Hurst, Ooi & Pedersen extend the evidence back roughly a century) and is the return source the
managed-futures industry is built on. The return source is trend persistence at a 3-12 month
horizon, harvested as a **portfolio effect**: no single instrument's momentum is a reliable bet,
but a wide, vol-scaled basket of them is (`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:236`).

**EXP-0 implication:** the coin-flip result (placebo −0.249R vs real +0.109R, 0/20 reps positive;
`docs/research/2026-07-31-exp0-coinflip-preregistration.md`) establishes that Titan's exit engine
amplifies a real entry edge (+0.231R) but does not manufacture one from noise (+0.075R on random
entries). Anchor's MARKET entry and signal-flip exit do not lean on the ratchet's skew-capture
mechanics the way SilverBullet's LIMIT-at-FVG entry does — TSMOM must show its own edge on a
portfolio equity curve; it cannot borrow the ratchet's amplification the way an FVG entry can.

## 2. Evidence base

There is no valid empirical result for Anchor in this repo yet. What exists is one falsified
adjacent test and a literature base that does not transfer directly:

| Study | Result | Source |
|---|---|---|
| Donchian-20/D1 test (undated, referenced in audit) | Falsified: "too fast, weak," cost-robust structure at −0.1 to −0.25R | `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:234` |
| Literature base (not measured on this repo's data) | Moskowitz/Ooi/Pedersen (2012), Hurst/Ooi/Pedersen — documents TSMOM at 3-12 month horizons across asset classes | cited in `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:232` |

**Adverse evidence, stated plainly — the falsified Donchian-20 test measured the wrong thing.** A
20-day lookback on D1 is short-term reversal territory, not the 3-12 month horizon the momentum
literature documents. The audit's own diagnosis: "you tested the wrong horizon and correctly
diagnosed it" (`05-STRATEGY-ARSENAL.md:234`). This is not evidence Anchor works — it is evidence
that one specific, badly-specified variant of a trend signal does not. Anchor as specified below
(63-bar H4 / 126-day D1 lookback, EMA(50) confirmation) has never been tested. Nothing in this
repo currently supports or refutes it; the "most evidence-backed strategy in the set" claim rests
entirely on external literature, not on Titan's data (`05-STRATEGY-ARSENAL.md:229`).

Two further reasons the literature does not transfer cleanly without more work: TSMOM's edge is
"overwhelmingly a portfolio effect," requiring 10+ instruments with volatility-scaled sizing so
each contributes equal risk, while Titan's research rigs test per-symbol and pool R
(finding STRAT-05, `05-STRATEGY-ARSENAL.md:236`) — a portfolio-level backtest does not exist
(P12). Single-instrument TSMOM has a poor Sharpe even when the portfolio version works well.

## 3. Signal specification

As designed (not yet implemented — no `src/strategies/models/anchor.py` exists):

- **Setup:** sign of the 63-bar return on H4 (≈10 trading days) or the 126-day return on D1
  (≈6 months), confirmed by price above/below its own EMA(50) on the same timeframe.
- **Trigger:** the confirming bar closes with sign(return) matching side of EMA(50).
- **Entry:** MARKET on the confirming bar close — no passive entry; TSMOM cannot afford to miss
  the defining move (`05-STRATEGY-ARSENAL.md:242-243`).
- **Stop:** 3.0×ATR(20) on the signal timeframe — deliberately very wide so every symbol clears
  the cost gate trivially (`05-STRATEGY-ARSENAL.md:244`).
- **Sizing:** inverse-volatility weighted so each position contributes equal portfolio risk — this
  is not optional; it is the mechanism that makes TSMOM a portfolio effect rather than noise.
- **Target:** none. Exit is signal flip, or the trailing component of the ratchet. This is a
  structurally different exit profile from SilverBullet's fixed-TP-anchored ratchet (see §4, P7).
- **Universe:** all 12 configured symbols — breadth is the point; TSMOM wants the widest possible
  basket, not a curated subset.
- **Hold:** weeks; expect 1.5-4% of bars in a position (`05-STRATEGY-ARSENAL.md:248`).

## 4. Architecture integration

- **Manifest sketch** (`config/manifests/anchor.yaml`, does not exist yet):
  ```yaml
  id: anchor
  version: "0.1"
  class_path: "src.strategies.models.anchor:Anchor"
  family: momentum
  timeframe: H4          # D1 after P10. NOTE: neither H4 nor D1 is routed today —
                         # DataStore builds M5 and H1 CandleMakers only
                         # (src/core/data_store.py:25-28) and _run_strategies
                         # dispatches strictly on matching timeframe
                         # (system_controller.py:917-921), so this manifest as
                         # written would load cleanly and never fire. P1 first.
  requires: [smc.enriched_df]   # raw OHLC + ATR/EMA only; check_smc=False path
  status: research
  priority: 90
  honors_htf_bias: false   # TSMOM's own signal IS the bias; controller HTF filter would fight it
  ```
- **Class placement:** `src/strategies/models/anchor.py`, subclassing `BaseStrategy`, implementing
  `async def on_new_candle`. Anchor should call `validate_data(df, min_length=..., check_smc=False)`
  — it needs raw OHLC + a rolling return + EMA(50) + ATR(20), not the SMC FVG/displacement
  columns SilverBullet relies on.
- **Config block sketch** (`config/config.yaml`, under `strategies:`):
  ```yaml
  anchor:
    enabled: false
    timeframe: "H4"
    lookback_bars: 63       # ≈10 trading days on H4; 126 on D1
    ema_confirm: 50
    stop_atr: 3.0
    pairs: [ ... all 12 ... ]
  ```
- **FeatureBus resources:** none new required for the H4 phase — ATR and an EMA are cheap
  additions to the existing enrichment; no SMC-specific resource is consumed. A rolling-return
  and EMA(50) helper would need registering if not already present in the enrichment pipeline
  (not verified in this pass — treat as an open item, not a fact).
- **Order types used:** MARKET only.
- **Grading path (P8 statement):** the audit's shorthand — that a non-SMC signal "has no grade"
  (`05-STRATEGY-ARSENAL.md:420`, P8) — is not literally true and the mechanism matters here.
  `SignalGrader.grade()` (`src/analysis/signal_grader.py`) computes all five factors from the
  controller's context dict and the signal candle, never from the strategy, so it always returns a
  grade. Anchor still under-scores badly, for two specific reasons rather than a generic "not SMC":
  1. **No target means no R:R points.** Anchor deliberately sets no fixed TP (§3), and R:R is worth
     up to 20 points. If the decision dict omits `tp`, the grader catches the `KeyError` and scores
     `rr = 0.0` → +0. If it instead passes `tp: 0.0`, `rr` evaluates against zero and comes out
     enormous → a spurious **+20**. Both are wrong, in opposite directions, and the second is worse
     because it silently inflates the grade. Whichever convention P7 settles on must be chosen
     deliberately and asserted in a test.
  2. **Killzone timing is structurally unreachable.** The killzone factor (+15) needs the NY hour to
     fall in 02-05, 07-11 or 13-16 (`signal_grader.py:23`); on a weeks-long-hold H4/D1 signal the
     entry hour is an artefact of the bar boundary, not the thesis.
  A realistic Anchor score is therefore neutral bias (+10) + rr (+0) + displacement (a trend
  confirmation bar is usually a modest body, +0 to +15) + PD unknown (+5), i.e. **15-30 against a
  `min_grade: B` floor of 55** (`signal_grader.py:21`) — a hard C. Anchor genuinely cannot execute
  under the current grader without a non-SMC grading path or an explicit carve-out; both are
  undesigned. This is a live-execution blocker independent of the data problem.
- **HTF-bias stance:** `honors_htf_bias: false`. Anchor's H4/D1 return sign *is* a bias signal; the
  controller's separate H1-cached HTF filter would be redundant at best and contradictory at worst
  if Anchor's own multi-week trend disagreed with the H1 SMC bias.
- **Exit profile:** needs a per-strategy exit profile (P7) — no fixed TP exists to anchor the
  ratchet's Fibonacci ladder (38.2%/61.8%/88.6% are measured against `initial_tp`, which Anchor by
  design does not set). Exit is signal-flip or a pure trailing stop; this is not the default
  ratchet+runner and must not silently inherit it.
- **Risk interaction:** inverse-volatility position sizing must compose with `RiskManager`'s
  broker-spec lot sizing (tick_value/tick_size) and with the NEUTRAL-bias half-risk rule. Six
  concurrent small positions (per the audit's proposed risk budget, `05-STRATEGY-ARSENAL.md:398`)
  stress the portfolio cap (`max_total_open_risk_pct`) differently than SilverBullet's
  one-symbol-one-position pattern — every added leg is a fresh "un-computable row blocks
  everything" surface if any symbol's specs haven't loaded.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| **P10** | 15-25y D1/H4 history via `GET_HISTORY`, plus `collect_signals` H4/D1 resampling rules | Current D1 ≈ 775 bars/symbol over the ~3y M5 archive (`05-STRATEGY-ARSENAL.md:53`; source archive per `data/lake/frozen/PROVENANCE.md`), which cannot validate a 6-month-horizon signal at all. `collect_signals` (`scripts/poc_sb_stops.py:54`) maps only `{"M15": "15min", "H1": "1h"}` at `poc_sb_stops.py:66`, so `tf="H4"` or `"D1"` raises `KeyError` today | 1 afternoon |
| **P1** | H4 (and later D1) CandleMakers on the live path | Distinct from P10 and easy to conflate with it: P10 fixes *research* resampling, P1 fixes *live* routing. `DataStore` builds M5 and H1 only (`data_store.py:25-28`), so an H4 Anchor manifest loads and silently never fires — the same defect as ENTRY-03 for M15. Note also that `candle_maker.py:121-122` buckets on `ts.minute` alone and cannot express a ≥60-min timeframe beyond H1 without an hour-aware bucket | 4 h (shared with Bell/Tide) |
| **P7** | Per-strategy exit profile (no fixed target, signal-flip exit) | Anchor's exit is structurally incompatible with the default TP-anchored ratchet | 1 day |
| **P8** | Non-SMC grading path | Grader is SMC-shaped; Anchor structurally under-grades | 1 day |
| **STRAT-05 / P12** | Portfolio-level backtest (vol-scaled sizing, count cap, aggregate cap measured together) | TSMOM's edge is a portfolio effect; per-symbol pooled-R testing (today's rig) cannot show it even if real | 3 days |
| **P3** | Pendings/positions counted correctly in exposure caps at 6-symbol breadth | Six concurrent legs multiply the surface for the fail-closed book-wide block | 1 hour (shared debt) |

None of the above exists today. Anchor cannot be pre-registered, let alone validated, until P10 at
minimum; P7/P8/P12 gate whether a valid pre-registration is even executable end-to-end.

## 6. Validation plan

**What cannot be validated with current data:** anything. H4 gives ~4,650 bars/symbol over three
years — enough to see something, not enough to trust it, and three years contains roughly one
macro regime (`05-STRATEGY-ARSENAL.md:253`). D1 gives ~775 bars/symbol, which the audit states
plainly cannot validate anything. Testing a 6-month momentum signal on three years of data and
concluding it fails would repeat the exact category of error the Donchian-20 test made
(`05-STRATEGY-ARSENAL.md:255`).

**Once P10 lands (D1 target, ~15-25y):**
- **Gate:** portfolio-level (not pooled-per-symbol) Sharpe ≥ 0.3 measured over 15 years; ≥60% of
  instruments individually positive; maximum drawdown duration ≤ 24 months
  (`05-STRATEGY-ARSENAL.md:261`).
- **Data:** full 12-symbol universe, D1, post-P10 extension.
- **Baseline:** must beat Almanac (zero fitted parameters) net of costs on the same data window —
  the standing complexity-yardstick requirement (see `docs/strategies/almanac.md` §1).
- **Method:** TVP discipline per `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:68-73` — 70/30
  chronological IS/OOS, ±30% parameter sweeps on lookback/EMA/stop-ATR, spread ×1.5/×2 stress,
  bootstrap CI, one-pass rule.
- **Kill criteria:** portfolio Sharpe < 0.3 on 15 years; fewer than 60% of instruments positive;
  max drawdown duration exceeding 24 months (`05-STRATEGY-ARSENAL.md:261`).

## 7. Failure modes and monitoring

- **Drawdown-duration intolerance is the human kill factor, not a technical one.** TSMOM's
  documented drawdown durations run to 18+ months of flat-to-negative equity — an institutional
  tolerance most retail operators discover they do not have around month nine
  (`05-STRATEGY-ARSENAL.md:261,463`). This must be decided *before* deployment, not discovered
  during it: sit with the historical drawdown-duration distribution for a week before committing
  capital (`05-STRATEGY-ARSENAL.md:464`).
- **Portfolio-vs-single-instrument gap.** If P12 is skipped or rushed, a positive-looking
  single-symbol Anchor result would be exactly the failure mode the literature warns about — poor
  Sharpe in isolation dressed up as an edge.
- **Grading silently blocking signals** (P8 unresolved): a live-enabled Anchor that never fires
  because every signal falls below `min_grade: B` is a silent failure mode indistinguishable from
  "no signals today" without an explicit grade-distribution monitor.
- **Correlation to the existing book:** the audit prior (not measured) puts Anchor at +0.3 to
  SilverBullet and +0.4 to Ledger — both are long-volatility/long-continuation biased regimes
  (`05-STRATEGY-ARSENAL.md:384,386`). Label explicitly: **these are priors, not measurements.**
  Live monitoring should track realized correlation once both strategies have overlapping trade
  history.
- **Ops:** as with every strategy, fail-safe lot=0 when specs/history haven't loaded is the
  designed silent-failure mode; six concurrent symbols widen that surface.

## 8. Verdict and sequencing

Candidate, blocked on data — not ready to build. The literature case is strong but untested on
this repo's data; the one adjacent test (Donchian-20) was diagnosed as measuring the wrong
horizon, which is informative about methodology, not about Anchor's premise. Sequencing per the
audit's staging plan: P10 (data extension, one afternoon) is the prerequisite that also unlocks
Ledger and Almanac (`05-STRATEGY-ARSENAL.md:422`); do it regardless of the Anchor decision, purely
for the infrastructure. Anchor itself sits at **Stage 4** (`05-STRATEGY-ARSENAL.md:441`), after
Coil and Tide have exercised the pipeline and after P7/P8/P12 exist. Do not attempt a
single-symbol or pooled-R Anchor test as a shortcut — it would repeat the Donchian mistake in a
new shape. Depends on: `docs/strategies/almanac.md` (P10 shared prerequisite, complexity
baseline); `docs/strategies/ledger.md` (P10 shared prerequisite, run Step-0 in parallel).
