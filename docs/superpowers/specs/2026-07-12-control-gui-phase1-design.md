# Titan Control GUI — Phase 1 Design (Live Cockpit + Settings)

**Date:** 2026-07-12
**Status:** SUPERSEDED by `2026-07-14-control-gui-phase1-v15-design.md` — written
pre-v15 kernel (Plans 01–06 added the EventBus/tape, strategy registry + promote-gate,
Intent Arbiter, and run-cards, which invalidate this doc's event-feed and
strategy-toggle designs). Kept for history; do not implement from this doc.
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
| Primary purpose | Unified (Live + Settings + Research), **phased** |
| Control channel | **Embedded** web server in the controller process |
| Deployment target | Local now; **must also work against a VPS**; future mobile + hosted SaaS |
| Auth (MVP) | **Token + TLS-ready** (`TITAN_GUI_TOKEN`, bind localhost by default) |
| Live v1 scope | Positions+PnL table, Signals/trade feed, Bridge/bot health, Control buttons (all four) |
| Frontend stack | **React SPA** (Vite + React + Tailwind + shadcn/ui + Recharts) |
| Settings/config | **Layered** (defaults → GUI overrides); **safe-subset applies live, rest on restart**. In **Phase 1**. |
| Backtests | GUI **spawns runners as subprocesses** (never in the live loop), streams results. **Phase 2**. |

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
 │     ├─ GET   /api/state      snapshot: positions, health, equity, paused flag
 │     ├─ GET   /api/history    recent closed trades (from state DB)
 │     ├─ POST  /api/command    pause | resume | close | closeall | panic
 │     ├─ GET   /api/settings   merged effective config (default vs override, tier)
 │     ├─ PATCH /api/settings   edit one key (live-apply if safe-subset, else restart)
 │     └─ WS    /ws             pushes events + heartbeat state deltas
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
- **`settings.py`** — the layered-config store (see "Settings / config" below):
  loads defaults + overrides, validates edits, writes overrides, and for safe-subset
  keys calls the controller's `apply_runtime_setting`. One job: config read/merge/write.

### Controller integration points (minimal, additive)

- On startup, after the bridge is up, call `web.server.start(self)` and keep the
  returned task. Wrap in try/except: on failure log a warning and continue trading.
- `telemetry.notify_*` gains a side-call to `events.publish(...)`. Existing Telegram
  behavior is unchanged.
- Expose read accessors the `state_view` needs (last heartbeat dict, paused flag) —
  read-only properties, no behavior change.
- Add `apply_runtime_setting(dotted_key, value)` — updates the in-memory `self.config`
  and pushes the value to the owning object (e.g. `grader.min_grade`, risk %, a
  strategy's `enabled` flag). Only ever called for whitelisted safe-subset keys.

## Settings / config (Phase 1)

**Layered config.** Loading becomes: read checked-in `config/config.yaml` (defaults),
then deep-merge `config/overrides.yaml` (GUI-written, git-ignored) on top; overrides
win key-by-key, missing overrides fall back to defaults. `_load_config` in the
controller is extended to do this merge. (Do **not** reuse `config/dev_override.yaml`
— CLAUDE.md marks it dead code; introduce a fresh `overrides.yaml`.)

**Two apply tiers, enforced by an explicit whitelist in code:**

- **Safe-subset → applies live immediately** (a hardcoded allowlist of dotted keys):
  `signal_grading.enabled`, `signal_grading.min_grade`,
  `risk.trade.risk_per_trade_pct`, `risk.account.max_daily_drawdown_pct`,
  `risk.account.max_global_exposure_pct`, `strategies.<name>.enabled`,
  `trade_management.runner.enabled`, `trade_management.runner.tighten_on_giveback`
  (+ its `giveback_frac` / `tight_trail_frac`). Editing one writes the override AND
  calls `apply_runtime_setting`.
- **Restart-tier → override saved, effective next start:** everything else — ports,
  host, timezone, paths, `mt5_path`, per-strategy `pairs` / `timeframe` / `stop_atr` /
  `windows` / `risk_reward`. The API response flags these as `restart_required: true`
  and the UI shows a "restart to apply" badge.

**Validation before write.** `settings.py` bounds/enum-checks every edit (e.g.
`min_grade ∈ {A++,A+,A,B,C}`, `0 < risk_per_trade_pct ≤ hard cap`, booleans are
booleans). Invalid edits are rejected with `422` and never written — a bad override
must never be able to wedge startup.

**Anything not in the safe-subset allowlist can never be live-mutated**, even by a
crafted request — the allowlist is the security/safety boundary, checked server-side.

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
- `GET /api/settings` → merged effective config, each field tagged
  `{value, source: "default|override", tier: "live|restart"}`.
- `PATCH /api/settings` → `{ key: "signal_grading.min_grade", value: "A" }`. Validates;
  writes override; if key is in the safe-subset, applies live and returns
  `{applied: "live"}`, else `{applied: "on_restart", restart_required: true}`. Invalid →
  `422`. Non-whitelisted live-mutation attempts are treated as restart-tier, never live.

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

A **Settings tab is in Phase 1**: renders the merged effective config grouped by
section (system/risk/grading/trade-management/strategies), each field showing its
source (default vs override) and tier. Safe-subset fields are editable with inline
save (live-apply, toast confirm); restart-tier fields are editable but show a
"restart to apply" badge; validation errors surface inline from the `422` body.

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
- **Config merge:** overrides deep-merge over defaults; a missing override key falls
  back to the default value.
- **Safe-subset whitelist:** a safe-subset key edit calls `apply_runtime_setting`; a
  restart-tier key edit writes the override but does NOT call it (returns
  `restart_required`); a non-whitelisted key can never trigger a live mutation.
- **Validation:** out-of-range / bad-enum edits return `422` and write nothing.
- The bridge/loop are not exercised by these tests — the web layer is tested against a
  fake controller only.

## Phasing

- **Phase 1 (this spec):** Live cockpit + Settings — backend API + WS + auth + React
  Live tab + layered config with safe-subset live-apply + Settings tab.
- **Phase 2:** Backtest runner + results — GUI spawns runners as subprocesses, streams
  progress, and explores results (trades CSVs, reports, equity curves). Journal/history
  explorer over `trade_history` folds in here.
- **Phase 3:** Native mobile app + hosted multi-user (accounts/roles) — the
  monetization path — reusing the same API.

## Phase 2 preview — Backtest runner (design intent, not built yet)

Recorded now so Phase 1 boundaries are drawn with it in mind; full spec at Phase 2.

- **Execution model (decided):** the GUI backend spawns each run as a **separate OS
  subprocess** (`.venv/bin/python` against `tests/backtest/backtest_engine.py` or a
  `scripts/poc_*.py` / `sweep_*.py` runner). It never runs backtest work inside the
  live controller loop — the isolation guarantee holds for backtests too. Runs are
  tracked by id; stdout/progress stream to the client over WS; artifacts (trades CSV,
  report) are parsed for the results view.
- **Configurable per run:** strategy, symbols, timeframe, date range, and key strategy
  params (stop_atr, risk_reward, windows), plus output location.
- **Results view:** table of runs (R/trade, winrate, PF, max drawdown), trade-by-trade
  drill-down, equity curve (`dataviz`), and side-by-side variant comparison.

## Out of scope for Phase 1

- Backtest/research UI and Journal explorer (Phase 2), native mobile app, multi-user
  accounts (Phase 3), charting beyond a basic equity/PnL view, editing restart-tier
  config semantics beyond save-and-flag, historical analytics dashboards.
