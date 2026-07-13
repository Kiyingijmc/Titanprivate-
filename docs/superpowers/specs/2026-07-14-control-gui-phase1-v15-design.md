# Titan Control GUI — Phase 1 Design, v15 Edition (Live Cockpit + Settings + Registry)

**Date:** 2026-07-14
**Status:** Approved design — Phase 1 scope
**Supersedes:** `2026-07-12-control-gui-phase1-design.md` (written pre-v15 kernel; its
transport/auth/settings core survives, its event-feed and strategy-toggle designs do not)
**Branch:** feat/trade-mgmt-pipeline (GUI implementation will get its own branch)

## Problem

Titan has no GUI. Monitoring and control happen through Telegram and logs. Since the
original GUI spec (2026-07-12), Plans 01–06 rebuilt the kernel: a typed EventBus with a
golden-tape journal, a manifest-driven strategy registry with a lifecycle FSM and
promote-gate, an Intent Arbiter with blocked-intent telemetry and a drawdown throttle,
and a research lake with run-card'd research runs. The GUI must be the control surface
for THAT system — the original design would have wired a parallel, unjournaled event
path and a config key (`strategies.<name>.enabled`) that no longer drives anything.

## Decisions (this brainstorm, superseding where noted)

| Question | Decision |
|---|---|
| Phase 1 scope | **v15 control plane**: old cockpit + settings, PLUS registry lifecycle panel and arbiter visibility |
| Event feed | **EventBus subscriber** (`bus_bridge`) — NOT telemetry hooks (supersedes old `events.py` design) |
| Registry power | **Telegram parity**: enable/disable freely for live-status; promote requires typed-id confirm; the registry's server-side gate is the enforcement point, GUI adds no bypass |
| New config tiers | `drawdown_throttle.{enabled,trigger_dd_pct,factor}` → **live safe-subset**; `arbiter.*` → **restart-tier** (mid-session pipeline mutation muddies tape attribution) |
| Strategy toggles | `strategies.<name>.enabled` REMOVED from safe-subset — the registry owns lifecycle |
| Hardening | GUI actions journaled to tape; WS auth via first frame (not query param); auth-failure throttling; read-only mode |
| Everything else | Inherited: embedded server, token auth, layered config, confirm-gate commands, React SPA, phasing to mobile/SaaS |

## Hard constraints (non-negotiable, unchanged)

- **Only one process binds the ZMQ ports.** The GUI never opens a bridge socket.
- **The trading loop is sacred.** Web-layer failure = log a warning, keep trading.
- **No new trade-path logic.** Commands reuse `set_system_pause` / `close_*` /
  `trigger_panic` / `cancel_pending_orders`; registry actions reuse
  `enable_strategy` / `disable_strategy` (the promote-gate lives in the registry,
  not in the web layer).
- Tests: stdlib `unittest`, fake controller, no bridge import. Suite baseline 337.

## Architecture

One process, one asyncio loop. FastAPI app served by a programmatic `uvicorn.Server`
as a second task on `:8770` (confirm no collision with the Plan-02 ops health port at
implementation time). Static React build served same-origin from `frontend/dist/`.

```
system_controller (one asyncio loop)
 ├─ bridge poll loop (untouched)
 ├─ EventBus (src/core/bus.py, existing) ── journals to golden tape (existing)
 │     └─ "gui" subscriber (NEW, registered at web start, circuit-broken like any
 │        P02 subscriber)
 │           └─ project(event) → {topic, ts, symbol, ...curated}
 │                ├─ RingBuffer(~200)        → GET /api/events backfill
 │                └─ per-client asyncio.Queue → WS push (drop-on-full, never block)
 └─ uvicorn/FastAPI task (NEW) → REST + WS on :8770, serves frontend/dist/
```

The GUI sees **exactly what the golden tape journals** — IntentEmitted, IntentBlocked
(rule/reason), StrategyActivated/Suspended, SpecsUpdated, executions, GuiActionExecuted
— one source of truth. Telemetry (`notify_*`) is untouched by this design.

## Backend modules (`src/ops/web/`)

| Module | vs 07-12 plan | Job |
|---|---|---|
| `config_layer.py` | unchanged | `deep_merge` + `load_layered_config` (defaults → `config/overrides.yaml`) |
| `auth.py` | updated | fail-closed bearer token (REST header); WS first-frame auth; failure throttling |
| `bus_bridge.py` | **new** (replaces `events.py`) | EventBus subscriber → projection → ring buffer → per-client queues |
| `state_view.py` | extended | `/api/state` snapshot + `arbiter` block (stats, throttle state) + `registry` roster summary |
| `commands.py` | unchanged | pause/resume/close/closeall/panic/cancel, confirm-gate on destructive |
| `registry_view.py` | **new** | registry list + enable/disable/promote mapped onto existing controller/registry methods |
| `settings.py` | updated | safe-subset per the tier decisions below |
| `server.py` | updated | app factory + uvicorn task; wires all of the above; read-only mode |

### Controller integration points (minimal, additive)

- Start the web task in `run()` wrapped in try/except (failure → warn, keep trading).
- Register the `bus_bridge` subscriber on the existing EventBus at web start.
- `_load_config` gains the layered merge (no `overrides.yaml` → byte-identical behavior).
- `apply_runtime_setting(key, value)` — updates in-memory config + pushes to the owning
  object; only ever invoked for whitelisted safe-subset keys.
- Publish `GuiActionExecuted` (new frozen event type in `src/core/events.py`) for every
  GUI mutation — action, args, outcome, client IP — via the existing `_publish` pattern.

## Settings / config

Layered config unchanged from the 07-12 spec: `config/config.yaml` defaults,
`config/overrides.yaml` (git-ignored) deep-merged on top; validation before write
(422 on bad enum/bounds); a bad override must never wedge startup.

**Live safe-subset (exact dotted keys, server-side allowlist = the safety boundary):**
- `signal_grading.enabled`, `signal_grading.min_grade`
- `risk.trade.risk_per_trade_pct`, `risk.account.max_daily_drawdown_pct`,
  `risk.account.max_global_exposure_pct`
- `trade_management.runner.enabled`, `trade_management.runner.tighten_on_giveback`,
  `trade_management.runner.giveback_frac`, `trade_management.runner.tight_trail_frac`
- **NEW:** `drawdown_throttle.enabled`, `drawdown_throttle.trigger_dd_pct`,
  `drawdown_throttle.factor` (read fresh at each sizing call; ships OFF — a natural
  live risk dial)

**Removed from safe-subset:** `strategies.<name>.enabled` (registry owns lifecycle).

**Restart-tier:** everything else, explicitly including the whole `arbiter.*` block
(opposition policy, caps, thesis TTL) and `ops.*`. The API flags these
`restart_required: true`; the UI badges them.

## API contract (Phase 1)

- `GET /api/state` → `{health: {bridge_connected, last_heartbeat_age_s, paused,
  last_error}, account: {balance, equity}, positions: [...],
  arbiter: {stats, throttle: {enabled, current_mult}},
  registry: [{id, name, version, status, timeframe}]}`
- `GET /api/events?limit=N` → ring-buffer backfill (curated projections, newest last).
- `GET /api/history?limit=N` → recent `trade_history` rows.
- `POST /api/command` → `{command: "pause|resume|close|closeall|panic|cancel",
  ticket?, confirm?}`. Destructive (`closeall`, `panic`) require `confirm: true` else
  `409 needs-confirm`. Outcomes verified from subsequent HEARTBEAT (never REQ replies).
- `GET /api/registry` → full manifest detail per strategy.
- `POST /api/registry/{id}/enable` / `/disable` → live-status strategies, no confirm.
- `POST /api/registry/{id}/promote` → body must echo `{"confirm": "<id>"}` (typed-id
  confirmation — the HTTP mirror of Telegram `/enable <id> confirm`); server calls the
  same registry path that enforces the research promote-gate.
- `GET /api/settings` / `PATCH /api/settings` → unchanged contract from 07-12 spec
  (tagged source/tier rows; live-apply vs restart_required; 422 on invalid).
- `WS /ws` → client sends token as FIRST frame within 3s (else close 1008); server then
  sends `{type:"state", ...}` snapshot, pushes state deltas on heartbeat cadence and
  `{type:"event", topic, ...}` per bus event (including IntentBlocked with rule).

## Security & hardening

- `TITAN_GUI_TOKEN` (env, `.env.example` documented); fail-closed when unset;
  constant-time compare. Binds `127.0.0.1`; `TITAN_GUI_BIND=0.0.0.0` documented as
  VPS-behind-TLS-proxy only.
- **WS auth via first frame** (token never in the query string → never in proxy logs);
  `Sec-WebSocket-Protocol` bearer as fallback.
- **Auth-failure throttling:** >5 bad tokens from one IP in 60s → 429 with backoff
  (in-process counter, no new deps).
- **Read-only mode:** `TITAN_GUI_READONLY=1` → mutating routes (command/settings/
  registry) return 403; state/events/settings-view stay live. Phone-dashboard mode.
- **Audit:** every accepted GUI mutation publishes `GuiActionExecuted` to the EventBus →
  golden tape. Operator actions are replay-visible alongside their consequences.
- The GUI never writes trade DBs; reads are WAL-safe.

## Frontend (`frontend/`)

Vite + React + Tailwind + shadcn/ui + Recharts, built to `frontend/dist/`, same-origin.
Panels: health strip (now including throttle-active indicator), positions+PnL table,
event feed (blocked intents rendered with blocking-rule chips: `opposition`,
`ttl-dedup`, `cap`), control buttons (confirm dialogs on closeall/panic), **Strategies
tab** (registry table with status badges; enable/disable buttons; promote dialog
requiring the typed strategy id; research rows visually distinct), **Settings tab**
(source + tier badges, inline 422 errors). Read-only mode greys all mutating UI.
WS hook with auto-reconnect + `GET /api/state` timer fallback; `ui-ux-pro-max` and
`dataviz` skills at build time. Research/Journal tabs scaffolded, empty until Phase 2.

## Error handling & isolation

- Handler exceptions → HTTP 5xx + log; bridge loop unaffected.
- uvicorn startup failure (port busy) → warn and keep trading.
- Bus subscriber is circuit-broken by the existing EventBus (P02) — a wedged GUI
  subscriber gets cut off, never blocks publishers.
- WS clients: drop-on-full queues; a dead phone connection cannot backpressure the loop.
- Verify at implementation: heartbeat cadence unchanged while hammering the API (the
  loop-yield risk from the original spec still applies).

## Testing (stdlib unittest, fake controller)

- All 07-12 test intents carry over (config merge, tiers, validation, confirm-gate,
  auth fail-closed, snapshot shape).
- **New:** `bus_bridge` tested against a REAL EventBus instance publishing real frozen
  events — projection correctness, ring-buffer backfill, drop-on-full.
- **New:** registry endpoints — promote unreachable without typed-id confirm (asserts
  the controller method is NOT called); enable/disable route to the existing methods.
- **New:** read-only mode — every mutating route 403s; reads still 200.
- **New:** `GuiActionExecuted` published on each mutation (assert on a bus test double).
- **New:** WS first-frame auth — no/late/wrong token → close 1008.

## Phasing

- **Phase 1 (this spec):** backend API (plan 1a) + React frontend (plan 1b) as above.
- **Phase 2:** **run-card browser** — read `data/results/<ts>_<strategy>_<sym>_<tf>/
  run.json` + `signals.jsonl` (Plan 06 artifacts) into a runs table / metrics /
  drill-down; launch `scripts/research_run.py` as a subprocess with streamed progress.
  This REPLACES the 07-12 "spawn poc scripts and parse stdout" design. Journal explorer
  over `trade_history` folds in here.
- **Phase 3:** native mobile + hosted multi-user SaaS — same API, unchanged.

## Out of scope (Phase 1)

Run-card browser and research launcher (Phase 2), journal explorer (Phase 2), mobile/
multi-user (Phase 3), charting beyond basic equity/PnL, manifest-priority editing
(blocked on Plan 07's priority plumbing), any arbiter live-mutation.
