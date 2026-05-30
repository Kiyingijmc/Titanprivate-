# Spec: MTF Trend-Pullback PoC ("MTF-PB") — 2026-05-30

Status: approved (brainstorming). Branch: `harden/normalize-price-crash`.
Supersedes nothing; this is the first proof-of-concept for our own (non-ICT) strategy.

## Purpose

Build the **simplest viable** multi-timeframe, trend-aligned, pullback-entry system and
**validate whether it has a net-of-cost edge** on the existing offline harness — *before*
writing any live or management code. This is a screening PoC, not a live strategy.

It is the direct response to the project's verified findings: every ICT strategy and a short
trend system are net-negative after costs (`data/history/VALIDATED_REPORT.md`), and the only
defensible idea left standing is *"enter on a pullback in the direction of the higher-TF trend,
with structural (wide) stops"* (`docs/research/2026-05-30-mtf-synthesis-interim.md`).

## Hard rules (inherited, non-negotiable)

- **Structural stops only.** Stop = `1.0 × ATR(1H)`. Never sub-pip/tight — tight stops die on
  spread (the SilverBullet lesson).
- **Validate net-of-cost in R** AND **out-of-sample** (train/test) AND **significance** (Wilson
  CI; flag `n<30`). A frictionless R result means nothing.
- **No parameter sweeping.** All parameters are a-priori, committed below *before* running, and
  documented. Overfitting is the #1 verified risk.
- **No look-ahead.** HTF bias from **closed** 4H/1H bars only; fib/pivot from past bars only;
  entry at the **next** bar open after a confirmation close.
- ICT specifics (the exact 0.705 level, stacked MTF confluence) are folklore; the edge, if any,
  comes from the **trend filter + cost-robust structure**, not from ICT lore.

## Data reality (constraints that shaped the design)

- **M5 is the finest granularity available**: 11 instruments × ~20k bars ≈ **3 months** each.
- **No M1 data** and exporting it is not viable (EA caps history at ~20k bars ≈ ~2 weeks of M1).
  Therefore the **"1-2m precise entry" is out of scope for validation** — it becomes a live-only
  execution refinement layered onto a *validated* M5 edge later.
- 4H/1H/15m are **resampled from M5** (the harness/`poc_trend_h4.py` already does this).
- 3 months × a 2-timeframe gate ⇒ **sparse samples**. Expect `n<30` per instrument; mitigated by
  pooling within asset class (see Validation).

## The strategy (one rule set; short is the mirror of long)

All timeframes resampled from M5. All HTF reads use **closed bars only**.

| Layer | Rule (long; short = mirror) | A-priori parameter |
|---|---|---|
| **4H bias** | 4H close > 4H 50-EMA → bullish | MA length = **50 EMA** |
| **1H confirm** | 1H close > 1H 50-EMA, must agree with 4H | MA length = **50 EMA** |
| **5m pullback zone** | price retraces into **0.5–0.705** of the most recent 5m impulse leg | pivot lookback = **5 bars**; fib band fixed **[0.5, 0.705]** |
| **5m entry trigger** | a 5m candle **closes back in the trend direction** after tagging the zone → **MARKET** at next-bar open. *Never a resting limit* (limits get wicked / expire — the OTE failure mode). | — |
| **Structural stop** | entry − **1.0 × ATR(1H)** (long); entry + 1.0×ATR(1H) (short) | k_stop = **1.0** |
| **Exit (two models, reported side-by-side)** | (a) fixed **2R** target; (b) **half at 1R → stop to break-even → trail remainder by 2.0×ATR(1H)** | trail k = **2.0** |

Trade only longs when 4H & 1H both bullish; only shorts when both bearish; else stand aside.
**Not session/time-bound.** One open position per symbol at a time.

**Total parameter budget (committed a-priori, never swept):** MA length 50, pivot lookback 5,
fib band [0.5, 0.705], stop k 1.0, trail k 2.0.

## Architecture

One new script: `scripts/poc_mtf_pb.py`, mirroring `scripts/poc_trend_h4.py`'s shape.

**Reused from the harness** (`tests/backtest/backtest_engine.py`): `simulate_signals`,
`resolve_trade`, `aggregate_metrics`, `split_trades`, `win_rate_ci`.
**Reused from `poc_trend_h4.py`**: `resample` (M5→HTF), `atr_series`, `net_r_after_costs`,
`_net`, `SPREAD` map + `data/specs.json` loading, the per-instrument report pattern.

**New pure functions (TDD-first, each independently testable):**

- `resample_tf(m5_df, rule)` — generalise `resample_h4` to '1h'/'4h'/'15min' (closed bars).
- `ma_bias(htf_df, ma_len)` → series of BULLISH/BEARISH/NEUTRAL per closed HTF bar.
- `mtf_bias_at(ts, bias_4h, bias_1h)` → combined bias for a 5m timestamp, reading only the
  **last closed** 4H and 1H bars at/under `ts` (cache per closed HTF bar — extends the
  backtester's H1-bias-cache pattern). No look-ahead.
- `last_impulse_leg(m5_window, pivot_lk)` → (leg_low, leg_high) of the most recent 5m swing leg
  using a fixed-lookback pivot/fractal, from **past bars only**.
- `in_fib_zone(price, leg, bias)` → bool, price within [0.5, 0.705] retrace of the leg.
- `confirmed_entry(m5_window, bias, leg)` → did the just-closed 5m bar tag the zone *and* close
  back in the trend direction? Returns the entry signal dict or None.
- `simulate_partial_trail(signals, bars, atr1h, trail_k)` → custom exit loop (like
  `simulate_flip`): half at 1R + BE + ATR-trail; returns a blended R per trade.

Fixed-2R path builds `resolve_trade`-style signal dicts (`tp = entry ± 2·risk`) and goes
**straight through `simulate_signals`** — no new exit code. Only partial/trail needs the custom loop.

Costs applied via `net_r_after_costs` on the full stop distance (documented approximation for the
partial/trail blend — one entry, dominant exit).

## Validation protocol (the go/no-go gate)

Every reported number is **net of cost** (`net_r = r − 2·spread/stop − commission_R`).

1. **Out-of-sample:** 70/30 chronological train/test (`split_trades`). Edge must survive in TEST.
2. **Significance:** Wilson CI (`win_rate_ci`) on win rate; **flag `n<30` loudly**. Pool within
   asset class to reach `n≥30` where per-instrument is too thin.
3. **Across all asset classes**, grouped (synthesis: trend best on indices/commodities/crypto,
   worst on FX majors): **FX-majors** (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD), **FX-crosses**
   (GBPCAD, GBPJPY), **metals** (XAUUSD), **index** (US30), **crypto** (BTCUSD), **energy**
   (XBRUSD) — plus per-instrument and pooled.
4. **Both exit models** side-by-side. Edge under only one exit = red flag, not green light.

**GO** (proceed to management layers) **only if:** net-of-cost expectancy is **positive in BOTH
train and test**, on a sample **n≥30**, in **at least the asset classes the synthesis predicts**
(indices / commodities / crypto) — not a single lucky instrument.

**NO-GO:** anything less → iterate the (few, a-priori) rules or shelve, exactly as with ICT. If
pooled samples remain too thin to conclude, the honest output is **"inconclusive on this data —
need more history,"** stated plainly, not dressed up as a win.

## Risks designed against

- **Sparse sample** (biggest): pool within asset class; report `n` honestly; treat `n<30` as
  *non-evidence*, not negative evidence.
- **Overfitting:** fixed a-priori params, no sweep, two exits as a robustness cross-check.
- **Look-ahead in MTF:** closed-bar-only bias cache; fib/pivot from past bars; entry at next open.
- **Entry granularity capped at M5:** the 1-2m refinement is explicitly deferred to a live-only
  layer once an M5 edge is validated.

## Out of scope (this PoC)

Live execution, the 1-2m entry, and **all** management layers (order, risk, account, compounding,
bookkeeping, accounting/auditing) and **ML** — those come *only after* a validated edge, in the
user's stated order, ML last.

## Sequence after a validated edge

order management → risk management → account management → compounding → bookkeeping →
accounting/auditing → ML (last).
