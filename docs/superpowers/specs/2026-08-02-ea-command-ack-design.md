# EA Command Ack — making management-command failures observable and recoverable

**Date:** 2026-08-02
**Status:** Design approved, awaiting implementation plan
**Author:** brainstormed with the owner

## 1. Motivation

Titan's trade-management commands — `CANCEL`, `MODIFY`, `CLOSE_POS` — are
fire-and-forget on the PUSH socket. `BridgeZMQ.send_command` returns `True` when
the *socket* accepted the frame, and nothing downstream ever learns what the
broker did with it. A refused command and a successful one are indistinguishable
to every layer above the wire.

This is not theoretical. On 2026-08-02 the operator cancelled an untracked
EURUSD pending order through the GUI:

```
POST /api/command {"command":"cancel","ticket":1936559060}
→ {"status":"ok","result":1}
```

The order never moved. The only evidence anywhere in the system was MT5's own
Experts log:

```
11:08:56.424  Titan_Gateway (EURUSD,M5)  TITAN | Cancel Failed: 10018
```

`10018` is `TRADE_RETCODE_MARKET_CLOSED` — EURUSD is shut on a Sunday. Nothing
in Python, Telegram, the journal or the GUI recorded a failure, and the operator
had no way to know the order was still resting other than reading a UTF-16LE log
file on the Windows side.

### 1.1 Two further defects in the same code

Found while scoping, and folded into this work because they live in the lines
being edited:

* [`Titan_Gateway.mq5:322`](../../../mql5_bridge/Experts/Titan_Gateway.mq5) (CANCEL)
  and `:342` (CLOSE_POS) test only `!OrderSend(...)`. They never inspect
  `res.retcode`. MODIFY at `:306-311` checks both. A request the server accepts
  but rejects by retcode therefore produces **no output at all** — not even an
  Experts line. The 10018 above was visible only because that particular failure
  happens to make `OrderSend` return false.
* The CANCEL branch matches `StringFind(json, "CANCEL") >= 0` — a substring test
  against the entire message — and, unlike MODIFY, neither CANCEL nor CLOSE_POS
  `return` afterwards. A single message can therefore fall through both branches.

## 2. Scope decisions

Settled with the owner during design. Each records the alternative rejected, so
a later reader can tell a decision from an accident.

| Decision | Choice | Rejected |
|---|---|---|
| Depth | Observability **and** auto-retry | Observability alone; operator-queue-with-retry-button |
| Retry horizon | Short only (seconds→minutes), in memory; long waits escalate | Persistent SQLite queue that re-fires when a session reopens |
| On exhaustion | Notify always; **halt new entries only on close failures** | Notify-only; halt on any failure |

**Why no persistent queue.** A market-closed reject implies an ~11h wait. Queuing
that to SQLite means a command can fire days later against a book that has since
changed, and it buys a new table, a scheduler and boot reconciliation. Escalating
to a human instead is both smaller and safer.

**Why halt only on close failures.** A failed `MODIFY` leaves the trade stopped,
just not where Titan intended — bad, not dangerous. A failed `CLOSE_POS` or panic
leaves the operator exposed while believing they are flat, which is the case that
must fail closed. Same discipline as the portfolio exposure cap.

## 3. Approach: ack for the reason, heartbeat for the truth

Three approaches were considered.

* **Ack-authoritative** — trust `CMD_RESULT` alone. Precise, but ZMQ PUSH/PULL can
  drop frames on an EA reattach or at high-water mark, and a lost ack would be
  indistinguishable from a real close failure. Given the halt rule, that could
  stop the book for no reason.
* **State-authoritative, no EA change** — infer from heartbeat state alone, no
  MQL5 edit, no recompile. Rejected: it cannot distinguish `10018` (wait) from
  `10013` (never going to work), so the transient/terminal classification the
  retry policy depends on is impossible.
* **Hybrid (chosen)** — the ack supplies the *reason* and drives fast, informed
  retry; the heartbeat remains the authority on whether the book actually
  changed.

The asymmetry is the point: an explicit reject is a confirmed non-application and
is safe to retry immediately; a *missing* ack is merely unknown and is resolved by
inspecting state. Retry and halt both fire on confirmed failure or confirmed
no-change — never on a dropped frame.

## 4. Wire protocol

### 4.1 Outbound (Python → EA, PUSH)

Every management command gains a Python-generated `cid`. Existing fields are
unchanged; `send_command` already sets `action`.

```json
{"action":"CANCEL","cid":"c-4821","ticket":1936559060}
{"action":"MODIFY","cid":"m-4822","ticket":123,"symbol":"EURUSD","sl":1.1,"tp":1.2}
{"action":"CLOSE_POS","cid":"x-4823","ticket":789,"volume":0.05}
```

`cid` is opaque to the EA — echo it back verbatim. It must be unique for the
lifetime of the process (a monotonic counter with a short prefix is sufficient;
it is never persisted and never parsed). Correlating on
`(ticket, action)` instead is **not** sufficient: the trade manager can legitimately
have two ratchet `MODIFY`s in flight for one ticket, and their results would be
ambiguous.

### 4.2 Inbound (EA → Python, PUSH → Python's PULL :32769)

A new frame type on the socket that already carries `TICK`/`HEARTBEAT`/
`HISTORY`/`EXECUTION`:

```json
{"type":"CMD_RESULT","cid":"c-4821","action":"CANCEL","ticket":1936559060,
 "ok":false,"retcode":10018,"err":0,"comment":"Market closed"}
```

* `ok` — true only when `OrderSend` returned true **and** `res.retcode` is
  `TRADE_RETCODE_DONE` (10009) or `TRADE_RETCODE_PLACED` (10008).
* `retcode` — `res.retcode`, or 0 when unset.
* `err` — `GetLastError()`. Carried alongside `retcode` because they populate in
  different failure modes: `OrderSend` returning false with a zero retcode is a
  client-side rejection where only `GetLastError()` is meaningful.

No new socket. The REQ/REP path is untouched — it stays reserved for order entry,
because a reply the EA cannot deliver in time wedges its REP socket.

## 5. EA changes (`Titan_Gateway.mq5`)

1. **One shared helper**, `ReportCmdResult(cid, action, ticket, ok, retcode, err, comment)`,
   which formats the frame and sends on `socket_push`. All three branches call it
   on every path. A single helper is deliberate: the three branches have already
   drifted apart once (§1.1) and independent reporting code would let them drift
   again.
2. **All three branches capture both** the `OrderSend` return value and
   `res.retcode`, then report exactly once.
3. **Match on `"action":"CANCEL"`** rather than the bare substring, and `return`
   after each branch.
4. `cid` is read with the existing `GetJSONString` helper; absent `cid` reports as
   an empty string, which Python treats as an uncorrelated result (logged, not
   matched).

### 5.1 Control-flow risk

Adding `return` after CANCEL changes control flow. In practice no behaviour
changes today: a CANCEL message does not contain the literal `CLOSE_POS`, so the
subsequent branch never matched anyway. The change makes that guarantee
structural rather than incidental. Recorded here so the reasoning is reviewable
rather than living in someone's head.

## 6. Python architecture

### 6.1 `src/execution/command_tracker.py` (new)

Pure: no sockets, no DB, no clock of its own. It receives registrations, results
and state snapshots, and returns decisions. This keeps the entire retry policy
unit-testable without a bridge, following the same shape as `RiskManager`.

```
register(cid, action, ticket, symbol, expected)   # called before send
on_result(cid, ok, retcode, err, comment)         # from the CMD_RESULT branch
tick(now, positions, orders) -> (retries, escalations, resolved)
```

`expected` is the post-state that proves application:

| Action | Applied when |
|---|---|
| `CANCEL` | ticket absent from heartbeat `orders` |
| `MODIFY` | position's `sl`/`tp` match the requested values |
| `CLOSE_POS` (full) | ticket absent from heartbeat `pos` |
| `CLOSE_POS` (partial) | position volume reduced to the expected remainder |

### 6.2 Retcode classification

Retry **only** these — genuinely fast-transient:

| Retcode | Meaning |
|---|---|
| 10004 | REQUOTE |
| 10020 | PRICE_CHANGED |
| 10021 | PRICE_OFF (no quotes) |
| 10024 | TOO_MANY_REQUESTS |
| 10031 | CONNECTION |

Everything else escalates immediately. That explicitly includes **10018
MARKET_CLOSED**: per §2 it is not retried, it notifies. Under this design the
2026-08-02 incident would have Telegrammed the operator at 11:08 instead of
silently doing nothing for eleven hours.

Schedule: **3 attempts, backoff 2s / 8s / 30s.**

### 6.3 The unknown path

A missing `CMD_RESULT` is **never** treated as failure. After a 10s timeout the
tracker compares heartbeat state against `expected`:

* applied → resolve as success, silently;
* unchanged across 2 consecutive heartbeats → treat as failed.

An unknown-path failure carries **no retcode**, so §6.2's classification cannot
be applied to it. It is treated as **transient**: there is no evidence the command
is permanently invalid, so it retries under the same 3-attempt / 2s-8s-30s
ceiling and escalates only once that is exhausted. Escalation then reports
`retcode: null` and a reason of `no-ack`, which is a materially different
operator message from a broker rejection and must read as one.

This is the safety-critical property of the whole design and must survive
refactoring: **retry and halt fire on an explicit reject or a heartbeat-confirmed
no-change, never on a dropped frame.** It is what makes retrying a close safe.

### 6.4 Wiring

* `SystemController._dispatch_mgmt_command` — generate `cid`, `register(...)`,
  then send.
* `SystemController._process_incoming_data` — new `CMD_RESULT` branch calling
  `on_result`.
* Main loop — call `tracker.tick(...)` each pass, dispatch returned retries,
  raise returned escalations.

`tick` goes in the **main loop, not the HEARTBEAT branch.** Bookkeeping placed in
the heartbeat handler has caused defects in this codebase before. The tracker
reads `current_open_positions` / `current_pending_orders`, which the heartbeat
keeps current — reading them from the main loop is correct and sufficient.

### 6.5 Escalation surface

* **Telegram** — action, ticket, symbol, retcode, attempts, and the EA's comment.
* **Bus** — a `CommandFailed` event, so it lands in the GUI Activity feed.
* **Snapshot** — a new `commands` block in `state_view.build_snapshot`:
  `{"in_flight": n, "failed": [...]}`, defensive in the same style as `risk` and
  `dollar` (a controller without a tracker degrades, never crashes).

### 6.6 The close-failure block

A failed `CLOSE_POS` (including panic/closeall) records a block entry. It is
checked in `_execute_signal` alongside the exposure cap and prevents new entries
while set.

It **auto-clears** when the ticket later disappears from the heartbeat — that
means the position did close after all, so no operator action is needed. This
matters: a block that only a human can clear would eventually be cleared
reflexively, which is how fail-closed guards rot.

## 7. Testing

**Tracker (pure, carries the weight):**

* retcode classification table — each retry code retries, a representative
  terminal code does not;
* backoff schedule and the 3-attempt ceiling;
* unknown → heartbeat resolution, separately for CANCEL / MODIFY / full close /
  partial close;
* a terminal retcode must **not** retry;
* two in-flight `MODIFY`s on one ticket resolve independently — the case that
  justifies `cid`;
* close-failure block sets, and auto-clears when the ticket leaves the heartbeat.

**Controller:** the `CMD_RESULT` routing branch, `cid` generation on dispatch, and
the `_execute_signal` halt path.

> Five existing modules construct `SystemController` via `object.__new__`, so a
> `grep 'SystemController('` sweep will miss them:
> `test_strategy_timeframe.py`, `test_controller_routing.py`,
> `test_controller_news_gate.py`, `test_gui_server.py`,
> `test_risk_manager_exposure_cap.py`.
> The plan must name them rather than rely on discovery — they have caught real
> defects here before.

**State view:** the `commands` block, including the degrade-without-tracker case.

**EA:** MQL5 cannot be unit-tested here. Verification is a live smoke test —
send a `CANCEL` for a nonexistent ticket and confirm a `CMD_RESULT` arrives with
a terminal retcode. Non-destructive, and it exercises the full path.

## 8. Rollout

Two independent steps, in this order.

1. **Land the Python side.** It is inert without the new EA: no `CMD_RESULT` ever
   arrives, every command takes the unknown path, and heartbeat verification
   runs. That is already strictly better than today, so it can soak for as long
   as the owner likes before any MQL5 work.
2. **Recompile the EA** in MetaEditor on Windows and reattach, at the owner's
   convenience. Then run the §7 smoke test.

No flag day: an EA predating this change simply never sends `CMD_RESULT`, so old
EA + new Python degrades to step 1 behaviour rather than breaking.

**Risk — EA reattach.** Reattaching drops the ZMQ connection briefly, and this
codebase has prior form with a wedged REP socket on reattach. Do it with no
orders in flight.

No new dependencies.

## 9. Out of scope

* Persistent/long-horizon retry (§2).
* Any change to the REQ/REP order-entry path.
* Counting manually-placed pending orders in the portfolio risk cap. That needs
  the EA to send `sl` on heartbeat `orders` rows — a related MQL5 change, but a
  separate one with its own risk surface.
