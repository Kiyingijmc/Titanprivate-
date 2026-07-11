# Titan Backend & Server Infrastructure Blueprint

**Date:** 2026-07-12
**Status:** Architecture blueprint (Phase III of the research session; no code yet)
**Companions:** `2026-07-12-novel-arsenal-brainstorm.md` (Phase I — strategies),
`2026-07-12-trading-os-blueprint.md` (Phase II — Trading OS kernel)

---

## 0. Design stance

**The backend is a modular monolith with extraction seams, not a microservice fleet.**
Every "service" the spec names becomes a *domain module* — a Python package with a typed
interface, its own storage tables/files, and communication through the event bus and
control-plane API. A module can be extracted into a separate process later by swapping its
interface implementation (in-proc call → RPC/queue) with zero changes to its consumers.
That is the entire scaling strategy: **boundaries now, processes later, rewrites never.**

Why this is the right call, from first principles rather than fashion-aversion:

- The platform is one operator, one broker (FBS via MT5), nine symbols, bar-cadence
  decisions. Network hops between "services" would add failure modes and latency while
  removing determinism — the single most valuable property the Phase II kernel guarantees.
- Fault isolation at this scale is achieved by *process class*, not by service mesh:
  the *live trader* must never share a fate with *research jobs* or the *cockpit UI*.
  Three process classes, strict boundaries between them, is real isolation.
- A single developer's scarcest resource is operational attention. Every additional
  always-on component (broker, queue, database server) is a thing that pages you.
  The design below runs on zero always-on infrastructure beyond the trader itself.

**Honoring the critical constraint:** this is not a data warehouse. Concrete numbers keep
us honest: 3 years × 9 symbols × M5+H1 OHLC ≈ 2.8M rows ≈ **~40 MB as compressed Parquet**.
Even 10× the research appetite fits in half a GB. Every storage decision below is sized to
that reality — retention policies and pruning exist to keep the research lake *curated and
reproducible*, not to manage volume that will never exist.

---

## 1. System architecture diagram (Deliverable 1)

```
     WINDOWS HOST (execution venue)          │            WSL / LINUX HOST (the platform)
                                             │
 ┌─────────────┐   ┌──────────────────┐      │   ┌─────────────────────────────────────────────┐
 │  MT5 (FBS)  │←──│ Titan_Gateway EA │◄─────┼──►│  PROCESS CLASS A — LIVE TRADER (systemd)    │
 │  terminal   │   │ (ZMQ connect)    │ zmq  │   │  ┌───────────────────────────────────────┐  │
 └─────────────┘   └──────────────────┘32768 │   │  │ Trading OS kernel (Phase II layers)   │  │
        ▲                                /69 │   │  │ L0 bridge · L1 data · L2 FeatureBus   │  │
        │          ┌──────────────────┐  /70 │   │  │ L3 runtime · L4 arbiter · L5 risk     │  │
        └──────────│ FastAPI MT5      │◄─────┼──►│  │ L6 execution · L7 telemetry           │  │
                   │ bridge :8766     │ http │   │  ├───────────────────────────────────────┤  │
                   │ (data plane)     │      │   │  │ EMBEDDED CONTROL PLANE (FastAPI)      │  │
                   └──────────────────┘      │   │  │ REST + WebSocket :8787 (cockpit API)  │  │
                                             │   │  └───────────────────────────────────────┘  │
                                             │   │        │ typed in-proc EVENT BUS │          │
                                             │   │        ▼ (journaled → golden tape)          │
                                             │   │  ┌──────────┐ ┌──────────┐ ┌────────────┐   │
                                             │   │  │ SQLite   │ │ Parquet  │ │ JSONL      │   │
                                             │   │  │ (state,  │ │ lake     │ │ journals + │   │
                                             │   │  │ registry,│ │ (history,│ │ audit chain│   │
                                             │   │  │ config,  │ │ results) │ │ + logs)    │   │
                                             │   │  │ metrics) │ └──────────┘ └────────────┘   │
                                             │   │  └──────────┘                               │
                                             │   ├─────────────────────────────────────────────┤
                                             │   │  PROCESS CLASS B — RESEARCH (on-demand)     │
                                             │   │  backtests · walk-forward · optimization    │
                                             │   │  (ProcessPool; reads lake, writes results;  │
                                             │   │   NEVER touches live sockets or live state) │
                                             │   ├─────────────────────────────────────────────┤
                                             │   │  PROCESS CLASS C — OPS (cron/systemd timers)│
                                             │   │  backups · pruning · calendar fetch ·       │
                                             │   │  log rotation · health probe                │
                                             │   └─────────────────────────────────────────────┘
                                             │
   OUTBOUND (egress-only from WSL): Telegram API (alerts+control) · backup remote (restic)
   INBOUND remote access: Tailscale mesh → cockpit :8787 (never port-forwarded to internet)
```

Three process classes, one machine pair, zero always-on third-party infrastructure.
The live trader owns the ZMQ ports and all live state; research and ops are stateless
readers/writers of disk artifacts (fault isolation by construction — a crashed backtest
cannot wedge the trader).

---

## 2. Domain map — every spec'd service, placed (Deliverable 2)

| Spec'd service | Realization | Process | Storage it owns |
|---|---|---|---|
| Trading Core | Phase II L3–L6 (runtime, arbiter, order pipeline, trade state) | A | SQLite `active_orders`/`trade_history` |
| Strategy Registry | Phase II §5 registry module | A | SQLite `strategies`, manifests in repo |
| Resource Management | Phase II FeatureBus (L2) | A | in-memory + rehydration snapshots |
| Cache Service | Phase II §4 (event-keyed memoization) — see §6 below for backend additions | A | in-memory; snapshots to disk |
| Historical Data Service | `src/data/lake.py` — Parquet lake + manifest + retention (§7) | A read / B+C write | `data/lake/` |
| Live Market Data | Phase II L1 (exists) | A | rolling in-memory windows |
| Backtesting Service | research runner CLI (`titan research run …`) on the *same kernel* via replay router | B | `data/results/<run_id>/` |
| Optimization Service | research runner modes: grid → random → (later) Bayesian via Optuna | B | same |
| Risk Management | Phase II L5 (extended RiskManager) | A | SQLite risk ledger tables |
| Portfolio Service | position/account views over StateManager + HEARTBEAT snapshots, attribution by strategy | A | SQLite views |
| Execution Gateway | L0/L6: ZMQ bridge + order router (validation, idempotency via `thesis_id`, latency stamps) | A | journal |
| Analytics Service | metrics registry (Phase II §10) + nightly rollups job | A + C | SQLite `metrics_*`, Parquet rollups |
| Notification Service | telemetry module behind a `Notifier` interface; Telegram adapter now, webhook adapter next (Discord/Slack/email later — adapters, not rewrites) | A | outbox table (§5.4) |
| Configuration Service | layered config engine (§2.1) | A | YAML in git + SQLite `config_revisions` |
| Identity & Access | control-plane auth (§8.3): bearer tokens, principal on every action | A | SQLite `principals`, `api_tokens` |
| Audit Service | hash-chained append-only audit journal (§8.5) | A | `journal/audit-YYYYMM.jsonl` |

Module layout (`src/` grows domains, not layers-of-abstraction):

```
src/
  core/        # kernel: runtime, scheduler, event bus, time engine   (Phase II L1,L3)
  features/    # FeatureBus + resource packages                        (L2)
  strategies/  # plugins + manifests                                   (L3 content)
  arbiter/     # intents, conflict rules, allocator                    (L4)
  risk/        # risk engine                                           (L5)
  execution/   # bridges, order router, trade manager, state           (L0,L6)
  data/        # lake, retention, import/export, dataset manifests
  control/     # FastAPI app: REST+WS, auth, cockpit endpoints
  ops/         # telemetry/notifier, metrics, audit, health
  research/    # replay router, backtest/walk-forward/optimize runners
```

Rule: **domains import downward only** (`strategies` may import `features` types; nothing
imports `control`). Enforced by a unit test that walks the import graph — architecture drift
caught in CI, not code review.

### 2.1 Configuration service (spec: versioning, rollback, validation, audit)

Layered resolution, deterministic: `defaults (code) ← config.yaml (git) ← settings.local.yaml
(machine, git-ignored) ← runtime overrides (control plane)`. This matches the layered-config
design already committed for the Phase-1 GUI. Every applied runtime change: schema-validated
(pydantic), written to SQLite `config_revisions` (who/when/diff/hash), audited, revertible
(`titan config rollback <rev>`). Feature flags are just config keys read through the same
engine. Git remains the source of truth for durable config — rollback of file config is
`git revert`, an already-solved problem we refuse to reinvent.

---

## 3. Database & storage architecture + data classification (Deliverables 3, and "Data Classification")

### 3.1 Technology decision

Evaluated: Postgres/Timescale (client-server RDBMS + TSDB), InfluxDB, MongoDB, Redis,
MinIO, SQLite, flat files. **Chosen: SQLite (WAL) + Parquet + append-only JSONL + YAML.**
Justification against the evaluation criteria:

- **SQLite** — transactional state that must survive crashes (orders, registry, config
  revisions, metrics rollups, auth). Already proven in this codebase (StateManager, WAL,
  reboot-surviving reconciliation). Single-writer model matches our single-writer
  architecture *exactly*; a DB server would add an always-on dependency to protect against
  concurrency we structurally don't have. Backup = file copy of a checkpointed snapshot.
- **Parquet** — columnar, compressed, memory-mappable; pandas/pyarrow native. A 3-yr M5
  backtest loads in tens of ms. This *is* the "time-series database" at our scale: a TSDB
  server (Influx/Timescale) would be strictly worse on operational cost and no better on
  query speed for whole-window scans, which is the only query pattern backtests have.
- **JSONL append-only** — journals (signals, events, audit): human-greppable, corruption-
  isolated (a torn line loses one line), trivially rotated and shipped.
- **No Redis** — the cache is in-process (Phase II); a network cache would *add* latency.
  The extraction seam (§6) keeps distributed-cache readiness without paying for it now.
- **No object storage** — restic to any cloud bucket covers the archive tier (§12).

### 3.2 Data classification table

| Category | Examples | Store | Lifetime / retention | Backup | Recovery priority |
|---|---|---|---|---|---|
| **Live trade state** | active_orders, pending meta | SQLite | until archived to history | continuous (WAL) + hourly snapshot | **P0** — needed to manage open positions |
| **Trade history** | closed trades, R-multiples | SQLite | permanent (tiny) | daily | P1 — attribution, allocator input |
| **Config** | YAML layers, revisions | git + SQLite | permanent, versioned | git remote + daily | **P0** — needed to boot |
| **Secrets** | .env (Telegram, bridge tokens) | file (0600) | until rotated | encrypted in restic only | **P0** |
| **Reference data** | symbol specs, calendars, sessions | JSON/SQLite | refresh-cycle | daily | P1 (specs re-fetchable from broker) |
| **Strategy metadata** | manifests, versions, weights | repo + SQLite | permanent | git + daily | P1 |
| **Market data (research lake)** | Parquet OHLC per symbol/tf/broker | Parquet lake | **retention-managed (§7): default 4 yr active, prune beyond** | weekly (cheap) | P3 — re-exportable from broker |
| **Validation/benchmark datasets** | frozen gate datasets + checksums | Parquet lake (`frozen/`) | permanent while referenced by a gate doc | weekly | P2 — reproducibility of GO/NO-GO calls |
| **Backtest artifacts** | run results, sweeps | Parquet/JSON | 90 days unless pinned | none (recomputable) | P4 |
| **Journals** | signal/event/audit JSONL | JSONL | audit: permanent; others: 12 mo compressed | daily (audit), weekly | P2 (audit P1) |
| **Metrics** | rollups, health snapshots | SQLite | 13 mo | weekly | P4 |
| **Logs** | structured app logs | JSONL rotated | 30 days | none | P4 |
| **Cache/temp** | FeatureBus entries, scratch | RAM/disk | ephemeral | none | P5 — always recomputable |

Recovery priority drives the restore runbook order in §12.

---

## 4. API architecture (Deliverable 4)

One **control plane** (FastAPI, embedded in the live trader, port :8787, localhost +
Tailscale only) — this is the same server as the Phase-1 cockpit design; the domains from
this document mount routers onto it rather than spawning new services.

| Concern | Style | Why |
|---|---|---|
| Strategy mgmt (`/strategies` list/enable/disable/suspend, manifest view) | REST | CRUD semantics, low rate |
| Portfolio (`/portfolio/positions`, `/portfolio/equity`) | REST + WS topic | snapshot + stream |
| Risk (`/risk/limits`, `/risk/throttle`, `/panic`) | REST (POST, confirm-token for destructive) | auditable commands |
| Config (`/config`, `/config/revisions`, rollback) | REST | versioned CRUD |
| Backtesting/Optimization (`/research/runs` submit/status/results) | REST submit + WS progress | long-running jobs |
| Live telemetry (bars, intents, executions, metrics) | **WebSocket topics** | push streams to cockpit; SSE rejected — WS already required bidirectionally by cockpit design |
| Health (`/healthz` liveness, `/readyz` bridge+specs+state checks) | REST | probes for systemd watchdog + uptime monitor |
| Auth (`/auth/token`) | REST | token issue/rotate |
| Admin/audit (`/audit/tail`, `/ops/backup-now`) | REST | operator tooling |

Rejected: **gRPC** (single language, single box — protobuf toolchain buys nothing here;
the seam if ever needed is the same interface classes), **external message queue as API**
(the bus is in-process; §5.5 defines its extraction path). Telegram remains a thin
*adapter* over the same command handlers the REST API calls — one implementation of
control, two transports, identical audit trail.

API versioning: `/v1/` prefix from day one; additive evolution; breaking changes bump once
a year at most (we are our own only client — ceremony minimized, seam preserved).

---

## 5. Event-driven messaging architecture (Deliverable 5)

### 5.1 The bus

A new typed in-process async bus (`src/core/bus.py`) — publish/subscribe over frozen
dataclasses, synchronous-by-default delivery within the bar cycle (determinism), async
fan-out for non-critical consumers (telemetry, metrics). The dead `event_bus.py` is
deleted, not revived (per repo convention: don't build on dead code).

### 5.2 Event catalog (the spec's list, typed)

```
market:   TickReceived · BarClosed · SessionChanged · CalendarUpdated · SpecsUpdated
          FeedGap(symbol, tf, span) · FeedRecovered
kernel:   ResourceComputed(name, key, ms) · CacheInvalidated(name, reason)
strategy: StrategyActivated/Suspended(id, reason) · IntentEmitted · IntentBlocked(rule)
trading:  OrderSubmitted(thesis_id) · OrderAccepted(ticket) · OrderRejected(reason)
          TradeOpened · TradeModified · TradeClosed(r_multiple)
risk:     RiskLimitHit(rule) · ThrottleChanged · PanicTriggered(source)
ops:      ConfigUpdated(rev) · BrokerDisconnected/Reconnected · BacktestCompleted(run_id)
          OptimizationCompleted(run_id) · BackupCompleted · HealthDegraded(check)
```

### 5.3 The journal is the tape

Every event (minus per-tick noise, which is sampled) is appended to the event journal.
This single decision buys three capabilities at once: the **golden tape** for Phase II's
replay regression, **post-incident forensics** (replay the exact sequence that preceded a
failure), and **backtest/live parity evidence** (diff live event stream vs replayed one).

### 5.4 Reliability patterns on the bus

- **Outbox pattern** for side-effects that must not be lost: notifications and order
  submissions are written to an SQLite outbox in the same transaction as the state change,
  then drained by the sender; crash between write and send ⇒ resent on boot (idempotent via
  `thesis_id` / notification key). Replay protection and at-least-once, without a broker.
- Consumers are isolated: a throwing subscriber is logged + circuit-broken (§11), never
  able to abort the bar cycle.

### 5.5 Extraction seam (distributed readiness)

`Bus` is an interface. Stage-3 multi-process (if earned) swaps in a NATS/Redis-streams
implementation *for cross-process topics only*, keeping in-proc delivery inside the trader.
Events are already immutable dataclasses with schema-versioned names — serialization is a
codec choice, not a redesign.

---

## 6. Cache architecture — backend view (Deliverable 6)

The cache *is* the Phase II FeatureBus (event-keyed invalidation, DAG dependencies, LRU
memory budget, hit/miss analytics). The backend adds exactly three things:

1. **Rehydration store** — PERSISTENT/GLOBAL-class entries (fitted model params, corr
   matrix, specs) snapshot to `data/warm/` on write; boot rehydrates so restarts don't
   re-fit models mid-session. Snapshot format = pickle-free (numpy .npz / JSON) for
   version-tolerance.
2. **Cache observability endpoints** — `/v1/cache/stats` (per-resource hit ratio, compute
   cost, bytes) and `CacheInvalidated` events onto the bus for the cockpit's cache panel.
3. **Distributed readiness, not distribution** — keys are already content-addressed
   `(name, symbol, tf, invalidation_token, pkg_version)`; if a stage-3 research cluster
   ever wants shared feature results, the same keys index a shared read-through store.
   Predictive warming remains boot-time-only (Phase II §4.3) — in a bar-driven system
   there is nothing to predict.

---

## 7. Historical Data Service — research lake, not warehouse (Deliverable 7)

```
data/lake/
  manifest.json                 # every dataset: source, span, checksum, size, last_used
  fbs/EURUSD/M5/2023.parquet    # partition: broker/symbol/tf/year
  fbs/EURUSD/H1/…
  synthetic/<generator>@<params_hash>/…    # Phase-I rig synthetic sets, regenerable
  imported/<source>/…                      # third-party sets, provenance in manifest
  frozen/<gate_id>/…                       # immutable copies referenced by gate docs
```

- **Import**: `titan data import --symbol XAUUSD --tf M5` wraps the existing HTTP-bridge
  export; writes Parquet + manifest entry (checksum, broker, span). CSV in `data/history/`
  is migrated once and deprecated.
- **Retrieval**: `lake.load(symbol, tf, span) -> DataFrame` — the *only* API backtests use;
  memory-mapped, whole-window scans, tens of ms.
- **Retention & pruning** (ops job, weekly): active window default 4 years rolling;
  partitions beyond retention *and* unused > 180 days (manifest `last_used`) are deleted —
  they are re-exportable from the broker, so "archive" for raw market data is simply
  *re-import on demand*. Only `frozen/` is permanent: gate reproducibility outranks disk
  thrift, and at ~40 MB/gate it costs nothing.
- **Validation on ingest**: monotonic timestamps, gap census vs trading calendar, spread
  sanity; a dataset failing validation lands quarantined (`.rejected/`) with a report —
  bad data is refused at the door, not discovered inside a backtest.
- **Multi-broker**: the partition scheme and manifest carry `broker` from day one (cost
  models differ per broker even when candles look similar); adding broker #2 is a new
  directory, not a migration.

Size honesty: full build-out ≈ hundreds of MB. The service's value is *curation,
provenance, and reproducibility* — never capacity.

---

## 8. Security architecture & trust boundaries (Deliverable 8)

### 8.1 Trust boundary map

```
  UNTRUSTED INTERNET
    │  (egress only: Telegram API, restic remote, calendar fetch — TLS, pinned hosts)
    ▼
┌───────────── TAILSCALE MESH (device-authenticated overlay) ─────────────┐
│  operator laptop/phone ──► cockpit :8787 (bearer token over TLS/WG)     │
└──────────────────────────────────────────────────────────────────────────┘
┌───────────── WSL HOST (trust zone A — the platform) ────────────────────┐
│  live trader · research · ops · SQLite/parquet/journals · .env (0600)   │
└───────────────────────────────┬──────────────────────────────────────────┘
                        WSL↔Windows vswitch (private, host-internal)
┌───────────────────────────────▼──────────────────────────────────────────┐
│  WINDOWS HOST (trust zone B — execution venue)                           │
│  MT5 terminal + EA (ZMQ → WSL IP only) · FastAPI bridge :8766 (token)    │
└──────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Controls per boundary

- **ZMQ bridge (B→A):** binds on the WSL interface, reachable only from the host-internal
  vswitch (Windows firewall rule scoped to the WSL subnet; never on a public interface).
  Message schema validation on every inbound frame (malformed → dropped + counted).
  Replay/duplicate protection: order entry is REQ/REP handshake + `thesis_id` idempotency;
  EXECUTION events are reconciled against known tickets (unknown tickets → "Adopted" path,
  already implemented, now also audited).
- **HTTP data bridge (A→B):** bearer token (`TITAN_BRIDGE_TOKEN`, exists), bound to the
  vswitch, read-mostly; rate-limited on the Windows side.
- **Control plane (:8787):** binds localhost + Tailscale interface only — *never*
  port-forwarded. Bearer tokens per principal, argon2-hashed at rest, scoped
  (`read`, `trade-control`, `admin`), 90-day expiry with `titan auth rotate`. Destructive
  endpoints (`/panic`, `/closeall`, config rollback) demand a fresh confirm-token
  (two-step, mirrors existing Telegram confirm pattern). MFA-readiness = Tailscale device
  auth (something you have) + token (something you know); explicit TOTP deferred until a
  second human exists.
- **Telegram:** single authorized chat ID (exists) + command allow-list; treated as a
  *low-privilege* principal: can pause/panic/query, cannot change config or limits.
- **Secrets:** `.env` file mode 0600, git-ignored (exists); enters backups only inside
  restic's encryption; rotation runbook per secret (Telegram token, bridge token, API
  tokens) with `titan auth rotate --secret <name>` updating both sides where scriptable.
- **Input validation:** pydantic schemas at every ingress (bridge messages, API bodies,
  config files, imported datasets). Least privilege: research/ops processes run without
  access to `.env` trade secrets (they never talk to brokers).

### 8.3 IAM (right-sized)

Principals table: `operator` (admin), `telegram` (control), `cockpit-viewer` (read),
`ops-job` (internal). Every control-plane and Telegram action executes *as* a principal and
lands in the audit chain with it. Roles beyond these four are YAGNI until a second human
exists — but because every action already carries a principal, adding roles later is a
policy change, not a plumbing change.

### 8.4 Tamper-evidence

Audit journal is hash-chained: each record carries `sha256(prev_hash || record)`; the ops
job anchors the day's head hash into the daily backup *and* posts it to the Telegram
channel (an off-box witness). Verification tool: `titan audit verify`. Immutability at
single-box scale means *tamper-evident*, and this is the honest way to get it.

---

## 9. Deployment architecture (Deliverable 9)

| Environment | What | How |
|---|---|---|
| **dev** | unit tests, replay regression, research runs | repo venv; no live sockets; replay router only |
| **staging** | full stack against **FBS-Demo** | second systemd unit `titan-demo.service`, own SQLite/journals dir, own ZMQ ports (33768+), demo MT5 terminal — the existing "demo-forward before live" gate, formalized |
| **prod** | live trader | `titan-live.service` |

Mechanics:

- **systemd units** (WSL supports systemd): `Restart=on-failure`, `WatchdogSec=90` fed by
  the health loop (a wedged asyncio loop gets restarted by init, not by hope),
  `MemoryMax=2G`, journald for stdout capture. Boot order: unit waits on `/readyz`-style
  preflight (config valid, SQLite openable, bridge reachable).
- **Windows side:** Task Scheduler entries for MT5 auto-start and the data bridge
  (`py -3.11 run_bridge.py`), replacing hand-run PowerShell; the existing `_reboot_terminal`
  watchdog remains the in-band recovery for a frozen terminal.
- **Docker:** *packaging option at stage 2* (a Dockerfile for the trader makes cloud-VM
  migration turnkey) — not used locally now, because WSL–Windows bridge networking is the
  one thing containers would complicate rather than simplify.
- **Kubernetes:** rejected for all foreseeable stages — nothing here needs orchestration,
  autoscaling, or service discovery; it would be pure operational drag.
- **Releases:** git tag → `titan deploy` script: run unit suite + replay regression, rsync
  to a versioned release dir, flip a `current` symlink, restart unit; rollback = re-point
  symlink. Blue-green at single-box scale, achieved with a symlink.

---

## 10. Scalability roadmap (Deliverable 10)

| Stage | Trigger | What changes | What does NOT change |
|---|---|---|---|
| **1 (now)** | — | everything above: 3 process classes, 1 machine pair | — |
| **2: multiple accounts / dozens of strategies** | 2nd account or strategy #10 | one trader process **per account** (own config layer, own SQLite, own ports); shared research lake & cockpit (multi-instance aware: instance selector in UI); Docker packaging; cloud VM or home server for the Linux side if WSL uptime becomes limiting | kernel, domain code, storage tech |
| **3: multiple brokers / distributed research** | broker #2 or optimization jobs saturating one box | Execution Gateway interface gets a 2nd adapter (the HTTP-bridge `Broker` client is the template; kernel already broker-agnostic); portfolio orchestration = a thin coordinator reading all instances' portfolio APIs, applying global caps via each instance's risk API; research fan-out to worker boxes reading a synced lake (rsync/syncthing), submitting via the runs API; bus grows a cross-process backend (NATS) **only** for coordinator topics | strategy plugins, FeatureBus, risk logic, storage formats |
| **4: enterprise-grade** | a team + capital that justifies it | HA pair for the coordinator, Postgres replacing SQLite *at the coordinator only* (multi-writer finally exists), Grafana/Prometheus replacing the embedded metrics view, secrets manager (Vault/SOPS), multi-region execution near brokers | domain boundaries, event catalog, plugin contract |

The invariant across stages: **interfaces defined at stage 1 are the extraction seams used
at stages 2–4.** Nothing on the roadmap is a rewrite; everything is an implementation swap
behind an existing boundary.

---

## 11. Observability, monitoring & incident response (Deliverable 11)

- **Structured logging:** JSON lines everywhere (`ts, level, domain, event, symbol,
  strategy, bar_cycle_id, msg`), rotated daily, 30-day retention. The existing
  audit_logger migrates to this schema.
- **Correlation, not distributed tracing:** a `bar_cycle_id` (symbol+tf+bar_time) stamps
  every log line, event, intent, order, and fill produced within one bar cycle — full
  causal reconstruction with `grep`, no tracing infrastructure. (OpenTelemetry becomes
  worthwhile only at stage 3 multi-process; the ID scheme is already compatible.)
- **Metrics:** Phase II registry; 15-min SQLite snapshots; cockpit dashboards (system
  health, bar-cycle latency, cache efficiency, per-strategy R curves, bridge health).
- **Health model:** `/healthz` (loop alive) and `/readyz` (bridge fresh, heartbeat < 30 s,
  specs loaded for all pairs, SQLite writable, clock sane) — consumed by systemd watchdog,
  an external uptime pinger (via Tailscale), and the cockpit.
- **Alerting tiers via Notifier:** P0 page-equivalent (Telegram + repeat until acked):
  panic, heartbeat lost, order rejected, audit-chain break, daily-loss hit. P1 notify-once:
  strategy auto-suspended, feed gap, backup failure. P2 daily digest: performance report
  (exists), cache/latency anomalies.
- **Circuit breakers:** bridge send failures → OPEN after N errors → no new entries,
  management still attempted, reconcile-on-recover (extends existing watchdog);
  notification adapter failures → outbox retry with backoff; consumer failures → subscriber
  circuit-break (§5.4).
- **Incident response:** runbooks in `docs/runbooks/` (bridge-down, wedged-REP-socket —
  already understood in CLAUDE.md, state-desync, restore-from-backup, secret-rotation);
  every P0 alert links its runbook. Post-incident: the event journal *is* the forensic
  record — replay to reproduce, then a regression test from the tape.
- **Self-healing inventory (exists, formalized):** EA reattach recovery, terminal reboot
  watchdog, ghost-order reconciliation, spec re-request on warmup — each now emits events
  so recoveries are visible and counted, not silent.

---

## 12. Disaster recovery, backup & restoration (Deliverable 12)

- **Tooling:** restic (encrypted, deduplicated, incremental) to one cloud bucket + optional
  second copy on the Windows host (`\\wsl.localhost` share). Config additionally lives in
  git (remote).
- **Schedule (ops timers):** hourly — SQLite online snapshot (`VACUUM INTO`) of live state;
  daily — full restic run (SQLite snapshots, journals+audit head, config, .env, warm
  snapshots, frozen datasets); weekly — lake partitions + metrics.
  Targets: **RPO ≤ 1 h** for trade state (with the true live position always recoverable
  from the broker via HEARTBEAT reconciliation — the existing ghost/adopted-order logic is
  the real safety net), **RTO ≤ 30 min** on any machine with the repo + restic key.
- **Restore runbook** (priority order from §3.2): (1) provision WSL + venv from repo;
  (2) restore .env + config; (3) restore SQLite state; (4) start in `PAUSED`; (5) let
  HEARTBEAT reconciliation adopt/verify open positions against broker truth; (6) verify
  audit chain head against the last off-box witness; (7) operator resumes. Drill twice a
  year against the demo instance — an untested restore is a rumor, not a backup.
- **Windows-side DR:** MT5 + EA + DLLs redeploy runbook (exists in CLAUDE.md, promoted to
  `docs/runbooks/`); WSL-IP change on reboot is part of the same runbook (`InpIP` update).
- **Data loss stance:** market data is *never* backed up beyond weekly convenience — it is
  re-exportable; the irreplaceables are state, config, secrets, journals, and frozen gate
  datasets, all P0–P2 and all under daily-or-better protection.

---

## 13. Recommended technology stack (Deliverable 13)

| Concern | Choice | Justification (vs alternatives) |
|---|---|---|
| Language/runtime | Python 3.11+ / asyncio | entire kernel, team knowledge, ecosystem; latency needs are ms-class, not μs |
| Control plane | FastAPI + uvicorn | already designed for cockpit; pydantic validation shared with config/schemas |
| Live bridge | ZMQ (existing) → HTTP bridge (Phases 2–3 per repo plan) | proven here; migration path already documented |
| State DB | SQLite WAL | §3.1; zero-ops, transactional, proven in repo |
| Research store | Parquet + pyarrow | §3.1; columnar speed, tiny footprint |
| Journals/audit | JSONL + hash chain | greppable, corruption-isolated, tamper-evident |
| Bus | in-proc typed pub/sub (new) | determinism; NATS reserved as stage-3 swap-in |
| Scheduler/jobs | systemd timers | no cron-vs-app ambiguity; journald logging for free |
| Optimization | Optuna (stage: research) | mature Bayesian/TPE, zero server; grid/random are trivial in-house |
| Remote access | Tailscale | device-auth mesh beats port-forwarding on every security axis |
| Backups | restic | encrypted, incremental, cloud-agnostic |
| Notifications | Telegram (existing) behind Notifier interface | adapters for Discord/Slack/email/webhooks are additive |
| Dashboards | cockpit (FastAPI+WS, Phase-1 design) | Grafana/Prometheus deferred to stage 4 — one fewer daemon |
| Secrets | .env 0600 now; SOPS+age when >1 machine | right-sized; encrypted-at-rest path defined |
| CI | unittest + replay regression + import-graph test (GitHub Actions) | repo convention (no pytest), plus the two architecture-guarding tests |

Anti-choices restated once: no Kubernetes, no microservices, no Redis, no TSDB server, no
message broker at stage 1–2 — each was evaluated and each subtracts reliability-per-ops-hour
at this scale.

---

## 14. Phased implementation roadmap (Deliverable 14)

Backend work interleaves with the Phase II kernel stages (v15.x) — infrastructure lands
when a kernel stage needs it, never speculatively:

| Phase | Scope | Depends on | Effort |
|---|---|---|---|
| **B0 — Foundations** | typed bus + event journal (golden tape); structured JSON logging; `/healthz`+`/readyz`; systemd units (live+demo) with watchdog | none — *unblocks kernel v15.0's regression harness* | 2–3 d |
| **B1 — Lake** | Parquet lake + manifest + import CLI + validation + retention job; migrate `data/history` CSVs; backtests read `lake.load()` | B0 | 2 d |
| **B2 — Control plane core** | FastAPI app, auth (tokens+principals), strategy/portfolio/risk read endpoints, WS telemetry topics; Telegram rewired as adapter over the same handlers; audit chain + `titan audit verify` | kernel v15.1 (registry) | 3–4 d |
| **B3 — Config service** | layered config engine + revisions + rollback + validation; runtime overrides via API | B2 | 2 d |
| **B4 — Ops hardening** | restic backups + timers + restore runbook (drilled once on demo); outbox for notifications/orders; circuit breakers; runbooks directory | B0 | 2–3 d |
| **B5 — Research runners** | replay router (same kernel), backtest/walk-forward CLI, runs API + artifacts dir; Optuna optimization mode | kernel v15.2 + B1 | 3–4 d |
| **B6 — Cockpit integration** | dashboards over metrics/WS (executes the Phase-1 GUI design); cache/latency/strategy panels | B2 | per GUI plan |
| **B7 — Stage-2 prep (deferred)** | Dockerfile, multi-instance config layering, per-account units | a real 2nd account | 2 d |

Sequencing principle, restated from Phase II and binding here too: **backend phases are
scheduled between strategy research cycles.** The platform exists to serve validated edges
(SilverBullet today; Gyroscope's gate next), and the roadmap above is deliberately sliced
into ≤4-day increments so infrastructure never blocks the research queue for long.

---

## 15. Blueprint acceptance criteria

The Phase III design is *done* (as architecture) when:

1. Every spec'd service maps to a named module with an owner interface (§2 table) — ✔ in
   this document; enforced later by the import-graph test.
2. The live trader runs with **zero** always-on dependencies beyond itself and the MT5 pair.
3. A cold-machine restore following §12 reaches PAUSED-and-reconciled in ≤ 30 min (drilled).
4. The event journal from a live session replays through the research runner and reproduces
   identical signals (parity evidence).
5. Killing the research process mid-backtest and yanking the cockpit connection leaves the
   live trader provably unaffected (fault-isolation drill).
