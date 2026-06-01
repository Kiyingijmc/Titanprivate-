# Spec: Titan HTTP Bridge — Phase 1 (Bridge + Broker seam + Data + Execution primitives) — 2026-06-01

Status: approved (brainstorming). Branch: `harden/normalize-price-crash`.

## Why

Titan currently talks to MT5 through a custom **MQL5 EA over three ZMQ sockets** (`src/execution/bridge_zmq.py` ⇄ `mql5_bridge/.../Titan_Gateway.mq5`). That design has cost us repeatedly:

- **WSL-IP churn:** the EA *connects* from Windows to the WSL IP (`InpIP`), which changes on every WSL restart — hours lost re-pointing it.
- **EA wedging:** a large `CopyRates` (200k M5 bars) blocked the EA's `OnTimer`, silently killing the bridge with no recovery.
- **Limited API:** the EA supports **market + limit only — no stop orders**; history is capped/awkward.

The MOS project (`~/mos/bridge`, same machine, same author) solves all three with a proven **HTTP/REST bridge**: a FastAPI server on Windows using the `MetaTrader5` Python package, with WSL as the *client*. This spec is **Phase 1** of migrating Titan onto that pattern (the user chose a **full live-bridge migration**, decomposed into phases).

### Phase decomposition (this spec = Phase 1)

| Phase | Scope | Status |
|---|---|---|
| **1 (this spec)** | Titan-owned HTTP bridge (copied from MOS, full endpoints) + abstract `Broker` seam + **data export** (history/specs) + **execution primitives** proven in isolation | **now** |
| 2 | Wire the broker into `system_controller` (poll loop, reconciliation, state, telemetry) | later |
| 3 | Cutover live to HTTP; retire `bridge_zmq.py` + the EA; delete dead ZMQ paths | later |

Phase 1 is **additive and does not touch the live ZMQ loop** — `system_controller.py`, `bridge_zmq.py`, and the EA keep working in parallel. Phase 1's only *live* side effects are (a) read-only data pulls and (b) an **opt-in** demo-order integration test.

## Goals / non-goals

**Goals**
- Stand up a Titan-owned HTTP MT5 bridge on Windows (port **8766**, bearer-token auth).
- Define an abstract `Broker` protocol (the seam) + an httpx implementation (`mt5_http.py`).
- Migrate **history export** and **specs export** to the broker — reliably pulling whatever M5 history FBS retains (the original blocker).
- Implement + isolation-test **execution primitives** (market/pending incl. **stops**, modify, close, partial-close, cancel).

**Non-goals (Phase 1)**
- Changing `system_controller.py` / the live loop (Phase 2).
- Removing the ZMQ bridge or the EA (Phase 3).
- Streaming ticks (HTTP is request/response; Titan acts on M5 close, so polling fits — designed in Phase 2).

## Architecture

```
WSL2 (Linux) — Titan                          Windows host — Titan bridge (NEW)
┌─────────────────────────────┐   HTTP/REST   ┌──────────────────────────────┐
│ scripts/export_history.py   │  :8766        │ bridge/app/main.py (FastAPI)  │
│ scripts/cache_specs.py      │  Bearer token │   → MT5Client (MetaTrader5)   │
│   → Broker (mt5_http.py)    │ ────────────► │   → circuit breaker + timeouts│
│ src/execution/broker/       │ ◄──JSON────── │   → MT5 terminal (FBS-Demo)   │
│   base.py     (protocol)    │               └──────────────────────────────┘
│   mt5_http.py (impl, httpx) │
│   errors.py   (typed)       │
└─────────────────────────────┘
```

### New components

**`bridge/` (Windows-side, copied near-verbatim from `~/mos/bridge`, rebranded):**
- `app/main.py` — FastAPI app; endpoints: `/health`, `/connection`, `/account`, `/symbols`, `/symbol/{symbol}`, `/candles/{symbol}/{tf}`, `/candles/{symbol}/{tf}/range`, `/tick/{symbol}`, `/positions`, `/positions/{ticket}`, `/orders`, `/order/market`, `/order/pending`, `PUT /position/{ticket}`, `/position/{ticket}/close`, `/position/{ticket}/partial`, `DELETE /order/{ticket}`. All token-gated; binds `0.0.0.0:8766`.
- `app/mt5_client.py` — wraps `MetaTrader5`; each call via `asyncio.to_thread` + `asyncio.wait_for`.
- `app/circuit.py` — 3-strike breaker with `shutdown()+initialize()` recovery.
- `app/models.py` — Pydantic models.
- `app/settings.py` — `bridge_host=0.0.0.0`, `bridge_port=8766`, token from `config/.env`.
- `run_bridge.py`, `requirements.txt`, `config/.env.example`.
- **Required extension to MOS's model:** `SymbolInfo` must add **`tick_value`** and **`tick_size`** (`mt5.symbol_info().trade_tick_value` / `.trade_tick_size`) — Titan's `risk_manager` sizes from these and MOS's `SymbolInfo` omits them.

**`src/execution/broker/` (Linux-side):**
- `base.py` — abstract `Broker` (ABC/Protocol):
  - reads: `get_account()`, `get_symbol_info(symbol)`, `get_candles(symbol, tf, count)`, `get_candles_range(symbol, tf, from_dt, to_dt)`, `get_positions()`, `get_orders()`, `get_tick(symbol)`.
  - writes: `place_market(symbol, side, volume, sl=None, tp=None, ...)`, `place_pending(symbol, type, price, volume, sl=None, tp=None, ...)` (limit **and stop**), `modify_position(ticket, sl=None, tp=None)`, `close_position(ticket)`, `partial_close(ticket, volume)`, `cancel_order(ticket)`.
- `mt5_http.py` — `MT5HttpBroker(Broker)` using `httpx`; the only module coupled to the bridge wire format. Ported from MOS's `mt5_bridge.py`.
- `errors.py` — `BrokerError`, `BrokerAuthError`, `BrokerNotFoundError`, `BrokerConnectionError`.

### Scripts
- `scripts/export_history.py` — **reworked** to use the broker (chunked range pulls, below). It's a standalone tool, not part of the live ZMQ loop, so reworking it in place is safe.
- `scripts/cache_specs.py` — **reworked** to use `broker.get_symbol_info` → `data/specs.json`.
- `scripts/check_bridge_http.py` — **new** HTTP health check (`GET /health`). The existing ZMQ `scripts/check_bridge.py` is **left intact** (the live ZMQ loop still needs it until Phase 3).

## Data flow (read path)

**History export — chunked range (beats the depth wall + the count cap):**
```
for symbol in SYMS:
    out = []
    cursor = now
    floor = now - MAX_LOOKBACK            # a-priori cap, e.g. 3 years
    while cursor > floor:
        win = broker.get_candles_range(symbol, "M5", cursor - CHUNK, cursor)   # CHUNK e.g. 30d
        if not win:                        # FBS has no more history -> natural floor
            break
        out = win + out
        cursor -= CHUNK
    dedupe/sort by time; write data/history/{symbol}_M5.csv  (datetime,open,high,low,close)
```
Small windows → no giant single request → no wedge; a stalled call returns `504` (timeout) or `503` (breaker), caught per-symbol. The CSV is **byte-compatible** with today's format (`datetime,open,high,low,close`, UTC `%Y-%m-%d %H:%M:%S`) so `poc_mtf_pb2.py` and the backtester read it unchanged.

**Specs export:** `broker.get_symbol_info(symbol)` → `{tick_value, tick_size, vol_min, vol_step}` per symbol in `data/specs.json` (the shape `risk_manager` already consumes). `volume_min/volume_step` → `vol_min/vol_step`.

## Execution primitives (proven in isolation)

`mt5_http.py` implements the write methods mapped to bridge endpoints; **writes never auto-retry**. Translation (per MOS): bridge `OrderType` IntEnum ↔ Titan side/pending StrEnum; `sl/tp == 0.0` sentinel ↔ `None` (exact-equality check). Stop orders (`BUY_STOP`/`SELL_STOP`) are now expressible.

**Not wired into `system_controller` in Phase 1** — execution is exercised only by tests.

## Networking, config & auth

- **Direction:** WSL is the client; bridge is the server on fixed port 8766 → **no WSL IP to chase.**
- **URL resolution in `mt5_http.py`:** (1) `TITAN_BRIDGE_URL` env override wins; (2) else auto-detect — **mirrored mode → `http://127.0.0.1:8766`**, NAT mode → default-route gateway (`ip route show default` → `172.x.x.1:8766`). Mirrored-vs-NAT decided by whether `eth0` carries a `172.x` NAT address.
- **Auth:** bearer token on every request; `TITAN_BRIDGE_TOKEN` (Linux `.env`) must match the bridge's `config/.env`. No silent localhost/token fallback — raise if missing.
- **Secrets:** tokens git-ignored; `.env.example` templates both sides.
- **Coexistence with MOS:** Titan `:8766` + token vs MOS `:8765` + token; both may run for reads. No concurrent live *writes* from both (Phase 3 concern).
- **Startup (documented in CLAUDE.md):** (1) MT5 up + logged into FBS-Demo; (2) `py -3.11 bridge/run_bridge.py`; (3) verify `curl -H "Authorization: Bearer $TITAN_BRIDGE_TOKEN" http://127.0.0.1:8766/health` → `{"status":"ok","mt5_connected":true}`; (4) run the scripts.

## Error handling

- **Bridge:** per-call `asyncio.wait_for` timeout → `504`; 3-strike circuit breaker → `503` while open, with `shutdown()+initialize()` recovery; `/health` never calls MT5 (cached breaker view) so liveness stays fast under a wedge.
- **Client:** `401→BrokerAuthError`, `404→BrokerNotFoundError`, `503/504→BrokerConnectionError`, httpx timeouts/connect → `BrokerConnectionError`, response `ValidationError → BrokerError`. **Reads retry once** (250 ms backoff); **writes never auto-retry**.
- **Export scripts:** per-symbol failure logs and continues; empty range window = natural history floor, not an error.

## Testing

- **Bridge surface** (`bridge/tests/`, MT5 mocked — runnable on Linux): auth required; `/candles` + `/candles/range` shapes; **`/symbol` includes `tick_value`/`tick_size`**; `504` on simulated timeout; `503` when breaker open; `/health` works with MT5 down.
- **Linux client** (`mt5_http.py`, mock HTTP via `respx`): URL resolution (env / mirrored / NAT); bearer header; every status→error mapping; read-retry-once; write-no-retry; Candle/SymbolInfo/Position/Order ↔ Titan-type translation incl. `0.0`↔`None` and IntEnum↔StrEnum.
- **Export scripts** (stdlib `unittest`, fake broker): chunked range loop (incl. empty-window floor + dedupe), CSV byte-compatibility with `poc_mtf_pb2.py`, `specs.json` shape.
- **Opt-in live integration** (`TITAN_BRIDGE_LIVE_TEST=1`, never in the auto suite; requires the bridge + demo terminal): `/health`; export one symbol and diff CSV format; **execution round-trip** — open 0.01 lot market → modify SL → partial-close → close, verified via `/positions`. Places real **demo** orders, hence opt-in.
- **Verify gate:** full `tests/unit` green; then a manual end-to-end (bridge up → `export_history.py` one symbol → `poc_mtf_pb2.py` on fresh data).

## Dependencies (approved)

- **`httpx`** — runtime (async HTTP client). **`respx`** — test-only (mock HTTP). Both already used by MOS on this machine (proven versions). Add to `requirements.txt` (+ a test/dev marker for `respx`).

## Risks

- **Two bridges, one terminal:** reads are safe; avoid concurrent live writes from MOS + Titan (Phase 3). Phase 1 writes only via the opt-in demo test.
- **FBS M5 depth unknown:** the chunked range pull discovers the real floor (empty window). If FBS only retains ~3 months, that's the answer — and we'll then revisit timeframe choice (separate decision), but the bridge itself is still the right foundation.
- **Mirrored-mode loopback:** `127.0.0.1` reachability from Windows→WSL relies on mirrored mode (now configured). The `TITAN_BRIDGE_URL` override is the escape hatch if auto-detect misjudges.
- **Windows runtime:** requires Python 3.11 + `MetaTrader5` + FastAPI/uvicorn on Windows (MOS already runs this, so proven).

## Out of scope / sequence after Phase 1

Phase 2 (controller migration) → Phase 3 (cutover + decommission ZMQ/EA). The reworked MTF-PB v2 research and its data needs are unaffected — Phase 1 simply makes the data pull reliable.
