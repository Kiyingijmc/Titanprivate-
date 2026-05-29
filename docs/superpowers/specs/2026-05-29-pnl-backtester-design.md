# Spec: Signal-Edge PnL Backtester (R-multiples)

- **Date:** 2026-05-29
- **Status:** Approved (design); pending implementation plan
- **Scope:** one focused feature — extend the existing backtester to measure strategy edge

## Goal

Today `tests/backtest/backtest_engine.py` only *counts signals* — it cannot tell us whether any strategy has a profitable edge. This adds outcome simulation so the backtester reports **win rate, expectancy, drawdown, and profit factor in R-multiples** (R = risk per trade). R-multiples are asset- and spread-agnostic, which sidesteps the fact that broker tick specs aren't available offline.

It answers one question: **do these signals have an edge?**

### Out of scope (deliberately, layer later)
- Spread, commission, dollar PnL (would need cached broker specs).
- The Fibonacci ratchet / partial closes (`trade_manager`).
- Multiple symbols in a single run.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Fidelity | Signal-edge in R-multiples (no ratchet, no costs) |
| Limit fills | Fill only if a later bar's range touches `entry`, within a TTL |
| TTL (per live cleanup) | `Silver*` → 12 M5 bars (1h); others → 24 bars (2h) |
| Market fills | At the next bar's open (no look-ahead) |
| Same-bar SL **and** TP | SL first (pessimistic) |
| R per trade | `(exit−entry)/|entry−sl|`, signed by direction → SL = −1.0R, TP = +RR |
| Concurrency | One open trade per symbol at a time (mirrors `ExposureManager`) |
| Eligibility | Keep the existing HTF-bias filter (only live-eligible signals count) |

## Architecture

Approach **A**: extend `tests/backtest/backtest_engine.py`; keep data-loading and signal-collection as they are. Add:

1. **`resolve_trade(signal, future_bars)` — a pure function** (the heart; fully unit-testable, no I/O).
2. A **simulation loop** in `Backtester.run()` that converts collected signals into resolved trades under the one-open-per-symbol rule.
3. **`_print_results()`** upgraded to a metrics report; optional `--trades-out` CSV of every trade.

No new dependencies, no new package.

### `resolve_trade` contract

**Input** `signal`: `{strat, dir ("BUY"/"SELL"), cmd ("MARKET"/"LIMIT"), entry, sl, tp, ttl_bars}`
**Input** `future_bars`: ordered bars strictly *after* the signal bar (each has `open/high/low/close`).
**Output**: `{filled: bool, outcome: "TP"|"SL"|"EXPIRED"|"OPEN_AT_END"|"INVALID", r: float, fill_offset: int|None, exit_offset: int}` where offsets are indices into `future_bars` (used to compute the absolute "busy until" bar).

**Algorithm**
1. `risk = abs(entry − sl)`; if `risk == 0` → `INVALID`, `filled=False` (skip).
2. `is_long = dir == "BUY"`.
3. **Fill:**
   - `MARKET`: fill at `future_bars[0].open`, `fill_offset = 0`. (No bars → `OPEN_AT_END`.)
   - `LIMIT`: find first offset `k < ttl_bars` where `low ≤ entry ≤ high`. Found → `fill_offset = k`. Not found within TTL → `EXPIRED`, `exit_offset = min(ttl_bars, len)-1`.
4. **Resolve SL/TP** scanning from `fill_offset` onward (inclusive of the fill bar):
   - long: `sl_hit = low ≤ sl`, `tp_hit = high ≥ tp`; short: `sl_hit = high ≥ sl`, `tp_hit = low ≤ tp`.
   - Same bar both hit → **SL** (`r = −1.0`). Only SL → `r = −1.0`. Only TP → `r = +|tp−entry|/risk`.
   - First hit sets `exit_offset` and outcome. No hit by the end → `OPEN_AT_END` (`r = 0`, excluded from win/loss).

### Concurrency loop (in `run()`)
Signals are already collected in time order with their bar index. Maintain `busy_until` (absolute bar index). For each signal: if `signal.bar_idx ≤ busy_until`, skip (a trade/limit is live — matches live exposure blocking a duplicate-symbol position). Otherwise resolve and record, then:
- `TP`/`SL`/`OPEN_AT_END`/`EXPIRED` → occupy the symbol: `busy_until = signal.bar_idx + exit_offset` (a resting limit blocks the symbol until it fills-and-exits or its TTL expires).
- `INVALID` (risk = 0, never placed) → dropped, does **not** occupy the symbol.

### Metrics report (console + optional CSV)
Per strategy **and** combined: trades, wins, losses, win rate, **expectancy (avg R)**, total R, **profit factor** (Σ win R / |Σ loss R|), **max drawdown in R** (peak-to-trough of the running R equity curve), avg win R, avg loss R, max losing streak, and limit **fill rate** (filled vs `EXPIRED`). `OPEN_AT_END` counted separately and excluded from win/loss stats.

## Usage
```
.venv/bin/python tests/backtest/backtest_engine.py            # default: discovers test_data.csv
.venv/bin/python tests/backtest/backtest_engine.py --csv data/history/EURUSD_M5.csv --shift -7 --trades-out /tmp/trades.csv
```
Single symbol per run (run again for others; CSVs come from `scripts/export_history.py`).

## Testing (TDD, no live data)
Unit tests in `tests/unit/test_backtest_resolver.py` over synthetic bars:
- market long → TP; market long → SL; short mirror (TP and SL)
- limit never touched within TTL → `EXPIRED`
- limit touched → then TP
- same-bar SL+TP → SL (pessimistic)
- open-at-end → `OPEN_AT_END`, excluded
- `risk == 0` → `INVALID`
- metrics aggregation: expectancy, profit factor, and max-drawdown-in-R on a known trade list
- concurrency: two overlapping signals → the second is skipped while the first is open

## Risks / assumptions
- **OHLC intrabar order is unknown**, so same-bar SL+TP defaults to SL (conservative; real results are ≥ reported on those bars).
- Backtest candles come from the CSV (broker M5 bars), not the live tick-built candles — so this measures the *signal logic*, and live results may differ slightly due to tick-built candle drift.
- R-multiples assume the strategy's own SL/TP define risk; no spread means real fills are slightly worse. This is a *relative* edge measure, not a dollar projection.
