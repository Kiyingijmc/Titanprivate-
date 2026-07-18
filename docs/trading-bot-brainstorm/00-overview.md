# Trading Bot — Deep Brainstorm (Master Overview)

This document set is the full in-depth brainstorm of the 11-topic roadmap. Read this file first.

## The system in one paragraph

Two strategy **families** (Trend Following, Session Mean Reversion) contain small, single-purpose **child models**. Children never compute anything — they declare feature requirements to a **central feature store** that computes each unique feature exactly once per candle, incrementally, driven by events. Signals are emitted as **intents** onto a signal bus, pass through a **risk manager** (enforced in every mode), get routed by the **mode router** (auto / hybrid / manual per child), are shaped by an **execution intelligence layer** (market vs pending, lifecycle-managed), and finally translated by a **broker adapter** that auto-discovered everything about the connected broker and its instruments. A **learning loop** feeds fills, slippage, and cost data back into execution defaults and strategy viability gates. GUI and Telegram share one confirmation/state store.

## Stack recommendation (decided here, argued in file 04)

- **Language:** Python 3.12+ (MetaTrader5 lib, pandas/numpy/numba, python-telegram-bot, FastAPI). Node.js is viable for the interface services if preferred, but the trading core stays Python.
- **Broker connectivity v1:** MetaTrader 5 (widest broker coverage + richest symbol metadata for auto-discovery). Adapter interface designed so an OANDA/cTrader/ccxt adapter can be added later without touching strategy code.
- **State:** in-memory hot state → SQLite (event log + warm state) → Parquet (cold history). Redis only if/when interfaces run on separate machines.
- **Process model v1:** single asyncio process with internal modules; interfaces (FastAPI + Telegram service) as a second process talking to the core over a local API/queue.

## File map

| File | Topics |
|---|---|
| 00-overview.md | This file — vision, stack, layer map |
| 01-strategies.md | Topic 1: family contracts, regime engine, full child roster with rules |
| 02-risk-and-signal-lifecycle.md | Topics 2–3: sizing, circuit breakers, signal schema, three modes |
| 03-execution-and-broker.md | Topics 4–5: order intelligence, broker auto-discovery, multi-asset model |
| 04-architecture-config.md | Topics 6–7: feature store, DAG, caching, processes, config system |
| 05-interfaces-validation-ops-learning.md | Topics 8–11: GUI, Telegram, validation gates, operations, learning loop |

## Layer stack (canonical)

```
Market data ingest (1 stream per instrument)
        │  candle-close / tick events
        ▼
Central feature store  ── feature DAG, incremental updates, tiered cache
        │  feature-changed events
        ▼
Strategy families ─ Trend Following ─┬─ child models (subscribe to features)
                  └ Mean Reversion ──┘
        │  signal intents (+ frozen feature snapshot)
        ▼
Signal bus (normalized events, persisted)
        ▼
Risk manager  ── sizing, limits, circuit breakers  [runs in ALL modes]
        ▼
Mode router   ── auto | hybrid | manual, per child, hot-switchable
        ▼
Execution intelligence ── market vs stop vs limit, lifecycle, OCO, spread gates
        ▼
Broker adapter ── discovery, canonical→broker translation, execution profiling
        ▼
Broker (MT5 v1)

Side rails: Config service (validated, hot-reload) · State/event store ·
GUI + Telegram (shared confirmation store) · Learning loop (feeds back upward)
```

## Build order (pragmatic)

1. Feature store + data ingest + backtester harness (they share one engine).
2. One trend child + one reversion child, full-auto mode only, demo account.
3. Risk manager + signal bus persistence.
4. Broker discovery + adapter hardening + execution intelligence.
5. Mode router + Telegram confirmations, then GUI.
6. Validation pipeline formalized; learning loop; ops hardening.
7. Grow the child roster.

## Non-negotiable principles

1. Risk layer executes in every mode — manual confirmation never bypasses sizing or limits.
2. No forex assumptions in core code — ticks and ATR multiples, never pips.
3. Same feature engine for live and backtest — zero drift.
4. Strategies emit intent, never order types.
5. A signal without a persisted feature snapshot ("why") is a bug.
6. Real money only after a child passes every gate in file 05.
