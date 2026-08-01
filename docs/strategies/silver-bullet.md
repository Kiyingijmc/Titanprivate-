# SILVER BULLET — session-timed FVG displacement continuation (the incumbent)

> **Status:** live (v14.4.2, demo-forward-test since 2026-07-28) · **Family:** ICT session-timing /
> displacement continuation · **Timeframe:** H1 ·
> **Origin:** `src/strategies/models/silver_bullet.py`; validated by
> `docs/research/2026-07-11-silverbullet-h1-stop-study.md` · **Doc version:** 2026-08-01

## 1. Thesis and return source

During specific session windows, macro volatility injects strong displacement; the first strong
fair-value gap (FVG) printed by a displacement candle marks institutional participation, and a
limit entry at the FVG edge rides the continuation. The tradable return source, as measured, is a
combination of (a) a genuinely selective entry — real entries beat marginal-matched random entries
by +0.202R under identical fixed exits (EXP-0) — and (b) positive skew that the ratchet/runner exit
engine converts into expectancy (fixed 2R exits are −0.122R on the same entries; ratchet+runner is
+0.109R).

## 2. Evidence base

The most-validated object in the repo, and the calibration anchor for everything else:

| Study | Result | Source |
|---|---|---|
| 3-yr stop/timeframe study (2026-07-11) | H1 + 1.0×ATR stop + ratchet/runner: **+0.109R** net pooled (11 sym, n=2,217), **+0.194R** on the 9-sym cost-screened portfolio (n=1,837, PF 1.53, OOS +0.185R, every year positive, survives 2× spread) | `docs/research/2026-07-11-silverbullet-h1-stop-study.md` |
| Same study, adverse | **M5/M15 are cost-dead at any stop width** (M5 live config −4.27R net). Gross edge +0.3…+0.45R exists on every TF — costs kill the small-R versions | ibid. §1 |
| Grading gate | `min_grade: B` improves the portfolio to +0.222R (OOS +0.262R); ≥A over-filters | ibid. §4 |
| Pullback-monetizer overlay (2026-07-11) | Arm C (runner-trail tighten on ≥0.75 give-back → 0.10×range): **+0.130R, PF 1.32, DD 21R** — Pareto improvement, adopted live; Arm A (bank-and-re-add) dominated everywhere, never build | `docs/research/2026-07-11-pullback-monetizer-overlay-results.md` |
| Universe expansion (2026-07-28) | US100 +0.285R, ETHUSD +0.261R, XTIUSD +0.421R all adopted (12-pair live universe); EURGBP failed cost gate, XAGUSD edge-dead, USDCHF/NZDUSD/EURJPY thin | `docs/research/2026-07-28-universe-expansion-screen.md` |
| EXP-0 coin-flip (2026-07-31) | Outcome 1: placebo −0.249R vs real +0.109R, 0/20 reps reach real. **The entry does genuine work; the exit engine amplifies (+0.231R) but does not subsidise (+0.075R)** | `docs/research/2026-07-31-exp0-coinflip-preregistration.md` |

**The open caveat that bounds all of it — STRAT-01 (CRITICAL):** every managed-exit number above
comes from the offline replay in `scripts/poc_sb_stops.py` (`replay_managed`), which is a *second
implementation* of the live `TradeManager` ratchet. The research harness (`research_run.py` /
`kernel_replay`) has entry-parity with live code but resolves trades with fixed-R exits only. The
live exit engine — where the sign of the edge lives — has never been driven by the research
harness. Quote +0.109R/+0.194R as upper bounds; the definitive number is the demo-forward-test
(live since 2026-07-28, checkpoint ~2026-08-11).

## 3. Signal specification

As implemented (`src/strategies/models/silver_bullet.py`):

- **Setup:** enriched H1 frame ≥50 bars; NY-time hour inside a configured window
  (multi-window `windows` config; legacy default 10:00–11:00 NY). v14.4.2 runs **no session
  gate** — the study showed the edge is positive broadly across the day; windows are configured
  wide open.
- **Trigger:** the just-closed candle prints `is_fvg_bear` / `is_fvg_bull` (from
  `smc.enriched_df`) **and** |body| ≥ 0.8×ATR (displacement filter). ATR must be > 0.
- **Entry:** LIMIT at the FVG edge (`fvg_bottom` for sells, `fvg_top` for buys). Pending TTL is
  controller-side: 12 bars × timeframe (`strategy_ttls`).
- **Stop:** entry ∓ 1.0×ATR (`stop_atr: 1.0` — validated; the code comment forbids lowering it
  without re-running the cost study).
- **Target:** RR 2.0 from the stop distance. The TP primarily arms the ratchet ladder; the runner
  does the harvesting.
- **Universe:** `strategies.silver_bullet.pairs` — 12 symbols (9 originals + US100, ETHUSD,
  XTIUSD). Cost screen excluded GBPCAD and XBRUSD.

## 4. Architecture integration

- **Manifest:** `config/manifests/silver_bullet.yaml` — `status: live`, `priority: 50`,
  `requires: [smc.enriched_df, smc.bias_context]`, `honors_htf_bias: true` (controller filters
  counter-bias signals).
- **Class:** `SilverBullet(BaseStrategy)`, `timeframe: H1`.
- **FeatureBus:** consumes the SMC pack; HTF bias cached per H1 bar close.
- **Grading:** the grader was shaped around this strategy (displacement, premium/discount,
  killzone factors all apply). `min_grade: B` live.
- **Exit profile:** default ratchet + runner + Arm C tighten — the validated combination.
- **Risk:** standard broker-spec sizing; NEUTRAL-bias signals sized at half risk.

## 5. Infrastructure prerequisites

None for continued operation. The strategy's open debts are measurement debts:

| Item | What | Why it matters here |
|---|---|---|
| STRAT-01 / roadmap A1 | Extract the live ratchet into a pure function the research harness drives | The edge's sign is produced by unvalidated-in-harness live code |
| STRAT-04 | Add US100/ETHUSD/XTIUSD to the rig cost table (`poc_sb_stops.py`) | The 3 newest pairs are absent from the authoritative spread table |
| STRAT-03/06, P6, P11 | Slippage, ask-price spread gate, swap modelling | Runner holds positions overnight; swap survey already underway (`feat/swap-survey`) |
| Demo checkpoint ~2026-08-11 | Realized vs modelled spreads, grade distribution vs study | The pre-agreed live-capital gate |

## 6. Validation plan

Complete (the study is the repo's reference TVP run). Standing obligations:

- **Do not re-tune on the same data** (one-pass rule). Any mechanical change (stop model, windows,
  grading floor) requires a fresh pre-registered study.
- Demo checkpoint criteria: realized spread within the stressed band; expectancy sign; grade
  distribution consistent with the study's.
- Re-run the cost stress if live-measured spreads deviate materially (study integrity caveat).

## 7. Failure modes and monitoring

- **Cost regime change:** FBS widening spreads flips thin symbols first (XAGUSD-shaped death).
  Monitor realized round-trip cost per symbol vs the 0.25R gate. Needs P6 (ask capture) to do
  properly live.
- **Selection-bias decay:** stop model and exit variant were selected on the study data (4×3
  grid). Mitigated by monotone neighbours, OOS/yearly consistency — but expect live expectancy
  below +0.194R; the honest central estimate is the 11-sym +0.109R.
- **Session drift:** killzone grading uses a fixed broker−7h NY offset (±1h DST wobble) — a known
  approximation.
- **Ops:** the strategy only trades if specs+history loaded for the symbol (fail-safe lot=0
  otherwise) — a silent no-trade is the designed failure mode; the Sync Guard and uncomputable-book
  Telegram alerts cover the loud ones.

## 8. Verdict and sequencing

The incumbent and the yardstick. Every new candidate must (a) beat its own baseline, and (b) be
compared against SilverBullet's realized demo numbers, not its replay upper bound. Highest-value
next actions for this strategy specifically, in order: the 2026-08-11 demo checkpoint read-out;
STRAT-01 ratchet extraction (A1) so the validated engine and the live engine are the same code;
STRAT-04 cost-table completion for the three new pairs.
