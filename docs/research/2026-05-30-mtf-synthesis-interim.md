# Interim evidence synthesis — MTF trend + OTE-pullback system (2026-05-30)

**Status:** the formal cited deep-research workflow FAILED on intermittent model outages (105 agents ran, synthesis couldn't complete). This is my evidence-grounded synthesis from (a) our prior *verified* research (`2026-05-29-ict-edge-research.md`) and (b) established quant literature. Confidence is labeled; **re-run the formal cited workflow** (brief in `RESEARCH_QUESTION_mtf.md`) when the model is stable to replace this.

## What's supported vs folklore (by element of the proposed design)

| Element | Verdict | Notes |
|---|---|---|
| **Trade only WITH a higher-TF trend** (the bias filter) | **Supported** | Trend/momentum is the *most evidenced* market anomaly (TSMOM: Moskowitz–Ooi–Pedersen; AQR). The directional filter is where the real edge, if any, lives. |
| **Multi-timeframe *confluence* (4H+1H+15m all agree)** | **Weak / mostly lore** | Little rigorous evidence that stacking many TF conditions improves *risk-adjusted* returns; each added condition is a degree of freedom → **overfitting risk** (our #1 verified caution). A trend filter helps; *many* stacked filters mostly cut sample + curve-fit. |
| **Pullback/retracement entry vs breakout** | **Plausible, modest** | Pullbacks give a better entry price → higher RR, but lower hit-rate (trend can run without you). No strong evidence either dominates; the value is *execution* (better fills, less whipsaw), not a separate edge. |
| **Fib 0.5–0.79 / OTE 0.705 specifically** | **Folklore** | No independent evidence the *specific* level matters. The generic "enter on a pullback into the trend" is the defensible part; the exact ratio is not. |
| **1-2m "sniper" entry** | **OK only with structural stop** | Precise entry timing is fine; it must NOT shrink the stop. (This is the SilverBullet lesson — sub-pip stops die on spread.) |
| **Structural (15m/1H/ATR) stop** | **Essential / supported** | Keeps spread a small fraction of R. The whole viability of an intraday system hinges on edge-per-trade >> cost. |
| **Not session/time-bound** | **Fine** | Removing the session gate is reasonable; time-of-day filters are mostly lore and add overfit risk. |

## The dominant constraint (verified, hard): cost vs edge
Most retail *intraday* systems lose net of costs. Viability requires per-trade expectancy to clear ~**2× the round-trip cost** comfortably. With **structural stops** (wide), cost-in-R = `2·spread/stop + commission_R` becomes small (e.g. a 40-pip stop vs 1-pip spread ⇒ ~0.05R cost) — so the design's structural-stop rule is exactly what makes an intraday trend-pullback system *possibly* viable. Realistic targets for such systems: **win 35–55%, RR 1.5–3, modest frequency**; let winners run (trend edge is in the tail).

## Evidence-aware design recommendation (a-priori, minimal-parameter)
1. **Bias = ONE simple rule per HTF.** e.g. 4H and 1H trend = price vs a single long MA (or MA slope, or Donchian/structure). Avoid many conditions. Require 4H, 1H, 15m **agreement** (the filter), nothing more elaborate.
2. **Entry = pullback in 5m to a zone** (MA / 0.5–0.705 retrace / prior structure) + a small 1-2m confirmation (micro structure shift or momentum). Precise, but the stop comes from structure.
3. **Stop = structural:** beyond the 15m (or 1H) swing, or ~k×ATR(15m), sized so spread < ~10% of risk. Never 1m-tight.
4. **Management:** partial at ~1R, **trail the remainder** by structure/ATR; break-even after 1R. Avoid a small fixed RR (caps the trend tail).
5. **Validate** net-of-cost in R + **out-of-sample** + significance, across **all asset classes** (trend works best on indices/commodities/crypto, worst on FX majors — test broadly, not just majors).

## Biggest risks (verified)
- **MTF overfitting:** every extra timeframe/condition curve-fits. Keep rules few and a-priori; never sweep to a win.
- **Costs:** mitigated by structural stops — but *measure*, don't assume.
- **Look-ahead bias in MTF backtests:** when computing 4H/1H bias for a 5m/1m entry, use only **closed** HTF bars (the backtester already caches bias per closed HTF bar — extend that pattern to 4H/15m).

## Bottom line
The design's *spine* — **trade with the HTF trend, enter on a pullback, risk structurally** — is the most defensible thing we've considered all project. Its edge (if any) comes from the trend filter + cost-robust structure, NOT from ICT/OTE specifics or stacked MTF confluence. Build the **simplest** version, validate net-of-cost + OOS, and add nothing that isn't earning its keep.
