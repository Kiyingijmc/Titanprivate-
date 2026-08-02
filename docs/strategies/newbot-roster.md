# NEW-BOT ROSTER — pointer index to the tradebot/ design track

> **Status:** hypothesis-tagged design roster (zero code) · **Scope:** the separate `tradebot/`
> event-sourcing skeleton, not the live Titan v14 engine · **Doc version:** 2026-08-01

**This is a pointer document, not a set of dossiers.** The full specification for every strategy
below — thesis, evidence grade, cost-sensitivity arithmetic, falsification protocol, board
red-team discussion — lives in
`docs/trading-bot-brainstorm/brainstorm-v2/pass2-research.md`. This document exists so the
Titan-track arsenal (Gyroscope, SilverBullet, the seven `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md`
candidates) and the separate new-bot track can be read against each other without duplicating
either.

## What this track is, and is not

- **Target platform:** the `tradebot/` event-sourcing skeleton designed in
  `docs/trading-bot-brainstorm/brainstorm-v2/`, milestone **M0 (trustworthy skeleton) is complete**
  (`docs/trading-bot-brainstorm/brainstorm-v2/pass8-synthesis.md:223`, INDEX.md's milestone list).
  This is **not** the live Titan v14 engine documented elsewhere in this directory — different
  codebase, different architecture (portfolio-scope feature-store DAG nodes, a regime engine, a
  calibration/graduation ledger), currently pre-M1.
- **Every quantitative figure below is hypothesis-tagged**, per the source document's own evidence-
  honesty rules (`pass2-research.md` §1.2). Zero code exists for any of these twelve candidates.
  Nothing has been backtested, let alone gated.
- **The Stage-R/Stage-L falsification protocol has never been run** for any candidate here. Stage-R
  (research-stage: OOS profit factor / expectancy thresholds, parameter-plateau requirements,
  cross-instrument robustness rules) and Stage-L (live-stage: CUSUM-based drift monitoring per
  `pass2-research.md` §1.4) are specified per-dossier but are protocol, not results.
- **Priority votes recorded below are board votes on build sequencing**, not GO/NO-GO verdicts —
  nothing in this roster has been gated, so "9–1 BUILD-EARLY" means "the design board agreed this
  should be attempted before its siblings," not "this works."

## The roster

**T1 · Donchian breakout (D1)** — the trend family's workhorse. Thesis: TSMOM/post-breakout drift,
Grade E1 (the best-documented anomaly class in the roster — Moskowitz–Ooi–Pedersen 2012,
Hurst–Ooi–Pedersen). Channel ∈ {15…30} days, stop 1.5–2.5×ATR, parameter-plateau falsification
required (a spike at exactly 20/2.0 with dead neighbours = fail, guarding against the well-known
publication-selection glow on the 20-day Donchian parameter specifically). Cost viability
hypothesis ≈1.1–1.7 depending on pricing tier — thin even for the "most cost-robust child in the
roster." `pass2-research.md` §2.1.

**T2 · EMA pullback continuation (H4)** — same TSMOM carrier as T1 plus an unproven candle-
confirmation timing overlay (Grade E3 — "no credible published evidence... practitioner belief is
near-universal and evidence-free"), so Stage-R requires an ablation proving the overlay adds
expectancy over naive in-trend entries or it is deleted. Cost geometry is worse than T1's despite
"better" (tighter) stops, because a smaller per-trade edge divides by a fixed cost. `pass2-research.md`
§2.2.

**T3 · Higher-timeframe momentum rotation (D1/W1)** — cross-sectional momentum (top-decile-vs-
bottom-decile relative outperformance), Grade E1 in equities/futures at the published scale but
demoted to E2-at-best on this roster's ~15–25 correlated CFD universe — "top decile" collapses to
"top-2," closer to a stealth macro-factor bet than the published anomaly. Swap drag was found to
consume 30–100% of the short book's gross edge (F-020), so short legs default OFF. Board
deprioritized T3 to 4th in the trend family, behind TC-2, on exactly this evidence/cost ratio.
`pass2-research.md` §2.3.

**T4 · Volatility-expansion straddle (M30/H1, London open)** — compression→expansion (Grade E1, the
most robust stylized fact available) expressed as a two-sided stop-order straddle at the London
open. The straddle mechanics themselves are Grade E3-post-decay (ORB is heavily published and
largely arbitraged flat at short horizons). A double-fill kill term (`f_df · c_df > 0.30 ·
edge_ticks`) was written specifically because the straddle's second, unwanted leg filling is a
distinct cost category from spread. Presumptively non-viable on standard pricing (≈0.6–1.0),
marginal on RAW (≈0.9–1.4). `pass2-research.md` §2.4.

**M1 · Asian-session Bollinger fade (M15)** — liquidity-provision premium during thin Tokyo-hours
flow; Grade E2 for the phenomenon, E3 for the specific BB(20,2.2) construction. Explicitly the
roster's cost canary: "only plausibly viable on RAW-tier pricing, and marginally there; on a
standard-markup broker it is dead on arrival." `pass2-research.md` §3.1.

**M2 · London-open stop-hunt fade (M15/M30)** — stop-cluster cascade-and-retrace at the London
open; Grade E2 for stop clustering (Osler, interbank data — "the one genuinely documented
microstructure fact in this child"), E3 for the failed-breakout-reversal construction itself. A
crowding paradox is flagged: if the fade trade becomes popular enough, its own stops become the
next cluster. `pass2-research.md` §3.2.

**M3 · RSI(2) extreme reverter (H1)** — the Connors-lineage RSI(2)<5 short-term reversal signal,
Grade E1 in equities at daily horizon *pre-2010*, explicitly noted as having decayed since; the FX/H1
transfer is Grade E3, "a transfer hypothesis... not a proven earner." The board flags M3 as a
positive-control-adjacent test case for the falsification pipeline itself — if the pipeline can't
kill a famous, published, decayed signal transferred to a new venue, the pipeline is broken.
`pass2-research.md` §3.3.

**M4 · Index open-drive fade (M5/M15)** — opening-auction imbalance reversion toward intraday VWAP;
Grade E2 for the phenomenon (the family's strongest premise), but retail CFD spreads at the cash
open run 3–10× session norms for the first minutes, which is precisely where the published effect
lives. Design consequence: v1 does not trade the first ~5–10 minutes, conditional on a per-instrument
measured open-spread decay curve that does not yet exist. `pass2-research.md` §3.4.

**TC-2 · Long-horizon TSMOM ballast** (`trend.tsmom12_v1`) — **priority vote 9–1 BUILD-EARLY.** The
purest expression of the trend family's core E1 factor: sign of the trailing 12-month return,
EWMA-vol-targeted sizing, weekly evaluation, no regime gate (the 12-month sign is its own regime
filter). Board rationale for prioritizing it ahead of T3: "TC-2 subsumes much of T3's rationale with
~3 parameters instead of a noisy n≈20 ranking." Effectively cost-immune (a handful of trades/year,
hypothesis viability 5–20 even on standard pricing). `pass2-research.md` §5.1.

**TC-1 · Carry-aligned trend variant** (`trend.donchian_carry_v1`) — **priority vote 6–4
DEFER-UNTIL-T1-VALIDATED.** T1 conditioned on carry sign (trade breakouts only in the swap-earning
direction) — two reinforcing E1/E2 premia, but it forks T1's identity before T1 itself has cleared
any gate. Vote rationale explicitly sequencing, not skepticism. `pass2-research.md` §5.2.

**MC-1 · Round-number liquidity fade** (`meanrev.roundlevel_v1`) — **priority vote 7–3
BUILD-AFTER-M2.** Resting limit-order clustering at round price levels (Osler, Grade E2,
interbank data) with a bounce-fade thesis. Falsification spine is a placebo test: identical rules
at non-round pseudo-levels must underperform, or the premise failed transfer to this data and the
child is never built. Cost profile mirrors M1 (dies with M1 on standard pricing). `pass2-research.md`
§5.3.

**MC-2 · Cross-pair divergence reverter** (`meanrev.pairdiv_v1`) — **priority vote 10–0 DEFER
(architecture-blocked).** Stat-arb-style beta-divergence reversion between linked pairs
(EURUSD/GBPUSD, US500/US100); the feature store has no portfolio-scope (cross-instrument) DAG nodes
until a later architecture pass, so the board declined to even spec entry rules for a signal the
engine cannot yet compute. Parked with a named re-entry condition. `pass2-research.md` §5.4.

## Overlap with the Titan-track arsenal — reconcile before duplicating research

Both tracks were designed against overlapping return-source theses, independently, on different
codebases. Before any candidate above gets prioritized for actual research spend, it should be
routed through the **same TVP pipeline** used for the Titan-track arsenal
(pre-registration → gate → GO/NO-GO, `docs/strategies/gyroscope.md` §6 and
`docs/strategies/retired-ict-family.md` "Standing falsification-log principles") and reconciled
against its Titan-track twin first, so a NO-GO or a GO on one side is not silently re-run from
scratch on the other:

| new-bot candidate | Titan-track twin | Relationship |
|---|---|---|
| T1 Donchian breakout D1 | Donchian-20 D1 (`docs/strategies/retired-ict-family.md` §6) | **Same idea, near-identical horizon** — the falsified Titan-track test used a 20-day channel; T1's own parameter-plateau range ({15…30} days) sits squarely inside the already-falsified band. T1 is not automatically dead (different stop model, different sample, a plateau requirement designed to catch exactly this kind of single-parameter glow) but it is not a fresh idea either — reconcile the two before spending Stage-R budget. |
| TC-2 long-horizon TSMOM | Anchor (H4→D1, `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §7) | **Direct twin.** Both are 3–12-month-horizon, vol-scaled, portfolio-breadth TSMOM, motivated by the identical literature (Moskowitz–Ooi–Pedersen) and the identical diagnosis that Donchian-20 tested the wrong horizon. Whichever track reaches a gate first should settle the question for both. |
| M1 Asian BB fade / M3 RSI(2) reverter | Tide (H1 intraday reversal, `05-STRATEGY-ARSENAL.md` §5) / Spring (OU half-life mean reversion, `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §5) | **Same family (session/statistical mean reversion), different mechanics and timeframes.** Not literal duplicates, but three-to-four independent bets on "short-horizon reversal is real and harvestable here" — worth tracking as one factor exposure across both tracks, not three unrelated ones. |
| T4 vol-expansion straddle | Coil (H1 volatility-compression expansion, `05-STRATEGY-ARSENAL.md` §4) | **Same return source (volatility clustering / compression→expansion), different execution** — Coil is a single directional STOP-both-sides breakout at H1; T4 is a true two-sided straddle at the London open on M30/H1. Reconcile which execution style is worth building first; both cannot claim the vol-clustering evidence independently. |
| M4 index open-drive fade | Bell (index session opening-range breakout, `05-STRATEGY-ARSENAL.md` §6) | **Same instruments and session anchor, opposite direction of trade** — Bell trades the opening-range breakout continuing; M4 fades the opening drive reverting to VWAP. These are close to mutually exclusive hypotheses about the same few minutes of market structure and should not both be built without first checking they are not simply negatively-correlated bets on the same noise. |

**Recommendation:** any of these twelve that gets prioritized for real research spend should (1) go
through the same pre-registered TVP gate as the Titan-track candidates, and (2) explicitly cite and
reconcile with its twin in the table above in its pre-registration doc, so a future reader does not
have to rediscover the overlap the way this document had to.
