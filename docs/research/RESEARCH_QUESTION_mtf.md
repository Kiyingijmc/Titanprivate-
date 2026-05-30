# Deep-research brief — MTF trend + OTE-pullback system (re-launch verbatim via the `deep-research` skill)

Research the evidence base and best practices for a multi-timeframe, trend-aligned, pullback-entry intraday trading system (for FX, gold, indices, crypto via MetaTrader 5), to inform designing one. The concept: a top-down "low-frequency but precise" system that (1) sets directional bias on 4H, confirmed on 1H; (2) requires a 15-minute trend in that same direction; (3) confirms a setup on the 5-minute chart using an ICT Optimal-Trade-Entry / Fibonacci-retracement-style pullback (a retracement INTO the trend, not a breakout); (4) executes a precise entry on the 1- or 2-minute chart; and (5) ONLY ever trades in the direction of both the higher-timeframe trend and the 4H bias. It is explicitly NOT session- or time-of-day-bound. Critically, it must keep stops STRUCTURAL (based on 15m/1H swing structure or ATR), never tiny 1-minute stops, so the per-trade edge stays larger than spread+commission (a prior tight-stop scalping attempt died because sub-pip stops were drowned by spread).

Separate QUANTITATIVELY-SUPPORTED findings from trading folklore. Cover:
(1) Multi-timeframe/top-down confluence — does aligning HTF trend/bias with LTF entries improve risk-adjusted outcomes? Timeframe-combination best practices; overfitting risk of stacking many MTF conditions.
(2) Trend-pullback entries vs breakouts — quantitative support for buying retracements (MA pullback, Fib 0.5-0.79/OTE, structure retest) in the HTF-trend direction; optimal retracement depth; pullback vs breakout performance.
(3) Robust trend/bias definition per timeframe (market-structure HH/HL, MA slope/stacking, ADX, Donchian, time-series momentum) and requiring MTF agreement.
(4) Cost-vs-edge for precise intraday entries — minimum per-trade expectancy to beat spread+commission; how "precise entry + structural (wide) stop" changes the math; realistic win-rate/RR/frequency for intraday trend-pullback systems and their failure modes.
(5) Stop/target/trade management for MTF trend systems — structural stop placement, partials vs trailing vs fixed RR, break-even; what preserves expectancy.
(6) ICT OTE specifically — what it prescribes; any independent support for retracement-into-trend beyond ICT folklore.

Conclude with: (a) which design elements are supported vs speculative, (b) biggest risks (MTF overfitting; costs; multi-timeframe look-ahead bias in backtests), (c) a prioritized, evidence-aware design recommendation. Flag ICT/SMC claims lacking independent evidence.
