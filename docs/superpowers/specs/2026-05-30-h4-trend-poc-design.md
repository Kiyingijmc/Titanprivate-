# Spec: H4 Trend-Following Proof-of-Concept

- **Date:** 2026-05-30
- **Status:** Approved (design); pending spec review → plan
- **Context:** All four ICT strategies are net-negative after costs; SilverBullet's apparent edge was a zero-cost artifact of sub-pip (`0.2×ATR`) stops drowned by spread. We pivoted to **evidence-based trend-following** (the most research-supported systematic approach; cost-friendly because trades are infrequent with large, structurally-stopped moves). This PoC is a **gate**: confirm a wide-stop H4 trend system can clear the cost bar *before* investing in the full HTF-trend + LTF-sniper architecture and the D1/M1 data pipeline.

## Goal
On the 11 instruments' existing ~3-month M5 data (resampled to H4), screen whether a simple, low-parameter trend system has a **positive, out-of-sample-consistent edge net of costs**. A clear yes earns the full architecture; a no saves the effort. This is a **screen, not a verdict** (thin sample).

## Decisions (locked)
| Decision | Choice |
|---|---|
| Timeframe | **H4** (resampled from existing M5 CSVs) |
| Entry signal | **Donchian(20) breakout** (one parameter; canonical, robust) |
| Risk (structural) | Stop = **2 × ATR(H4)**; **1R = that stop distance** (wide → spread is a small fraction; the anti-SilverBullet rule) |
| Exits compared | **(a) signal-flip** (exit on opposite Donchian break or stop) and **(b) fixed 3R** target |
| Entry fill | Next H4 bar open after the breakout (no look-ahead) |
| Concurrency | One position per instrument at a time (flip on signal) |
| Costs | **cost-in-R** = `2×spread/stop + commission_R` with typical weekday spreads (confirm live later) |
| Validation | Train/test 70/30, **Wilson** significance, pooled **and** per-instrument |
| Parameters | Fixed a priori (Donchian 20, 2×ATR, 3R) — **no sweeping** (overfit guard) |
| Form | Standalone `scripts/poc_trend_h4.py` reusing the pure harness functions; no controller/strategy plumbing |

## Components
1. **Resample** M5 → H4 OHLC per instrument (pandas `resample('4h')`).
2. **Indicators (pure):** Donchian(20) upper/lower channel (prior-20-bar high/low, excluding current) + ATR(14) on H4.
3. **Signals (pure):** long when close breaks above the channel high, short when below the channel low.
4. **Simulators:**
   - *Fixed-3R:* entry next-bar open, SL = entry ∓ 2·ATR, TP = entry ± 3·(2·ATR); resolve via the existing `resolve_trade` over subsequent H4 bars.
   - *Signal-flip:* custom forward walk from entry — exit at −1R if stop hit first, else at the bar where the opposite Donchian break occurs (R = signed move / risk).
5. **Costs + metrics:** apply `cost-in-R` per trade; then `aggregate_metrics`, `split_trades`, `win_rate_ci` (all existing) for pooled + per-instrument, for **both** exit variants.
6. **Report:** a table comparing signal-flip vs fixed-3R — n, win%, net expectancy (R), total R, PF, max DD (R), train vs test, significance flag — pooled and per-instrument.

## Testing (TDD)
- **Donchian signal (pure):** synthetic bar series → correct long/short/no-break flags at the boundary (break = strictly beyond prior-N extreme; current bar excluded).
- **Signal-flip simulator (pure):** a crafted H4 series → correct trade list, entry/exit offsets, and signed R (incl. stop-hit-first and flip-exit cases).
- **Resample correctness:** a small M5 set → expected H4 OHLC (open=first, high=max, low=min, close=last).
- Reuse already-tested `resolve_trade`, `aggregate_metrics`, `split_trades`, `win_rate_ci`, cost-in-R.

## Out of scope (gated on a positive result)
- Live integration / the strategy-system wiring; M1/M5 "sniper" entry refinement; the D1/M1 data-pipeline + EA changes; multi-year daily validation; parameter optimization. All come **after** the PoC shows an edge.

## Risks / caveats
- **Thin sample:** ~360 H4 bars/instrument → ~10–30 trend trades each. Pooled helps, but per-instrument significance will often be `n<30`. This screens direction/magnitude, it does not prove a durable edge.
- **Typical spreads** (markets closed); the wide structural stops make the result robust to spread size, but confirm live on a weekday.
- **Single ~3-month period**; the full validation on years of daily data is the post-gate step.
- Donchian/ATR/RR values are chosen a priori, not optimized, specifically to avoid the overfitting the research flagged.
