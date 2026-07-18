# PASS 2 — RESEARCH & THEORY DEEPENING

**Co-chairs:** Senior Quant Researcher + Master Trading Strategist. **Contributors:** all ten seats; the Auditor red-teams every performance statement per board rule (b).
**Inputs:** `00-overview.md`–`05-interfaces-validation-ops-learning.md`, `pass1-audit.md` (findings register normative).
**Findings resolved in this pass:** F-018 (regime confidence/hysteresis — §4.1), F-020 (T3 rebalance window + swap math — §2.3), F-021 (T4 double-fill economics — §2.4). F-037's labeling convention is applied throughout.
**Binding constraints honored:** F-003 corrected viability math (all edge/cost arithmetic below is in ticks with an expectancy numerator; the old threshold "4" is void); F-012 (no touch-fill or "earns spread" assumptions; adverse-selection term priced); F-013 (all live falsification criteria use block evaluation + CUSUM-style monitoring, action at sustained 99%); F-011 (gap-stressed risk noted on every close-holding child); F-006 (every session child states its IANA anchor). F-002/F-005/F-016 remain OPEN — nothing below assumes netting support, margin limits, or a platform topology.

---

## §1 Method and evidence-honesty rules

### 1.1 Dossier method

Each child gets the same seven-part examination: (a) microstructure/behavioral thesis with a **named loser** — a specific flow, constraint, or bias that persistently supplies the edge; (b) evidence base for the **effect class**, graded; (c) capacity and decay profile; (d) regime dependence stated as **pre-registered testable predictions** (these become Pass-7 regime-attribution checks, 05§D4); (e) cost sensitivity under the F-003-corrected viability math; (f) a two-stage falsification criterion; (g) hypothesis performance ranges with the Auditor's red-team note inline.

### 1.2 Evidence grading scale (used in every dossier)

| Grade | Meaning |
|---|---|
| **E1** | Effect class replicated across decades/assets/venues in peer-reviewed + practitioner literature; survived post-publication scrutiny |
| **E2** | Effect class documented in credible literature but with known post-publication decay, or documented on institutional data (futures/interbank) whose transfer to retail CFD feeds is unproven |
| **E3** | Effect class plausible from microstructure reasoning + practitioner folklore; little or no formal evidence at this timeframe/venue; treat as pure hypothesis |

**Honesty rules (board-adopted, binding on all dossiers):**
1. Every number is tagged **(measured)** — we measured it on our own data/feed (nothing qualifies yet); **(literature-informed)** — order-of-magnitude from published work, not verified on our instruments; or **(hypothesis)** — a starting guess that must be backtested. Per F-037 this is mandatory, not stylistic.
2. Published effects are assumed to have **decayed post-publication** unless there is specific evidence of persistence. The multiple-testing discount (05§B3) applies with extra force to parameters that are famous (the 20-day Donchian channel and RSI(2)<5 are among the most-published parameters in retail trading; their in-sample glow is partly selection by the literature itself).
3. Evidence from futures/interbank data does **not** automatically transfer to a marked-up OTC CFD feed. The transfer loss is exactly the cost wedge F-003 measures; dossiers must state which side of that wedge the published evidence sat on.
4. An edge without a named loser is not an edge, it is a pattern. If the dossier cannot say who pays and why they keep paying, the thesis grade caps at E3.
5. No dossier may present a Sharpe, win rate, or return without the phrase "hypothesis" attached and a red-team note from the Auditor. (Auditor sign-off condition for this entire pass.)

### 1.3 The F-003 viability arithmetic used throughout

For every child × instrument × broker (all terms in **ticks**, tick = broker `tick_size` from discovery 03§B1; for 5-digit EURUSD, 1 tick = 0.00001 = 0.1 pip):

```
cost_ticks = median_spread_ticks(session) + commission_ticks + E[slippage_ticks | mechanism]
             + adverse_selection_ticks (limit mechanisms only, per F-012)
edge_ticks = p_win·avg_win_ticks − (1−p_win)·avg_loss_ticks        # PRE-cost gross expectancy
viability  = edge_ticks / cost_ticks          # disable below threshold; 1.5–2.0 starting hypothesis (F-003, Pass-7 calibrates)
```

Two reference broker tiers used in the cost-sensitivity sections (both **literature-informed** from published retail broker pricing; replaced by measured discovery data at G2):

| Tier | EURUSD example | cost_ticks (market order, London) | cost_ticks (Asian session) |
|---|---|---|---|
| RAW (raw spread + commission) | 0.2 pip spread + $7/lot RT ≈ 0.7 pip | ≈ 9–11 | ≈ 12–15 |
| STD (markup, no commission) | 1.0–1.5 pip spread | ≈ 10–15 | ≈ 15–25 |

Note the honest surprise: on EURUSD the RAW tier is only ~20–40% cheaper than STD once commission is tick-converted — commission $7/lot ≈ 7 ticks. Children whose survival depends on RAW-tier pricing are flagged as such; "find a cheaper broker" is a capped lever.

### 1.4 The two-stage falsification template (F-013-consistent)

Every child's criterion below instantiates this template; none may deviate:

- **Stage-R (research kill, pre-registered before the first backtest run):** explicit OOS thresholds on the F-003-costed backtest. Failing Stage-R means the child is never born — no parameter re-tuning to rescue it beyond the pre-declared parameter grid (every variant logged per 05§B3).
- **Stage-L (live kill):** trade R-multiples accumulated into **blocks of 20 trades or 4 calendar weeks (whichever first)**; a CUSUM statistic on block mean-R vs the G1 backtest expectancy, with per-child alpha budget (spec in Pass 7). Breach of the 95% boundary = WARN only; breach of the 99% boundary **sustained over 2 consecutive blocks** = risk-halved; demote-to-paused requires the sustained 99% breach **plus** either human ack or a corroborating slippage/cost-regime shift in execution telemetry (03§A4). No per-trade peeking, ever (F-013).
- Additionally, each child carries a **regime-attribution falsifier** (from its §d predictions): if live regime-sliced P&L contradicts the thesis over ≥3 blocks, the child is flagged even if net-positive (05§B3 regime-slice rule — a "profitable for the wrong reason" child is a time bomb, per the Strategist).

---

## §2 Trend-Following family dossiers

### 2.1 T1 · Donchian breakout (D1) — the workhorse

**(a) Thesis — who loses, and why they keep losing.** Time-series momentum exists because price adjusts to information *gradually*, and three persistent flows fight the adjustment: (1) **profit-takers with the disposition effect** — holders sell winners into strength and hold losers, mechanically supplying liquidity against the trend's continuation (behavioral, constraint: mental accounting; they keep doing it because realizing gains feels like winning); (2) **price-insensitive hedging and rebalancing flow** — corporate FX hedgers, central-bank smoothers, and fixed-weight rebalancers sell what went up regardless of view (constraint: mandate, not belief — they *cannot* stop); (3) **institutional gradualism** — large allocators split entries over days/weeks, autocorrelating order flow; the breakout is often the visible edge of a flow that is not finished. The Donchian entry is a crude but robust discretization of "the adjustment has begun." The Strategist's caution, recorded: the same breakout level is where retail breakout traders cluster stops-and-entries, so the *first* hours after a D1 break are contested and slippage-prone (F-022 applies with force to stop-entry fills here).

**(b) Evidence base.** Effect class: time-series momentum / post-breakout drift. **Grade E1** — the single best-documented anomaly class in the roster: 12-month TSMOM documented across ~60 futures markets (Moskowitz–Ooi–Pedersen 2012), extended to a century of data across asset classes (Hurst–Ooi–Pedersen), and run at scale by CTAs for four decades (literature-informed). Honest caveats: (i) the published Sharpe is a *portfolio* Sharpe over 50+ diversified markets — a retail roster of 8–12 correlated FX/metals/index CFDs captures a fraction of it; (ii) FX-specific trend was famously weak 2012–2019 and revived 2020–2022 with the vol/rates regime (literature-informed) — multi-year flat stretches are the norm, not a failure signature; (iii) the 20-day channel specifically is Turtle folklore — its exact parameter carries maximal publication-selection glow; the parameter-plateau requirement (05§B3) is the defense.

**(c) Capacity & decay.** Capacity irrelevant at retail size (CTAs run hundreds of billions in the effect class; our footprint is invisible). Decay is *secular and slow*: the effect has survived 40 years of being publicly known, likely because the losing flows are constraint-driven, not naive. Expected decay mode is not death but **compression**: shallower trends, more failed breakouts as vol regimes shift. Profile: multi-year drawdowns of 15–25% of the sleeve's equity are within historical norms for trend at this concentration (literature-informed).

**(d) Regime dependence — testable predictions (pre-registered).**
- P1: ≥ 65% of net P&L accrues in bars labeled TRENDING_UP/DOWN (hypothesis).
- P2: entries taken with efficiency ratio ≥ 0.35 outperform sub-0.35 entries by ≥ 0.1R mean (hypothesis).
- P3: performance in the ATR-percentile 40–90 band exceeds the <40 band (trend needs fuel); the >90 skip-rule (01§3) costs nothing net (hypothesis; if the skip-rule turns out to *cost* P&L, that finding goes to the board — it would say chaos entries are where the payoff lives, contradicting the safety gate).

**(e) Cost sensitivity.** The most cost-robust child in the roster. Worked F-003 numbers, EURUSD D1 (all **hypothesis**, to be replaced by G1 output): p_win 0.36, avg_win 180 ticks (2.6R at 2.0×ATR(20)≈70-tick stop), avg_loss 70 ticks → edge_ticks = 0.36·180 − 0.64·70 = **+20.0 ticks**. cost_ticks (STD tier, BREAKOUT stop-entry slippage ≈ +3) ≈ 15–18 → **viability ≈ 1.1–1.3**. On RAW ≈ 12–14 → **viability ≈ 1.4–1.7**. Sobering and honest: even the workhorse sits barely above the 1.5 hypothesis threshold on a standard-markup feed — this is what "retail edges are small" looks like in ticks, and why F-003's inert gate was a CRITICAL. T1 dies *last* as spreads widen, but it does die: at 2× spread (news-adjacent, exotic symbols) viability halves to <1.
**Gap constraint (F-011):** T1 holds over weekends by design; its positions carry gap-stressed risk at k≈1.3 (fx majors) to k≈3 (index CFDs) per the Pass-3 ledger; the Friday-reduce default stays OFF for fx majors, ON for index CFDs (board vote 9–1, Strategist dissent noted in §7).

**(f) Falsification.**
- Stage-R: pooled across ≥ 6 instruments, OOS (05§B3 split) profit factor ≥ 1.3 after the full F-003 cost model, ≥ 100 trades, WF efficiency ≥ 0.5, parameter plateau on channel ∈ {15…30} and stop ∈ {1.5…2.5}×ATR — a spike at exactly (20, 2.0) with dead neighbors = **fail** (publication-selection signature).
- Stage-L: per §1.4 template. Additional regime falsifier: P1 below 50% for 3 consecutive blocks → thesis-drift flag even if net-positive.

**(g) Expected profile (hypothesis) + red team.** Win rate 30–42%, payoff 1.8–2.6, expectancy +0.10…+0.25R/trade, 10–25 trades/yr/instrument — **all hypothesis**. **Auditor:** the viability arithmetic in (e) already assumes the backtest's p_win/avg_win survive costs and slippage that the backtest itself estimates — circularity is controlled only by conservative slippage priors as floors (F-029). Further: at 10–25 trades/yr/instrument, G1's 100-trade minimum needs 6 instruments × ~1.5 years OOS minimum; nobody gets to claim T1 works from 30 trades. Signed off with those two conditions.

### 2.2 T2 · EMA pullback continuation (H4)

**(a) Thesis.** Two-layer thesis, and the board insists the layers be scored separately. **Layer 1 (carrier):** same TSMOM flows as T1 — T2 is a second entry gate into the identical underlying drift. **Layer 2 (timing overlay):** within an established trend, pullbacks are created by profit-taking and stopped-out weak hands; the pullback terminates when that supply exhausts near widely-watched dynamic reference levels (EMA zones), and the "rejection candle" is the visible footprint of exhaustion. Who loses on the overlay: **counter-trend faders** who short strength/buy weakness on "overbought/oversold" logic at precisely the resumption point (bias: gambler's-fallacy expectation of reversion in a trending series), and **late pullback sellers** who bail at the low of the retracement (loss aversion). Strategist's honesty note, recorded verbatim in the debate log: *"the carrier is E1; the candle-pattern trigger is E3 folklore until an ablation proves it adds expectancy."*

**(b) Evidence.** Carrier: **E1** (as T1). Timing overlay: **E3** — there is no credible published evidence that pullback entries with candle confirmation beat naive in-trend entries after costs at H4; practitioner belief is near-universal and evidence-free, the worst combination. The dossier therefore treats T2 as *T1's factor exposure with an unproven execution-timing claim* until the Stage-R ablation says otherwise.

**(c) Capacity & decay.** As T1 (same underlying effect). One extra decay channel: EMA(21)-touch entries are a crowded retail template; if the level is front-run, fills degrade and the rejection candle prints without us. Detectable in execution telemetry as worsening entry-vs-signal slippage — tagged for the learning loop.

**(d) Regime predictions.** P1: ≥ 70% of net P&L in TRENDING regimes (tighter than T1 — T2 has no business existing outside established trends) (hypothesis). P2: performance conditional on ADX ≥ 25 at entry strictly better than 20–25 band (hypothesis). P3: T2's trades cluster *later* in trend lifecycle than T1's (measured by bars-since-regime-flip); if T2 systematically enters *earlier*, the "continuation" framing is wrong (hypothesis).

**(e) Cost sensitivity.** Moderate-low. H4 stop 1.5×ATR(14) ≈ 45–60 ticks EURUSD; hypothesis edge_ticks ≈ +12–18 (p 0.45, W 75, L 50 → 0.45·75−0.55·50 = +6.3… the board notes this parameterization is *thin*; a payoff-1.5 version: p 0.42, W 90, L 50 → +8.8). cost_ticks 10–15 STD → **viability ≈ 0.6–1.2 — T2 is plausibly NON-viable on STD-tier pricing** and marginal on RAW (≈0.8–1.6). This was the pass's first genuine surprise: the "better prices, tighter stops" child (01§3) has *worse* cost geometry than T1 because tighter stops shrink the per-trade edge while the cost is fixed. Dies before T1.

**(f) Falsification.**
- Stage-R (two-part, the overlay must justify itself): (i) OOS PF ≥ 1.25 after costs, ≥ 100 trades, WF ≥ 0.5; (ii) **ablation**: T2-with-candle-trigger must beat T2-entering-on-any-EMA21-touch-in-trend by ≥ 0.05R mean OOS; if not, the trigger is deleted (fewer parameters win) or T2 is not built.
- Stage-L: §1.4 template; regime falsifier P1 < 55% over 3 blocks.

**(g) Profile (hypothesis) + red team.** Win 40–50%, payoff 1.4–1.8, expectancy +0.05…+0.15R, 20–40 trades/yr/instrument — hypothesis. **Auditor:** T2 and T1 P&L will correlate heavily (same carrier); T2 must additionally show *incremental* portfolio value (positive alpha residual to T1's return stream OOS, §6.3) or it is roster bloat that doubles trend-factor exposure while looking like diversification. That test is now part of Stage-R part (iii). Signed off with it.

### 2.3 T3 · Higher-timeframe momentum rotation (D1/W1) — F-020 resolved here

**(a) Thesis.** Cross-sectional momentum: instruments that outperformed peers over ~3 months continue to outperform over the next ~1 month. Losers: (1) **fixed-weight rebalancers** (mandate-bound sellers of relative winners); (2) **retail bottom-fishers** buying the worst performers ("it's cheap now" — anchoring to past price); (3) **benchmark-hugging capital** that under-reacts to relative news because tracking-error limits forbid conviction. These constraints are structural; the flow persists.

**(b) Evidence.** Cross-sectional momentum: **E1 in equities/futures** (Jegadeesh–Titman lineage; Asness–Moskowitz–Pedersen "everywhere" evidence across asset classes — literature-informed). **But the transfer to this roster is E2 at best**, for a reason the Quant seat insists be printed in bold: **the published effect is harvested across 40–80 instruments; our tagged universe is ~15–25 highly-correlated CFDs, so "top decile" means top-2 — the ranking signal at n≈20 is mostly noise around a couple of macro factors (dollar, risk appetite).** Cross-sectional momentum on 20 correlated names is closer to a stealth macro-factor bet than to the published anomaly.

**(c) Capacity & decay.** Capacity irrelevant at our size. Decay: equity cross-sectional momentum has visibly weakened post-2000s publication (momentum crashes 2009, 2016, 2023 — literature-informed); the multi-asset version held up better. Known crash mode: violent reversal after prolonged trends (momentum crash) — hits exactly when T1/T2 are also long the same trends. Printed as a §6 concentration risk.

**(d) Regime predictions.** P1: T3 P&L is *not* strongly regime-labeled per-instrument (it is cross-sectional) — instead: portfolio-level prediction that T3's drawdowns co-occur with regime-flip clusters (many instruments flipping TRENDING→RANGING within 2 weeks) (hypothesis, testable from the regime event log). P2: T3 long legs outperform short legs pre-costs (momentum is asymmetric in rates/carry-laden CFDs) (hypothesis).

**(e) Cost sensitivity + F-020 resolution.** Per-trade spread cost is small relative to weekly holding moves, **but T3's real costs are structural, and Pass 1 caught both**:
1. **Rebalance window (F-020, RESOLVED):** rebalance moves from "Sunday session open" to **Monday 08:00–10:00 Europe/London** (F-006-anchored; hypothesis window, G1 tests 08:00–10:00 vs 14:00–16:00 London). Sunday-open spreads are 3–10× weekday norms (literature-informed) — a weekly structural leak on the roster's lowest-per-trade-edge child, now closed. Urgency stays `low`; execution spreads fills across the window.
2. **Swap drag (F-020, RESOLVED):** T3's viability math **must** include swap for the average holding period: `edge_ticks_net = edge_ticks_price − E[swap_ticks_per_night]·E[nights_held]`, using discovered per-symbol swap (03§B1) including triple-swap day. Retail CFD short legs are the killer: short index/commodity CFDs typically pay financing both ways; **hypothesis: swap alone consumes 30–100% of the short book's gross edge**. Board decision: **short legs default OFF**; T3 v1 ships long-top-k + flat, shorts enabled per-instrument only where the swap-inclusive backtest shows the short leg positive net (recorded in §7; Strategist dissent — "half a momentum strategy" — resolved by the decision matrix in §7.3).
**Gap constraint (F-011):** weekly holds across weekends on index CFDs → gap-stressed k≈3 budgeting applies; this materially shrinks T3's effective book size on indices. Stated, not hidden.

**(f) Falsification.**
- Stage-R: OOS (swap- and session-spread-inclusive) PF ≥ 1.2 AND block-bootstrap 90% CI of weekly expectancy excludes ≤ 0; rank-signal sanity check: rank IC (Spearman of 12-week momentum rank vs next-4-week return rank) > 0 in ≥ 60% of OOS quarters (hypothesis threshold). If the long-only variant fails Stage-R, T3 is not built — there is no fallback variant.
- Stage-L: §1.4 template on weekly blocks (20 trades ≈ 5 months at weekly cadence — the Auditor notes below that this makes T3 the *slowest child to falsify live* and the priority vote in §8 reflects that).

**(g) Profile (hypothesis) + red team.** Portfolio-level: expectancy +0.02…+0.08R/position-week, long stretches of noise; Sharpe contribution meaningful only via diversification — hypothesis. **Auditor:** n≈2-per-decile ranking noise + slowest falsification + swap-eaten short book = the weakest evidence-to-cost ratio in the trend family. The Auditor formally proposed T3 be deprioritized below the new candidate TC-2 (§5.1), which captures the same effect class with fewer moving parts; board vote in §8 agreed (T3 build-priority demoted to 4th in family). This is a Pass-2 roster recommendation, not a deletion — T3 remains specced.

### 2.4 T4 · Volatility-expansion straddle (M30/H1, London open) — F-021 resolved here

**(a) Thesis.** Volatility clusters, and range compression predicts expansion (E1 for the *volatility* claim). The London open is the day's largest scheduled liquidity regime change for European pairs: overnight inventory gets repriced, Asian-session stops sit just outside a narrow range, and the first institutional flow of the European day sweeps them, converting clustered stops into fuel for a directional impulse. Losers: (1) **Asian-session range holders** whose stops are the fuel (constraint: they positioned in a low-information regime and are forced out at the transition); (2) **late breakout chasers** who buy the move after it has traveled — we are *early* mechanical chasers by construction, they are discretionary late ones. Honest structural note from the Strategist: the *direction* is unknowable at placement — T4's edge, if any, is that expansion after compression is large enough to pay for one stopped leg plus costs. It is a long-volatility bet expressed with stop orders.

**(b) Evidence.** Compression→expansion (vol clustering): **E1** (the most robust stylized fact in finance — literature-informed). Session-anchored expansion at London open: **E2** — intraday FX volatility seasonality (London/NY overlap peaks) is well documented on interbank data; the *tradability* of the straddle at retail costs is not. The straddle mechanics (opening-range breakout lineage, Crabel 1990) are **E3 post-decay** — ORB on liquid futures is heavily published and largely arbitraged flat at short horizons (literature-informed).

**(c) Capacity & decay.** Effectively unlimited capacity at retail size; decay risk is *microstructural*: as spreads at 08:00 London tighten and algos react in milliseconds, the impulse's first ticks are gone before a retail stop order fills — the edge migrates toward whoever is fastest, and we are slow by design. Expected decay mode: slippage creep on the entry leg, visible in telemetry (03§A4) before it is visible in P&L.

**(d) Regime predictions.** P1: conditional on entry (narrow Asian range < 40th pct), the London-session realized range exceeds its unconditional distribution's median in ≥ 60% of trade days (this tests the compression→expansion premise separately from P&L) (hypothesis). P2: T4 profits concentrate on days the regime engine flips RANGING→TRENDING intraday; T4 should *lose* on days that stay RANGING (both legs chopped) — if T4 makes money on RANGING days the model of the trade is wrong (hypothesis). P3: performance degrades within 60 min of red-calendar events (see F-021 rule below) (hypothesis).

**(e) Cost sensitivity + F-021 resolution.** High sensitivity — the second-most cost-fragile child after the M-family scalps. Worked numbers, EURUSD (hypothesis): narrow Asian range ≈ 250–400 ticks (25–40 pips); TP 1.5×range ≈ 375–600 ticks; stop = opposite side ≈ range height. p 0.42, W 450, L 300 → edge_ticks = 0.42·450 − 0.58·300 = **+15**. Costs: two stop orders placed, ≥1 cancelled or filled; entry slippage on fast opens 3–8 ticks (literature-informed for retail stops at London open), spread 10–15 → cost_ticks ≈ 15–23 **before the double-fill tax**. **F-021 RESOLVED — three binding rules:**
1. **Blackout:** no straddle placement when a red-calendar event falls within ±60 min of the London open window (hypothesis width; same calendar service as M1, F-006-anchored `Europe/London`). This rule existed for M1 and inexplicably not for T4; fixed.
2. **Measured double-fill economics:** Stage-R must simulate, on M1 data, the frequency f_df of both legs filling within the OCO grace window and the realized cost c_df of flattening leg 2 (spread + estimated news-slippage). The **kill term**: if `f_df · c_df > 0.30 · edge_ticks` (hypothesis threshold), T4 fails Stage-R regardless of headline PF.
3. **Grace window as measured parameter:** the OCO cancel-race window (03§A3.4) is set from the measured distribution of leg1-fill→leg2-fill gaps in backtest, not a constant.
Viability with the double-fill tax included: **≈ 0.6–1.0 STD-tier — T4 is presumptively non-viable on standard pricing** and marginal (≈0.9–1.4) on RAW. The board keeps T4 in the roster as the designated *long-vol diversifier* (§6.2) but its Stage-R bar is strict and its build priority reflects the marginal math.

**(f) Falsification.** Stage-R: OOS PF ≥ 1.25 after costs *including* simulated double-fill tax and trade-through-consistent stop fills; ≥ 100 straddle-days; the F-021 kill term above; P1 must hold (≥ 60%). Stage-L: §1.4 template; additional telemetry falsifier — rolling 50-fill mean entry slippage exceeding 2× the backtest assumption demotes T4 to paused pending cost-model refresh (this is the F-030-style execution check, applied early because T4's edge is thinnest against slippage).

**(g) Profile (hypothesis) + red team.** Win 38–48%, payoff 1.3–1.7, expectancy +0.03…+0.10R/straddle, ~80–150 straddle-days/yr/instrument — hypothesis. **Auditor:** T4 has the roster's largest gap between the elegance of its premise (E1 vol clustering) and the evidence for its tradability (E3 ORB post-decay). The premise being true does not make the trade profitable; the double-fill tax and open-slippage are exactly where the premise leaks out. The Auditor's condition: T4's G1 report must show the full cost waterfall (gross → spread → slippage → double-fill → net) per instrument, so the board sees *where* the edge dies if it dies. Accepted.

---

## §3 Session Mean-Reversion family dossiers

### 3.1 M1 · Asian-session Bollinger fade (M15) — anchor: `Asia/Tokyo` session table computed per F-006

**(a) Thesis.** During Tokyo hours, EUR-cross information flow is minimal: the marginal price-setters are inventory-managing dealers and flow desks, not opinion-driven capital. Price motion is dominated by liquidity demand — orders that want immediacy and pay for it. Fading the band is **selling immediacy in the market's quietest hours**: the fade's counterparty is (1) **impatient flow** (late-Asia corporate conversions, retail chasing small breakouts) that pays the spread + impact to transact *now* in a thin book (constraint: they need to transact, the hour is what it is); and (2) **short-timeframe breakout traders** whose Asian "breakouts" die for lack of follow-through flow (bias: applying London-hours playbooks to Tokyo-hours liquidity). This is a liquidity-provision risk premium, not an informational edge — small, steady, and paid back with interest on the nights when a real move (BoJ, risk shock) runs through every fade. Fat left tail *by construction*; the VOLATILE_CHAOS hard-block and news blackout are the tail's only mitigants.

**(b) Evidence.** Short-horizon FX reversal in low-information hours: **E2** — intraday reversal and session-conditional vol patterns are documented on interbank/futures data (literature-informed), but nearly all published intraday-reversal profitability evaporates at retail spread levels, and the published tests predate the F-012 correction (touch-fill optimism is endemic in this literature). The specific BB(20,2.2)/M15/Asian construction: **E3**. The board's posture: the *phenomenon* (Asian ranging) is real; the *harvestability at our costs* is the entire question, and it is open.

**(c) Capacity & decay.** Capacity trivially sufficient. Decay: this premium requires the Tokyo-hours liquidity structure to persist (it has, for decades) but is exquisitely sensitive to broker pricing changes — a 0.3-pip markup increase can erase it (see (e)). Decay will look like slow expectancy bleed, not a crash — exactly the profile CUSUM block monitoring (F-013) is designed for.

**(d) Regime predictions.** P1: ≥ 80% of net P&L in RANGING-labeled bars (tightest requirement in the roster — M1 has *no* thesis outside ranging) (hypothesis). P2: losses concentrate in the final pre-London hour as early European flow arrives; a session-end cutoff 1h before London open (F-006-anchored) should improve expectancy (hypothesis — tested in Stage-R as an ablation, not tuned by hand). P3: trades taken when spread_now > 1.5× Asian-session norm underperform (the spread gate 03§A2 should be binding, not decorative) (hypothesis).

**(e) Cost sensitivity — the roster's canary.** M1 **dies first**. Worked F-003 numbers, EURUSD M15 Asian (hypothesis): band-to-midline TP ≈ 60 ticks; stop 1.2×ATR beyond band, avg loss ≈ 65 ticks; p 0.62 → edge_ticks = 0.62·60 − 0.38·65 = **+12.5**. Costs (Asian session, LIMIT mechanism): spread avoided (F-012: *avoided, never earned*) but adverse-selection term charged at 50% of the spread-avoidance credit pre-live (F-012 default): STD tier ≈ 15–25 tick Asian spread → cost_ticks ≈ 8–14; RAW ≈ 6–9. **Viability ≈ 0.9–1.6 RAW, 0.5–1.0 STD.** Conclusion printed in bold at board insistence: **M1 is only plausibly viable on RAW-tier pricing, and marginally there; on a standard markup broker it is dead on arrival, and the viability gate must say so automatically.** The 01§4 auto-disable rule (spread > 25% of TP distance) survives as a coarse backstop, but the F-003 gate is the real guard.
**F-006 constraint:** the DST-mismatch windows (2–3 weeks, twice yearly) put "Asian" trades into London flow — Stage-R excludes and Stage-L blocks the mismatch windows until the Pass-4 calendar service is proven; these windows are named test cases.

**(f) Falsification.** Stage-R: with trade-through fills + adverse-selection charge (F-012 fill-simulation spec, Pass-7): OOS expectancy ≥ 1.5 × cost_ticks (i.e., viability ≥ 1.5 measured in-backtest), PF ≥ 1.25, ≥ 150 trades (M1 trades often; the sample is cheap), WF ≥ 0.5; ablation: the 2-attempts-per-session cap must not be the source of the edge (removing it should degrade, not improve — if unlimited attempts improve results, the "max 2" was overfit). Stage-L: §1.4; regime falsifier P1 < 65% over 3 blocks; **cost falsifier**: rolling measured spread (learning loop, 05§D2) pushing viability < 1.2 for 2 consecutive weeks → auto-disable per instrument (this is the F-003 gate doing its job; hysteresis re-enable at ≥ 1.5).

**(g) Profile (hypothesis) + red team.** Win 58–66%, payoff 0.85–1.0, expectancy +0.02…+0.08R, 150–400 trades/yr/instrument — hypothesis. **Auditor:** M1's expectancy is a rounding error away from zero *by design*; its statistical appeal (many trades, fast evidence) is real but cuts both ways — it will also hit its CUSUM boundaries fastest. The Auditor requires M1's G2 demo phase to publish measured adverse-selection (fill-vs-next-20-bar drift, 03§A4) *before* G3, replacing the 50%-credit hypothesis with data — M1 is the child most likely to be killed by that single measurement, and better on demo than live. Accepted; recorded as an M1-specific G2 exit criterion.

### 3.2 M2 · London-open stop-hunt fade (M15/M30) — anchor: `Europe/London` per F-006

**(a) Thesis.** Stop-loss orders cluster at salient levels — Asian range extremes qualify — and clustered stops create price-cascade fuel (Osler's limit/stop clustering work on interbank data: **the one genuinely documented microstructure fact in this child** — literature-informed). Early London flow sweeps the cluster; the cascade overshoots the level because stop executions are price-insensitive market orders; when the sweep exhausts without genuine directional flow behind it, price re-enters the range and the overshoot retraces. Losers: (1) **the stopped-out** — Asian-session positioners whose forced exits *are* the spike (constraint: they pre-committed their exit price; the market found it); (2) **momentum joiners** who read the sweep as a breakout and buy the extreme (bias: extrapolating the first 15 minutes of London as the day's direction). The tell — close back inside the range — filters sweeps (fade them) from genuine breakouts (don't). No dealer-conspiracy claim is made or needed: clustered price-insensitive orders + thin pre-open book = cascade, mechanically.

**(b) Evidence.** Stop clustering at salient levels: **E2** (documented on interbank data; direct evidence at CFD retail feeds absent). Failed-breakout reversal as a tradable class: **E3** — massive practitioner folklore (the entire ICT/liquidity-narrative retail complex), effectively no formal evidence at this timeframe/venue. The Quant flags the folklore's crowding paradox: if the fade crowd grows large enough, their entries dampen the overshoot and their stops (beyond the spike extreme) become the *next* cluster — the pattern can invert. Grade honestly: **E2 premise, E3 construction.**

**(c) Capacity & decay.** Small capacity in the strict sense (the overshoot is ticks-to-tens-of-pips), irrelevant at our size. Decay: tied to the persistence of Asian-range stop placement habits — durable, since each cohort of retail traders re-learns stop-at-the-range-edge; the *parameters* (0.3–0.8×ATR spike window) will drift faster than the phenomenon. Re-validation cadence (05§D6) matters more here than for T1.

**(d) Regime predictions.** P1: M2's edge concentrates in the first 90 min of London and decays to zero by the third hour (hypothesis — pre-registered as a time-bucket attribution test). P2: fades of sweeps that occurred *without* a red-news catalyst outperform news-driven spikes (news spikes have flow behind them; the blackout should be doing real work) (hypothesis). P3: profitable mainly when the *daily* regime is RANGING or weakly trending; in strong TRENDING regimes the "failed breakout" is more often a pullback in a real move (hypothesis).

**(e) Cost sensitivity.** Moderate-high. Worked numbers (hypothesis): TP1 range-midpoint ≈ 120–180 ticks from entry, stop beyond spike ≈ 100–140; p 0.52 blended (partial at TP1, runner to TP2), avg_win ≈ 130, avg_loss ≈ 115 → edge_ticks = 0.52·130 − 0.48·115 = **+12.4**. London spreads are the day's tightest (STD ≈ 10–12, RAW ≈ 8–10 incl. commission) → **viability ≈ 1.0–1.3 STD, 1.2–1.6 RAW.** Marginal; better geometry than M1 because London pricing is tight, worse because the entry is often IMMEDIATE (pays spread + slippage on a moving market). Dies after M1/M4 but before T1.

**(f) Falsification.** Stage-R: OOS PF ≥ 1.25 after costs (IMMEDIATE entries charged market-mechanism slippage; LIMIT re-entries charged F-012 adverse selection), ≥ 120 trades; **parameter-plateau requirement with teeth**: the spike window (0.3–0.8×ATR) is 2 free parameters of 4 allowed; expectancy must be positive across all contiguous sub-windows of width ≥ 0.3 within [0.2, 1.0] — a single profitable island = fail. Stage-L: §1.4; P1 time-bucket falsifier (edge in hour 3+ = thesis wrong); F-006 mismatch windows blocked as in M1.

**(g) Profile (hypothesis) + red team.** Win 48–56%, payoff 1.1–1.4, expectancy +0.04…+0.12R, 60–120 trades/yr/instrument — hypothesis. **Auditor:** this child carries the roster's highest narrative risk — "stop-hunt fade" is a story retail traders *want* to be true, which is precisely when pre-registration discipline matters most. The Auditor's condition: the Stage-R report must include the null-model comparison (fade any 0.3–0.8×ATR excursion at *random* times of day) to prove the London-open conditioning adds the edge, not the excursion geometry alone. Accepted — this doubles as the session-seasonality evidence M2's whole premise rests on.

### 3.3 M3 · RSI(2) extreme reverter (H1)

**(a) Thesis.** Short-horizon reversal: after a fast multi-bar extension, the marginal flow is exhausted — latecomers who chased the move (bias: recency extrapolation) and forced flows (margin liquidations, stop cascades) have transacted; the price concession they paid reverts. The counterparty is **whoever demanded liquidity at the extreme**: chasers and the forcibly liquidated. RSI(2) < 5 on H1 is simply a normalized "fast, deep, recent extension" detector; the range filter (price in outer third of an established range, regime RANGING) attempts to exclude extensions that are trend births.

**(b) Evidence.** Short-term reversal as an effect class: **E1 in equities at daily horizon pre-2010** (Connors-lineage RSI(2) results on US indices — literature-informed) — and **the equity-daily version visibly decayed post-publication** (widely reported degradation after ~2010; honesty rule 2 applies in full). Transfer to FX at H1: **E3** — FX exhibits weaker short-horizon reversal than equity indices (literature-informed; FX autocorrelation structure differs), and we know of no credible retail-cost-adjusted evidence at H1. M3 is a *transfer hypothesis*, stated as such: the board builds it as an experiment on reversal-in-ranging-FX, not as a proven earner.

**(c) Capacity & decay.** Capacity ample. Decay: the equity-daily original decayed within ~6 years of mass publication; there is no reason to expect the FX-H1 transfer (if it works at all) to be more durable. Plan for a short shelf-life and cheap re-validation.

**(d) Regime predictions.** P1: ≥ 70% of net P&L in RANGING (hypothesis). P2: expectancy conditional on the range filter passing must exceed the unfiltered RSI(2) signal by ≥ 0.05R (the filter is 2 extra parameters; it must pay rent) (hypothesis). P3: time-stop exits (12 bars) should be net-negative trades on average — reversion that hasn't come isn't coming; if time-stopped trades are net-*positive*, the exit is leaving money and the time-stop parameter is wrong (hypothesis; diagnostic, not tuning license).

**(e) Cost sensitivity.** Moderate. Worked (hypothesis): H1 avg_win ≈ 120 ticks (RSI-50 exit), avg_loss ≈ 140 (1.5×ATR stop), p 0.58 → edge_ticks = 0.58·120 − 0.42·140 = **+10.8**; IMMEDIATE entries, cost 10–15 STD → **viability ≈ 0.7–1.1 STD, 0.9–1.4 RAW**. Marginal like its siblings; survives longer than M1 (bigger tick targets) and dies around the same spread level as M2.

**(f) Falsification.** Stage-R: OOS PF ≥ 1.25, ≥ 100 trades, WF ≥ 0.5, **and the cross-instrument robustness rule**: positive OOS expectancy on ≥ 3 instruments from ≥ 2 correlation groups (02§A3) — an edge that exists on exactly one symbol is a data-mining artifact by default (Quant's rule, board-adopted for all M-family children). Ablation of the range filter per P2. Stage-L: §1.4; P1 falsifier at < 55% over 3 blocks.

**(g) Profile (hypothesis) + red team.** Win 54–62%, payoff 0.8–1.0, expectancy +0.02…+0.08R, 80–150 trades/yr/instrument — hypothesis. **Auditor:** M3 is the roster's cleanest test of the honesty machinery itself — a famous, published, decayed signal transferred to a new venue. If the pipeline can't kill a dead transfer cleanly (Stage-R fail or fast Stage-L demotion), the pipeline is broken. The Auditor formally suggests M3 double as Pass-7's **positive-control-adjacent** specimen (T7 in pass1 §4: gates need controls); the board agreed to feed M3's variants into the gate-control suite regardless of whether M3 ships.

### 3.4 M4 · Index open-drive fade (M5/M15) — anchor: per-index exchange calendar (`America/New_York` for US indices, `Europe/Berlin` for DAX) per F-006

**(a) Thesis.** Equity cash opens aggregate overnight news into a one-shot auction; market-on-open imbalances and overnight-gap overreaction create the day's largest *temporary* price pressure. A drive extending > 1.2× the average opening move without pullback is disproportionately pressure (flow) rather than information, and pressure reverts toward the session's developing fair value (VWAP) once the imbalance clears. Losers: (1) **overnight overreactors** — gap-direction chasers converting headlines into market orders at the open (bias: salience of overnight news); (2) **mechanical open flow** — MOO/auction imbalance and margin-call liquidations that must transact at the open regardless of price (constraint: mandate/margin). This is the M-family's best-documented loser population.

**(b) Evidence.** Opening overreaction / gap fading / intraday VWAP reversion in equity indices: **E2** — the underlying phenomena (open auction imbalance effects, intraday reversal at the open, VWAP magnetism) are documented on exchange data (literature-informed), making M4's *premise* the strongest in the family. But the venue transfer is brutal and specific: **retail CFD spreads at the cash open are 3–10× their session norm for the first minutes** (literature-informed; every index CFD trader's lived experience) — the published effect lives at exchange spreads precisely where our costs peak. E2 premise, harvestability open.

**(c) Capacity & decay.** Capacity fine. Decay: open-auction reversion has persisted in exchange data for decades (structural flow causes); the retail-harvestable residue depends almost entirely on CFD open-spread behavior, which is a broker-pricing variable, not a market variable — decay risk is therefore *broker-driven* and per-broker measurable (exactly what discovery + spread sampling exist for).

**(d) Regime predictions.** P1: expectancy is increasing in the entry's delay after the open within the first hour (later entries face less spread, less imbalance-continuation risk) up to a cutoff (hypothesis — time-bucket attribution pre-registered). P2: fades of drives *without* overnight red-news catalysts outperform news-driven drives (hypothesis, mirrors M2-P2). P3: flat-by-2h rule should truncate losers more than winners (hypothesis; same diagnostic logic as M3-P3).

**(e) Cost sensitivity.** **Extreme, and session-shaped**: M4's cost must be modeled with the *open-window spread distribution*, never the daily median — using median spread here is exactly the F-003 failure resurrected, and the board writes the rule explicitly: **M4's viability gate consumes `median_spread_ticks(open_window)` sampled over the first 15 minutes** (hypothesis window). Worked (hypothesis, US500 CFD): avg_win ≈ 90 ticks to VWAP, avg_loss ≈ 110, p 0.58 → edge_ticks = **+6.0**; open-window cost 8–25 ticks depending on broker/minute → **viability ≈ 0.25–0.75 in the first minutes, possibly ≥ 1.2 from minute ~10 onward.** Design consequence, adopted: M4 v1 **does not trade the first N minutes** (N ≈ 5–10, set per-instrument from measured open-spread decay curves at G2) — the child's viable existence is *conditional on entry delay*, and the dossier says so up front. Dies first alongside M1 as spreads widen.

**(f) Falsification.** Stage-R: OOS PF ≥ 1.25 with the open-window spread model + IMMEDIATE slippage; ≥ 100 trades; P1 curve must show the predicted shape (if expectancy is *flat or decreasing* in entry delay, the "spread decay buys viability" premise is wrong and the child fails); cross-index robustness (≥ 2 indices) per the M-family rule. Stage-L: §1.4; broker-cost falsifier — measured open-window spread drifting above the G1 assumption by > 30% for 2 weeks → auto-disable (per-instrument, hysteresis re-enable).

**(g) Profile (hypothesis) + red team.** Win 55–62%, payoff 0.75–0.95, expectancy +0.02…+0.07R, 100–200 trades/yr/index — hypothesis. **Auditor:** M4's dossier contains the pass's most load-bearing conditional — "possibly viable from minute ~10" — resting on zero measured data. The Auditor requires the open-spread decay curve (per broker, per index, per minute) to be among the *first* measurements the spread sampler takes at G2, and M4's build gated behind that measurement rather than in parallel with it. Accepted; reflected in the §8 priority (M4 builds after its measurement, not before).

---

## §4 Regime-engine extensions

The regime engine (01§2) is the roster's common-mode dependency (§6.4); extensions must clear a high bar: O(1) incremental updates within the feature-store contract (04§A1), few parameters, and a consumer that provably needs the output. Verdicts: one mandatory fix, two ADOPT, one DEFER, one REJECT.

### 4.1 E0 · Confidence formula + dwell/hysteresis — **MANDATORY (resolves F-018)**

**Specification (adopted):** each of the four inputs produces an agreement score in [0,1] for the candidate regime label:

```
s_ADX  = clip((ADX − 18) / (25 − 18), 0, 1)                      # trending candidates; inverted for RANGING
s_ER   = clip((ER − 0.25) / (0.40 − 0.25), 0, 1)                 # ditto
s_ATR  = 1 − chaos_proximity                                     # distance from the CHAOS/DEAD bands, scaled
s_DIR  = 1 if EMA50/EMA200 alignment + slope agree with label else 0   # direction gate, trending labels only
confidence = 0.30·s_ADX + 0.30·s_ER + 0.15·s_ATR + 0.25·s_DIR    # weights: hypothesis, Pass-7 sensitivity-tests
```

**Hysteresis on all inputs, not just ADX (F-018):** ER enter/exit 0.35/0.25; ATR-percentile CHAOS enter > 92, exit < 85; DEAD enter < 8, exit < 15 (all hypothesis). **Dwell:** a regime transition is *published* only after 3 consecutive bars of the new label (hypothesis) — **except transitions into VOLATILE_CHAOS or DEAD, which publish after 1 bar** (safety asymmetry: standing down is fast, standing up is slow; board unanimous). Family-priority arbitration (01§5.2) consumes only *published* transitions, ending the flapping path F-018 identified. Incremental cost: zero new state beyond a 3-bar label buffer. **Objection (Strategist):** the 3-bar dwell delays trend-child activation by 3 bars — on D1 that is 3 days of missed breakout. **Resolution:** dwell applies to the *published* regime label used for arbitration and meanrev gating; trend children's own entry filters (01§3: "regime TRENDING **or** ER > 0.35") may consume the raw per-bar inputs directly — the delay binds where flapping is dangerous (priority, meanrev enablement), not where responsiveness is the point. Signed off.

### 4.2 E1 · EWMA volatility state (GARCH-lite) — **ADOPT**

**Spec:** RiskMetrics-style EWMA variance per (instrument, timeframe): `σ²_t = λ·σ²_{t−1} + (1−λ)·r²_t`, λ = 0.94 (literature-informed default; the single parameter). O(1), one float of state — the cheapest feature in the store. **Consumers with proven need:** T3/TC-2 vol-targeted sizing (02§A1 overlay), F-024's anomaly-breaker denominator (Pass 3 needs a live vol estimate), the ATR-percentile's smoother cousin for CHAOS/DEAD detection, and the Pass-7 cost model's vol-conditional slippage. **Statistical power vs parameters:** vol clustering is the most robust stylized fact available (E1); one parameter buys a genuine forecast. **Objection (Auditor):** duplicate of ATR-percentile — two vol states invite inconsistent gating ("which vol is the vol?"). **Resolution:** EWMA becomes the canonical *sizing/forecast* vol; ATR-percentile remains the canonical *regime-band* input (its percentile framing is what the CHAOS/DEAD thresholds are calibrated on); a Pass-7 parity study decides whether ATR-percentile is retired in v2. One owner per use, documented. **Verdict: ADOPT** (9–1, Auditor dissent recorded as the parity-study condition).

### 4.3 E2 · Session-conditional baselines — **ADOPT (narrow form only)**

**Spec:** per (instrument, session) rolling baselines — median spread (already specced, 02§B1 snapshot uses it), realized vol, and average range — maintained as per-session Welford accumulators keyed by the F-006 calendar service. O(1) per tick/bar. Consumers: spread gate (03§A2), M1/M2/T4 session-relative range logic, M4's open-window spread model (§3.4e — this extension is what makes that model implementable). **Objection (Quant, sustained):** the *broad* form — session-specific regime **labels** (regime × session = 20 cells) — starves every cell of sample and adds silent parameters; REJECTED. Only session-conditional *normalization* of existing features is adopted; the regime label stays session-blind. **Verdict: ADOPT narrow / REJECT broad** (unanimous with the scope restriction).

### 4.4 E3 · Cross-asset risk-on/off state — **DEFER**

**Proposal considered:** composite z-score (equity index return + AUD/JPY − gold − JPY strength, EWMA-normalized) published as a portfolio-level regime input; would serve F-017's macro-factor cap and M4/T3 gating. **Why deferred, three grounds:** (1) **architecture** — the feature store is keyed per-instrument (04§A1); a cross-instrument feature needs portfolio-scope DAG nodes with multi-instrument event synchronization (instruments tick asynchronously; "the" composite at time t is ill-defined without a sync policy) — a Pass-5 design item, not a config entry; (2) **F-017's v1 resolution** already covers the macro-concentration hole with static groups + explicit accepted-risk documentation (Pass 3); (3) parameters (component weights, normalization windows) are exactly the silently-tuned macro model the overfitting charter warns about. **Objection (Strategist, recorded):** deferral leaves T3/M4 without the macro context their dossiers admit they're exposed to. **Resolution:** accepted as true; the exposure is *documented* in §6.4 as a v1 accepted risk, and E3 is first in line for v2 once Pass 5 lands portfolio-scope nodes. **Verdict: DEFER** (with a named re-entry condition, not an indefinite parking).

### 4.5 E4 · HMM / learned regime model — **REJECT**

2-state Gaussian HMM on returns: ~6+ parameters, EM refits are batch (violates the O(1) incremental contract without approximations that have their own failure modes), label instability under refit destroys the regime-attribution ledger's comparability across time (05§D4 becomes uninterpretable when the labeler itself drifts), and unfalsifiable label churn is precisely the F-018 disease with more math. The rule-based engine's labels are auditable — a human can recompute them from four published inputs — which the board weights above marginal classification accuracy for a system whose regime labels gate live risk. **Objection (Quant, pro-HMM):** rule thresholds are themselves parameters, just honest-looking ones. **Resolution:** true, but they are *few, inspectable, and hysteresis-stabilized*; the HMM's parameters are many and refit-unstable. Rejected for v1 and v2; revisit only with a frozen-label offline study demonstrating material gating improvement. **Verdict: REJECT** (8–2).

---

## §5 New child candidates

Per 01§6, each is a hypothesis document — a roster *candidate*, not a commitment; one child graduates the gates at a time. Build-priority votes (10 seats, approve/defer): recorded per candidate.

### 5.1 TC-2 · Long-horizon TSMOM ballast (`trend.tsmom12_v1`) — **priority vote 9–1 BUILD-EARLY**

*(Numbered TC-2 but presented first because the board voted it ahead of TC-1 and ahead of T3.)*
- **Thesis:** the purest expression of the E1 effect T1/T2 approximate: per-instrument sign of the trailing 12-month return decides direction; EWMA vol targeting (E1 adoption, §4.2) decides size; weekly evaluation, positions held weeks-to-months. Losers: identical population to T1(a) — this is deliberate; TC-2 is the *low-noise carrier* of the family's core factor.
- **Who's on the other side:** as T1(a); at 12-month horizon the rebalancing/mandate-constrained flows dominate the behavioral ones (literature-informed).
- **Required features:** `close_252d_return` (rolling window from cold history + O(1) update), EWMA vol (§4.2), regime engine (for reporting only — TC-2 deliberately does *not* regime-gate; the 12-month sign is its own regime filter, and adding a second one double-counts).
- **Entry/exit/stop (all hypothesis):** evaluate weekly (Monday London window, inheriting the F-020 fix); enter/hold long if sign(+), short if sign(−) *where swap permits* (F-020 swap math applies; shorts default OFF where financing-negative, as T3); position vol-targeted to a fixed risk budget; exit = sign flip at weekly evaluation; **stop:** 3.0×ATR(20) catastrophe stop, broker-side from fill (02§A5) — wide because the exit is the signal flip, the stop is disaster insurance only. `tags_required: {vol_tier ≤ high}`; holds across weekends/closes → full F-011 gap-stressed budgeting (index k≈3).
- **Expected profile (hypothesis):** 1–4 signal flips/yr/instrument; expectancy per position-week small; value is factor purity + the lowest cost sensitivity in the entire roster (a handful of trades a year — viability ≈ 5–20 even on STD pricing; effectively cost-immune).
- **Falsification:** Stage-R: 15-year, swap-inclusive, OOS PF ≥ 1.2 pooled across ≥ 8 instruments; sign-flip whipsaw share of gross losses < 40% (hypothesis). Stage-L: §1.4 on weekly blocks — with the honest caveat that at this cadence live falsification takes years; the child is monitored primarily against its *published effect class* (if 12M TSMOM dies globally, the literature will show it before our CUSUM does).
- **Pass-1 constraints:** F-011 (binding, the roster's largest gap-risk holder), F-020 (inherited), F-005 (margin/notional caps bind TC-2's vol-targeted sizing — vol targeting must re-clamp per F-034).
- **Board note:** TC-2 subsumes much of T3's rationale with ~3 parameters instead of a noisy n≈20 ranking; the Auditor's §2.3 recommendation (build TC-2 before T3) carried 9–1 (Strategist dissenting for cross-sectional diversification — see §7.3 decision matrix).

### 5.2 TC-1 · Carry-aligned trend variant (`trend.donchian_carry_v1`) — **priority vote 6–4 DEFER-UNTIL-T1-VALIDATED**

- **Thesis:** condition T1's breakout on the carry sign: trade breakouts only in the direction that *earns* swap (discovered `swap_long/short`, 03§B1). Two E1/E2 premia (trend, carry) reinforce; carry-positive trends are structurally longer-lived because the carry flow itself feeds them (literature-informed: carry and momentum interaction in FX).
- **Other side:** as T1, plus carry-unwinders forced out in risk-off (which is also this child's crash mode: carry-aligned trend positions are exactly what unwinds violently in risk-off — the child inherits carry's left tail; stated, not hidden).
- **Features:** T1's set + per-symbol swap from discovery (already a discovered field; zero new feature-engine work).
- **Rules (hypothesis):** T1 rules unchanged; additional pre_filter: `swap_in_trade_direction ≥ 0` (or ≥ small negative floor −X ticks/night, X tunable within the 3–4-param budget by *replacing* a T1 parameter, not adding — board condition). Same tags, stops, exits as T1.
- **Expected profile (hypothesis):** fewer trades than T1 (filter removes ~40–60% of signals), higher expectancy per trade if the interaction holds; cost profile identical to T1.
- **Falsification:** Stage-R is *comparative*: OOS expectancy must exceed T1's by ≥ 0.05R on the shared signal subset AND the filtered-out subset must underperform the kept subset (both directions of the claim tested); otherwise the filter is noise and the child is not built. Stage-L: §1.4.
- **Pass-1 constraints:** all of T1's (F-011, F-022); F-023 (swap values must be fresh — stale discovery swap corrupts the filter; refresh-at-signal rule extends to swap fields).
- **Vote rationale:** cheap to build, but it forks T1's identity before T1 itself is validated — sequencing, not skepticism.

### 5.3 MC-1 · Round-number liquidity fade (`meanrev.roundlevel_v1`) — **priority vote 7–3 BUILD-AFTER-M2**

- **Thesis:** limit orders cluster at round numbers (x.xx00, x.x500 for fx; 00/50 handles for indices/gold) — the documented Osler result (E2, interbank data): take-profit limits cluster *at* rounds, stops cluster just *beyond*. First touch of a major round in a RANGING regime meets a wall of resting passive interest → bounce. Losers: **impatient flow that pays through the cluster** (chasers hitting the level with market orders) and — when the bounce fails — us, into the stop cascade beyond (the child's defined tail).
- **Other side / why it persists:** round-number order placement is a human salience bias with decades of documented persistence (E2); each retail cohort re-creates it.
- **Features:** distance-to-nearest-major-round (O(1) arithmetic), regime state, session baselines (§4.3), ATR.
- **Rules (hypothesis):** RANGING regime, Asian or late-NY session (thin books amplify cluster effects; anchors per F-006); LIMIT intent at round ± small offset (F-012 fill rules apply in full); stop 1.0×ATR(14) beyond the level (inside the stop-cluster zone is deliberate — beyond it is where cascades run); TP 0.5× the distance to the opposite band/reference; max 1 attempt per level per session; red-news blackout as M1.
- **Expected profile (hypothesis):** win 60–68%, payoff 0.6–0.8, expectancy +0.02…+0.06R; cost profile ≈ M1 (dies with M1 on STD pricing — RAW-tier conditional, stated).
- **Falsification:** Stage-R: OOS PF ≥ 1.25 with F-012 fills; **placebo test (the dossier's spine):** identical rules at *non-round* pseudo-levels (x.xx37 offsets) must show materially worse expectancy — if rounds aren't special in our data, the Osler premise failed transfer and the child dies pre-build. Stage-L: §1.4.
- **Pass-1 constraints:** F-012 (definitive — this child is 100% passive fills), F-006, F-003 (M1-class cost fragility).

### 5.4 MC-2 · Cross-pair divergence reverter (`meanrev.pairdiv_v1`) — **priority vote 10–0 DEFER (architecture-blocked)**

- **Thesis:** tightly-linked pairs (EURUSD/GBPUSD; US500/US100) share macro drivers; short-horizon divergence of one from its rolling-beta-predicted value is disproportionately idiosyncratic liquidity noise and reverts. Losers: single-pair momentum chasers pushing one leg without the macro flow that moves both.
- **Evidence:** stat-arb pairs logic, E2 at institutional scale in equities; FX-cross version at retail costs E3.
- **Blocker (same as §4.4 E3):** requires cross-instrument feature nodes (rolling beta, residual z-score across two asynchronous streams) — the feature store has no portfolio-scope keys until Pass 5 designs them. The board declines to spec entry rules for an engine that cannot compute the signal. Full hypothesis doc owed when the dependency lands; parked with a named re-entry condition (Pass-5 portfolio-scope nodes shipped + F-017 group accounting live, since a pairs child *is* a correlation-group bet and the ledger must see it as one).
- **Pass-1 constraints:** F-017 (definitional), F-015/F-004 (its state spans instruments — event-log design must support it).

---

## §6 Portfolio construction view (Quant seat)

### 6.1 What the roster actually is, factor-honestly

Eight-plus children are **not** eight bets. Decomposed by design intent:

| Factor sleeve | Children | Return-stream character |
|---|---|---|
| **Trend/TSMOM carrier** | T1, T2, TC-2, (TC-1), most of T3 | long-vol-ish, right-skewed, multi-year droughts, gap-exposed (F-011) |
| **Long-vol expansion** | T4 | long-gamma at session scale; pays off when RANGING breaks |
| **Short-vol liquidity provision** | M1, M3, MC-1 | left-skewed, steady small wins, CHAOS-gated tail |
| **Structural-flow reversion** | M2, M4 | event-window reversion; between the two vol postures |

Effective bet count with hypothesis average pairwise correlation ρ̄ ≈ 0.35 across 8 streams: `N_eff = N / (1 + (N−1)·ρ̄) = 8 / 3.45 ≈ 2.3` **(hypothesis)** — the honest number the dashboard should display next to "8 children". The roster is essentially **a trend factor, a reversion-liquidity factor, and a session-timing residual**.

### 6.2 Why it still isn't 8 flavors of one bet

The two dominant sleeves are **complementary by construction**, on three axes: (1) **regime activation** — the regime engine turns trend children on exactly where meanrev children are off (01§2 rules of engagement), so their *active periods* anti-overlap; (2) **vol posture** — trend+T4 are long realized vol, M-family is short it; portfolio realized-vol beta is partially internally hedged (hypothesis, must be measured in the combined backtest, Pass 7); (3) **holding period** — weeks (TC-2/T3) vs hours (M4/M1) means shared shocks hit different exposure windows. This is genuine diversification — but it is *conditional on the regime engine being right*, which is §6.4's first risk.

### 6.3 Family risk budgets (feeds Pass 3's ledger; all hypothesis)

Within the 8% account open-risk budget (02§A2, as amended by F-005's margin/notional/gap columns): **trend sleeve 55%, meanrev sleeve 35%, probation reserve 10%** (children in G3 draw only from the reserve). Within-sleeve: no single child > 50% of its sleeve; T2 and TC-1 share T1's *factor* sub-budget (their correlation to T1 is by design — the ledger must not count them as independent risk). **Stage-R portfolio rule (new, board-adopted):** any new child must show OOS **residual** value — regressing its return stream on the live sleeves' streams, the residual's contribution must be positive — before it earns budget outside the reserve. This operationalizes the Auditor's T2 condition (§2.2g) for every future child.

### 6.4 Concentration risks, stated plainly

1. **Regime engine as common mode.** Every child's activation, and the family arbitration, hangs on one labeler. A systematic regime misclassification correlates the whole book instantly (meanrev trading through trend births, trend children asleep in trends). Mitigants: E0's hysteresis/dwell, regime-attribution monitoring (05§D4); residual risk accepted and printed.
2. **Dollar/macro factor.** ~70% of the tagged universe is USD-legged or risk-appetite-driven; F-017's example (risk-on long + safe-haven short = one 8% macro bet) applies to this roster *as designed*. v1 mitigant: static-group caps (Pass 3); E3 deferred (§4.4) — this hole is documented as accepted until v2.
3. **London-window concentration.** M2, T4, and (partially) M1's session end all transact in the same 90 minutes; a single bad London open (flash event, feed outage — F-025) hits three children simultaneously. Mitigant: per-correlation-window exposure note to Pass 3; otherwise accepted.
4. **Evidence-era concentration.** Half the roster's evidence base (RSI2, ORB, Donchian-20) is pre-2010 published material with documented decay; the E1 core (TSMOM, vol clustering) carries the roster. If TSMOM is in a secular drought, the roster's expected return is approximately the M-family's marginal viability — i.e., near zero. This is the honest base case for bad years.
5. **Gap-risk concentration.** All weekend/close gap exposure (F-011) lives in one sleeve (trend); the k× budgeting must therefore bind at the *sleeve* level, not just per-position, or the sleeve quietly accumulates the account's entire tail (flagged to Pass 3).

---

## §7 Board debate log (objections that changed content)

1. **Auditor vs T2's existence (§2.2):** objection — T2 doubles trend-factor exposure while presenting as a second strategy. Change forced: Stage-R part (iii) residual-value test added for T2 and generalized to all future children (§6.3). Resolved; signed off.
2. **Day Trader vs M1/M4 viability (§3.1e, §3.4e):** objection — worked tick math shows both children dead on STD-tier pricing; shipping them without saying so violates the charter. Change forced: explicit "RAW-tier conditional" labels; M4 gated behind measured open-spread decay curves; M1's adverse-selection measurement made a G2 exit criterion. Resolved.
3. **Strategist vs T3 short-leg removal (§2.3e, F-020):** objection — long-only cross-sectional momentum is "half a strategy" and loses the hedged character. Counter (Quant/Auditor): swap math makes retail CFD short legs structurally negative-carry; hedging that costs more than its variance reduction is not hedging. **Decision matrix:** (A) full long/short: cleaner factor, swap drag hypothesis −30…−100% of short-book edge, gap+margin heavier; (B) long-top-k+flat: keeps most of the documented premium (momentum asymmetry, §2.3d P2), halves structural cost; recommended default **B**, shorts re-enabled per-instrument on positive swap-inclusive backtest. Carried 8–2.
4. **Strategist vs TC-2 displacing T3 (§5.1):** objection — cross-sectional and time-series momentum are distinct premia; dropping T3 narrows the factor base. Resolution: T3 not dropped — demoted to 4th build priority in-family with Stage-R unchanged; TC-2 first. Vote 9–1.
5. **Architect vs cross-instrument features (§4.4, §5.4):** objection — E3 and MC-2 were heading toward specifying signals the feature store cannot compute; "spec now, architect later" is how checkbox findings (pass1 §4 T1) happen. Change forced: both DEFERRED with named re-entry conditions instead of specced. Unanimous.
6. **Quant vs session-regime cell explosion (§4.3):** objection to the broad form of session-conditional regimes (20 cells × per-instrument sample starvation). Change forced: adoption narrowed to baseline normalization only. Unanimous with scope restriction.
7. **Strategist vs 3-bar regime dwell (§4.1):** objection — dwell delays trend activation. Change forced: dwell binds published/arbitration labels only; trend children may consume raw inputs in their own filters. Signed off.
8. **Auditor vs M2's narrative risk (§3.2):** objection — stop-hunt folklore invites motivated analysis. Change forced: null-model comparison (random-time excursion fades) added to M2's Stage-R as a mandatory control. Resolved.
9. **Swing Trader vs T4/M1 news symmetry (F-021):** observation that M1 had a news blackout and T4 — *more* news-exposed — did not. Change forced: T4 blackout rule (§2.4e-1). Unanimous.
10. **Networking seat, standing note:** every session anchor in this pass (Tokyo, London, New York, Berlin) is a claim on the Pass-4 calendar service (F-006); none of these children may go live before it exists. Recorded as a hard sequencing dependency.

---

## §8 Summary table

Thesis strength = evidence grade of the *construction as specced* (premise grade in parentheses where they differ). Cost sensitivity: order of death as costs rise (1 = dies first). Priority: board build-order vote within the whole roster.

| Child | Thesis strength | Named loser | Cost sensitivity (death order) | Viability (hyp., RAW / STD) | Falsification one-liner | Build priority |
|---|---|---|---|---|---|---|
| **T1** Donchian D1 | E1 | disposition-effect sellers; mandate-bound hedgers/rebalancers | 8 (dies last) | 1.4–1.7 / 1.1–1.3 | Stage-R: pooled OOS PF ≥ 1.3, plateau on (channel, stop) grid; Stage-L: CUSUM 99%×2 blocks | **1** |
| **TC-2** TSMOM ballast | E1 | as T1, mandate flows dominant | 9 (cost-immune) | ≫2 both tiers | 15-yr swap-inclusive OOS PF ≥ 1.2 across ≥ 8 instruments; whipsaw share < 40% | **2** |
| **M2** London stop-hunt fade | E2 premise (E3 construction) | stopped-out Asian positioners; open-momentum chasers | 4 | 1.2–1.6 / 1.0–1.3 | Stage-R incl. random-time null model + spike-window plateau; edge must live in first 90 min | **3** |
| **M1** Asian BB fade | E2 (E3 construction) | impatient Tokyo-hours flow paying for immediacy | 1 (dies first, ties M4) | 0.9–1.6 / 0.5–1.0 (**RAW-only child**) | F-012 fills: OOS viability ≥ 1.5; G2 measured adverse selection replaces the 50% hypothesis before G3 | **4** |
| **T2** EMA pullback | E1 carrier + E3 overlay | counter-trend faders; shaken-out pullback sellers | 6 | 0.8–1.6 / 0.6–1.2 | Ablation: candle trigger must add ≥ 0.05R vs naive touch entry; residual value vs T1 required | **5** |
| **T4** Vol-expansion straddle | E1 premise (E3 construction) | Asian range holders (stop fuel); late chasers | 3 | 0.9–1.4 / 0.6–1.0 | Double-fill tax ≤ 30% of gross edge (F-021); P1 expansion-conditional test; slippage-creep telemetry falsifier | **6** |
| **M4** Index open-drive fade | E2 premise | overnight overreactors; forced MOO/margin flow | 1–2 (open-window spreads) | conditional on entry delay; ≥ 1.2 only after minute ~10 (hyp.) | Expectancy-vs-entry-delay curve must match prediction; build gated on measured open-spread decay | **7** (after measurement) |
| **M3** RSI(2) reverter | E1-decayed origin, E3 transfer | short-horizon chasers; forced liquidations | 5 | 0.9–1.4 / 0.7–1.1 | ≥ 3 instruments from ≥ 2 corr-groups OOS-positive or dead; range-filter ablation | **8** (doubles as gate-control specimen) |
| **T3** Momentum rotation | E1 class, E2 transfer (n≈20 universe) | fixed-weight rebalancers; bottom-fishers | 7 (swap-driven, not spread) | n/a per-trade; swap-dominated | Long-only swap-inclusive OOS PF ≥ 1.2 + rank-IC > 0 in 60% of quarters; no fallback variant | **9** |
| **TC-1** Carry-aligned T1 | E1×E2 interaction | as T1 + risk-off carry unwinders | 8 (as T1) | as T1 or better | Comparative: must beat T1 by ≥ 0.05R on shared subset AND rejected subset must underperform | **10** (after T1 validates) |
| **MC-1** Round-number fade | E2 premise | flow paying through round-level clusters | 1–2 (M1-class) | ≈ M1 (**RAW-only**) | Placebo: non-round pseudo-levels must be materially worse, else premise failed transfer | **11** |
| **MC-2** Pair divergence | E2/E3 | single-leg momentum chasers | 2 | not computable yet | Architecture-blocked (portfolio-scope feature nodes, Pass 5); full doc owed at unblock | **DEFER** |

**Regime-engine verdicts:** E0 confidence/dwell/hysteresis — MANDATORY (F-018 resolved) · E1 EWMA vol — ADOPT · E2 session baselines — ADOPT narrow / REJECT broad · E3 risk-on/off — DEFER (named re-entry: Pass-5 portfolio nodes) · E4 HMM — REJECT.

**New constraints exported to later passes:** Pass 3 — sleeve-level gap-risk budgeting (§6.4-5), factor sub-budgets and residual-value rule (§6.3), T3/TC-2 swap-inclusive sizing with F-034 re-clamp. Pass 4 — calendar service is a hard predecessor of every session child (§7-10); OCO grace window is a measured parameter (F-021). Pass 5 — portfolio-scope feature nodes are the named unblock for E3+MC-2. Pass 7 — viability-threshold calibration (F-003) now has per-child worked hypotheses to calibrate against; fill-simulation spec (F-012) is load-bearing for M1/MC-1's existence; M3 variants feed the gate-control suite; T4/M4 cost waterfalls mandatory in G1 reports.

— End of Pass 2. Dossiers T1–T4, M1–M4 §2–§3; candidates §5; register citations inline. Every performance number above is a hypothesis until G1 says otherwise.
