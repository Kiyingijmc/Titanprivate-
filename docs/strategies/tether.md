# TETHER — Cointegration Spread Reversion (H1, paired legs)

> **Status:** candidate (pre-registration pending) — staged LAST · **Family:** relative value /
> statistical arbitrage · **Timeframe:** H1 ·
> **Origin:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §8 · **Doc version:** 2026-08-01

## 1. Thesis and return source

Relative-value mean reversion between economically linked instruments is a return source with no
net directional market exposure: the position is long one leg, short a beta-matched amount of the
other, and profits when a temporarily divergent spread reverts to its statistical mean. Titan's
universe contains natural candidates — US30/US100 (shared US-equity beta, differing sector
composition), BTCUSD/ETHUSD (near-identical crypto beta), and more loosely XAUUSD/XTIUSD and the
dollar-side FX cluster (`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:270`). Because the return
source is spread convergence rather than trend or displacement, Tether is expected to be close to
uncorrelated with every other candidate in the arsenal — the audit's stated prior is "~zero" to
SilverBullet, Coil, Bell, Anchor and Ledger (`05-STRATEGY-ARSENAL.md:385`; **this is a prior, not a
measurement**).

**EXP-0 implication:** the coin-flip finding (real entries +0.109R vs placebo −0.249R, exit engine
amplifies +0.231R but does not manufacture edge from noise +0.075R;
`docs/research/2026-07-31-exp0-coinflip-preregistration.md`) applies with a caveat here — Tether's
default exit (z-score target, not a fixed-R TP) does not naturally engage the ratchet's
Fibonacci-on-TP-progress ladder at all (see §4). Whatever edge Tether has must come from the
cointegration/mean-reversion signal itself; it cannot lean on Titan's proven exit machinery the way
SilverBullet does, and it inherits none of the "+0.08R of cost-drag mitigation" the brief describes
as the baseline gift to a new entry, because that gift is delivered through the ratchet and Tether's
exit does not use it in the same form.

## 2. Evidence base

No empirical result exists for Tether in this repo. The one concrete asset it inherits is
infrastructure, not a validated finding:

| Item | Status | Source |
|---|---|---|
| `src/analysis/kalman_drift.py` | 183 LOC, 11 passing unit tests (`tests/unit/test_kalman_drift.py`), retained from the NO-GO'd Gyroscope strategy as the time-varying hedge-ratio estimator | `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:272` |
| Gyroscope (the strategy that built kalman_drift) | NO-GO, −0.067R pooled, 4/9 symbols positive, 27.1% realized false-entry rate vs 5% designed alpha (2026-07-15, third H1-momentum NO-GO) | brief, "the graveyard" |

**Adverse evidence, stated plainly:** the component Tether depends on most heavily was built for a
strategy that failed. Gyroscope's failure was about its *momentum/SPRT signal logic*, not about
`kalman_drift.py` itself (the module passed its own 11 tests and is a generic hedge-ratio
estimator, reusable regardless of Gyroscope's outcome) — but this is not evidence *for* Tether
either. No cointegration test, no spread backtest, and no paired-leg execution has ever run on this
platform. The "genuinely orthogonal, genuinely expensive" framing in the source document
(`05-STRATEGY-ARSENAL.md:267`) is a design judgment, not a result.

## 3. Signal specification

As designed (not implemented — no `src/strategies/models/tether.py` exists):

- **Spread:** `log(A) − β_t × log(B)`, with β_t estimated live by `kalman_drift.py`'s Kalman
  filter — reused as the time-varying hedge-ratio estimator it was already built for.
- **Setup:** `|z-score of spread| > 2.0` over a 200-bar window, **AND** the pair passes an
  ADF/Engle-Granger cointegration test on the trailing 500 bars, **AND** β_t stability — the
  Kalman innovation variance within its normal band (`05-STRATEGY-ARSENAL.md:278-280`).
- **Entry:** LIMIT on both legs simultaneously, notional-matched by β_t.
- **Stop:** `|z| > 3.5` (spread divergence beyond the entry threshold) OR the cointegration test
  fails on refresh — a structural (not price-only) stop.
- **Target:** `|z| < 0.5` — spread reversion toward its mean, not a fixed-R price target.
- **Sizing:** the combined two-leg position counts as **one** position against the risk budget.
- **Universe:** US30/US100, BTCUSD/ETHUSD as primary candidates; XAUUSD/XTIUSD and dollar-side FX
  pairs as looser, unvalidated secondary candidates.

## 4. Architecture integration

- **Manifest sketch** (`config/manifests/tether.yaml`, does not exist yet):
  ```yaml
  id: tether
  version: "0.1"
  class_path: "src.strategies.models.tether:Tether"
  family: relative_value
  timeframe: H1
  requires: []   # raw OHLC only — no SMC pattern dependency (mirrors gyroscope.yaml)
  status: research
  priority: 95
  honors_htf_bias: false   # spread-relative signal has no single-instrument directional bias
  ```
- **Class placement:** `src/strategies/models/tether.py`. Tether does not map cleanly onto
  `BaseStrategy.on_new_candle`'s single-symbol, single-decision-dict contract
  (`{signal, type, price, sl, tp}`) — a paired-leg signal needs to emit or coordinate **two**
  orders atomically. This is an unresolved design gap, not a detail: either the strategy class
  needs to reach outside the standard `on_new_candle` return contract, or a wrapper coordination
  layer is needed above it. Flagging as open rather than presuming a solution.
- **Config block sketch** (`config/config.yaml`, under `strategies:`):
  ```yaml
  tether:
    enabled: false
    timeframe: "H1"
    z_entry: 2.0
    z_exit: 0.5
    z_stop: 3.5
    coint_window: 500
    z_window: 200
    pairs: [["US30", "US100"], ["BTCUSD", "ETHUSD"]]
  ```
- **FeatureBus resources:** reuses `kalman_drift.py` directly (not currently a registered
  FeatureBus resource — it is called ad hoc by Gyroscope); would need registration as a shared
  resource (`analysis.kalman_hedge_ratio` or similar) if more than one strategy is to reuse it, or
  Tether can instantiate it privately as Gyroscope does today. Also needs an ADF/cointegration test
  — not present anywhere in the repo today; would need to be added, likely in
  `src/analysis/` alongside `kalman_drift.py`.
- **Order types used:** LIMIT ×2 (both legs). No STOP, no MARKET.
- **Grading path (P8 statement):** Tether is not an SMC pattern — no displacement, no
  premium/discount, no killzone. Like Anchor, it is structurally capped below `min_grade: B` under
  the current SMC-shaped grader (`05-STRATEGY-ARSENAL.md:420`, P8) and needs the same non-SMC
  grading path before it can execute live.
- **HTF-bias stance:** `honors_htf_bias: false`. A spread-relative signal has no meaningful
  single-instrument directional bias to filter against; the controller's HTF bias filter is not
  applicable to a paired position by construction.
- **Exit profile:** needs a dedicated exit profile (P7), and it is the most different from the
  default of any candidate in the arsenal — the target is `|z| < 0.5`, not an R-multiple, and the
  "initial_tp" concept the ratchet keys off of (`src/execution/trade_manager.py`, "Engages ONLY when state-DB
  `initial_entry/initial_tp` are non-zero") has no natural translation for a spread target. Tether
  likely needs an entirely separate exit code path rather than an instantiation of the existing
  ratchet with different parameters.
- **Risk interaction:** the combined-leg-counts-as-one-position rule must be enforced explicitly;
  today's `ExposureManager` and `max_positions_per_symbol` logic have no concept of a paired
  position (they count per-symbol). Without P4 (signed correlation) the correlation gate will
  actively block the trade — see §5.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| **ARCH-01** | Two-leg execution is not atomic — the bridge sends orders one at a time with no idempotency key | A filled leg with an unfilled sibling is a naked directional position, the opposite of the strategy's premise | not sized in audit — treat as substantial |
| **P13** | Position-lifecycle state machine + multi-leg handling | Tether's paired entry/exit has no home in the current single-position model | 3 days |
| **RISK-04 / P4** | Signed, direction-aware correlation gate + asset-class groups | `check_correlation` is direction-blind and blocks any pair above ρ = 0.8 — which is definitionally every Tether pair; **Tether cannot run at all without this fix** | 2 days |
| **P8** | Non-SMC grading path | Grader is SMC-specific; Tether structurally under-grades | 1 day |
| **P7** | Per-strategy exit profile (z-score target, not R-multiple TP) | Default ratchet has no natural translation for a spread target | 1 day (likely more given the exit-code-path gap above) |
| ADF/cointegration test | Not present anywhere in the repo | Required for the setup gate and the stop-on-cointegration-failure rule | not sized — new component |

**Doubled transaction cost** is a fifth, non-infrastructure problem: two legs in, two legs out.
Cheap enough for US30/US100; likely kills the edge outright for any FX-side pair given the FBS
spread table (`scripts/poc_sb_stops.py:43` — GBPJPY 25 pts, GBPCAD/XBRUSD excluded from
SilverBullet's own cost-screened universe for the same reason).

## 6. Validation plan

**What cannot be validated with current data:** the strategy cannot even be pre-registered until
RISK-04 (signed correlation) exists, since the correlation gate would block every candidate pair
by definition before a single trade could be attempted, live or in backtest replay. The
cointegration test itself is unbuilt.

**Once infrastructure exists:**
- **Gate:** OOS Sharpe ≥ 0.5 — relative-value strategies need a higher Sharpe bar than directional
  ones to justify the added complexity (`05-STRATEGY-ARSENAL.md:298`).
- **Data:** H1, US30/US100 and BTCUSD/ETHUSD as primary pairs (best cost profile); FX-side pairs
  only if the doubled-cost math survives the FBS spread table.
- **Method:** TVP discipline — 70/30 IS/OOS, ±30% sweeps on z-thresholds and windows, spread
  ×1.5/×2 stress (doubled, since two legs), bootstrap CI, one-pass rule
  (`05-STRATEGY-ARSENAL.md:68-73`). Baseline comparison against Almanac's zero-parameter yardstick
  still applies.
- **Kill criteria:** OOS Sharpe < 0.5; Kalman β unstable on more than 20% of bars; any leg-mismatch
  incident during the demo soak (`05-STRATEGY-ARSENAL.md:298`) — the last of these is a hard stop,
  not a statistical one, given ARCH-01.

## 7. Failure modes and monitoring

- **Naked leg exposure (the primary live risk).** Until ARCH-01 is fixed, any partial fill leaves
  a directional position that is the exact opposite of what the strategy is meant to be. This must
  be monitored as a distinct alert class — a filled leg with no confirmed sibling fill within a
  tight window should page the operator, not wait for the next heartbeat reconciliation.
- **Cointegration breaks without warning, and typically at the worst moment** — every historical
  pairs-trading blowup shares this shape (`05-STRATEGY-ARSENAL.md:292`). The stop-on-cointegration-
  failure rule is the mitigation; it depends on the ADF test running reliably on every refresh.
- **Correlation-gate interaction:** even after RISK-04 ships, Tether pairs are, by construction,
  highly correlated instruments — the gate must distinguish "correlated and directionally
  offsetting" from "correlated and compounding," which is exactly what direction-blindness
  currently cannot do.
- **Portfolio correlation to the rest of the book** is an audit prior of ~zero to SilverBullet,
  Coil, Bell, Anchor, and a stated prior of +0.1 to Tide (`05-STRATEGY-ARSENAL.md:385`) — **priors,
  not measurements.** If realized correlation diverges materially from ~zero, the diversification
  case for building Tether at all weakens.
- **Ops:** as with every strategy, fail-safe lot=0 when specs/history haven't loaded on either leg
  is a designed silent-failure mode; here it additionally has to cover the case where one leg's
  specs load and the other's don't.

## 8. Verdict and sequencing

High intellectual appeal, genuine diversification value if it works, and staged **last** of the
arsenal by design (`05-STRATEGY-ARSENAL.md:295,443`). The hardest technical component — a
time-varying hedge-ratio estimator — already exists and is tested (`kalman_drift.py`, 183 LOC, 11
passing tests), which is a real head start. But three separate, non-trivial infrastructure items
gate it: atomic two-leg execution (ARCH-01), a signed correlation gate that Tether cannot run
without at all (RISK-04), and a position-lifecycle state machine for multi-leg positions (P13) —
roughly 2-3 weeks of infrastructure for one strategy (`05-STRATEGY-ARSENAL.md:295`). **Verdict:
worth doing after two cheaper strategies (Coil, Tide) have proven the pipeline works** — Stage 6,
the last stage in the audit's roadmap, contingent on Stages 2-5 having produced at least two
survivors (`05-STRATEGY-ARSENAL.md:443`). Depends on: RISK-04/P4 also gates every other multi-
strategy claim (shared with Anchor's portfolio risk budgeting); does not depend on the D1 data
extension (P10) that Anchor/Ledger/Almanac need — Tether's data problem is infrastructural, not a
sample-size problem.
