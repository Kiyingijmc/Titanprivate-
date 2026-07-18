# 01 — Strategy Families & Child Models

## 1. The family contract

A family is not a strategy. It is a base class + shared services + a compatibility contract.

```python
class ChildStrategy(ABC):
    id: str                     # "trend.donchian_v1"
    family: str                 # "trend" | "meanrev"
    tags_required: set[str]     # instrument tags this child can trade
    timeframe: str              # evaluation timeframe

    def required_features(self) -> list[FeatureKey]: ...
    def pre_filter(self, ctx) -> bool:        # microsecond gate: session? regime? enabled?
    def generate_signal(self, ctx) -> Intent | None: ...
    def manage_position(self, pos, ctx) -> PositionAction | None: ...  # trail/exit logic
    def risk_profile(self) -> RiskProfile:    # default stop logic, max concurrent, urgency class
    def invalidation(self, intent, ctx) -> bool:  # is a resting intent's thesis dead?
```

Family-level shared services (computed once, in the feature store, used by all children):
- **Trend family:** regime state, higher-timeframe bias, ADX/ATR context.
- **MeanRev family:** session clock, session range statistics, regime state (they need it to know when NOT to trade).

## 2. The regime engine (shared, critical)

The single most important shared component. Output per instrument per timeframe:

```
regime ∈ {TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE_CHAOS, DEAD}
confidence ∈ [0,1]
```

Inputs (all cheap, all incremental):
- **ADX(14):** >25 trending, <18 ranging (hysteresis band 18–25 to prevent flapping).
- **ATR percentile:** current ATR vs rolling 90-day distribution. >90th pct → VOLATILE_CHAOS (news/shock — most children stand down). <10th pct → DEAD (spread eats any edge — stand down).
- **Efficiency ratio (Kaufman):** |net move| / Σ|bar moves| over N bars. High = clean trend, low = chop. Confirms ADX.
- **Direction:** EMA(50) vs EMA(200) relationship + slope sign of EMA(50).

Rules of engagement:
- Trend children require TRENDING_* with confidence ≥ threshold (per-child config).
- MeanRev children require RANGING, and are hard-blocked in VOLATILE_CHAOS.
- Regime flip while a pending order rests → invalidation() fires → order cancelled (see file 03).
- Regime transitions are events on the bus → GUI displays them, learning loop logs edge-by-regime.

## 3. Child roster v1 — Trend Following family

Start parameters are starting points for backtesting, not truths. All distances in ATR multiples.

### T1 · Donchian breakout (the workhorse)
- **Timeframe:** D1. **Instruments:** majors + gold + 1–2 indices (tag: `vol_tier<=high`).
- **Entry:** close breaks the 20-day Donchian high (long) / low (short). Intent type: BREAKOUT (stop order at channel edge, see file 03).
- **Filter:** regime TRENDING in breakout direction OR efficiency ratio > 0.35; skip if ATR percentile > 90.
- **Initial stop:** 2.0 × ATR(20). **Exit:** opposite 10-day channel touch (classic Turtle-style asymmetry) or trailing 2.5 × ATR chandelier — backtest both.
- **Expected profile:** win rate 35–45%, payoff ratio > 1.8, few trades (quality over count).

### T2 · EMA pullback continuation
- **Timeframe:** H4. **Entry:** in an established trend (EMA50>EMA200, ADX>25), price pulls back to touch EMA(21) zone, then prints a rejection candle (close back in trend direction). Intent: IMMEDIATE on candle close.
- **Stop:** 1.5 × ATR(14) beyond pullback extreme. **TP:** none fixed — trail 2 × ATR after 1R in profit; move to breakeven at +1R.
- **Why it exists:** enters trends T1 missed, at better prices, with tighter stops.

### T3 · Higher-timeframe momentum rotation
- **Timeframe:** D1/W1, evaluated weekly. **Universe:** all tagged instruments.
- **Logic:** rank instruments by 12-week risk-adjusted momentum (return / ATR); hold small long exposure in top decile, short bottom decile, subject to per-class caps. This is the "CTA in miniature" child — slow, diversified, the portfolio ballast.
- **Rebalance:** weekly, Sunday session open. Intent: IMMEDIATE, urgency low.

### T4 · Volatility expansion breakout (session-scoped bridge child)
- **Timeframe:** M30/H1. **Logic:** after an unusually narrow Asian range (< 40th percentile of 60-day Asian ranges), straddle the range with buy-stop above / sell-stop below at London open. OCO: first fill cancels the twin. Unfilled orders expire 3h after London open.
- **Stop:** opposite side of the range. **TP:** 1.5–2.0 × range height, or trail.
- Note: sits philosophically between families; lives in Trend because it bets on expansion.

## 4. Child roster v1 — Session Mean Reversion family

### M1 · Asian-session Bollinger fade
- **Timeframe:** M15. **Instruments:** EURUSD, USDJPY, EURGBP (low-vol majors only, tag `session=fx_24_5`, `spread_ratio=low`).
- **Window:** Asian session only (precomputed calendar), regime = RANGING.
- **Entry:** price touches BB(20, 2.2) band → LIMIT intent at the band (passive fill, earns spread). **Stop:** 1.2 × ATR(14) beyond band. **TP:** BB midline.
- **Hard rules:** max 2 attempts per session per instrument; disabled 60 min before/after red-calendar news; auto-disabled if measured spread > 25% of average TP distance (viability gate, file 03).

### M2 · London-open reversal (stop-hunt fade)
- **Timeframe:** M15/M30. **Logic:** in the first 90 min of London, price spikes beyond the Asian range high/low by 0.3–0.8 × ATR then closes back inside the range → fade it. LIMIT or IMMEDIATE intent depending on re-entry speed.
- **Stop:** beyond the spike extreme + buffer. **TP1:** Asian range midpoint (take half, stop→BE). **TP2:** opposite side of the range.
- **Why it works (thesis):** London liquidity runs Asian-session stops before choosing direction; the failed breakout is the tell. Thesis must be re-verified in backtest per instrument.

### M3 · RSI-extreme reverter with range filter
- **Timeframe:** H1. **Entry:** RSI(2) < 5 (long) / > 95 (short) while regime = RANGING and price within the established range's outer third. IMMEDIATE intent.
- **Stop:** 1.5 × ATR. **Exit:** RSI(2) crosses 50, or time-stop of 12 bars (reversion that hasn't happened isn't happening).
- RSI(2) (Connors-style) is deliberately extreme-and-fast; RSI(14) reverts too slowly to fade.

### M4 · Index open-drive fade (multi-asset child)
- **Timeframe:** M5/M15. **Instruments:** tag `asset_class=index_cfd` only.
- **Logic:** cash-open gap/drive that extends > 1.2 × 14-day average opening move without pullback → fade toward VWAP / prior close within the first hour. Strict time-stop; flat by 2h after open.
- Demonstrates the multi-asset promise: the child exists only because capability tags unlock index instruments.

## 5. Signal conflict resolution

Same instrument, conflicting intents:
1. **Netting rule:** opposing intents within a configurable window (default 5 min) cancel each other; neither trades; conflict event logged for analysis (frequent conflicts = misconfigured roster).
2. **Family priority in regime terms:** regime TRENDING → trend children outrank meanrev on the same instrument; RANGING → reverse. The regime engine is the arbiter.
3. **Position stacking:** same-direction intents from different children may stack up to per-instrument exposure cap (file 02); each child manages its own tranche's exit.

## 6. Growth discipline

- A new child = a hypothesis document (thesis, features, rules, expected profile) BEFORE code.
- One child graduates through the validation gates (file 05) at a time.
- Children are versioned (`trend.donchian_v2`); versions never edited in place — old version retired, new version re-validated. Performance history stays attached to the exact version that produced it.
