# Titan Control GUI — Phase 1 Design (Live Cockpit)

**Date:** 2026-07-12
**Status:** Approved design — Phase 1 scope
**Branch:** feat/trade-mgmt-pipeline (GUI work will get its own branch)

## Problem

Titan has no GUI. Monitoring and control of the live bot happen entirely through
Telegram (`/status`, `/pause`, `/close`, `/closeall`, `/panic`, `/confirm`) and by
tailing logs. This is serviceable but low-bandwidth: no live positions table, no
equity view, no at-a-glance health, and control is text-command-only. We want a
visual cockpit that is also the foundation for a future phone app and a possibly
monetized hosted version.

## Hard constraints (non-negotiable)

- **Only one process may bind the ZMQ ports** (`32768/32769/32770`). The GUI must
  NOT open its own bridge. It either reads the WAL SQLite state DBs or is fed by the
  controller, and it issues control actions *through* the controller.
- **The trading loop is sacred.** Nothing in the GUI layer may crash, block, or slow
  the bridge poll loop. The GUI is strictly optional infrastructure — if it fails to
  start or throws, the bot keeps trading.
- **No new trade-path logic.** Control actions reuse the existing, audited
  `_dispatch_mgmt_command` / pause-resume / panic / confirm paths. The GUI is a new
  *transport* over existing behavior, not a second implementation of it.
- Tests use stdlib `unittest` (no pytest), per repo convention.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Primary purpose | Unified (Live + Research), **phased — Live first** |
| Control channel | **Embedded** web server in the controller process |
| Deployment target | Local now; **must also work against a VPS**; future mobile + hosted SaaS |
| Auth (MVP) | **Token + TLS-ready** (`TITAN_GUI_TOKEN`, bind localhost by default) |
| Live v1 scope | Positions+PnL table, Signals/trade feed, Bridge/bot health, Control buttons (all four) |
| Frontend stack | **React SPA** (Vite + React + Tailwind + shadcn/ui + Recharts) |

**Guiding principle:** the HTTP + WebSocket API is the *product boundary*. Every
future frontend (phone browser, React Native app, hosted multi-user SaaS) reuses the
same API. Frontends are swappable; the API is the asset.

## Architecture

The controller process gains a **second async task** — a FastAPI app served by a
programmatically-run `uvicorn.Server`, scheduled onto the *same* event loop as the
bridge loop via `asyncio.create_task(server.serve())`. No new process, no new ZMQ
binding, no threads. API handlers `await`/call into the controller exactly as the
loop does.

```
system_controller  (one process, one asyncio loop)
 ├─ bridge poll loop        (existing, untouched)
 ├─ uvicorn/FastAPI task    (NEW)  →  REST + WebSocket on :8770
 │     ├─ GET  /api/state      snapshot: positions, health, equity, paused flag
 │     ├─ GET  /api/history    recent closed trades (from state DB)
 │     ├─ POST /api/command    pause | resume | close | closeall | panic
 │     └─ WS   /ws             pushes events + heartbeat state deltas
 └─ serves frontend/dist/     (static React build)

Browser (desktop or phone)  ──HTTP/WS──>  controller
Future: React Native app / hosted SaaS  ── same /api ──>
```

## Backend modules (new, isolated under `src/ops/web/`)

Each module has one job, a clear interface, and is unit-testable with a fake
controller / in-memory DB.

- **`server.py`** — builds the FastAPI app + `uvicorn.Config`/`Server`, wires routes,
  mounts `frontend/dist/` as static, exposes `start(controller)` returning the
  asyncio task. Owns HTTP transport only.
- **`state_view.py`** — read-only. Assembles the `/api/state` JSON snapshot from
  `StateManager` (active_orders), the last HEARTBEAT (equity/positions/balance), and
  the controller pause flag. No control logic. Pure function of inputs → dict.
- **`commands.py`** — maps `POST /api/command` payloads to the **existing** controller
  methods (`_dispatch_mgmt_command` and the pause/resume/panic handlers). Validates
  the command name, enforces the confirm-gate on destructive actions. Adds nothing to
  the trade path.
- **`events.py`** — a tiny in-process async pub/sub (`asyncio.Queue` per WS client, or
  a broadcast helper). The existing `telemetry.notify_*` hooks *also* publish here, so
  the WS feed and Telegram surface the same events from a single source.
- **`auth.py`** — bearer-token dependency for REST; token check for WS
  (query param or subprotocol). Reads `TITAN_GUI_TOKEN` from env.

### Controller integration points (minimal, additive)

- On startup, after the bridge is up, call `web.server.start(self)` and keep the
  returned task. Wrap in try/except: on failure log a warning and continue trading.
- `telemetry.notify_*` gains a side-call to `events.publish(...)`. Existing Telegram
  behavior is unchanged.
- Expose read accessors the `state_view` needs (last heartbeat dict, paused flag) —
  read-only properties, no behavior change.

## API contract (Phase 1)

- `GET /api/state` → `{ health: {bridge_connected, last_heartbeat_age_s, paused,
  last_error}, account: {balance, equity}, positions: [ {ticket, symbol, side, lots,
  entry, sl, tp, pnl, phase, grade, strategy} ] }`
- `GET /api/history?limit=N` → recent rows from `trade_history`.
- `POST /api/command` → `{ command: "pause|resume|close|closeall|panic",
  ticket?: int, confirm?: true }`. Destructive commands (`closeall`, `panic`) require
  `confirm: true` or return `409 needs-confirm`. Returns the action outcome; final
  state is verified from subsequent HEARTBEAT (never from a REQ reply — per the ZMQ
  gotcha in CLAUDE.md).
- `WS /ws` → server pushes `{type:"state", ...snapshot}` on each HEARTBEAT and
  `{type:"event", kind:"signal|execution|close|management", ...}` per activity.

## Frontend (`frontend/`)

Vite + React + Tailwind + shadcn/ui; Recharts for equity/PnL. Built to
`frontend/dist/`, served by the controller (same origin → no CORS in the localhost/
reverse-proxy model). One responsive page, four panels matching Live v1:

1. **Health strip** — bridge ●, last-heartbeat age, balance/equity, PAUSED badge,
   last error.
2. **Positions + PnL table** — live open positions, per-row PnL, SL/TP, phase, grade.
3. **Signals / trade feed** — recent signals (with grade) + executions/closes/partials.
4. **Control buttons** — Pause/Resume, Close (row-level), CloseAll, Panic. CloseAll
   and Panic open a confirm dialog that sends `confirm: true`.

Research and Journal tabs are scaffolded (route + empty shell) but out of scope for
Phase 1. Data via a small typed API client + a WS hook with auto-reconnect and a
GET-`/api/state`-on-timer fallback when the socket is down. Design/implementation will
lean on the `ui-ux-pro-max` skill (layout/components) and `dataviz` skill (equity/PnL
charts) during the build.

## Real-time data flow

On connect the client GETs `/api/state` (full snapshot), then subscribes to `/ws`.
The controller pushes a **state delta on each HEARTBEAT** and an **event message** per
signal/execution/close/management action. No polling in the happy path. If the WS
drops, the client re-GETs `/api/state` on a timer until it reconnects.

## Security

- `TITAN_GUI_TOKEN` in `.env` (add to `.env.example`). Every `/api/*` and `/ws`
  requires `Authorization: Bearer <token>` (WS via query param or subprotocol).
- Binds `127.0.0.1` by default. `TITAN_GUI_BIND` env allows `0.0.0.0` for a VPS,
  documented as **only** valid behind a Caddy/nginx TLS reverse proxy + firewall.
- Destructive commands require an explicit `confirm: true` (mirrors Telegram
  `/confirm`).
- The GUI never writes to the trade DBs directly; it only issues commands the
  controller executes.

## Error handling & isolation guarantee

- The web task is wrapped so a handler exception returns HTTP 5xx and is logged —
  the bridge loop is never affected.
- If uvicorn cannot start (e.g., port busy), the controller logs a warning and
  **keeps trading**. GUI is optional.
- Reads are WAL-safe concurrent reads. No direct writes to trade state from the GUI.
- **Verify-during-implementation risk:** the main loop must yield often enough for the
  web task to stay responsive. It is already `async`; confirm no blocking work starves
  the server task, and measure WS latency under load during the verify step.

## Testing (stdlib `unittest`, isolated from the trading loop)

- `state_view` builds the correct snapshot shape from a seeded in-memory DB + a fake
  heartbeat.
- `commands` routes each command name to the right controller method on a mock
  controller; unknown commands rejected.
- `auth` rejects missing/invalid tokens on REST and WS.
- Confirm-gate: `closeall`/`panic` without `confirm:true` returns needs-confirm and
  does NOT call the controller.
- The bridge/loop are not exercised by these tests — the web layer is tested against a
  fake controller only.

## Phasing

- **Phase 1 (this spec):** Live cockpit end-to-end — backend API + WS + auth + React
  Live tab.
- **Phase 2:** Journal/history tab — rich explorer over `trade_history`.
- **Phase 3:** Research cockpit — launch/compare backtests & sweeps (POC runners,
  history CSVs, equity curves).
- **Phase 4:** Native mobile app + hosted multi-user (accounts/roles) — the
  monetization path — reusing the same API.

## Out of scope for Phase 1

- Research/backtest UI, Journal explorer, native mobile app, multi-user accounts,
  charting beyond a basic equity/PnL view, editing config from the UI, historical
  analytics dashboards.
