# Spec: Validation Harness (Phase 1 of the edge-improvement program)

- **Date:** 2026-05-29
- **Status:** Approved (design); pending spec review → plan
- **Context:** Research ([../../research/2026-05-29-ict-edge-research.md](../../research/2026-05-29-ict-edge-research.md)) showed the edge is net-negative and that the #1 risk in fixing it is **overfitting**. Before changing any strategy logic (Phases 3–4) or sizing (Phase 2), we need measurements we can trust. This phase builds that.

## Goal
Extend the existing backtester ([tests/backtest/backtest_engine.py](../../../tests/backtest/backtest_engine.py)) so results are **realistic, statistically honest, and validated out-of-sample**, and fast enough to run on ~6 months of data. Keep R-multiples as the base metric; add dollars, costs, a train/test split, and significance — without changing any strategy's signals.

## Decisions (locked)
| Decision | Choice |
|---|---|
| History depth | Pull **up to ~50k M5 bars** per instrument (accept fewer if FBS caps it) |
| Performance | Optimize the backtest hot loop; **must be behavior-preserving** (identical trades on a fixed CSV) |
| Dollar PnL | Reuse `RiskManager.calculate_lot_size` for sizing; PnL = R × risk$ − commission − spread cost |
| Specs source | Pull tick_value/tick_size/vol per instrument via the bridge **once**, cache to `data/specs.json` |
| Spread | Per-instrument **config table** of typical spreads (points); commission from `static_commission_usd` |
| Walk-forward v1 | Chronological **train 70% / test 30%**, metrics reported separately (extensible to rolling) |
| Significance | Trade count, **Wilson CI** on win rate, expectancy std-error, **`n<30 → insufficient`** flag |
| Base metric | R-multiples remain; dollars + costs reported alongside |

## Components

### 1. Performance pass (behavior-preserving) — the enabler
Profiling target: the per-candle loop recomputes HTF bias and copies a 400-row window every M5 bar. Optimizations, all signal-preserving:
- **Cache HTF bias per H1 bar.** Bias only changes when a new H1 candle closes; compute once per H1 timestamp and reuse for all M5 candles within it (was: `BiasEngine` rebuilt every M5 bar — the dominant cost).
- Avoid per-iteration DataFrame copies where a view/`numpy` slice suffices.
- **Acceptance gate:** running before/after on a fixed CSV (e.g. the bundled `test_data.csv`) must produce an **identical trades CSV** (same signals, same outcomes). A test asserts this equivalence.

### 2. Spec cache — `scripts/cache_specs.py`
Reuses the bridge: pings, then `GET_HISTORY` per instrument, captures `tv/ts/vm/vs`, writes `data/specs.json` (`{symbol: {tick_value, tick_size, vol_min, vol_step}}`). Run manually when the bridge is up; the backtester reads the JSON offline.

### 3. Cost model (pure, unit-tested)
`apply_costs(trade, specs, spread_points, commission_per_lot, risk_dollars)` → dollar PnL:
- `lots` = `RiskManager.calculate_lot_size(entry, sl, symbol, ...)` using cached specs (broker-spec sizing — already correct/asset-agnostic).
- `gross$` = `R × risk_dollars`.
- `commission$` = `lots × commission_per_lot`; `spread$` = `spread_points × tick_value × lots`.
- `net$` = `gross$ − commission$ − spread$`. Report gross R, net $, and total cost drag.
- Spread table lives in a small module constant (FX majors ~0.1–1.5 pip, crosses higher, XAU/US30/BTC/Brent per typical FBS values); overridable via CLI.

### 4. Walk-forward split (pure, unit-tested)
`split_trades(trades, train_frac=0.7)` partitions chronologically by `bar_idx`; the report shows **TRAIN vs TEST** metric blocks per strategy and combined, so we can see if an edge holds out-of-sample.

### 5. Significance (pure, unit-tested)
`win_rate_ci(wins, n)` → Wilson 95% interval; expectancy std-error = `stdev(R)/sqrt(n)`; report flags `n<30` as **insufficient**. Surfaced in the report per strategy.

### 6. Backtester CLI additions
`--equity` (default 10000), `--risk-pct` (default 1.0), `--split` (default 0.7), `--specs data/specs.json`, `--no-costs`. The report gains $-PnL, cost drag, train/test split, and significance columns.

## Data flow
`cache_specs.py` (bridge) → `data/specs.json`; export ~50k bars → CSVs; backtester loads CSV + specs → SMC (optimized) → simulate → split train/test → per-trade dollarize+cost → metrics + significance → report (R + $).

## Testing (TDD)
- `apply_costs`: known trade → exact net$/commission/spread.
- `split_trades`: ordering + boundary (70/30, empty, all-train).
- `win_rate_ci`: known counts → known Wilson bounds; `n<30` flag.
- **Perf equivalence:** trades CSV identical before/after the optimization on `test_data.csv`.
- Full existing suite stays green.

## Out of scope (later phases)
- Any change to strategy *signals* (Phases 3–4). The perf pass must NOT alter them.
- Fractional-Kelly sizing, correlation caps, disable-losers logic (Phase 2).
- Rolling walk-forward / parameter optimization (future; v1 is a single split).

## Risks / caveats
- **Spread values are assumptions** (not tick-level historical spread); costs are indicative, directionally correct (results get worse, as expected).
- **FBS may not serve 50k M5 bars** via `CopyRates`; harness must handle variable lengths.
- Even with realism + OOS validation, **ICT may still show no durable edge** — this phase is built to reveal that honestly, not to manufacture an edge.
