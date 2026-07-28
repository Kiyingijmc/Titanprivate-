# PASS 3 — SYSTEMS DEEP DESIGN

**Co-chairs:** Chief Systems Architect + Backend Architect + Principal Algo-Bot Developer, Networking & Infrastructure Specialist co-chairing §8. **Contributors:** all ten seats; the Auditor red-teams per board rule (b).
**Inputs (read in full):** `00-overview.md`–`05-…`, `pass1-audit.md` (39 findings), `pass2-research.md`.
**Scope note:** Pass 1 routed several state/architecture findings to "Pass 5"; the summit re-scoped systems deep design into this pass. F-004, F-008 (mechanism), F-014, F-015, F-016 (matrix), F-028, F-032, F-035, F-038 are therefore designed **here**; §10 records each. F-002 and F-016 remain OPEN-FOR-HUMAN — this pass supplies the decision matrices and recommended defaults.
**Prior-art convention:** every borrowable Titan component gets a **BORROW / ADAPT / REBUILD** verdict in §6.2 with file-level rationale (files skimmed: `src/risk/risk_manager.py`, `src/core/bus.py`, `src/core/state_manager.py`, `src/features/feature_bus.py`, `src/ops/telemetry.py`, `src/ops/event_journal.py`, `src/ops/web/{server,commands,config_layer}.py`, `src/execution/broker/{base,mt5_http}.py`, `src/research/kernel_replay.py`, `bridge/app/`).

---

## §1 Event schemas & data contracts

### 1.1 The envelope (every event, no exceptions)

One envelope wraps every payload written to the event log or published on the bus. The log is a single SQLite table `events`; the bus carries the same object in memory.

| Field | Type | Null | Semantics |
|---|---|---|---|
| `seq` | u64 | no | Log-assigned, strictly monotonic, **gapless** per log. Assigned only by the single writer (§1.4, F-015). Bus-only events (tick fan-out) that are not journaled have `seq=null` in memory and are never citable as facts. |
| `event_id` | uuid7 | no | Globally unique; time-ordered UUID so id order ≈ time order for debugging. |
| `schema` | str | no | Dotted type name, e.g. `signal.state_changed`. Registry-validated at publish. |
| `schema_version` | u16 | no | Per-schema version. Consumers must reject unknown majors; replay uses versioned decoders (upcasters) so old logs stay replayable. |
| `ts_event` | i64 (ns, UTC) | no | When the fact became true, from the **core monotonic clock anchored to NTP wall time at boot** (F-033 discipline: comparisons inside the core use monotonic; wall time only at edges). |
| `ts_ingest` | i64 | no | When the writer committed it. `ts_ingest − ts_event` is a first-class health metric (loop lag, F-028). |
| `correlation_id` | uuid | yes | Root of the causal chain — `signal_id` for the whole signal→order→position→close chain; config-change id for config chains. |
| `parent_ids` | [uuid] | no (may be empty) | Direct causal parents (e.g. a `exec.fill` lists the `exec.order_submitted` event and the `market.tick` batch that triggered it where known). |
| `idempotency_key` | str | yes | Present on externally-effectful events (order submits, Telegram sends, commands). Writer enforces uniqueness: a second append with the same key is dropped + counted. |
| `actor` | str enum-pattern | no | `core`, `child:<child_id>`, `risk`, `exec`, `reconciler`, `timer:<name>`, `human:gui:<user>`, `human:tg:<chat_id>`, `config`, `breaker`, `broker`. Commands additionally carry HMAC (§8.5, F-031). **Chain-covered** (inside `row_hash`) — rewriting it breaks the chain. |
| `payload` | JSON (typed per schema) | no | Canonical JSON: sorted keys, `NaN` forbidden, numerics normalized (int-valued floats emitted as ints) — same canonicalization as `params_hash` (F-038). |
| `prev_hash` | bytes32 hex | no | Hash chain (F-004): `row_hash` of `seq−1`. Genesis row uses 32 zero bytes. |
| `row_hash` | bytes32 hex | no | `SHA-256(prev_hash ‖ seq ‖ schema ‖ schema_version ‖ ts_event ‖ actor ‖ canonical_json(payload))`. Computed by the writer inside the same transaction. |

> **Amended 2026-07-28, S009, owner-ratified — `actor` chained.** `row_hash` was originally defined over six fields, leaving `actor` stored but unchained, so `verify_chain` could not detect a rewritten commanding principal (RS007 finding 4) — the exact provenance §8.5's command audit is built on. Widened to the seven-field pre-image above while no `events.sqlite3` existed anywhere (no deployed, committed, or otherwise load-bearing log; no pinned golden chain hash), so the change carried zero migration cost. No `chain_format_version`/upcaster machinery was added: with no prior logs there is nothing to version against. The other five envelope columns (`event_id`, `ts_ingest`, `correlation_id`, `parent_ids`, `idempotency_key`) deliberately remain unchained. Rationale and blast-radius evidence: `docs/decisions/0001-widen-row-hash-preimage-actor.md`.

### 1.2 Event families (typed payload schemas)

Field tables give `name : type (null?)` — semantics inline. All prices are `float` in broker price units; all tick quantities are `int` ticks; all risk figures are `float` fractions of equity (0.005 = 0.5%).

**market.\***

| Schema | Payload |
|---|---|
| `market.tick` | `instrument:str, bid:float, ask:float, ts_broker:i64(ns), spread_ticks:int`. Journaled **sampled** (1-in-50 per instrument, Titan `event_journal` pattern) + always around order sends (±5 s ring buffer flushed on any exec event). |
| `market.candle_closed` | `instrument:str, timeframe:str, bar_ts:i64 (bar OPEN time, UTC), o,h,l,c:float, volume:float, bar_index:u64` — `bar_index` is per-(instrument,timeframe) (§4.4; fixes Titan `_bar_index` defect by contract: no global counter exists in any schema). |
| `market.feed_staleness_changed` | `instrument:str, state:{FRESH,STALE,DEAD}, quote_age_ms:i64, expected_by_calendar:bool` (F-025: staleness judged against the calendar service). |

**feature.\***

| Schema | Payload |
|---|---|
| `feature.changed` | `instrument:str, timeframe:str, bar_ts:i64, epoch:u64, changed:[{key:FeatureKey, value:json}]` — **one batched event per (instrument, timeframe, bar close)**, not one per node (§4.6). `epoch` increments per batch; snapshots cite it. |
| `feature.state_persisted` | `manifest_id:uuid, keys:int, bytes:int` — DAG state checkpoint marker (§4.5). |
| `feature.rebuild_performed` | `keys:[FeatureKey], reason:{GAP,DUP,VERSION,CHECKSUM_FAIL}, source:{parquet,broker_backfill}, duration_ms:i64` (F-014 audit trail). |
| `regime.transition` | `instrument:str, timeframe:str, from:Regime, to:Regime, confidence:float, dwell_bars:int, published:bool` — only `published=true` transitions feed arbitration (Pass 2 §4.1). |

**signal.\* / confirm.\***

| Schema | Payload |
|---|---|
| `signal.generated` | Full signal object of 02§B1 **plus**: `signal_id:uuid, child_id:str, child_version:str, params_hash:str, instrument, direction, intent_type, level:float?, urgency, valid_until:i64, risk:{stop_price, tp_prices:[float], time_stop_bars:int?}, snapshot_epoch:u64` (snapshot by reference to the `feature.changed` epoch + a frozen copy — the "why" is stored once, cited twice). |
| `signal.state_changed` | `signal_id, from_state:SigState, to_state:SigState, cause:TransitionCause, resolved_by:str?, detail:json` — **the only way signal state changes**; emitted solely by the Signal Transition Actor (§2.1). |
| `risk.evaluated` | `signal_id, verdict:{APPROVED,REJECTED}, reject_reason:str?, approved_risk_frac:float?, lots:float?, ledger_after:LedgerSnapshot` — the ledger snapshot (§2.6 schema) rides on every verdict so every approval is audit-reconstructable (Auditor requirement). |
| `confirm.requested` | `signal_id, mode:{hybrid,manual}, timeout_at:i64?, card:json` (card = rendered snapshot, immutable). |
| `confirm.delivery_ack` | `signal_id, channel:{telegram,gui_ws}, ack_ts:i64` (F-009: at least one ack required or timeout degrades to skip). |
| `confirm.card_updated` | `signal_id, reason:{PARTIAL_FILL,FULL_FILL,SPREAD_GATE}, filled_lots:float?` — F-001 Auditor condition: the human must see what they are now approving; the update is an event so the audit trail shows what they saw. |
| `confirm.resolution_requested` | `signal_id, request:{APPROVE,REJECT,TIMEOUT_EXECUTE,TIMEOUT_SKIP,EXPIRE}, actor, request_ts:i64` — human taps, timeout timers, and the expiry sweeper all emit **requests**, never state (F-008). |
| `confirm.resolved` | `signal_id, outcome:{CONFIRMED,REJECTED_BY_HUMAN,TIMEOUT_EXECUTED,TIMEOUT_SKIPPED,EXPIRED,SUPERSEDED_BY_FILL}, resolved_by, race_losers:[actor]` — `race_losers` names actors whose requests arrived after resolution (F-008 UI-truth requirement). |

**exec.\*** (order-level; §2.2 machine)

| Schema | Payload |
|---|---|
| `exec.intent_persisted` | `client_key:str, signal_id, leg:{ENTRY,ENTRY_OCO_B,STOP,TP,CLOSE,MODIFY,CANCEL}, attempt:u8, order:CanonicalOrder` — **written before any broker call** (F-032; §3.1). |
| `exec.order_submitted` | `client_key, broker_call:{MARKET,LIMIT,STOP,MODIFY,CANCEL,CLOSE}, request:json, idempotency_key=client_key` |
| `exec.order_ack` | `client_key, ticket:i64, broker_ts:i64, working_price:float?` — patches the client_key↔ticket map. |
| `exec.order_reject` | `client_key, reason:RejectCode {STOPS_LEVEL, FREEZE, NO_MONEY, MARKET_CLOSED, INVALID_VOLUME, TRADE_DISABLED, REQUOTE, TIMEOUT_UNKNOWN, OTHER}, raw:json` |
| `exec.fill` | `client_key?, ticket:i64, deal_id:i64, lots:float, price:float, remaining_lots:float, kind:{PARTIAL,FULL}, broker_ts:i64` — `client_key` nullable because reconciliation can surface fills we can't attribute yet (F-032 quarantine path). |
| `exec.cancel_result` | `client_key, outcome:{CANCELLED, ALREADY_FILLED, ALREADY_CANCELLED, REJECTED}` — the F-010 "already filled" arm is a first-class outcome, not an error. |
| `exec.telemetry_sample` | `client_key, mechanism, requested_price, filled_price, slippage_ticks:int, latency_ms:int, requotes:int, spread_at_send_ticks:int, session:str` (03§A4 unchanged, tick-typed per F-003). |

**position.\* / risk.\* ledger / breaker.\***

| Schema | Payload |
|---|---|
| `position.opened` | `position_id:uuid, signal_id, child_id, instrument, direction, lots, entry_price, stop_price, tp_prices, approved_risk_frac, realized_risk_frac, gap_class:str, stop_verified:bool` — `realized_risk_frac` recomputed from actual fill (F-022). |
| `position.adjusted` | `position_id, kind:{STOP_MOVED,PARTIAL_CLOSE,TP_HIT_PARTIAL,RISK_TRIM}, detail:json` — `RISK_TRIM` is the F-022 partial-close-to-target action. |
| `position.stop_state` | `position_id, state:{VERIFIED, MISSING, ATTACH_RETRYING, ATTACH_FAILED}` — 02§A5 enforcement is observable (F-007 interacts here). |
| `position.closed` | `position_id, close_price, realized_R:float, pnl_ccy:float, closed_by:{bot,human:gui,human:tg,broker_stopout,quarantine_policy}, swap_ccy:float, commission_ccy:float` |
| `position.adopted` | `ticket, source:{RECON_ORPHAN, FILL_AFTER_INVALIDATION, VETO_RACE}, attributed_child:str?, quarantined:bool` (F-010/F-032). |
| `risk.limit_breached` | `limit_id:str, scope:str, value:float, cap:float, gross_or_net:str, action:{REJECT_SIGNAL,ALERT_ONLY}` (F-017: every breach names its counting semantics). |
| `breaker.transition` | `breaker_id, from:BrkState, to:BrkState, trigger:json, requires_ack:bool` (§2.4). |

**config.\* / broker.\* / recon.\* / health.\***

| Schema | Payload |
|---|---|
| `config.change_applied` | `change_id:uuid, actor, keys:[str], old:json, new:json, layer:{runtime}, reload_class:{live,next_signal,restart}, provenance:str` (04§B3/B4; F-026 provenance). |
| `config.change_rejected` | `change_id, errors:[{key,rule,message}]` |
| `broker.spec_changed` | `broker_id, instrument?, diffs:[{field, old, new, severity:{INFO,REVALIDATE_ORDERS,RECOMPUTE_LEDGER,BREAKER}}], open_positions_affected:int` (F-007 impact classes pre-computed at diff time; Pass 4 owns the analyzer). |
| `recon.run` | `run_id:uuid, kind:{STARTUP,PERIODIC,POST_RECONNECT,POST_SPEC_CHANGE}, diffs:[ReconDiff], duration_ms, verdict:{CLEAN,REPAIRED,QUARANTINE,REFUSE_TRADE}` (§3.3). |
| `snapshot.projection` | §1.3 below. |
| `health.metric` | `name, value:float, unit, state:{OK,WARN,CRIT}` — loop lag, WS clients, Telegram API, NTP offset, broker clock offset, disk, WAL size. |

### 1.3 F-004 integrity design (hash chain, snapshots, backup, verification)

**Chain.** As in §1.1: `prev_hash`/`row_hash` computed by the single writer inside the append transaction. Replay verifies (a) `seq` gapless, (b) chain continuity, (c) tail integrity (last row's hash recomputes). SQLite WAL torn-tail after power loss surfaces as either a clean rollback (fine) or a failed chain check (caught).

**Snapshots.** A `snapshot.projection` event is appended every **10,000 events or 24 h, whichever first (hypothesis cadence)**, containing the full projection: open positions (+realized/gap-stressed risk), working orders + client_key map, pending confirmations, breaker states, effective-config hash, feature-state manifest id (§4.5), ledger totals, and `chain_head` (seq + row_hash at snapshot time). Snapshot payloads > 256 KB are stored as a sidecar file `snapshots/<seq>.json.zst` with its SHA-256 in the event — the chain covers the hash, so sidecar corruption is detectable.

**Replay = last verified snapshot + tail.** Boot procedure:

```
verify_and_replay():
  head = read_last_row()
  snap = latest snapshot event with verifiable chain up to head
  walk chain from snap.seq to head:
      if seq gap OR hash mismatch OR undecodable row:
          -> INTEGRITY_FAIL: enter RECOVERY_REQUIRED
  project(snap); apply tail events in seq order
  run feature restart policy (§4.5, F-014)
  run STARTUP reconcile (§3.3)  # broker truth wins
  if any(verdict in {QUARANTINE, REFUSE_TRADE}) or INTEGRITY_FAIL:
      trading_disabled until human ack (kill paths + exits REMAIN available)
```

`RECOVERY_REQUIRED` behavior (binding, per Pass-1 rule 4): **refuse new trades**; reconstruct state from broker truth + last good snapshot; existing positions get stops verified and exits managed under a conservative default policy; human ack via GUI/Telegram required to resume signal generation. "Best-effort replay and go" is a forbidden code path.

**Growth & retention.** WAL: `PRAGMA busy_timeout=5000`, `synchronous=NORMAL`, checkpoint `TRUNCATE` every 60 s or 16 MB WAL (whichever first). Events older than the **second**-newest verified snapshot are eligible for archive: nightly job exports them to `archive/events-YYYYMM.parquet` (chain metadata included) and deletes from SQLite — replay time is bounded by snapshot cadence forever (fixes the "month-18 replay timeout" failure).

**Backup + verification job.** Nightly at 00:15 UTC: `VACUUM INTO` a dated copy → zstd → off-box (object storage / rsync target; two retained generations ≥ 30 days). The job then **restores the backup to a temp path and runs the full chain walk + a projection smoke-build**; a backup that fails verification raises CRITICAL. An unverified backup is treated as no backup (Auditor's rule).

**Corruption drills in CI** (§7.4): truncate mid-transaction; bit-flip a payload byte; bit-flip a `row_hash`; delete a middle row; corrupt the snapshot sidecar. Each must produce `RECOVERY_REQUIRED`, never a clean boot.

### 1.4 Log ownership (F-015 resolved)

**The core process is the sole writer to the events DB. Total.** The interface process never opens the DB read-write; it may open it `mode=ro` for warm reads (GUI history) and otherwise consumes the core's WS event stream. All interface-originated mutations (confirmations, commands, config changes) travel over the command channel (§8.5) into the core, where they become `confirm.resolution_requested` / command events **serialized through the same transition queue as everything else** — F-008 and F-015 collapse into one serialization point by construction. `busy_timeout` still set defensively; contention is now structurally impossible on the write path.

---

## §2 State machines

Notation: every table row is `from | event | guard | to | actions | emits`. Any (state, event) pair not listed is **logged-and-ignored** (`sm.unexpected_event` counter + WARN at rate) — never an exception, never a silent drop.

### 2.1 Signal lifecycle (F-001, F-008, F-009, F-010, F-035)

**States.** `GENERATED, RISK_APPROVED, AWAITING_CONFIRM, CONFIRMED, EXECUTING, WORKING, PARTIAL_PENDING_DECISION, FILLED_PENDING_DECISION, VETO_CLOSING` + terminals `REJECTED_BY_RISK, REJECTED_BY_HUMAN, VETO_CLOSED, TIMEOUT_SKIPPED, EXPIRED, INVALIDATED, FAILED, DONE(→position)`.
Flags on the signal record (not states): `resting:bool` (a broker order exists), `delivery_acked:bool` (F-009), `filled_lots:float`.

**Single transition owner (F-008 mechanism).** One asyncio task, the **Signal Transition Actor (STA)**, owns an in-process FIFO `transition_requests: asyncio.Queue`. Producers: risk engine, mode router, human commands (via command channel), timeout timers, the expiry sweeper, broker execution events (fills/rejects/cancel results), invalidation watchers. The STA processes one request at a time; guards are evaluated **inside** the handler against `ts_event` (so an expiry with earlier event-time beats a same-instant timeout-execute); each accepted transition appends `signal.state_changed` and updates the projection atomically. Losing requests emit `confirm.resolved.race_losers` so the UI tells the human the truth ("resolved by timeout before your tap").

**Expiry scope (F-035 adopted):** the expiry sweeper only enqueues `EXPIRE` for signals in `{GENERATED, RISK_APPROVED, AWAITING_CONFIRM, WORKING, PARTIAL_PENDING_DECISION*}` — post-fill lifetime is governed solely by the risk block. (*expiry of a partial cancels the remainder but routes the filled part through the veto policy, row 22.)

| # | From | Event | Guard | To | Actions | Emits |
|---|---|---|---|---|---|---|
| 1 | GENERATED | risk_verdict(APPROVED) | — | RISK_APPROVED | reserve ledger budget (approved figures) | risk.evaluated |
| 2 | GENERATED | risk_verdict(REJECTED) | — | REJECTED_BY_RISK | — | risk.evaluated |
| 3 | GENERATED/RISK_APPROVED | expire | valid_until ≤ ts_event | EXPIRED | release budget | signal.state_changed |
| 4 | RISK_APPROVED | route(auto) | breakers clear | EXECUTING | build order plan, hand to OMS | signal.state_changed |
| 5 | RISK_APPROVED | route(hybrid∣manual) | — | AWAITING_CONFIRM | create card; **if intent passive-limit and mode=hybrid: place resting order now (budget already reserved at row 1 — F-001 "reserve at placement")**; arm timeout (hybrid only); request delivery via both channels | confirm.requested, exec.intent_persisted? |
| 6 | AWAITING_CONFIRM | delivery_ack | first ack | AWAITING_CONFIRM | set delivery_acked | confirm.delivery_ack |
| 7 | AWAITING_CONFIRM | resolution_req(APPROVE) | not expired; not superseded | CONFIRMED | — | confirm.resolved |
| 8 | AWAITING_CONFIRM | resolution_req(REJECT) | resting=false | REJECTED_BY_HUMAN | release budget | confirm.resolved |
| 9 | AWAITING_CONFIRM | resolution_req(REJECT) | resting=true, filled_lots=0 | REJECTED_BY_HUMAN | cancel resting order (request; see row 20 race arm); release budget on `CANCELLED` | confirm.resolved, exec.order_submitted(CANCEL) |
| 10 | AWAITING_CONFIRM | timeout_fire | hybrid ∧ action=execute ∧ **delivery_acked** | CONFIRMED | resolved_by=timeout | confirm.resolved(TIMEOUT_EXECUTED) |
| 11 | AWAITING_CONFIRM | timeout_fire | hybrid ∧ action=execute ∧ **¬delivery_acked ∧ ¬execute_unacked** | TIMEOUT_SKIPPED | cancel any resting order; release budget; WARN "hybrid degraded to skip: no delivery ack" | confirm.resolved(TIMEOUT_SKIPPED) **(F-009 fail-closed)** |
| 12 | AWAITING_CONFIRM | timeout_fire | hybrid ∧ action=skip | TIMEOUT_SKIPPED | cancel resting; release budget | confirm.resolved |
| 13 | AWAITING_CONFIRM | expire | valid_until ≤ ts_event | EXPIRED | cancel resting; release budget | confirm.resolved(EXPIRED) |
| 14 | AWAITING_CONFIRM | invalidation | child.invalidation()=true | INVALIDATED | cancel resting (row 20 arm applies) | signal.state_changed |
| 15 | AWAITING_CONFIRM | fill(PARTIAL) | resting=true | **PARTIAL_PENDING_DECISION** | update filled_lots; **attach broker-side stop to filled portion immediately (02§A5 from first fill)**; update card | exec.fill, position.opened(partial), confirm.card_updated **(F-001)** |
| 16 | AWAITING_CONFIRM | fill(FULL) | resting=true | **FILLED_PENDING_DECISION** | attach stop; update card ("now a position — approve keeps, reject closes") | exec.fill, position.opened, confirm.card_updated |
| 17 | PARTIAL_PENDING_DECISION | resolution_req(APPROVE) | — | EXECUTING | remainder handled per urgency policy (leave working / convert / cancel, 03§A3.5) | confirm.resolved |
| 18 | PARTIAL_PENDING_DECISION ∣ FILLED_PENDING_DECISION | resolution_req(REJECT) | — | VETO_CLOSING | cancel remainder; **close filled portion at market via risk-managed close** | confirm.resolved, signal.state_changed(cause=VETO_AFTER_FILL) **(F-001 default policy)** |
| 19 | VETO_CLOSING | close_confirmed | — | VETO_CLOSED | release budget; learning-loop tag `veto_after_fill` | position.closed |
| 20 | any-with-cancel-pending | cancel_result(ALREADY_FILLED) | — | (state-dependent) | **F-010 arm:** if current=INVALIDATED/EXPIRED/REJECTED_BY_HUMAN → adopt position: attach frozen-risk stop, engage child `manage_position()`, tag `fill_after_invalidation`; else treat as fill event | exec.cancel_result, position.adopted |
| 21 | PARTIAL_PENDING_DECISION | timeout_fire ∣ expire | — | (as rows 10–13 for remainder) | remainder follows timeout/expiry action; **filled portion NEVER auto-closed by timeout — only explicit human veto closes it** (board decision, §9-3); if skipped/expired: remainder cancelled, filled portion → EXECUTING-equivalent adoption, child engaged | confirm.resolved |
| 22 | CONFIRMED | — (immediate) | breakers clear | EXECUTING | hand to OMS | signal.state_changed |
| 23 | EXECUTING | order_ack(pending order) | intent BREAKOUT/LIMIT | WORKING | invalidation watch + reprice manager armed | exec.order_ack |
| 24 | EXECUTING | fill(FULL) | market order | DONE | position lifecycle owns from here | position.opened |
| 25 | EXECUTING | order_reject(terminal) | retries exhausted | FAILED | release budget; alert WARN | exec.order_reject |
| 26 | WORKING | fill(PARTIAL/FULL) | — | DONE (full) / stays WORKING (partial, remainder policy) | position lifecycle engages per fill | exec.fill |
| 27 | WORKING | invalidation ∣ expire | — | INVALIDATED ∣ EXPIRED | cancel (row 20 arm live) | signal.state_changed |
| 28 | any non-terminal | breaker_trip(global pause) | — | (unchanged) | **breakers block only rows 4/5/22 entry actions; resting cancels and exits still run** (02§A4: never block exits) | breaker.transition |

**Mode-contract note (04§B4 preserved):** a mode hot-switch never rewrites signals already in AWAITING_CONFIRM; the STA reads the mode pinned on the signal record at route time.

### 2.2 Order lifecycle (place / modify / cancel)

Owned by the **Order Management actor (OMS)** — a second serialized task consuming an order-action queue; it is the only code that calls the broker adapter's write methods.

**States.** `DRAFT, INTENT_PERSISTED, SENDING, SENT_UNKNOWN, ACKED_WORKING, PARTIALLY_FILLED, FILLED, REJECTED, CANCEL_REQUESTED, CANCELLED, CANCEL_FAILED_FILLED, MODIFY_PENDING, LOST_LINK_PENDING_RECON, FAILED`.

| # | From | Event | Guard | To | Actions | Emits |
|---|---|---|---|---|---|---|
| 1 | DRAFT | submit_intent | specs fresh (≤1 h, F-023: `tick_value`/swap refreshed at signal time) | INTENT_PERSISTED | append `exec.intent_persisted` (client_key, full order) **before broker call** (F-032) | exec.intent_persisted |
| 2 | INTENT_PERSISTED | send | connection LIVE | SENDING | broker call with deadline 5 s (market) / 10 s (pending) | exec.order_submitted |
| 3 | SENDING | ack | — | ACKED_WORKING (pending) / FILLED (market) | patch client_key↔ticket map | exec.order_ack |
| 4 | SENDING | reject(REQUOTE) | attempts < 3 ∧ urgency≠passive ∧ requote_dev ≤ max_deviation | SENDING | resend **same client_key**, attempt+1, price refreshed | exec.order_reject(REQUOTE) |
| 5 | SENDING | reject(REQUOTE) | attempts ≥ 3 ∨ deviation gate fails | REJECTED | release; signal FAILED path | exec.order_reject |
| 6 | SENDING | reject(STOPS_LEVEL/FREEZE) | pending order | REJECTED | escalate to execution intelligence: synthetic-stop fallback decision (03§A1); if spec drift suspected → trigger spec re-discovery (F-007) | exec.order_reject |
| 7 | SENDING | reject(NO_MONEY) | — | REJECTED | CRITICAL alert (margin model disagrees with broker — F-005 ledger recheck forced) | exec.order_reject, risk.limit_breached |
| 8 | SENDING | timeout ∣ disconnect | — | SENT_UNKNOWN | **no retry with a new key, ever.** Schedule probe (§3.2) | health.metric |
| 9 | SENT_UNKNOWN | probe: found ticket | matched via client_key/inference | ACKED_WORKING ∣ FILLED | adopt outcome | recon.run(diff) |
| 10 | SENT_UNKNOWN | probe: not found after T_probe=30 s ∧ connection LIVE | — | FAILED | release budget; signal FAILED | recon.run |
| 11 | SENT_UNKNOWN | disconnect persists | — | LOST_LINK_PENDING_RECON | resolved only by POST_RECONNECT reconcile; **no new orders for this instrument meanwhile** | connection event |
| 12 | ACKED_WORKING | fill(PARTIAL) | — | PARTIALLY_FILLED | position partial-open; remainder per policy | exec.fill |
| 13 | ACKED_WORKING ∣ PARTIALLY_FILLED | fill(FULL/remainder) | — | FILLED | — | exec.fill |
| 14 | ACKED_WORKING | cancel_request | — | CANCEL_REQUESTED | broker cancel with deadline | exec.order_submitted(CANCEL) |
| 15 | CANCEL_REQUESTED | cancel_ok | — | CANCELLED | release remainder budget | exec.cancel_result(CANCELLED) |
| 16 | CANCEL_REQUESTED | cancel_reject(already filled) | — | CANCEL_FAILED_FILLED | route fill to STA row 20 (F-010) | exec.cancel_result(ALREADY_FILLED) |
| 17 | ACKED_WORKING | modify_request (reprice/SL/TP) | reprice ≥ min-reprice-distance; rate limiter clear (03§A3.3) | MODIFY_PENDING | broker modify | exec.order_submitted(MODIFY) |
| 18 | MODIFY_PENDING | modify_ok / modify_reject | — | ACKED_WORKING | on reject: if STOPS_LEVEL → F-007 path; stop-attach rejects escalate `position.stop_state=ATTACH_RETRYING` | exec.order_ack/reject |
| 19 | any | broker.spec_changed(REVALIDATE_ORDERS) | working orders exist | (re-enter validation) | re-check every working order + pending stop attachment against new specs; widen/convert/cancel per F-007 policy | broker.spec_changed |

**Disconnect-during-send** is rows 8/11: the order is in `SENT_UNKNOWN`/`LOST_LINK_PENDING_RECON` and the **reconciler, not the OMS, is the only actor allowed to resolve it** — this is what makes duplicate sends structurally impossible (§3).

### 2.3 Position lifecycle

**States.** `PENDING_OPEN, OPEN_STOP_UNVERIFIED, OPEN, REDUCING, CLOSING, CLOSED, QUARANTINED`.

| # | From | Event | Guard | To | Actions | Emits |
|---|---|---|---|---|---|---|
| 1 | — | fill (first) | — | PENDING_OPEN | recompute `realized_risk_frac` from actual entry (F-022); ledger swaps approved→realized figures | position.opened |
| 2 | PENDING_OPEN | stop_attach ok (or stop was in order) | — | OPEN | `stop_verified=true` | position.stop_state(VERIFIED) |
| 3 | PENDING_OPEN | stop_attach reject | attempts < 5 (backoff 1,2,4,8,16 s) | PENDING_OPEN | retry; if STOPS_LEVEL → widen to min legal distance **and** partial-close so risk-at-legal-stop ≤ approved (never just widen — F-022 principle: stop distance is thesis, size is the adjustable) | position.stop_state(ATTACH_RETRYING) |
| 4 | PENDING_OPEN | attach exhausted | — | OPEN_STOP_UNVERIFIED | CRITICAL alert; **protective close policy** per child config: default `close_now` for meanrev, `synthetic_watch + close_on_touch` for trend (operator-visible choice) | position.stop_state(ATTACH_FAILED) |
| 5 | OPEN | realized_risk > 1.25× approved | (F-022 threshold, hypothesis) | REDUCING | partial-close to target risk | position.adjusted(RISK_TRIM) |
| 6 | OPEN | manage_position() action | child owns exits (02§B6); **params pinned at fill via `params_hash`** (F-027) | OPEN/REDUCING | BE moves, trails, partial TPs, time-stops | position.adjusted |
| 7 | OPEN | human close (GUI/TG) | always allowed | CLOSING | market close; `closed_by=human` | position.closed |
| 8 | OPEN | broker fill(close) unseen by us | reconciler detects | CLOSED | "ghost close" adoption: P&L from deal history | recon.run, position.closed(closed_by=broker) |
| 9 | QUARANTINED (from adoption) | human attribution ∣ safety close | default policy: verify stop exists at k-safe distance, no adds, no scaling | OPEN(attributed) ∣ CLOSING | — | position.adopted |
| 10 | any open state | breaker(flat-only) | — | (unchanged) | new risk blocked; **exit management continues** | breaker.transition |

Ledger accounting per position (F-005/F-011/F-017 — three columns, always): `risk_at_stop`, `gap_stressed_risk = risk_at_stop × k(asset_class)` while held across a close-window (k: fx major 1.3, fx cross 1.5, metal 2.0, index CFD 3.0, crypto 1.0 weekend/1.5 liquidity-gap — all hypothesis, Pass 7 calibrates from gap distributions), `margin_used + notional`. BE positions: `risk_at_stop=0` but margin/notional/gap columns **never** zero out (F-005). Limits stack, each annotated gross/net (§2.6).

### 2.4 Breaker state machine (per breaker instance)

**States.** `ARMED, TRIPPED, COOLDOWN, ACK_WAIT`.

| From | Event | Guard | To | Actions |
|---|---|---|---|---|
| ARMED | trigger_condition | per-breaker (02§A4 + F-024 spec below) | TRIPPED | apply restriction (new-risk block scope per breaker); CRITICAL/WARN per class; Telegram+GUI |
| TRIPPED | auto_reset_condition | breaker.reset=automatic (daily loss: next trading day per calendar service; data-integrity: feed recovery) | COOLDOWN | restriction lifted after cooldown 15 min (hypothesis, anti-flap) |
| TRIPPED | human_ack | breaker.reset=manual (weekly, streak, DD, anomaly) | ACK_WAIT → ARMED | restriction lifted; ack actor logged |
| COOLDOWN | re-trigger | — | TRIPPED | counter++; 3 trips/24 h escalates severity one level |
| any | kill_command | — | (unchanged) | **kill paths bypass breaker machinery entirely** — flatten-all/pause-all are executable in every breaker state |

**F-024 anomaly breaker, specified:** metric `X_t` = account P&L in **R units** over a rolling 24 h window (realized + mark-to-market), recomputed each bar-close batch. Reference distribution: Monte-Carlo 24 h-window P&L from the **portfolio** backtest (Pass 7 artifact `mc_windows_24h.parquet`; refreshed at each re-validation). Trip: `X_t < P1` of the distribution → global pause + CRITICAL (manual reset); WARN at `< P5`. Per-child anomalies are **not** this breaker's job — they belong to the F-013 CUSUM machinery (no dedup drift). A child with no live history contributes its backtest stream to the portfolio MC — the breaker is defined from day one.

**Aggregation:** effective restriction = most restrictive across all TRIPPED breakers + manual overrides (02§B4 stack preserved).

### 2.5 Connection state machine (per link: quote stream, trade channel — tracked separately)

**States.** `DOWN, CONNECTING, UP_UNVERIFIED, LIVE, DEGRADED_STALE, RECONCILING`.

| From | Event | Guard | To | Actions |
|---|---|---|---|---|
| DOWN | connect_attempt | backoff schedule 1,2,4…60 s cap + jitter | CONNECTING | — |
| CONNECTING | connected | — | UP_UNVERIFIED | run verification: server clock offset vs NTP (alarm > 250 ms WARN / > 750 ms block new session-scoped entries — F-033), spec fingerprint vs cached (diff → F-007 path), account id match |
| UP_UNVERIFIED | verified | — | RECONCILING | POST_RECONNECT reconcile (§3.3) **before** any order flow resumes |
| RECONCILING | recon CLEAN/REPAIRED | — | LIVE | resume; resolve `LOST_LINK_PENDING_RECON` orders |
| RECONCILING | recon QUARANTINE/REFUSE | — | LIVE(restricted) | exits-only until human ack |
| LIVE | quote_age > calendar-expected threshold | per-instrument, session-aware (F-025) | DEGRADED_STALE | data-integrity breaker arms per 02§A4; **exits still allowed** |
| DEGRADED_STALE | quotes fresh | — | LIVE | breaker auto-reset path |
| LIVE | send/recv error ∣ heartbeat miss ×3 | — | DOWN | orders in flight → SENT_UNKNOWN handling; dead-man's-switch continues independently |

---

## §3 Idempotency & exactly-once order semantics

### 3.1 Client order-id scheme

```
client_key = "{cs}-{leg}-{attempt}"
  cs      = signal_id short form (uuid7 last 12 hex chars — collision-safe within retention)
  leg     ∈ {E, EB, S, T, C, M, X}   (entry, OCO-B entry, stop, tp, close, modify, cancel)
  attempt = 0..9  (requote resends share attempt; a NEW attempt is only minted after a
                   confirmed terminal reject — never after a timeout)
```

Carriage on MT5: `magic` = 32-bit registry id per `child_id@version` (assigned by the child registry, collision-checked at startup); `comment` = client_key best-effort (brokers truncate/mangle comments — F-032 — so the comment is a hint, never the authority). **The authority is the `exec.intent_persisted` row written before the broker call** plus the client_key↔ticket map patched at ack. This is Titan's send-time-mapping lesson (F-032) formalized: attribution never depends on broker-carried strings.

### 3.2 Dedup after timeout-with-unknown-outcome

The invariant: **an order intent is sent at most once per attempt, and a new attempt requires proof the previous one did not land.**

```
on SENT_UNKNOWN(client_key):
  for t in probe_schedule(2s, 5s, 10s, 30s):
      orders  = adapter.working_orders();  positions = adapter.positions()
      deals   = adapter.deals_since(intent.ts - 60s)
      hit = match_by(ticket_map) or match_by(magic, symbol, volume, side,
                     |price - intent.price| ≤ tolerance, ts ∈ [intent.ts, now])
      if hit:  adopt outcome (ACKED_WORKING / FILLED); patch map; return
      if trade_channel is LIVE and t == last:  mark FAILED; release budget; return
  # link still down:
  park as LOST_LINK_PENDING_RECON  # POST_RECONNECT reconcile owns it
```

If a duplicate is ever detected (two broker artifacts matching one client_key — e.g. a requote resend where the "rejected" first attempt actually landed): keep the **first** by broker time, immediately cancel/close the second at market, emit `recon.diff(DUPLICATE_EXECUTION)` CRITICAL. The learning loop counts these; > 0/month means the probe matcher needs tightening.

### 3.3 Reconciliation algorithm (broker truth wins)

Runs as: **STARTUP** (blocking, before trading), **POST_RECONNECT** (blocking for order flow), **PERIODIC** (every 60 s against heartbeat-fresh data; cheap diff, full pull every 10 min), **POST_SPEC_CHANGE** (F-007).

```
reconcile(kind):
  B = {positions, working_orders, deals since last recon checkpoint}   # broker truth
  L = projection {positions, working_orders, client_key→ticket map}    # log truth
  diffs = []
  for ticket in B.positions ∪ B.orders:
      if ticket in L:                                   # MATCHED — field check
          if fields_drift(sl, tp, volume, price):
              diffs += FIELD_DRIFT(ticket, deltas)
      else:
          k = infer_client_key(ticket)                  # map, then magic+attrs inference
          diffs += ORPHAN(ticket, attributed=k)         # BROKER_ONLY
  for item in L not in B:
      d = deals_explaining(item)                        # closed/cancelled while away?
      diffs += GHOST_CLOSED(item, d) if d else MISSING_AT_BROKER(item)
  resolve(diffs); emit recon.run(...)

resolve rules (in order):
  FIELD_DRIFT      → facts from broker (volume, prices) overwrite projection;
                     INTENTS re-asserted by us (a missing stop is re-attached; a
                     human-widened-at-terminal stop is adopted + WARN closed_by hint)
  GHOST_CLOSED     → position.closed(closed_by=broker) with P&L from deal history
  ORPHAN attributed→ adopt to its signal/child (F-010 / crash-window sends);
                     stop verified; child engaged
  ORPHAN unmatched → QUARANTINE book: verify/attach stop at conservative distance
                     (1.5×ATR, hypothesis), no adds, CRITICAL alert, human attribution
  MISSING_AT_BROKER→ if deals show it never existed: FAILED + budget release;
                     if inexplicable: REFUSE_TRADE verdict (projection can't be trusted)
  DUPLICATE_EXECUTION → §3.2 policy
```

**Alert taxonomy:** `FIELD_DRIFT` INFO (logged) unless stop-related (WARN); `GHOST_CLOSED` INFO; `ORPHAN attributed` WARN; `ORPHAN unmatched` CRITICAL; `MISSING_AT_BROKER inexplicable` CRITICAL + REFUSE_TRADE; `DUPLICATE_EXECUTION` CRITICAL. All recon events pierce quiet hours at CRITICAL per F-039 mapping.

The ledger (risk budgets, margin, notional) is **rebuilt from the post-reconcile projection**, never patched incrementally after a reconcile — one code path, always consistent (Auditor sign-off condition).

---

## §4 Feature-DAG implementation plan

### 4.1 Why REBUILD (vs Titan FeatureBus)

Titan's `src/features/feature_bus.py` is a **token-keyed memoized recompute DAG**: pure functions over a window, cache keyed `(name, symbol_key, token, version)`, latest-entry-only. Good bones (registration, cycle detection via DFS, topo evaluation, per-node stats) — wrong compute model for this system, which requires **persistent incremental state** (O(1) updates, serialize/restore, warmup tracking) and carries the known single-global-`_bar_index` defect in its surrounding integration. Verdict: **REBUILD the engine, ADAPT the registry/validation/stats surface** (§6.2).

### 4.2 Node contract

```python
class FeatureNode(ABC):
    key: FeatureKey            # frozen dataclass: (instrument, timeframe, name, params_hash, scope)
    STATE_VERSION: int         # bump on any state-layout change → forces rebuild (F-014)
    warmup_bars: int           # node reports not_ready until bar_count >= warmup_bars
    deps: tuple[FeatureKey, ...]

    def update(self, bar: Candle, dep_values: dict[FeatureKey, Any]) -> Any: ...
        # O(1); called exactly once per (instrument, tf) bar close, in topo order.
        # Must be pure w.r.t. (self.state, bar, dep_values) — no clocks, no I/O.
    def value(self) -> Any                      # last computed value (cheap; snapshot API)
    def serialize(self) -> bytes                # state + STATE_VERSION + last_bar_ts + bar_count
    @classmethod
    def deserialize(cls, blob) -> "FeatureNode" # raises StateVersionMismatch → rebuild path
```

`params_hash` (F-038 resolved): canonical JSON — sorted keys, numerics normalized (`20.0`→`20`, no exponent notation, `-0`→`0`), then SHA-256 first 16 hex. A unit test asserts `{n:20}` and `{n:20.0}` collide to one node. `scope ∈ {instrument_tf, instrument, portfolio}` — the **portfolio seam** (§4.7).

### 4.3 Incremental formulas — every v1 indicator

All operate on completed bars; `n` = period; state listed explicitly (it is what `serialize` persists).

| Node | State | Update (O(1)) | Warmup / notes |
|---|---|---|---|
| **EMA(n)** | `e` | `e += α(c − e)`, `α=2/(n+1)` | Seed with SMA of first n closes; `warmup=n`. |
| **SMA(n) / rolling var / BB(n,k)** | ring buffer `[n]`, `Σx`, `Σx²` | on push: `Σx += new − old; Σx² += new² − old²`; `μ=Σx/n`; `σ²=max(0, Σx²/n − μ²)`; `BB±=μ±kσ` | Drift control: every 10,000 bars recompute `Σx, Σx²` from the buffer (kills float accumulation); property test §7.2 pins incremental==batch. |
| **Wilder ATR(n)** | `atr`, `prev_close` | `TR=max(h−l, |h−pc|, |l−pc|)`; `atr=(atr(n−1)+TR)/n` | Seed = SMA of first n TRs; `warmup=n+1`. |
| **Wilder RSI(n)** | `avg_gain, avg_loss, prev_close` | `g=max(Δ,0), l=max(−Δ,0)`; Wilder-smooth both; `RSI=100−100/(1+g̅/l̅)` (`l̅=0 → 100`) | RSI(2) same node, `n=2`. |
| **ADX(n)** | `atr_state, sm_pdm, sm_ndm, adx, prev_h/l/c` | `+DM/−DM` classic; Wilder-smooth; `DI±=100·smDM/ATR`; `DX=100·|DI+−DI−|/(DI++DI−)`; `adx=(adx(n−1)+DX)/n` | `warmup=2n`; the internal ATR is **shared via dep** on the ATR node (compute-once, 04§A1). |
| **Donchian(n)** | two monotonic deques of `(bar_index, val)` | push-pop dominated entries; pop-front while `front.bar_index ≤ i−n` | `bar_index` is the **per-(instrument,tf)** index (§4.4). O(1) amortized. |
| **ATR-percentile(90 d)** | ring buffer of daily ATR `[90]` + sorted list (bisect) | on daily roll: remove oldest from sorted (bisect), insert newest; percentile of current = `bisect_rank/len` | Exact, O(log 90); driven by the D1 stream of the same instrument (cross-tf dep). |
| **Efficiency ratio(n)** | ring `|Δc|` `[n]`, `Σ|Δc|`, `close[i−n]` (from ring of closes) | `ER = |c − c_{i−n}| / Σ|Δc|` (0 if denom 0) | `warmup=n+1`. |
| **EWMA vol (λ=0.94)** | `σ²`, `prev_close` | `r=ln(c/pc)`; `σ² = λσ² + (1−λ)r²` | Pass 2 E1; the canonical sizing/forecast vol. One float of state. |
| **Session-range stats** | per-session Welford `(n, mean, M2)` for {range, spread, realized vol} + current-session running hi/lo + ring of last 60 session ranges | on tick/bar: update current-session hi/lo; **on `session.boundary` event from the calendar service** (F-006 — hard dependency, Pass 4 spec): close current session into Welford + ring, reset trackers | Keyed `(instrument, session_id)`; consumed by spread gate, M1/M2/T4/M4, and M4's open-window spread model (Pass 2 §3.4e). |
| **Regime composite (E0)** | last published label, candidate label, dwell counter `[0..3]`, hysteresis flags per input | per Pass 2 §4.1: agreement scores → confidence; candidate must persist 3 bars to publish (1 bar into CHAOS/DEAD); consumes ADX, ER, ATR-pct, EMA50/200 as deps | Emits `regime.transition(published=…)`; state is 4 small fields — fully serializable. |

### 4.4 Per-symbol bar indexing (Titan defect fixed by design)

A **BarClock per (instrument, timeframe)** lives in the ingest layer: it owns `bar_index: u64` (count of completed bars since stream genesis) and `last_bar_ts`. Rules: (i) `bar_index` increments only when a bar with `bar_ts == expected_next(bar_ts_prev, tf, calendar)` is committed; (ii) any other `bar_ts` → gap/duplicate handling (§4.5), never a silent increment; (iii) the tuple `(instrument, tf, bar_index, bar_ts)` rides on `market.candle_closed` and is the only bar identity any node ever sees. There is no module-level or engine-level counter anywhere — the defect class is unrepresentable, and a property test (§7.2) interleaves multi-symbol streams and asserts per-key indices are independent.

### 4.5 F-014 restart policy (persisted state + gap detection + rebuild trigger)

- **Persist:** full DAG state manifest (all `serialize()` blobs + `STATE_VERSION`s + each key's `last_bar_ts`/`bar_count`) written at the §1.3 snapshot cadence and at clean shutdown; manifest id cited by `snapshot.projection`.
- **On restart:** for each (instrument, tf): fetch bars from broker backfill + cold lake covering `[last_bar_ts, now]`. The **replay validator** checks the sequence against the calendar service's expected bar grid *before any state mutation*: contiguous & duplicate-free → incremental catch-up (`update()` per bar). Any gap, duplicate, out-of-order bar, or `StateVersionMismatch` → **refuse the incremental patch; rebuild the affected key subtree** from cold Parquet + fresh backfill (bounded: deepest warmup ≈ 90 d of D1 + `2n` of the largest intraday window — seconds to low minutes), emitting `feature.rebuild_performed`.
- **Checksum canary:** post-replay, recompute a sampled window (last 200 bars, 3 random instruments/tfs) from scratch and compare node values within `1e-9` relative tolerance; mismatch → rebuild those keys + WARN (a canary failure twice in a row is a bug, CRITICAL).

### 4.6 DAG scheduling & FEATURE_CHANGED fan-out contract

- Topo order computed once per (instrument, timeframe) subgraph at startup/config-reload (child `required_features()` collection, dedup by `params_hash`).
- `market.candle_closed(instrument, tf)` → execute that subgraph sequentially in topo order (CPU-trivial: tens of O(1) updates), **plus** registered cross-tf dependents (e.g. ATR-percentile's D1 feed) via explicit cross-tf edges.
- Fan-out: **one** `feature.changed` batch per (instrument, tf, bar) with all changed keys + `epoch`. Children subscribe with a key-set; the dispatcher wakes a child iff intersection non-empty **and** `pre_filter(ctx)` passes (04§A2 preserved). Snapshot freezing for signals = `(epoch, frozen dict copy)` — cheap, immutable, and the epoch ties the "why" to an exact DAG evaluation.
- **F-028 discipline:** DAG updates and children run on the loop with a per-callback wall-clock budget of 50 ms (hypothesis); breaches counted + WARN. CPU-heavy work (T3/TC-2 universe evaluation, backtest warmups, MC computations) goes to a `ProcessPoolExecutor` — the loop only awaits. `loop_lag_ms` (timer-drift probe) exported: WARN > 100 ms, CRITICAL > 500 ms.

### 4.7 Portfolio-scope seam (Pass 2 §4.4/§5.4 named need)

Shipped in v1 as **architecture, not features**: (i) `FeatureKey.scope` includes `portfolio`; (ii) the scheduler exposes a **barrier hook** — after all per-instrument subgraphs for a wall-clock grid slot (e.g. all M5 closes within [t, t+ε)) complete or a staleness deadline passes, portfolio-scope nodes run with a `dep_values` map carrying each instrument's latest value + `staleness_bars` marks (the sync policy E3 lacked, now defined: *barrier with staleness marks, deadline = 25% of the grid period*); (iii) `feature.changed` for portfolio nodes carries `instrument="__portfolio__"`. E3 (risk-on/off) and MC-2 (pair divergence) slot in here in v2 with zero engine changes. No portfolio node ships in v1 (board holds Pass 2's DEFER).

---

## §2.6 (addendum, placed here to keep §1–§4 numbering stable) — Exposure ledger & limit semantics (F-005, F-011, F-017, F-019, F-034, F-036)

**LedgerSnapshot schema** (rides on every `risk.evaluated`, §1.2):

| Field | Type | Semantics |
|---|---|---|
| `positions[]` | rows | `{position_id, child_id, instrument, direction, lots, risk_at_stop:frac, gap_stressed:frac, margin_ccy, notional_ccy, asset_class:str, groups:[str], factor_loadings:{usd:int, risk_app:int}}` |
| `totals` | obj | every limit scope's current gross/net value, computed by the declared aggregation below |
| `resting_reserved` | frac | budget reserved for resting/AWAITING_CONFIRM orders (F-001: reserved at placement) |

**The limit stack, with counting semantics declared per limit (F-017 resolved):**

| # | Limit | Default | Gross/Net | Aggregation | Notes |
|---|---|---|---|---|---|
| 1 | Per-trade risk | 0.5% (hard cap 1.0%) | n/a | single trade | `effective_risk = min(risk_pct × vol_scalar, hard_cap)` — **F-034 re-clamp**, enforced in `risk/sizing.py`, asserted by Pydantic cross-field rule + pinned unit test |
| 2 | Per-instrument open risk | 1.5% | **gross** | Σ\|risk_at_stop\| all children | hedged same-instrument books are impossible anyway under F-002 default |
| 3 | Per-child open risk | 2.0% | **gross** | Σ across its instruments | |
| 4 | Per-asset-class | 4.0% | **gross** | Σ\|risk\| | membership **exactly one** class per instrument, config-validated (F-017) |
| 5 | Per-correlation-group | 4.0% | **net (signed)** | Σ signed risk | zero-or-more group memberships, explicit in config, validated |
| 6 | **Macro-factor caps (new)** | \|net\| ≤ 5% each (hypothesis) | **net (signed)** | Σ risk × loading | static loadings ∈ {−1,0,+1} per instrument for `usd_factor`, `risk_appetite` — closes the F-017 risk-on/safe-haven hole (long risk-on + short safe-haven now counts once, at 8%, and is blocked); loadings in config, the two Pass-1 register examples are unit tests |
| 7 | Account total open risk | 8.0% | **gross** | Σ\|risk_at_stop\| | sub-budgets: trend sleeve 55% / meanrev 35% / probation reserve 10% (Pass 2 §6.3) |
| 8 | **Gap-stressed account total (new)** | ≤ 12% (hypothesis) | gross | Σ gap_stressed | k per class (§2.3); **sleeve-level**: trend-sleeve gap-stressed ≤ 6% (Pass 2 §6.4-5) — binds on Fridays for index CFDs, by design |
| 9 | **Margin utilization (new, F-005)** | ≤ 25% (hypothesis) | gross | Σ margin / equity | BE positions keep counting forever |
| 10 | **Notional per class (new, F-005)** | fx 6× / metal 3× / index 2× / crypto 1× equity (hypothesis) | gross | Σ notional | |
| 11 | Max positions | 12 | count | | sanity backstop |

Checked in numeric order; first failure rejects with `risk.limit_breached` naming the limit and its counting semantics. **F-036 resolved:** config validation emits a *binding-order report* — which limits can mathematically bind at current settings (at defaults, #7 cannot bind pre-gap-stress since 12 × 0.5% = 6% < 8%; the report prints "limit #7 dead under current #1/#11 — binding limits: #2,#4,#6,#8,#9"), so dead limits are visible instead of assumed.

**F-019 resolved:** the 5-minute opposing-intent netting rule applies **only to intents in pre-route states** `{GENERATED, RISK_APPROVED}` — both cancel, `conflict` event logged. An opposing intent against an **open position or any post-route signal** is a distinct `POSITION_CONFLICT`: default **block the new intent + log** (v1); regime-priority override (01§5.2) is a config option deferred until the F-002 tranche design exists, since acting on it implies netting semantics.

---

## §5 Backtester architecture

### 5.1 Event parity: one kernel, three entrypoints (00 build order preserved)

The backtester is **not a second implementation** — it is the same composition root (`core/controller.py`) assembled with three substitutions:

| Live component | Backtest substitution | Contract |
|---|---|---|
| `LiveClock` (monotonic + NTP wall) | `SimClock` — virtual time advanced by the data feeder; **all** timers (hybrid timeouts, expiry sweeper, breaker cooldowns, probe schedules) schedule via the `Clock` protocol (`now_ns()`, `call_at(ts, cb)`), so lifecycle timing replays deterministically | `core/clock.py` |
| `MT5BridgeAdapter` | `SimBrokerAdapter` (same `BrokerAdapter` protocol) | §5.2 |
| Interface processes | `ConfirmationPolicy` scripts | §5.3 |

Everything else — EventBus, feature DAG, risk ledger + breakers, STA, OMS, reconciler, event log (a per-run SQLite with the **same hash chain**) — is byte-identical code. Non-negotiable principle 00-§3 ("same engine, zero drift") is thereby structural, and the F-004 corruption drills run against backtest-produced logs too.

### 5.2 Simulated adapter & the Pass-4 execution-simulator plug point

```python
class SimBrokerAdapter(BrokerAdapter):
    def __init__(self, feed: BarTickFeed, fill_model: FillModel,
                 cost_model: CostModel, account: SimAccount, specs: BrokerProfile): ...

class FillModel(Protocol):                      # ← Pass 4's execution simulator implements this
    def on_order(self, order, market_state) -> list[SimEvent]: ...   # ack/reject/requote/fill(partial)
    def on_bar(self, working_orders, bar) -> list[SimEvent]: ...     # resting-order triggers within-bar
```

v1 ships `ConservativeFillModel` (the floor, F-029): market orders fill at `price ± ½spread ± slippage_draw(mechanism, session)`; **limit fills require trade-through ≥ 1 tick + adverse-selection charge** (F-012 — touch-fills are unrepresentable); stop entries slip by the mechanism's slippage distribution; requote probability per (session, vol-state); partial-fill probability per order size vs `liquidity_proxy`; **OCO double-fill simulation** from M1 path data with measured `f_df`/`c_df` outputs (F-021 kill-term inputs). Pass 4's richer simulator (queue effects, spec constraints `stops_level`/`freeze_level`, disconnect injection) replaces the class behind the same protocol — nothing above the seam changes. Intra-bar ambiguity (stop and limit both touchable in one bar) resolves **pessimistically** (stop first) unless M1/tick sub-data resolves the path — the choice is recorded per-trade in artifacts.

### 5.3 Confirmation policies (mode paths exercised, never bypassed)

`ConfirmationPolicy ∈ {auto_approve, always_skip, scripted(latency_dist, approve_rate), replay(journal)}` — hybrid/manual code paths (card creation, delivery-ack, timeout, F-001 partial-fill edges) execute in backtest with simulated resolution requests through the **same STA queue**. G1 runs use `auto_approve` (edge measurement must not depend on simulated humans); the F-001/F-008 scenario suite (§7.3) uses `scripted` with adversarial latencies.

### 5.4 Cost-model injection

`CostModel` is a versioned, serialized object: per (instrument, session) spread distributions, per-mechanism slippage distributions, commission, swap schedule incl. triple-swap day, adverse-selection term. Sources: conservative literature-informed priors pre-live → measured execution-profile data (03§A4) with priors as floors (F-029). The **same object** feeds the SimBroker fills and the F-003 viability gate; `cost_model_version` is pinned in the run manifest so any backtest is auditable against the exact cost assumptions it consumed (F-029 pinning requirement).

### 5.5 Determinism, seeding, artifacts

- **Run manifest (run-card, BORROWED from Titan's proven `research_run` pattern):** `{run_id, git_sha, config_hash, dataset_manifest_hash, cost_model_version, fill_model_version, seed, clock_range}`. One master seed → per-component child seeds (fill draws, MC). Same manifest ⇒ bit-identical `events` log (asserted in CI).
- **Frozen lake:** `research/lake/` Parquet partitioned instrument/year + a **committed** manifest (checksums, ranges) — Titan's frozen-lake pattern adopted *with the lesson applied*: the manifest is in git (Titan's was gitignored and it nearly cost a gate dataset — memory-recorded advisory).
- **Artifacts per run:** `events.sqlite` (full chained log — replayable, corruptable-for-drills), `trades.parquet`, `metrics.json` (G1 gate inputs: OOS PF, max DD, trade count, WF efficiency, parameter-plateau grid, regime-sliced P&L), `cost_waterfall.json` per child (gross → spread → slippage → double-fill → swap → net; mandatory for T4/M4 per Pass 2), `mc_windows_24h.parquet` (F-024 breaker reference).

### 5.6 Golden-replay parity (Titan kernel-replay mapped)

Titan's `src/research/kernel_replay.py` proved element-for-element parity by driving the *live* controller class with stubbed edges. Our version inverts the direction but keeps the discipline: a **live/demo session's event journal** (candles + signals + feature epochs) is replayed through the backtest kernel fed the same candles; the parity test diffs `(bar_index, feature values at epoch, signal_id-less signal tuples: child, instrument, direction, level, stop, tp)` element-for-element, tolerance zero. Runs in CI on a pinned golden fixture + nightly on the previous demo day. Any diff = kernel drift = merge-blocking.

---

## §6 Repository module tree (verdicts vs Titan)

### 6.1 Tree — one-line responsibility each; verdict tags [B]=BORROW [A]=ADAPT [R]=REBUILD

```
tradebot/
├── pyproject.toml                  # py3.12; deps: pydantic, fastapi, uvicorn[standard]+websockets, httpx, pyarrow, numpy, python-telegram-bot, zstandard
├── config/
│   ├── defaults.yaml               # shipped safe defaults (04§B1)                                  [R]
│   ├── broker/                     # discovery overlays per broker_id                               [R]
│   └── schema.py                   # Pydantic validation: caps, F-034 re-clamp, F-017 memberships,
│                                   #   F-036 binding-order report, reload-class tagging            [R]
├── core/
│   ├── clock.py                    # Clock protocol; LiveClock (monotonic+NTP), SimClock           [R]
│   ├── bus.py                      # typed sync in-order bus, per-sub stats/circuit               [A: src/core/bus.py — keep deterministic sync delivery + stats; ADD two subscriber tiers: `critical` subscribers (risk, OMS, journal) are never circuit-broken — their exception halts-and-alerts instead of being swallowed]
│   ├── events.py                   # §1 envelope + schema registry + canonical JSON + upcasters    [R]
│   ├── event_log.py                # sole-writer chained SQLite log, snapshots, archive            [R engine; A: WAL/pragma/persistent-conn discipline from src/core/state_manager.py]
│   ├── projection.py               # in-memory state = fold(events); rebuilt post-recon (§3.3)     [R]
│   ├── sta.py                      # Signal Transition Actor: the one serialized owner (§2.1)      [R]
│   ├── recovery.py                 # verify_and_replay, RECOVERY_REQUIRED, boot sequence (§1.3)    [R]
│   └── controller.py               # asyncio composition root; per-callback budget + loop-lag (F-028) [R]
├── features/
│   ├── registry.py                 # node registration, dep validation, cycle check, topo, stats   [A: feature_bus.py registry/validate/stats — proven]
│   ├── engine.py                   # incremental scheduler, batched feature.changed, barrier hook (§4.6/4.7) [R: memoized-recompute model replaced by persistent incremental state]
│   ├── barclock.py                 # per-(instrument,tf) BarClock (§4.4 — Titan _bar_index defect unrepresentable) [R]
│   ├── state_store.py              # serialize/restore manifests + F-014 validator + canary        [R]
│   └── nodes/                      # one file per §4.3 indicator + regime composite (E0)           [R]
├── calendar_svc/                   # F-006 owned-time service: IANA sessions, DST windows, broker
│   │                               #   offset verification, expected-bar grids  (SPEC: Pass 4)     [R]
├── strategies/
│   ├── base.py                     # ChildStrategy ABC (01§1) + pinned-params contract (F-027)     [R]
│   ├── registry.py                 # child_id@version → magic id; version immutability (01§6)      [R]
│   └── children/                   # T1, TC-2, M2, M1 … in Pass-2 §8 build order                  [R]
├── risk/
│   ├── sizing.py                   # tick_value/tick_size sizing, Decimal precision, round-down,
│   │                               #   fail-safe 0-lots on missing/stale specs, normalize_price    [A: src/risk/risk_manager.py — the sizing math, quantized normalize_price and fail-safe philosophy survive; the class (equity tracking, report metrics, config coupling) does not]
│   ├── ledger.py                   # §2.6 three-column ledger + declared gross/net limit stack     [R]
│   ├── breakers.py                 # §2.4 machines incl. F-024 anomaly                             [R]
│   └── viability.py                # F-003 tick-unit gate w/ hysteresis                            [R]
├── execution/
│   ├── intelligence.py             # intent→mechanism, spread gate (ticks), OCO mgr, repricer (03§A) [R]
│   ├── oms.py                      # §2.2 order machine, §3 client_key/probe/dedup                 [R]
│   ├── reconcile.py                # §3.3 algorithm + quarantine book                              [R]
│   └── adapters/
│       ├── base.py                 # BrokerAdapter protocol + canonical types                      [A: src/execution/broker/base.py + types.py — clean async Protocol, UTC datetimes, OrderResult convention; extended with discovery/spec/deal-history methods]
│       ├── mt5_bridge.py           # HTTP client to Windows bridge; URL autoresolve; writes-never-
│       │                           #   auto-retry (feeds SENT_UNKNOWN, §3.2)                       [B: src/execution/broker/mt5_http.py — the no-retry-on-writes rule is exactly our invariant]
│       └── sim.py                  # SimBrokerAdapter + FillModel seam (§5.2)                      [R]
├── bridge_win/                     # Windows-side FastAPI MT5 bridge (:8766, token, circuit)       [B: bridge/ — deployed and proven; add /deals_since, /specs_full, clock endpoint for §2.5 verification]
├── interfaces/
│   ├── api/                        # interface-process FastAPI: GUI serving, WS relay, read-only DB [A: src/ops/web/ — first-frame WS auth, tape-audited mutations (GuiActionExecuted pattern), layered live/restart config tiers, fake-controller dev mode all survive; command execution moves behind the core command channel (§8.5) instead of in-process calls]
│   ├── telegram/                   # bot, cards, delivery-acks (F-009), allowlist, confirm-TTL     [A: src/ops/telemetry.py + telegram_format.py — session pooling, retry/backoff, destructive-confirm TTL kept; command surface rebuilt on the command channel]
│   └── confirm_view.py             # read-model of pending confirmations (resolution is core-side) [R]
├── ops/
│   ├── journal.py                  # golden tape: subscribe-all JSONL, tick sampling               [B: src/ops/event_journal.py — pattern as-is over the new envelope]
│   ├── health.py                   # NTP/broker-clock offsets, loop lag, deadman ping, disk/WAL    [A: src/ops/health.py]
│   └── backup.py                   # §1.3 nightly VACUUM INTO + restore-verify + offbox ship       [R]
├── research/
│   ├── backtester.py               # §5 composition; walk-forward driver                           [R]
│   ├── kernel_replay.py            # §5.6 golden parity seam                                       [B: src/research/kernel_replay.py pattern — GOLDEN_FIELDS element diff, stubbed edges]
│   ├── runcard.py                  # manifest-pinned research CLI                                  [B: Titan research_run pattern]
│   ├── costmodel.py                # §5.4 versioned cost models, priors-as-floors                  [R]
│   └── lake/                       # frozen Parquet + COMMITTED manifest                           [B pattern, lesson applied]
├── frontend/                       # Vite+React+TS SPA served by interfaces/api                    [A: Titan frontend/ — shell, design system, WS store, settings/tier badges; new pages per 05§A1]
└── tests/                          # §7: unit/ property/ sim_scenarios/ chaos/ golden/             [R; A: Titan's uvicorn-websockets guard test ported — the "TestClient masks a dead /ws" regression is pinned forever]
```

### 6.2 Verdict summary vs the named prior-art list

| Titan component | Verdict | Rationale (from skim) |
|---|---|---|
| Broker-spec sizing (`src/risk/risk_manager.py`) | **ADAPT** | Keep: tick_value/tick_size math, step-quantized `normalize_price` with Decimal precision (survives `1e-05` ticks), fail-safe 0-lots on missing specs. Drop: config coupling, equity/report state, `InstrumentHelper` pip fallback (violates "no pip in core"). |
| Control GUI Phase 1 (`src/ops/web/` + `frontend/`) | **ADAPT** | Embedded FastAPI+WS, first-frame WS auth, tape-audited mutations, layered config, fake-controller dev harness, websockets-dep guard test: all proven, all kept. Changed: command execution routes through the §8.5 authenticated command channel into the core (F-015/F-031), not in-process controller calls. |
| Telegram ops (`src/ops/telemetry.py`) | **ADAPT** | Session pooling, retry/backoff, allowlist, 30 s destructive-confirm TTL kept; add delivery-acks (F-009), quiet-hours/severity mapping (F-039), command-channel rebase. |
| Windows FastAPI MT5 bridge (`bridge/`, :8766) | **BORROW** | Deployed, tokened, circuit-breakered; the F-016 default topology's cornerstone. Extend endpoints (deals, full specs, server clock). |
| Linux Broker client (`src/execution/broker/`) | **BORROW/ADAPT** | `mt5_http.py` borrowed nearly whole (URL autoresolve, writes-never-retry); `base.py`/`types.py` protocol adapted with discovery + deal-history additions. |
| FeatureBus (`src/features/`) | **REBUILD** (registry ADAPTed) | Memoized-recompute cache model ≠ required persistent incremental state; `_bar_index` defect fixed by BarClock design, not patching. Registry/cycle-check/stats surface survives. |
| SQLite-WAL state manager (`src/core/state_manager.py`) | **ADAPT (pattern only)** | Persistent-connection + WAL discipline kept; table schema replaced entirely by the chained event log + projections. |
| v15 event bus (`src/core/bus.py`) | **ADAPT** | Deterministic sync in-order delivery + stats + circuit breaker kept; add typed envelope integration and a `critical` subscriber tier that is never silently circuit-broken (risk/OMS/journal failures must halt-and-alert, not be swallowed). |
| Research/replay (`kernel_replay.py`, `event_journal.py`, frozen lake, run-cards) | **BORROW** | Proven element-for-element parity + golden tape + manifest-pinned runs; adopted as §5.5–5.6 with the commit-the-manifest lesson applied. |

---

## §7 Testing pyramid

### 7.1 Unit (base of the pyramid)

Per-module; notable mandatory suites: every §4.3 node vs reference batch implementations; sizing round-down cases incl. `POSITION_TOO_SMALL`; F-003 gate arithmetic (incl. the Pass-1 register's 30%-win-rate example as a regression test — the gate must fire); STA guard evaluation on event-time (expiry-beats-timeout same-instant case); F-017's two register examples (gold double-count; risk-on/safe-haven macro bet blocked by limit #6); F-034 composed-cap pin; reject-code taxonomy mapping.

### 7.2 Property-based (hypothesis lib) — named invariants

| ID | Invariant |
|---|---|
| P1 | **Incremental == batch:** for every feature node, random bar streams (incl. gaps rejected by validator) → incremental state values equal from-scratch recompute within 1e-9 relative. The single most valuable test in the repo (guards F-014's premise). |
| P2 | Sizing: `lots ≤ risk_amount / value_per_lot` always (round-down never exceeds); lots on the volume-step grid; 0 when specs missing/stale. |
| P3 | Ledger conservation: after any generated event sequence, per-scope totals equal the fold over position rows; BE transitions never reduce margin/notional columns (F-005). |
| P4 | Hash chain: any single-byte mutation, row deletion, or truncation of a generated log is detected by `verify_and_replay` (F-004). |
| P5 | State machines: no transition out of terminal states; every (state,event) either matched or counted-ignored — fuzz random event interleavings through the STA. |
| P6 | Projection idempotency: replaying a log twice, or a log with writer-side duplicate-key drops, yields identical projections. |
| P7 | `params_hash`: equivalent params ({n:20} vs {n:20.0}, key order) collide; distinct params never collide (F-038). |
| P8 | `normalize_price` results always on the tick grid, incl. 0.25/0.05 and 1e-05 ticks. |
| P9 | BarClock independence: interleaved multi-symbol streams → per-key indices unaffected by other symbols (the Titan-defect test). |
| P10 | Reconcile: for random (broker-truth, projection) divergence pairs, resolve() output restores projection == broker facts, and every diff got exactly one classification. |

### 7.3 Simulation scenario library (every CRITICAL finding has its failure scenario; run on the §5 kernel)

| Scenario | Finding | Pass criterion |
|---|---|---|
| Partial fill during AWAITING_CONFIRM, then human Reject | F-001 | remainder cancelled, filled part closed via VETO_CLOSING, stop existed from first fill, card_updated event precedes resolution |
| Full fill during confirm, timeout skip | F-001 | position adopted + managed (row 21), never auto-closed |
| Netting account discovered | F-002 | degraded mode engaged; 2nd child intent on same instrument → POSITION_CONFLICT, no trade |
| Marked-up broker, scalpy child | F-003 | viability gate disables the child; the inert-gate regression cannot recur |
| Truncated / bit-flipped / snapshot-corrupt log at boot | F-004 | RECOVERY_REQUIRED; refuses new trades; exits available |
| 6 positions trailed to BE, 7th signal wave | F-005 | margin/notional/gap limits reject despite risk-at-stop ≈ 0 |
| DST mismatch weeks (both windows) | F-006 | session children blocked per Pass-2 rule; named test dates |
| `stops_level` 10→50 with resting limit | F-007 | attach-reject path → widen+partial-close or cancel; no stopless position |
| Confirm race storm: timeout+expiry+human within 300 ms ×100 seeds | F-008 | exactly one resolution; race_losers reported; expiry beats same-instant execute |
| Telegram outage + GUI closed, hybrid execute-on-timeout | F-009 | TIMEOUT_SKIPPED + WARN (fail-closed); with `execute_unacked:true` → executes |
| Cancel sent, broker already filled | F-010 | ALREADY_FILLED arm adopts position, stop attached, child engaged |
| Weekend 3×ATR gap on index CFD book | F-011 | gap-stressed budget bound pre-Friday; Monday loss within stressed budget |
| Requote storm (5 consecutive) | §2.2 r4–5 | ≤3 resends, same client_key, then REJECTED |
| Send-timeout, order actually landed | §3.2 | probe adopts; zero duplicate orders |
| OCO double-fill within grace window | F-021 | twin flattened; f_df/c_df counted into cost waterfall |
| Fill slips realized risk to 1.4× approved | F-022 | RISK_TRIM partial-close; stop untouched |
| 24 h P&L below MC P1 | F-024 | anomaly breaker global pause, manual reset |
| DAX overnight (calendar-legit stale) vs mid-session feed death | F-025 | no false trip; true trip < 2 min |

### 7.4 Chaos tier — the kill-9 drill as automated CI (05§C made real)

**Harness:** docker-compose: `core` container + `simbroker` service (SimBrokerAdapter server-ized behind the same HTTP wire as `bridge_win`) + `toxiproxy` between them. Scenario driver: warm up 2 children on 3 instruments; open 3 positions (one at BE), 1 resting limit, 1 signal parked in AWAITING_CONFIRM; then `kill -9` the core at a **randomized injection point** (phase-tagged via test hooks: mid-order-send, post-send-pre-ack, mid-log-commit, mid-snapshot-write); restart the container.

**Assertions (all must hold):** (a) boot → trading-ready < 60 s; (b) chain verification passes or RECOVERY_REQUIRED is correctly entered (per injected phase); (c) recon verdict CLEAN/REPAIRED with zero unexplained diffs; (d) every open position has a **verified broker-side stop**; (e) client_key uniqueness at simbroker — zero duplicate orders across the crash; (f) ledger totals equal simbroker truth exactly; (g) the parked confirmation is re-presented or rule-resolved — never silently executed. **Pass criteria: 25/25 random seeds green; nightly CI job; merge-blocking weekly.** The §1.3 corruption drills (truncate, bit-flip, sidecar) run in the same harness. This extends Titan's live-drive lesson (the uvicorn/websockets bug that TestClient masked): drills run against **real** transports, never in-process test clients.

### 7.5 Golden-replay parity tier

As §5.6: pinned golden fixture on every PR touching `core/`, `features/`, `risk/`, `strategies/`; nightly against the latest demo session. Zero-tolerance diff. Plus determinism check: same run-card twice ⇒ identical `events` chain head hash.

---

## §8 CI/CD, secrets, network & security posture

### 8.1 F-016 platform topology — decision matrix (OPEN-FOR-HUMAN; board default recorded)

| Criterion | (a) All-Windows VPS | (b) Linux core + Windows MT5 bridge **(recommended)** |
|---|---|---|
| Process supervision | NSSM/Task Scheduler — weak, bespoke | systemd + Docker — the entire 05§C ops chapter as written |
| Failure domains | 1 box, but terminal auto-updates/re-logins take the *whole bot* down | 2 boxes + 1 hop; terminal failures degrade to LOST_LINK (§2.5) while core state stays intact |
| Chaos/CI parity | kill-9 drills on Windows CI: poor tooling | drills run identically in CI and prod (§7.4) |
| Latency | in-box (~0) | +1 LAN/WG hop, ~1–5 ms — irrelevant at H1+ cadence (measured class, Titan bridge) |
| Prior art | Titan `_reboot_terminal` watchdog | Titan `bridge/` :8766 + `mt5_http.py` client — **deployed and proven in this repo** |
| Security | trading creds + core + GUI on one internet-facing Windows box | broker creds isolated on Windows box; core/GUI on hardened Linux; WG-only between |
| Cost | 1 VPS (~$25–40/mo) | 2 VPS (~$40–70/mo) (Infra seat's noted objection, §9-10) |
| Event-sourcing durability | NTFS + Windows backup story | Linux + object-storage backup job (§1.3) |

**Recommended default: (b).** Every architectural commitment in this pass (systemd recovery, chaos CI, sole-writer SQLite on ext4, off-box backup) assumes Linux-grade ops; (a) would re-litigate §1, §7.4 and 05§C. Human decision is cost + VPS-provider preference.

### 8.2 Network diagram (topology (b))

```
                     Internet
                        │ 443/tcp TLS (GUI, authn+rate-limit)      Telegram API / NTP pools /
                        │                                          object storage  (outbound only)
                  ┌─────┴──────────────────────────────────────────────────────┐
                  │  LINUX VPS (core)                                          │
                  │  nginx :443 ──► interfaces/api :8790 (interface process)   │
                  │  core process :8770 (127.0.0.1 ONLY — command channel/WS)  │
                  │  chrony · systemd · docker · backup.py (out to obj store)  │
                  └─────┬──────────────────────────────────────────────────────┘
                        │ WireGuard 51820/udp (only route between boxes)
                  ┌─────┴──────────────────────────────────────────────────────┐
                  │  WINDOWS VPS                                               │
                  │  MT5 terminal (broker creds live ONLY here)                │
                  │  bridge_win :8766 — bound to WG interface, bearer token    │
                  │  NSSM: bridge autostart · terminal watchdog · w32tm/chrony │
                  └────────────────────────────────────────────────────────────┘
```

**Port/auth table:** 8766 bridge — WG-only bind, static bearer token, rotates monthly; 8770 core — localhost-only, session token for reads/WS + **HMAC per command** (§8.5); 8790 interface — localhost-only behind nginx; 443 — TLS (Let's Encrypt), login + IP allowlist option; no other inbound anywhere. Firewall default-deny both boxes.

### 8.3 Time sync (F-033 numbers)

chrony on Linux, chrony-or-w32tm tightened polling on Windows. Health loop (ops/health.py): NTP offset **WARN > 250 ms; > 750 ms block new session-scoped entries; CRITICAL > 1 s** (all hypothesis). Broker server-clock offset measured continuously from tick timestamps vs core UTC, stored per session (calendar service consumes it, F-006); drift of the *measured broker offset* > 90 s from its session baseline raises WARN (broker clock event or our drift — either matters).

### 8.4 Failover / degraded modes

| Failure | Detection | Degraded behavior |
|---|---|---|
| Bridge/terminal down | health poll + trade-channel machine (§2.5) | LOST_LINK: no new orders; SENT_UNKNOWN parked; NSSM restarts bridge; terminal watchdog restarts MT5; **CRITICAL — exits are impossible while down**, which is why stops are broker-side (02§A5) |
| Telegram outage | send failures + delivery-ack absence | F-009 fail-closed (hybrid→skip); GUI carries confirmations |
| GUI/interface process crash | systemd restart; core unaffected (F-015 isolation) | Telegram carries ops; core trades on |
| Core crash | systemd restart | §1.3 boot: verify→replay→reconcile→(ack if needed) |
| Windows Update / broker weekly restart | scheduled maintenance window Sat (market closed) | patching pinned to the window; unexpected restart = bridge-down path |
| Disk pressure | health metric | WARN 80%; 90% = pause new signals (log writes are sacred), CRITICAL |
| Dead-man's-switch | healthchecks.io-style ping every 30 s from core | external silence alert — detects "everything died including alerting" |

### 8.5 Command channel & secrets (F-031 hardening)

Interface→core commands: HTTP POST to 127.0.0.1:8770 with body `{command, args, actor, nonce, ts}` + `HMAC-SHA256(key_iface, canonical_json(body))`; core validates HMAC, ts skew ≤ 30 s, nonce uniqueness (replay cache), actor permissions (live-class config keys only per 04§B4; destructive commands need the confirm handshake — Titan's `needs_confirm`/TTL pattern kept), rate limits; then event-logs the command with actor before executing. Defense-in-depth even on localhost.

**Secrets:** broker login/password — Windows box only (never transits to Linux); bridge token + command HMAC key + Telegram token + GUI session secret — systemd `LoadCredential` from root-owned files (sops-age encrypted at rest in the ops repo); nothing secret in `config/*.yaml` (05§C rule kept); rotation runbook per secret; `.env.example` documents shape only.

### 8.6 CI/CD pipeline

```
PR:      ruff+mypy → unit → property (P1–P10) → sim scenarios (§7.3) → golden parity (pinned) → build image
nightly: chaos drills (§7.4, 25 seeds) → corruption drills → determinism check → full golden (latest demo day)
main→staging (auto): deploy container to staging Linux VPS wired to DEMO bridge → 24 h canary soak
         (canary pass = deadman unbroken, recon CLEAN×24h, zero CRITICAL, loop-lag p99 < 100 ms)
staging→prod (manual gate): operator approves; deploy is DRAIN-AWARE:
         new-risk pause → wait flat (or operator override; positions keep pinned params per F-027)
         → stop core → migrate (schema/config migrations versioned, applied atomically) → start → boot verify (§1.3)
rollback: previous image + config version retained; event log is forward-compatible (upcasters, §1.1)
```

### 8.7 F-002 — account-type discovery gate + degraded netting mode (decision matrix)

**Discovery gate (runs at connect, before any trading):**

```
profile = adapter.discover()
mode = profile.account.margin_mode           # HEDGING | NETTING | EXCHANGE
if mode == HEDGING:  tranche_model = FULL    # per-child positions, per-position broker stops
else:
    tranche_model = config.netting_policy    # REFUSE (default-safe) | DEGRADED
    emit breaker-style banner in GUI/Telegram: "netting account: <policy>"
```

**Degraded-netting mode (option B), designed:** risk manager enforces **max one child position per instrument** (a second same-direction intent is blocked `NETTING_OCCUPANCY`; opposing intent → `POSITION_CONFLICT` per F-019 — no trade, conflict event). Consequence: the broker's one position *is* the one tranche, so 02§A5's per-position broker-side stop is satisfiable, reconciliation is 1:1, and no synthetic bookkeeping exists to corrupt. Cost: forgone stacking/conflict-priority features on netting brokers.

| Criterion | A: refuse netting accounts | **B: degraded mode (recommended default)** | C: synthetic tranche ledger (Pass-4 design item) |
|---|---|---|---|
| 02§A5 broker-side stop | n/a | **satisfied exactly** | violated per-tranche (one aggregate stop; tranches bot-side — dies with the bot) |
| Complexity / new failure modes | none | small (2 guards in risk manager) | high: tranche↔net reconciliation, aggregate-stop recompute on every tranche change |
| Capital access | excludes netting-only operators | full | full |
| Honesty | honest | honest (documented capability loss) | risk of quietly violating stop guarantees (Pass-1 F-002 write-up) |

**Recommended default: B** (A as the conservative config option; C only if Pass 4 produces a reconciliation-complete design **and** a human accepts the weaker stop guarantee). Final call: human, per Pass-1 OPEN-FOR-HUMAN.

---

## §9 Board debate log (objections that changed content)

1. **Frontend Architect vs auto-close of unconfirmed partials (§2.1 row 21).** Draft had timeout-skip closing the filled portion at market. Objection: a human who never saw the card would find a position opened *and* closed by timers — worse UX-truth than either alternative. Bot Dev countered with orphan risk. Resolution: filled portion is adopted and child-managed; **only an explicit human veto closes it**; card and journal show the adoption. Changed row 21.
2. **Backend Architect vs embedding the control server in the core (Titan Phase-1a pattern).** Titan embeds FastAPI in the controller process — trivially single-writer but couples GUI serving to the trading loop (F-028 risk). Resolution: split — core keeps a *thin* localhost command/WS endpoint (:8770); GUI serving, SPA, Telegram live in the interface process (:8790). F-015 single-writer preserved, loop protected. Changed §6 tree + §8.2.
3. **Auditor vs snapshot sidecar files (§1.3).** "State outside the chained DB is state outside the audit." Resolution: chain covers the sidecar SHA-256; the nightly backup-verify job restores and hashes sidecars too; a missing/corrupt sidecar fails verification loudly. Sign-off given.
4. **Networking seat vs any request/reply socket on the trade path.** Titan scar tissue: a wedged ZMQ REP socket required EA reattachment. Resolution: trade path is HTTP with hard deadlines + `SENT_UNKNOWN` machinery (§2.2 r8); no protocol state that can wedge across requests. Shaped §2.2/§3.2.
5. **Auditor red-team of "exactly-once" (§3).** True exactly-once delivery is unattainable over a broker API. Wording and design changed to the achievable invariant: **at-most-once send per attempt + reconcile-to-exactly-once effects**, with `DUPLICATE_EXECUTION` as a counted, alarmed event rather than an assumed impossibility.
6. **Day Trader vs 60 s periodic reconcile during London bursts.** Resolution: heartbeat-diff-triggered mini-recon (positions/orders count + hash compare each broker heartbeat) between full pulls. Changed §3.3 cadence.
7. **Quant vs the 1e-9 canary tolerance (§4.5).** Wilder chains legitimately accumulate float drift over long incremental runs; a strict canary would cry wolf. Resolution: relative tolerance + the every-10k-bars recompute discipline (§4.3) so drift is bounded by design; canary failures twice-in-a-row escalate. Changed §4.3/§4.5.
8. **Bot Dev vs comment/magic-based attribution.** Brokers mangle comments (F-032); magic is one int. Resolution: `exec.intent_persisted` **before** the broker call is the sole authority; broker-carried fields are hints. Unanimous; shaped §3.1.
9. **Strategist vs the drain-gate on deploys (§8.6).** Objection: waiting flat can strand a deploy for weeks (TC-2 holds months). Resolution: operator override deploys with positions open; F-027 params-pinning guarantees running positions keep their contract; boot reconcile verifies stops. Accepted.
10. **Infra seat's cost objection on F-016(b)** (two VPS, WireGuard upkeep) — recorded in the §8.1 matrix as the honest cost of the recommended default; not resolved away.

---

## §10 Findings-resolution table (Pass-3 dispositions)

| Finding | Resolution section | Status |
|---|---|---|
| F-001 | §2.1 rows 5, 15–21 (fill edges, reserve-at-placement, veto-after-fill, card_updated) | RESOLVED (Pass 4 implements order handling) |
| F-002 | §8.7 gate + degraded-mode design + decision matrix; default **B** | DESIGNED; OPEN-FOR-HUMAN (default choice) |
| F-004 | §1.1 chain, §1.3 snapshots/backup/verify/refuse-to-trade, §7.4 drills | RESOLVED |
| F-005 | §2.3 ledger columns, §2.6 limits #8–#10 | RESOLVED (k / caps calibration → Pass 7) |
| F-006 | `calendar_svc` seam (§4.3 session node, §6.1, §8.3 broker offset); full spec owed | PARTIAL — Pass 4 owns the service spec (hard predecessor, Pass 2 §7-10) |
| F-008 | §2.1 STA (semantics **and** mechanism), §1.4 single serialization point | RESOLVED |
| F-009 | §2.1 rows 6, 10–11 fail-closed arms | RESOLVED (delivery/ack transport details → Pass 6) |
| F-010 | §2.1 row 20, §2.2 row 16, §1.2 `exec.cancel_result` | RESOLVED |
| F-011 | §2.3 gap columns + k table, §2.6 limit #8 sleeve budgets | RESOLVED (k calibration → Pass 7) |
| F-014 | §4.5 validator/rebuild/canary, §7.2 P1 | RESOLVED |
| F-015 | §1.4 total core ownership + §8.5 command channel | RESOLVED |
| F-016 | §8.1 matrix; recommended default **(b)** | DESIGNED; OPEN-FOR-HUMAN |
| F-017 | §2.6 limit table (gross/net declared, exclusive classes, macro-factor caps, register examples as tests) | RESOLVED |
| F-019 | §2.6 (pre-route netting only; POSITION_CONFLICT) | RESOLVED |
| F-022 | §2.3 rows 1, 3, 5 (realized-risk recompute, RISK_TRIM, never-move-the-stop) | RESOLVED |
| F-024 | §2.4 anomaly spec (24 h R vs portfolio-MC windows) | RESOLVED |
| F-025 | §2.5 calendar-aware staleness (thresholds finalized with Pass-4 calendar) | PARTIAL |
| F-027 | §2.3 row 6 params pinned at fill | RESOLVED |
| F-028 | §4.6 budgets/executor/loop-lag metrics | RESOLVED |
| F-031 | §8.5 HMAC command channel | RESOLVED (Pass 6 inherits) |
| F-032 | §3.1 intent-persisted authority, §3.3 quarantine book | RESOLVED |
| F-033 | §1.1 monotonic-core clock, §2.5 verification, §8.3 thresholds | RESOLVED (monitoring surfacing → Pass 6) |
| F-034 | §2.6 limit #1 re-clamp | RESOLVED |
| F-035 | §2.1 expiry-scope restriction adopted | RESOLVED |
| F-036 | §2.6 binding-order report | RESOLVED |
| F-038 | §4.2 canonical params_hash + P7 | RESOLVED |

**Constraints exported to Passes 4–8:** Pass 4 — calendar service full spec (F-006) is the hard predecessor of every session child; execution simulator implements the §5.2 `FillModel` protocol; F-007 spec-diff analyzer per-field severities of §1.2; option-C tranche ledger only as a complete reconciliation design. Pass 5/6 — interface process is DB-read-only forever; all mutations via §8.5 channel; confirmation UX must render `race_losers` and `card_updated` truthfully. Pass 7 — calibrate: gap k factors, margin/notional caps, viability threshold, MC anomaly reference, canary tolerances; every gate ships negative/positive controls (Pass-1 T7). Pass 8 — the §10 OPEN-FOR-HUMAN items (F-002 default, F-016 topology) go on the human decision sheet with these matrices attached.

— End of Pass 3. Schemas and machines above are normative for implementation; numbers labeled hypothesis remain hypotheses until Pass 7 calibrates them.
