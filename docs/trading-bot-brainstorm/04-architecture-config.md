# 04 — Core Architecture, Performance & Configuration

## PART A — Architecture & the compute-once engine (Topic 6)

### A1. Feature store

- **Key:** `(instrument, timeframe, feature, params_hash)` → e.g. `EURUSD:H4:EMA:{n:20}`.
- **Registration:** at startup (and on config hot-reload) collect `required_features()` from every enabled child + family services, deduplicate, build the DAG.
- **DAG:** features declare dependencies (`BB(20,2.2)` → `SMA(20)`, `STDDEV(20)`; `ADX` → `ATR` internals; regime → ADX+ATR-pct+ER+EMAs). Topologically sorted once; on a candle-close event only the affected subgraph updates, in order.
- **Incremental math:** every v1 indicator has O(1) update from (prev_state, new_candle): EMA, Wilder-smoothed ATR/RSI/ADX, rolling sum/mean/var (Welford) for SMA/BB/stddev, monotonic deque for Donchian/rolling-max ATR-percentile. Running state persisted per key → restart = load state + replay missed candles, seconds not minutes.
- **Snapshot API:** `store.snapshot(keys) -> dict` — cheap dict copy used to freeze signal 'why' data (file 02).

### A2. Event-driven core

- One MT5 stream per instrument (adapter multiplexes); tick events roll into candle-close events per timeframe.
- Candle close → DAG subgraph update → `FEATURE_CHANGED` events → only children subscribed to changed keys on that timeframe wake → `pre_filter()` gate (session? regime? enabled? viability?) exits ~90% of wakes in microseconds → survivors run `generate_signal()`.
- Between events the process is idle. An H4 child is invoked 6 times a day, not 17,000.
- Honest framing: on H1+ timeframes this is over-engineering for live trading — the real payoff is **backtesting** (millions of candles through the same engine; incremental + vectorized warmup turns hours into minutes) and marginal-cost-zero child growth.

### A3. Tiered state

| Tier | Contents | Store |
|---|---|---|
| Hot | current feature values, DAG state, open positions, working orders, pending confirmations | in-process memory |
| Warm | recent candles, feature history for GUI charts, confirmation store, config | SQLite (WAL mode) |
| Event log | every signal/order/fill/config/breaker transition, append-only | SQLite table (source of truth; memory is a replayable projection) |
| Cold | full candle history per instrument/timeframe | Parquet files, partitioned by instrument/year |

Redis enters only when GUI/Telegram move to a different machine than the core. Don't pay the ops tax early.

### A4. Process model

- **Process 1 — core:** asyncio: adapter stream → feature store → children → bus → risk → router → execution. Single-writer to the event log.
- **Process 2 — interface service:** FastAPI (REST + websocket for the GUI) + python-telegram-bot; reads warm state, writes commands/confirmations to a command table the core polls/subscribes to. Core survives interface crashes and vice versa.
- **Process 3 — backtest/research CLI:** same feature engine + children + risk + a simulated adapter fed from Parquet, with the cost model from execution profiles. One codebase, three entrypoints.
- Watchdog (systemd) restarts core on crash; recovery = replay event log → reconcile positions/orders against broker truth (broker wins; diffs alerted).

### A5. Performance extras

- numba/vectorized batch mode for backtest warmup of indicator state.
- Session/news calendars precomputed weekly into lookup tables (file 01 children just index).
- Feature-store metrics (updates/sec, cache hits, subgraph sizes) exposed to the GUI — observability of the compute-once claim itself.

---

## PART B — Configuration system (Topic 7)

### B1. Layered config (later overrides earlier)

```
defaults.yaml            # shipped, sane, safe
broker/<broker_id>.yaml  # auto-generated overlay from discovery + user tweaks per broker
user.yaml                # the user's intent: children on/off, modes, risk overrides
runtime (DB)             # GUI/Telegram changes; wins; persisted; exportable back to YAML
```

### B2. Shape (excerpt)

```yaml
risk:
  per_trade_pct: 0.5        # hard-capped at 1.0 by validation, not by trust
  daily_loss_breaker_pct: 2.0
children:
  trend.donchian_v1:
    enabled: true
    mode: auto              # auto | hybrid | manual
    instruments: auto       # auto = tag-driven; or explicit list
    params: { channel: 20, stop_atr: 2.0 }
    hybrid_timeout: { after: 10m, action: execute }
  meanrev.asian_bb_v1:
    mode: hybrid
    hybrid_timeout: { after: 10m, action: skip }
instruments:
  auto_enable: propose      # silent | propose | manual
telegram:
  authorized_ids: [ ... ]   # allowlist, mandatory
  quiet_hours: { from: "23:00", to: "06:00", urgent_only: true }
```

### B3. Validation (a bad config must never execute)

- Pydantic schema: types, ranges, hard caps (risk %, lot ceilings), cross-field rules (TP beyond stop, timeout ≤ validity), existence checks (child ids, instrument tags).
- Rejected config → previous config stays live + diff-style error report to GUI/Telegram. Never partial-apply.
- Every accepted change = event log row (who, when, what changed) → config history is auditable and revertible.

### B4. Hot-reload classes

| Class | Examples | Behavior |
|---|---|---|
| Live | modes, enable/disable child, risk %, timeouts, notification prefs | applied instantly via config event |
| Next-signal | child params, instrument lists | applied to new signals; working orders keep their contract |
| Restart | timeframes/feature graph changes, adapter choice, process topology | flagged `restart_required` in GUI |
