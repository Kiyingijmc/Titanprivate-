# PASS 5 — INTERFACES & HUMAN FACTORS

**Co-chairs:** Industry-Proven Frontend Architect + Retail Day Trader + Swing Trader (the two traders sit as the *users under time pressure*; every screen in this pass was walked with them on a phone-sized mock). **Contributors:** all ten seats; Auditor red-teams per board rule (b).
**Inputs (read in full):** `00`–`05` baseline docs, `pass1-audit.md` (39 findings), `pass2-research.md`, `pass3-systems.md` §1–§4 + §8.5/§8.7 (normative; §5+ treated as informative per summit note).
**Findings owned here** (per the disposition-inconsistency rule, we own every interfaces/confirmation-UX/notification-delivery finding regardless of the pass number cited): **F-001 (display face), F-008 (UX face — `race_losers` truth), F-009 (full delivery-ack UX + degraded modes), F-013 (display framing of live-vs-expectation), F-026, F-031 (interface-side enforcement), F-033 (monitoring surfacing), F-039 (adopted + detailed)**; plus display duties from F-002 (netting banner), F-005/F-011 (two-number risk display), F-016 (interface-process consequences), F-025 (staleness display), F-036 (binding-order report display), F-037 (labeling applied throughout).
**Binding constraints honored:** pass3 §2.1 signal machine is consumed as-is (fill edges, STA single owner, fail-closed rows 10–11); the interface process is DB-read-only forever; every mutation rides the §8.5 HMAC command channel; confirmation UX renders `race_losers` and `card_updated` truthfully. Exits are automated in every mode — no screen in this pass offers a way to make an exit depend on a human. Numbers are labeled **(measured)** / **(literature-informed)** / **(hypothesis)**.

---

## §1 The confirmation card — decision-making under time pressure

### 1.1 The decision model the card is built for

The board first agreed on *what the human is actually doing* in hybrid mode, because the field order falls out of it. The human is **not re-analyzing the trade** — the signal has already passed regime gating, risk sizing, and every limit (02§A, pass3 §2.6). Re-analysis in a 10-minute window on a phone is worse than the bot's own gates and invites second-guessing noise (the human-decision analytics, §5.3, will show whether that's true per child). The human's real job is **anomaly veto**: *"does anything about this look wrong that the bot cannot see?"* — news the calendar missed, a broker acting strangely, a personal risk-appetite override ("it's Friday, I don't want new index exposure"), a child the operator has grown suspicious of.

Design consequence (board-adopted): the card is ordered so that **the fields most likely to reveal an anomaly come first**, and the fields that merely restate what the bot already validated come last. Under time pressure people read top-down and quit early (mobile notification glance ≈ 2–4 s — literature-informed); the top three lines must therefore carry: what it is, what it costs if wrong, and what happens on silence.

### 1.2 Field order (normative, both interfaces render this order)

| # | Field | Content example | Rationale (decision-under-pressure) |
|---|---|---|---|
| 1 | **Action header** | `LONG EURUSD — trend.donchian_v1` | Identity first: direction + instrument is the single highest-signal anomaly check ("why is it shorting gold?"). Child id present because operators develop per-child trust levels — it changes the prior for everything below. |
| 2 | **Cost of being wrong** | `Risk $52 (0.50% eq) · stop 70t · gap-stressed $68` | The human confirms **risk acceptance**, not entry precision. Both risk numbers (F-005/F-011): risk-at-stop *and* gap-stressed when the position would be held across a close — the Friday card for an index CFD reads differently from the Tuesday one, by design. |
| 3 | **Silence line** | `If you do nothing: EXECUTES in 9:41` / `SKIPS at 06:00` | F-009's UX face: the timeout **action** is the headline of the countdown, never a bare timer. §1.5. |
| 4 | **The why (≤ 4 sentences)** | `Close broke the 20-day high (1.0921). Regime TRENDING_UP 0.84 (published 5 bars). ER 0.41 — clean trend.` | Frozen-snapshot sentences (§1.4). Anomaly detection needs the thesis stated in the child's own terms — a meanrev card citing a TRENDING regime is the kind of wrongness a human spots instantly. |
| 5 | **The against line (mandatory)** | `Against: spread 1.4× session norm · held over weekend if slow · macro-factor USD net +3.2%/5%` | Auditor's condition for sign-off: every card must carry the strongest reasons *not* to take the trade — spread state, gap flag, the nearest risk-limit headroom. A card that only argues for itself is a salesman, not an instrument. |
| 6 | **Execution details** | `Entry stop-order @1.0921 · SL 1.0851 · TP 1.1041 (2.0R) · 0.10 lots` | Restatement of what risk already validated. Present for audit and for the minority of operators who do check levels — but below the fold on a phone, deliberately. |
| 7 | **Status chips** | `TG✓ GUI✓ acked · card v1 · valid until 14:00` | Delivery/ack state, card version (§1.8), validity. |
| 8 | **Buttons** | `[Approve] [Hold] / [Reject]` | Last, after the evidence. Layout + protection in §1.8. |

**Day Trader objection (recorded, §8-1):** "price level should be line 2 — I think in levels." **Resolution:** levels stay in block 6. The human's contractual role in this system is risk consent; entry mechanics are the execution layer's job and exits are automated regardless. The trader seats accepted after the counterfactual walk-through: no veto decision in the mock sessions ever hinged on the fourth decimal of the level, several hinged on risk/spread/weekend flags.

### 1.3 One-glance test and GUI wireframe

The 3-second phone test (board-adopted acceptance criterion): **lines 1–3 alone must let the operator make a defensible decision or a deliberate deferral.** They fit in a Telegram notification preview (~90 chars visible on lock screen — literature-informed):

```
🟢 LONG EURUSD · trend.donchian_v1
Risk $52 (0.50%) · gap-str $68 (Fri hold)
If you do nothing: EXECUTES in 9:41
```

Full GUI card (desktop; phone renders identically minus the right column):

```
┌──────────────────────────────────────────────────────────────┐
│ ▲ LONG  EURUSD          trend.donchian_v1        HYBRID      │
│ Risk $52 = 0.50% eq   ·  gap-stressed $68 (weekend hold)     │
│ ⏳ If you do nothing: EXECUTES in 9:41   (valid until 14:00) │
│──────────────────────────────────────────────────────────────│
│ WHY  · Close broke the 20-day high (1.09210)                 │
│      · Regime TRENDING_UP conf 0.84 — published 5 bars ago   │
│      · Efficiency ratio 0.41 (clean trend)                   │
│ AGAINST · Spread 1.4× session norm (gate: pass)              │
│         · USD macro-factor after fill: +3.2% of 5% cap       │
│──────────────────────────────────────────────────────────────│
│ Entry STOP @1.09210 · SL 1.08510 (70t) · TP 1.10610 (2.0R)   │
│ 0.10 lots · exits bot-managed in all modes                   │
│ Delivered: TG ✓ 05:50:12 · GUI ✓ 05:50:11 · card v1          │
│                                                              │
│   [ ✅ APPROVE ]      [ ⏸ HOLD ]                             │
│                                        [ ❌ Reject ]         │
└──────────────────────────────────────────────────────────────┘
```

The line `exits bot-managed in all modes` is printed on **every** card, permanently. It is the locked-requirements sentence ("humans confirm entries only") made visible at the moment it matters, and it pre-empts the support question every new operator asks ("if I approve and fall asleep, who trails the stop?" — the bot does, always).

### 1.4 Frozen snapshot → human sentences (renderer spec)

Card prose is rendered **once, core-side, at `confirm.requested` time**, from the frozen snapshot only (02§B5: zero recomputation) and shipped inside `card:json`. Both interfaces are dumb renderers of the same object — divergence between what the GUI showed and what Telegram showed is structurally impossible, which is what makes the audit trail ("what the human saw", F-001 Auditor condition) meaningful.

Renderer contract:

```
CardTemplate (per child, registered with the child version):
  why:      [SentenceSpec]     # ordered, max 4 rendered on phone, all on GUI expand
  against:  [SentenceSpec]     # child-specific extras; system lines appended (below)
SentenceSpec:
  keys:     [FeatureKey]       # must ⊆ child.required_features() ∪ snapshot std keys
                               #   (validated at child registration — a template citing
                               #   an unfrozen feature is a startup error, not a runtime one)
  template: str                # "RSI(2) = {rsi2:.1f} — deeply oversold" ; ≤ 60 chars rendered
  severity: info|caution       # caution renders amber in GUI, ⚠ prefix in TG
Fallback: any snapshot key not consumed by a template renders in a collapsed
  "raw snapshot" section (GUI) / omitted (TG). Keys are never silently dropped
  from the audit copy — the full frozen snapshot rides in the card object.
System-appended AGAINST lines (not child-authored, always present):
  spread_now vs session norm + gate verdict · gap-stress flag if held-over-close
  · tightest post-fill limit headroom (from the risk.evaluated LedgerSnapshot)
  · regime confidence if < 0.6 (hypothesis threshold) · DST-mismatch window flag (F-006)
```

Numbers in sentences follow display rules: ticks for distances (`70t`), R for targets, account currency for risk, no pips anywhere (00 non-negotiable #2 extends to copy).

### 1.5 Countdown and timeout-action visibility (F-009 UX face)

- The countdown line always couples **time + consequence**: `EXECUTES in 9:41` (hybrid, `action=execute`, delivery-acked), `SKIPS in 9:41` (hybrid `action=skip`), `SKIPS at 14:00 — manual mode never auto-executes` (manual). Bare timers are forbidden by spec.
- Two clocks can exist (hybrid timeout vs `valid_until`); the card shows the **next** deadline as primary and the other parenthetically. When timeout resolves and validity remains (held signals, §1.7), the line re-renders from the remaining clock.
- **Fail-closed rendering:** if the STA degraded a timeout from execute→skip because no delivery-ack existed (pass3 §2.1 row 11), the late-delivered card renders a WARN band: `Auto-execute was disabled for this signal: no interface acknowledged delivery by T-2:30. It will SKIP at 14:00 unless you act.` The operator learns *that the safety net fired and why* — a silent degrade would trade one silent mode violation (F-009) for another.
- Color/urgency: countdown turns amber ≤ 25% of window remaining, red ≤ 60 s (hypothesis); GUI adds a subtle progress ring; **no sound in the last seconds** — panic-inducing audio at the deadline measurably increases error rates in time-pressured UI (literature-informed, alarm-fatigue/startle literature); the design goal is calm veto, not twitch approval.
- Countdown ticks are computed **client-side** from `timeout_at`/`valid_until` plus the clock-offset in the WS heartbeat (§3.3) — the server never streams ticks, and a stale feed therefore freezes the ring visibly rather than lying smoothly (staleness chip, §3.5, sits beside it).

### 1.6 Partial fill during confirmation (F-001 states, rendered)

When the STA emits `confirm.card_updated(reason=PARTIAL_FILL|FULL_FILL)`, the card **visibly mutates and bumps `card_version`**:

```
│ ⚠ FILLED 0.04 / 0.10 lots at 1.08418 WHILE YOU DECIDE          │
│   A live position exists. Its stop (1.08290) is already        │
│   attached broker-side.                                        │
│ ⏳ If you do nothing: remainder cancels at 06:00; the filled   │
│   0.04 stays open and is bot-managed (never auto-closed).      │
│ [ ✅ APPROVE — keep position + working remainder ]              │
│ [ ⏸ HOLD ]                        [ ❌ Reject — cancel rest    │
│                                      + CLOSE 0.04 at market ]  │
```

Rules: (a) button labels state their **consequences explicitly** — "Reject" on a partially-filled card is a materially different act (market-closes a live position, `VETO_AFTER_FILL`) and the label says so; (b) the silence line changes to the row-21 truth: timeout/expiry never auto-closes the filled part; (c) in `FILLED_PENDING_DECISION` the header itself changes to `NOW A POSITION — approve keeps, reject closes`; (d) Telegram receives the same mutation via edit-in-place (§2.2) **with a fresh notification ping even inside quiet hours at silent-priority** — a card that became a position is a state change the human is entitled to know about immediately.

### 1.7 Approve / Reject / Snooze semantics

- **Approve** → `confirm.resolution_requested(APPROVE)` over the command channel. Version-pinned (§1.8). Outcome renders only from `confirm.resolved` (§3.4 — never optimistic).
- **Reject** → `resolution_requested(REJECT)`. **Not** version-pinned: a reject issued against any card version is honored (rejecting is always the conservative direction; forcing a re-read before allowing a veto would be safety-inverted). On partial-fill states it triggers the F-001 veto-close policy, as labeled.
- **Snooze ("Hold — decide later")** — the board settled snooze semantics after real debate (§8-2). Snooze is **a claim of the decision, not a pause button**:
  1. It counts as a delivery-ack *and* an explicit human acknowledgment (`seen`, §2.3).
  2. It **cancels the pending hybrid timeout action for this signal** — the STA disarms the timeout timer and the signal now resolves only by human action or by `valid_until` expiry (skip). Rendered immediately: `Auto-execute cancelled — this signal now SKIPS at 14:00 unless you approve.`
  3. It never extends `valid_until`. The thesis decays on the child's schedule; no interface can stretch a signal's life (02§B1 "never forever" preserved).
  4. A reminder re-ping fires at T-2 min before `valid_until` (hypothesis), and immediately on any `card_updated` (a held card that partially fills pings at once).
  Mechanically this is additive to pass3 §2.1: a new event `confirm.hold_applied {signal_id, actor, timeout_cancelled:true}` and a `held:bool` flag on the signal record (flags, not states, per §2.1's own convention). **Flagged as a proposed amendment for Pass-8 adoption** — it introduces no new transition and touches no existing row; row 10's guard gains `∧ ¬held`.
  **Strategist objection (§8-2):** snooze-as-claim lets a distracted human silently kill good trend signals that were configured execute-on-timeout. **Resolution:** that is precisely what pressing "wait" *should* mean — an explicit human taking the decision away from the timer must beat the timer, or the button lies. The mitigation is the T-2 min re-ping plus the human-decision analytics (§5.3) which will price the operator's snooze habit per child in R. Carried 9–1.

### 1.8 Error-proofing, idempotency, and the CAS surface

- **Version-pinned approvals.** Every card carries `card_version` (v1 at `confirm.requested`, bumped only by *material* `card_updated` events: fills, spread-gate flips — countdown ticks and ack chips do not bump it). `APPROVE` requests carry the version the human saw; the STA rejects a stale-version approve with outcome `STALE_CARD`, and the UI responds: *"The signal changed since you saw it (partial fill). Review the updated card."* This is the F-001 Auditor condition operationalized: nobody can approve a position while believing it's still a proposal. **Backend Architect objection (§8-3):** version pinning adds a retry loop under time pressure. **Resolution:** material-change-only bumping keeps the stale-approve case rare (it fires exactly when re-reading is genuinely required); rejects are exempt. Signed off.
- **Idempotent taps.** The command idempotency key is `(signal_id, action, card_version)` (rides the §8.5 envelope's nonce discipline). Double-taps, Telegram callback retries, and GUI reconnect replays collapse server-side; the second tap renders the authoritative outcome, not an error.
- **Race truth (F-008).** When a human's request loses the STA race, `confirm.resolved.race_losers` names them, and both interfaces render it verbatim: *"Resolved by timeout (executed) 0.8 s before your approve arrived. Your tap did not cause this trade."* — and the journal stores which message the human saw. An interface that quietly showed "approved ✓" to a human whose tap lost would be manufacturing a false model of control in the exact user population that must stay calibrated (Frontend Architect's own Pass-1 requirement, honored here).
- **Mis-tap protection.** Approve and Reject are never adjacent: separate rows (Telegram) / opposite corners with ≥ 12 px dead zone (GUI); touch targets ≥ 44×44 pt (literature-informed, Apple HIG). **No confirm dialog on Approve/Reject** — a second dialog under a countdown adds error-prone hurry, and both actions are recoverable by design (approve → position with automated exits and a manual-close path; reject → at worst a missed trade, plus the analytics record). Destructive *account* actions (flatten, killswitch, breaker ack) are a different class: typed-confirmation or double-tap with 30 s TTL (Titan `CONFIRM_TTL` pattern — measured-in-repo constant, borrowed).
- **No editing, ever.** The card offers approve/hold/reject only. No size nudge, no level nudge: an edited proposal is a *new* signal that never passed risk as edited. Operators who want smaller size change per-child risk config (live-class key) and the *next* signal obeys. This omission is deliberate and permanent.

### 1.9 Card client-side state chart

```
            ┌────────────┐ render+ack ┌─────────┐  hold   ┌──────────┐
 delivered ─►  VISIBLE   ├───────────►│  ACKED  ├────────►│   HELD   │
            └─────┬──────┘            └──┬───┬──┘         └────┬─────┘
                  │ card_updated(vN+1)   │   │ tap                │ tap
                  ▼  (any state, loops)  │   ▼                    ▼
            [re-render, bump v, ping]    │ ┌────────────────────────┐
                                         │ │ RESOLVING (req in      │
                                         │ │ flight; spinner ≤ 5 s, │
                                         │ │ then "retrying…")      │
                                         │ └──────────┬─────────────┘
                                         │            │ confirm.resolved
                                         ▼            ▼
                                   ┌─────────────────────────────┐
                                   │ RESOLVED: outcome + resolver │
                                   │ (+ race_losers truth line;   │
                                   │  STALE_CARD → back to VISIBLE│
                                   │  on updated card)            │
                                   └─────────────────────────────┘
```

---

## §2 Telegram — mobile-first ergonomics

### 2.1 Card format within Telegram's constraints

Constraints designed against: 4096-char message cap (cards target ≤ 700 chars / ≤ 14 lines — hypothesis, leaves headroom for the against-block); inline keyboards up to 8 buttons/row but thumb ergonomics cap us at 2 per row; per-chat sustained send ≈ 1 msg/s and ~20 msg/min (literature-informed Telegram Bot API limits) — which forbids per-second countdown edits (§2.2).

```
🟢 LONG EURUSD · trend.donchian_v1        [HYBRID]
Risk $52 (0.50%) · gap-str $68 (Fri hold)
⏳ Does nothing → EXECUTES at 06:00 UTC (~9 min)

WHY  breakout of 20d high 1.09210
     regime TRENDING_UP 0.84 · ER 0.41
⚠ AGAINST  spread 1.4× norm · USD factor 3.2/5.0%

STOP @1.09210 · SL −70t · TP +2.0R · 0.10 lots
Exits bot-managed. Card v1 · valid to 14:00
   [ ✅ Approve ]  [ ⏸ Hold ]
   [ ❌ Reject ]
```

Countdown renders as **absolute deadline + coarse relative** (`at 06:00 UTC (~9 min)`) because the message cannot tick. Callback data: `cf:<signal_id_short>:<action>:<card_version>` (≤ 64-byte callback limit respected). Every tap gets an instant `answerCallbackQuery` toast ("request sent — awaiting core…") so the human knows the tap registered even before resolution — feedback ≤ 400 ms, resolution truth only from the event (§3.4 rule applies to Telegram equally).

### 2.2 Edit-in-place lifecycle (≤ 5 edits per card, rate-limit-safe)

State changes **edit the original message** (`editMessageText`) rather than sending new ones — one card = one message = one place to look, and dead cards can't be tapped:

| Trigger | Edit |
|---|---|
| delivery-ack from *other* channel / hold applied | status line + (hold) silence-line rewrite; keyboard kept |
| `card_updated` (partial/full fill, spread-gate flip) | full re-render, v bump, **new notification ping** (silent-priority in quiet hours) |
| T-2 min reminder (held or unresolved) | prefix `⏰ 2 min left`; ping |
| `confirm.resolved` | final: outcome + resolver + race truth; **keyboard removed** (un-tappable by construction); e.g. `⏱ TIMEOUT-EXECUTED 06:00:00 · your approve arrived 06:00:00.8 — did not cause this trade` |
| expiry/invalidations | final render, keyboard removed, reason line (`INVALIDATED: regime flipped`) |

Budget: worst case 5 edits/card, well inside per-chat limits even with 4 concurrent cards (hypothesis: ≤ 6 concurrent confirmations at defaults; the mode router + per-child caps make bursts small).

### 2.3 Delivery-ack protocol, UX face (F-009)

Ack ladder (each level journaled with timestamp + channel):

1. **`sent`** — interface handed the message to the Telegram API and got HTTP 200 + `message_id`. This is the F-009 `confirm.delivery_ack(channel=telegram)` trigger, per pass3 row 6. *It means "Telegram accepted", not "human saw" — the board records this honestly and accepts it*: the fail-closed machinery exists to catch *outages*, and send-success is exactly the outage discriminator (pass1 F-009 synthesis: absence-by-outage vs absence-by-choice).
2. **`seen`** — any human interaction with the card (tap incl. Hold, or GUI card render event). Upgrades the record; consumed by analytics (§5.3) and displayed on the signal feed (`TG✓ 👁`).
3. **`resolved`** — terminal.

The Titan `send_message` fire-and-forget pattern (`asyncio.create_task`, no result consumed — measured in `src/ops/telemetry.py:84`) is **forbidden for the confirmation class**: confirmation sends are awaited, retried (3× exponential backoff, borrowed), and their failure is itself an event (`health.metric telegram_api state=WARN`) — because an unacked confirmation changes trading behavior (row 11). INFO-class notifications may keep fire-and-forget.

### 2.4 Degraded modes

| Condition | Behavior |
|---|---|
| Telegram down, GUI acked | Cards proceed on GUI ack alone (≥ 1 ack suffices). Telegram catch-up on recovery: **digest, not replay** — resolved cards arrive as one summary message ("while Telegram was down: 3 signals — 2 executed by timeout✱, 1 skipped"), never as stale tappable cards. ✱only possible if GUI acked. |
| Both channels unacked | Row 11 fail-closed: TIMEOUT_SKIPPED + WARN. The WARN itself is queued for delivery on recovery **and** trips `health.metric interfaces state=CRIT` after 3 consecutive unacked cards (hypothesis) → dead-man's-channel escalation (05§C healthchecks-style ping carries an `interfaces_degraded` flag, so the external monitor alerts even though the bot's own channels are dark — the only path that can report the reporters). |
| GUI up, operator absent | Normal timeout semantics — GUI ack is delivery, absence-by-choice is the operator's configured contract. |
| Telegram *callback* path degraded (sends ok, taps failing) | Taps are idempotent commands; interface surfaces `answerCallbackQuery` failures as a GUI banner ("Telegram taps may not be reaching the core — use GUI"). |

### 2.5 Quiet hours vs urgency taxonomy (F-039 adopted and completed)

Mapping (F-039's rule, made total):

| Class | Quiet hours (default 23:00–06:00 operator-local, config) | Notes |
|---|---|---|
| CRITICAL (breaker trips, recon QUARANTINE/REFUSE, dead feed, stop-attach failure, duplicate execution) | **Always pierces, full sound** | Non-negotiable; matches 05§C. |
| WARN (viability disable, spec change, hybrid degraded-to-skip, loop-lag) | Suppressed → **morning digest** at quiet-hours end, count badge in GUI immediately | Digest is one message, grouped by class. |
| INFO (fills, exits, config applied) | Suppressed → digest | |
| **Confirmation requests** | **Delivered silently** (`disable_notification=true`): the card arrives, acks fire, no sound. Per-child override `quiet_hours: {deliver: silent\|suppress, timeout_action: unchanged\|skip}` | See debate. |

**The debate that set the confirmation default (§8-4).** Swing Trader: "a hybrid child with `timeout: execute` plus silent overnight delivery is just auto with extra steps while I sleep — that's a mode violation with a clear conscience." Day Trader: "suppressing delivery means the fail-closed row 11 fires and my trend children skip all night — that's converting hybrid to manual-overnight without me asking." Both are right, which is why it is **per-child config, with the honest default `deliver: silent, timeout_action: unchanged`** and a mandatory one-time GUI notice at child setup: *"During quiet hours this child will execute on timeout without waking you. Change `timeout_action: skip` for a hard human gate overnight."* The mode contract stays whatever the operator wrote — but the interface makes them write it with eyes open. Unanimous after wording.

### 2.6 Command grammar (consistency contract)

Uniform shape: **`/verb [scope] [args]`**, scope ∈ `child-id | family | instrument | all`; every command answers with current state after the change (idempotent reads back). The full v1 surface:

```
/status [scope]        equity, open R (both risk numbers), breakers, mode summary
/signals               pending confirmations (tappable cards re-linked, not re-sent)
/positions [scope]     open positions: child, R, mode badge, stop state
/mode <child> <auto|hybrid|manual>       (live-class; logged with actor)
/pause <scope> · /resume <scope>
/hold <signal-id-short>                  (snooze parity with buttons)
/flatten <instrument|all>   ⚠ double-confirm, 30 s TTL
/killswitch                 ⚠ double-confirm, 30 s TTL
/breakers [ack <breaker-id>]             ack = manual-reset path (02§A4)
/risk                  ledger: per-scope usage vs caps, binding-order note (F-036)
/overrides             active runtime config overrides + provenance (F-026)
/config get <key> · /config set <key> <value>    (live-class keys only, schema-validated)
/report daily|weekly
/help [verb]
```

Unknown/misspelled commands return the nearest match (`did you mean /flatten?`) — never silence. Anything not on this list is not reachable from Telegram (no config file edits, no param changes, no gate overrides — those are GUI+schema territory).

### 2.7 Rate limiting & allowlist — enforcement points (F-031 interface face)

Defense-in-depth, three independent layers, each sufficient alone:

1. **Edge:** nginx — TLS, IP-allowlist option, request rate caps (30 req/min/IP on `/api`, hypothesis) — protects the interface process.
2. **Interface process:** Telegram `chat_id`/user-id allowlist checked before parsing (Titan single-chat pattern, extended to a list with per-user role `operator|viewer`); GUI session auth + the Titan `AuthThrottle` (5 failures/60 s/IP — measured-in-repo constant, borrowed) ; destructive-command TTL handshake lives here.
3. **Core:** §8.5 HMAC validation, nonce replay cache, actor permission table (live-class keys only), and **core-side rate limits per actor**: mode switches ≤ 6/min, config writes ≤ 12/min (hypothesis) — the core defends itself even against a compromised interface process (F-031's premise).

**Exemption, stated in bold: the two red buttons are never rate-limited.** `/killswitch` and `/flatten all` bypass every throttle at every layer (they still require the double-confirm handshake). A rate limiter that can delay the kill path fails the locked requirement "kill paths always available"; the Auditor walked this exact interaction and the limiter code must special-case it with a pinned unit test.

---

## §3 GUI real-time architecture

### 3.1 Topology (consumes pass3 §8.2 as-is)

Browser ⇄ nginx :443 ⇄ **interface process** :8790 (FastAPI + WS fan-out, SPA static serving, Telegram bot) ⇄ core :8770 (localhost): WS event stream down, HMAC command channel up. The interface process holds a read-only SQLite connection for history/journal queries and is **stateless with respect to authority** — it caches, renders, and relays; every fact it shows carries a core `seq`.

### 3.2 WebSocket message contract (typed, versioned)

All frames are JSON with envelope:

```
Server → client:
{ "v": 1, "kind": "snapshot" | "delta" | "heartbeat" | "resolved" | "error",
  "channel": "signals"|"confirmations"|"positions"|"risk"|"breakers"|
             "health"|"regime"|"config"|"market",
  "seq": <u64 core event seq — the same seq as pass3 §1.1; null only on heartbeat>,
  "ts": <server ns>, "payload": { ... typed per (channel, kind) } }

Client → server:
{ "v": 1, "kind": "hello",  "ticket": "<one-time WS ticket, §3.6>",
  "channels": ["confirmations","positions",...], "resume_from": <u64|null> }
{ "v": 1, "kind": "card_ack", "signal_id": "...", "card_version": 2 }   # F-009 GUI ack
{ "v": 1, "kind": "sub" | "unsub", "channels": [...] }
```

Channel payloads are **projections of pass3 §1.2 event families**, not raw events: `confirmations` carries the card object + card_version + ack state; `positions` carries the three-column ledger rows (risk-at-stop / gap-stressed / margin+notional — F-005/F-011 display duty); `risk` carries `totals` + limit headrooms + binding-order; `market` is throttled to 1 Hz per instrument (hypothesis) and clearly a courtesy feed. **Mutations never travel on the WS** — approve/reject/hold/commands go over REST → interface → HMAC command channel, keeping one auditable mutation path (F-015/F-031). The single exception is `card_ack`, which is not a mutation of trading state but a delivery fact; the interface forwards it to the core as the GUI delivery-ack.

### 3.3 Snapshot + delta + resume (gap replay)

- On `hello` with `resume_from=null` (or unresumable): server sends one `snapshot` per subscribed channel (full projection + `seq` high-water mark), then live `delta`s.
- On `hello` with `resume_from=S`: if `head_seq − S ≤ 5,000` events **and** S is within the un-archived SQLite tail (pass3 §1.3 retention guarantees ≥ last two snapshot spans) — both hypothesis thresholds — the interface replays channel-relevant deltas from the read-only DB in seq order, then goes live. Otherwise it answers `error{code: RESUME_TOO_OLD}` and the client re-requests snapshots. Client keeps `last_seq` per channel; on any received delta with `seq` implying a gap (interface fan-out is ordered, so this means interface restart), client resets to snapshot.
- **Heartbeat** every 5 s: `{kind:"heartbeat", payload:{head_seq, server_wall_ns, core_link:"LIVE|DOWN"}}`. Client uses it for (a) gap detection, (b) clock-offset for countdown rendering (§1.5), (c) staleness (§3.5), (d) surfacing `core_link` — the interface being up while the core is down is a distinct, displayed state ("interface alive, core unreachable — commands will fail, data frozen at seq N").
- Reconnect: exponential backoff 1 s → 15 s cap + jitter with REST poll fallback of `/api/state` every 5 s while disconnected (Titan `useLiveState` skeleton — borrowed, measured-in-repo — extended with seq/resume).

### 3.4 Optimistic UI rules (normative table)

| May render immediately (client-local truth) | Must wait for the core event (authoritative truth) |
|---|---|
| Navigation, filters, form edits pre-submit | **Confirmation outcomes** — card shows `RESOLVING` spinner; outcome only from `confirm.resolved` (F-008: the human must never see an outcome the STA hasn't produced; `race_losers` renders verbatim) |
| "Request sent" pending chips (with the request's idempotency key shown on long-press for support) | Mode badge flips — only on `config.change_applied` |
| Config diff *preview* (client-computed, labeled "preview") | Config applied/rejected state — `config.change_applied/rejected` |
| Countdown ticks (from timestamps + offset) | Breaker ack results, manual closes, flatten/kill progress (in-flight banner until events arrive) |
| — | Anything that implies money state changed |

Timeout for the pending state: if no event within 5 s (hypothesis), the chip degrades to "still waiting — core busy or link degraded; your request is idempotent and will not double-fire", never to an assumed success *or* an assumed failure. **Frontend Architect's note (§8-5):** the original draft had optimistic resolution flips for responsiveness; the seat withdrew it upon re-reading F-008's race analysis — an optimistic "approved ✓" that later becomes "actually, timeout beat you" is strictly worse than 800 ms of spinner. The board records this as the pass's easiest unanimous decision.

### 3.5 Staleness indicators (F-025/F-033 surfacing)

Two staleness domains, **never conflated** (Frontend + Infra joint requirement, §8-6):

1. **GUI link staleness** — heartbeat age > 12 s (hypothesis): global amber banner "live feed stale Xs — showing last known state (seq N)". All money numbers get a subtle desaturation + last-updated stamp; the confirmation countdown ring freezes visibly (it computes locally but the *card might be resolved already* — the banner text says exactly that).
2. **Market feed staleness** — from `market.feed_staleness_changed` (calendar-aware, F-025): per-instrument chips FRESH/STALE/DEAD on every instrument-bearing row; DEAD chips link to the data-integrity breaker's status ("no new entries; exits still allowed") so the operator sees cause→policy in one hop.

Clock health (F-033): NTP offset and broker-clock offset render in the health strip with the pass3 §8.3 thresholds (WARN > 250 ms, entry-block > 750 ms, CRIT > 1 s — hypothesis); the entry-block state explains itself: "session-scoped entries blocked: clock offset 810 ms".

### 3.6 Auth model

- Login (username + password, argon2id — hypothesis params per OWASP defaults) at nginx-fronted interface → httpOnly SameSite session cookie, 12 h idle expiry (hypothesis). Roles: `operator` (full), `viewer` (read-only — Titan `ReadOnlyContext`/`require_writable` pattern adapted from env-flag to role).
- WS auth: REST `POST /api/ws-ticket` (session-authed) returns a single-use 60 s ticket; the client sends it as the **first frame** (Titan first-frame pattern kept — it exists because browsers can't set WS auth headers) — tickets never appear in URLs/logs.
- Failed-auth throttling: Titan `AuthThrottle` borrowed (5/60 s/IP) at the interface + nginx rate caps at the edge.
- The GUI session secret, command-HMAC key, and Telegram token live per pass3 §8.5 (`LoadCredential`); the browser never sees anything but its own session.

### 3.7 Guard tests carried forward (the paid-for lesson)

The Titan uvicorn/websockets incident (real /ws upgrades failing in production while TestClient passed — measured, this repo) becomes three pinned CI checks: (1) dependency guard — `uvicorn[standard]` + `websockets` importable in the shipped image (Titan's guard test ported verbatim); (2) a **real-transport** WS smoke in the chaos harness (pass3 §7.4's "never in-process test clients" rule applied to the interface: connect through nginx, complete hello/ticket, receive a heartbeat); (3) a Telegram sandbox send/ack round-trip against a mock API server over real HTTP. Interface features that only work under TestClient are treated as regressions by construction.

---

## §4 Information architecture — the seven pages, refined

Global chrome (always visible, every page): **top strip** = breaker states (per-breaker chip: ARMED grey / TRIPPED red + ack affordance if manual-reset / COOLDOWN amber with timer), connection + clock health, netting-mode badge when degraded (F-002: `NETTING — 1 child/instrument`, links to the §8.7 explainer), pending-confirmation count (pulsing when > 0), and the two red buttons (PAUSE-ALL, FLATTEN-ALL — double-confirm, never throttled). The strip is the same component the traders see first on every visit; it answers "is anything on fire" before any page loads.

| Page | Purpose | Primary question answered | Key components (with Pass 1–3 additions) | Deliberately omits |
|---|---|---|---|---|
| **1 Dashboard** | Account state at a glance | *"Am I okay right now?"* | Equity curve (session/day/week); **two-number risk gauge**: risk-at-stop vs gap-stressed vs caps (F-005/F-011), margin utilization bar (limit #9); positions table (child, R, mode badge, stop-state chip from `position.stop_state` — VERIFIED green / ATTACH_RETRYING amber / FAILED red); live signal feed with state chips incl. delivery-ack icons; regime heat strip **with dwell**: published label + candidate label + dwell counter when a flip is brewing (E0); `N_eff` display beside child count ("8 children ≈ 2.3 independent bets — hypothesis" — Pass 2 §6.1's honesty number, on the front page by board vote) | Tick-flashing P&L (1 Hz max — no casino feedback loop); per-trade noise; anything editable |
| **2 Confirmations** | Decide under time pressure | *"What is the bot asking, and what happens if I ignore it?"* | §1 cards, newest-deadline-first; resolved-card history (last 24 h) with race-truth lines; per-child snooze/approval stats inline (small, non-judgmental) | Charts, analysis tools, editing — anything inviting re-analysis in the window |
| **3 Children** | Roster management | *"Is this child healthy, and in what mode?"* | Per child: mode segmented control + override stack (§6.3); **viability badge with the corrected F-003 number and hysteresis state** (`viab 1.6 ✓` / `disabled 0.9 — re-enables ≥ 1.5`) per instrument; live-vs-expectation **block ribbon** (§5.1, F-013 framing); params (read-only values + validated-range editor for next-signal class) with **pinned-params badge** ("2 open positions on params v3" — F-027); gate status (G1/G2/G3 with per-gate evidence links); build-priority + evidence grade from the Pass-2 dossier (E1/E2/E3 shown — the operator should know M2 is folklore-constructed while T1 is E1) | Any control that edits entry logic live (anti-goal 05§D7); per-trade cheering |
| **4 Instruments & Broker** | Discovery + capability truth | *"What can I trade here, and at what cost?"* | Discovery table: tags, resolution confidence with one-click confirm queue (03§B2), propose queue (`auto_enable: propose`); per-session spread sparklines + **open-window spread decay curve** for indices (M4's gating measurement, Pass 2 §3.4); swap table with triple-swap day marked; spec-change diff timeline with per-field severity (F-007); netting/hedging account panel | Manual symbol mapping free-text (confirm/reject only — typos here are money bugs) |
| **5 Config** | Safe change | *"What is the effective config, and how did it get this way?"* | Schema-driven forms (invalid states unclickable, inline 422s — Titan pattern); reload-class chips per key (live / next-signal / restart-required); **runtime-overrides drawer** (F-026): "3 runtime overrides active", each with provenance + created_at + keep/drop actions, YAML-reload conflict resolution flow; **binding-order report** (F-036) rendered after every validation ("limit #7 cannot bind at current settings — binding: #2 #4 #6 #8 #9"); config history timeline, revert = new change (§5.4) | Raw YAML editing in-browser; secrets (never displayed, 05§C) |
| **6 Research / Backtests** | Gate evidence | *"Has this child earned its risk?"* | Run cards (manifest-pinned: git sha, config hash, dataset hash, cost-model version — pass3 §5.5); gate checklists per child version with **negative/positive control status** (pass1 T7: "controls last ran green 2026-07-12"); cost waterfall chart (gross→spread→slippage→double-fill→swap→net; mandatory for T4/M4); parameter-plateau heatmap (a spike-at-one-cell renders as the failure it is); WF efficiency; regime-sliced P&L vs the child's pre-registered predictions | Any "promote to live" button that bypasses gate checklist state; parameter tweak-and-rerun loops (runs launch from explicit new run cards only — every variant logged, 05§B3) |
| **7 Journal** | Auditable memory | *"What actually happened, and why?"* | Closed trades with frozen snapshot + card-as-seen (what the human saw at approval, F-001 audit); execution telemetry per trade; `closed_by` attribution incl. `quarantine_policy`/`broker_stopout`; quarantine book view (F-032) with attribution workflow; human-decision analytics (§5.3); event-log day replay (the GUI is a projection of the log — it can re-render any day, 05§A1 kept) | Aggregate vanity stats without labels; any affordance that edits history |

---

## §5 Journal & learning-loop legibility

### 5.1 Live-vs-expectation, in the F-013 frame (not naive cones)

The board explicitly bans the seductive wrong chart: a per-trade equity line inside a 95% Monte-Carlo fan. That chart *invites* per-trade peeking — the exact optional-stopping failure F-013 killed. What renders instead, per child × instrument:

```
BLOCK RIBBON  (1 cell = 20 trades or 4 weeks, whichever first — the F-013 block)
  [ +0.14R ✓ ][ +0.06R ✓ ][ −0.02R ⚠ ][ +0.11R ✓ ][ … ]   cell = block mean-R
     vs the G1 expectancy band at block scale (MC of 20-trade means)
CUSUM TRACK   below the ribbon: the actual monitored statistic, with two labeled
  boundaries: "WARN (95%)" and "ACTION (99%, must sustain 2 blocks → risk halved)"
  — the same numbers the automation uses; the chart shows the alarm's own state,
  not a prettier proxy.
CAPTION (permanent): "Evaluated per block, never per trade. A single ⚠ block is
  expected noise (≈1 in 20 under H₀ — literature-informed); the alarm acts on the
  CUSUM boundary, not on this ribbon."
```

Mid-block progress renders as a **greyed partial cell with no verdict** — visible but uninterpretable by design (Quant seat's condition: the UI must not create a per-trade alarm the statistics don't back). Regime-attribution panel sits alongside: live regime-sliced P&L vs the dossier's pre-registered predictions (P1/P2/P3 per child), each labeled `prediction: ≥65% in TRENDING (hypothesis) · live: 71% (measured, n=48)`.

### 5.2 Execution-quality dashboard

Per (broker, instrument, mechanism, session) — the exact cells the learning loop learns on (03§A4, F-029):

- Slippage distribution (signed ticks) per mechanism × session as small-multiple histograms; cell sample count displayed, and cells with `n < 100` (F-029 floor — hypothesis) render greyed with "insufficient sample — priors in force" so nobody reads noise as knowledge.
- Requote/reject rates; `SENT_UNKNOWN` probe outcomes; duplicate-execution counter (must read 0 — it renders red at any value, pass3 §3.2).
- **Adverse-selection panel** (F-012): limit-fill vs next-N-bar drift, per child — M1's G2 exit criterion is a chart the operator watches fill in, with the 50%-credit hypothesis line drawn until measurement replaces it.
- Cost-model drift: measured spread/slippage vs the cost-model version pinned in the child's last G1 run — divergence > 30% for 2 weeks (Pass-2 falsifier) renders as the auto-disable warning it will trigger.

### 5.3 Human-decision analytics (05§D5 made visible, honestly)

Per child and per operator: approve/reject/hold/timeout counts; median decision latency; approval rate by hour (the 3 a.m. approvals get their own row — quiet-hours policy feedback); and the centerpiece, **counterfactual R of rejected signals**, computed by replaying the frozen risk block through the fill model. Labeled permanently: *"counterfactual — fill-model estimate (hypothesis-grade); rejected signals were never exposed to real slippage."* The Auditor's wording condition (§8-7): the phrase "your rejections would have made +14R" is banned; the panel says *"rejected signals' modeled outcome: +14R over 31 signals; approved signals' realized: +9R over 87"* — data, not accusation. A per-child **decision-value line** (approved-realized mean R minus all-signals modeled mean R, per block) feeds the graduation panel (§6.4): it is the number that says whether this human, on this child, is a filter or a tax.

### 5.4 Config history & revert (F-026 resolved here)

- Every `config.change_applied` renders as a timeline entry: actor, timestamp, per-key old→new chips, reload-class, provenance (`gui`, `telegram`, `yaml-reload`).
- **Revert is always a new forward change** pre-filled with the old values, re-validated, re-logged — history is append-only in the UI exactly as in the log (no "undo" verb anywhere; the button says "restore these values").
- The runtime-overrides drawer implements F-026's contract: persistent badge `N runtime overrides active` in the Config page header **and** in `/status`; each override shows provenance + age; on YAML reload with conflicts, a blocking modal lists each conflict with keep-override / take-yaml choices — silent divergence between file and effective config is no longer a representable state. Export-to-YAML (04§B1) is the blessed "make permanent" action, one click per override or bulk.

---

## §6 Mode-switching ergonomics

### 6.1 Controls

Per-child segmented control `AUTO | HYBRID | MANUAL` (Children page + `/mode`), applied via command channel → `config.change_applied` → badge flips on the event (never optimistically, §3.4). Family- and global-level scope selectors reuse the same command grammar (§2.6). Every switch is journaled with actor — mode churn is itself a pattern the journal can show ("mode changed 9× this week on M2" is information about the operator).

### 6.2 The no-rug-pull rule, surfaced

On any mode switch affecting a child with signals in `AWAITING_CONFIRM`, the confirmation toast states the pass3 §2.1 contract: *"Mode → AUTO applied. 2 signals already awaiting confirmation keep their HYBRID contract (no rug-pulls); new signals route AUTO."* The affected cards gain a small chip `contract: hybrid (pinned at route)`. Same pattern for param edits: next-signal class changes toast *"applies to new signals; 3 open positions keep pinned params v3 (F-027)"*.

### 6.3 Override stacking display

Effective mode is a computed stack, and the UI renders the stack, not just the result:

```
meanrev.asian_bb_v1   effective: MANUAL 🔒
  └ breaker: DRAWDOWN −12% forced MANUAL (manual-ack reset)   ← winning layer
  └ family override: —
  └ child config: hybrid
```

Rules: most-restrictive-wins (02§B4) is visually literal — the winning layer is topmost with a lock icon; breaker-forced layers are **not editable in place** (the segmented control disables with a tooltip: "release the drawdown breaker to change modes — [Breaker ack]"), so the operator is walked to the governing object instead of fighting a mysteriously stuck control. Global `/pause all` renders as a full-width banner on every page, with who/when/why.

### 6.4 From "hybrid everywhere" to "auto everywhere", with evidence

The graduation panel (per child, on the Children page) is a **checklist of thresholds, all states displayed, no recommendation copy**:

```
Graduation evidence — meanrev.asian_bb_v1        [3 of 5 met]
 ✓ ≥ 3 consecutive blocks inside CUSUM expectation (currently 4)
 ✓ delivery-acked rate ≥ 99% over window (99.6% — measured)
 ✓ timeout-degrade (row 11) events = 0 in window
 ✗ ≥ 30 human decisions on this child (currently 21)             (hypothesis: 30)
 ✗ |decision-value| < 0.03R/trade over last 3 blocks (−0.06R)    (hypothesis: 0.03)
```

The fifth line is §5.3's number: while the human's vetoes are measurably adding (or costing) value, the panel shows it; when the human filter converges to noise, the evidence says so. **Quant objection (§8-8):** an earlier draft ended with "consider switching to AUTO" — a nudge is a decision the system is not entitled to make about its own supervision. **Resolution:** all prescriptive copy deleted; the panel states criteria and their states; the mode control sits beside it, untouched. The reverse path is asymmetric by design: switching *toward* MANUAL/HYBRID never asks for evidence and never gets friction — restricting the bot is always one tap; freeing it is a human conclusion drawn from a filled-in checklist.

---

## §7 BORROW / ADAPT / REBUILD vs Titan Control GUI (file-level)

Consistent with pass3 §6.2; this table is the interface-detail refinement.

| Titan artifact | Verdict | Rationale |
|---|---|---|
| `src/ops/web/auth.py` — fail-closed bearer check (`hmac.compare_digest`), `AuthThrottle` (5/60 s/IP), `require_writable` | **ADAPT** | Throttle + compare-digest + fail-closed shape kept verbatim; single static env token → login-issued session + one-time WS tickets (§3.6); env read-only flag → `viewer` role. |
| `src/ops/web/server.py` — first-frame WS auth (3 s timeout), `/api`-before-SPA route ordering, path-traversal-safe SPA fallback, headless-when-no-dist | **ADAPT** | First-frame auth kept (ticket instead of raw token); route-ordering + traversal guard + headless fallback kept; the naive `{"type":"state"} + {"type":"event"}` fan-out is replaced by the §3.2 channel/seq/resume contract; app moves from in-core embedding to the interface process (pass3 §9-2 split). |
| `src/ops/web/server.py::_audit` (`GuiActionExecuted` tape) | **REBUILD (pattern promoted)** | The idea — every GUI mutation is a logged event with actor/args/outcome — is right and survives; the implementation moves into the core (commands event-logged with actor + HMAC identity per §8.5), because an interface-side audit of interface-side actions is the fox journaling the henhouse (F-031). Interface keeps only local auth-failure logs. |
| `src/ops/web/settings.py` + `config_layer.py` — safe-subset live keys, tier/source badges, inline 422 | **ADAPT** | Live/restart tiering UX maps directly onto 04§B4's three reload classes (adds next-signal tier); badges + inline 422 pattern kept; backing store becomes the core config service via command channel. |
| `src/ops/web/fake_controller.py` + `devserver.py` | **BORROW** | Drive-the-SPA-without-a-broker dev harness; regenerated against the new channel contract but the pattern ships as-is. |
| `src/ops/web/state_view.py` / `bus_bridge.py` / `commands.py` / `registry_view.py` | **REBUILD** | Snapshot/relay/command shapes are Titan-controller-specific; superseded by projections of the pass3 event families + the command channel. |
| `frontend/src/lib/useLiveState.ts` — WS + backoff (1 s→15 s cap) + REST poll fallback | **ADAPT** | Reconnect skeleton and poll fallback kept; add per-channel `last_seq`, resume handshake, heartbeat staleness, snapshot+delta reducer. |
| `frontend/` shell — Vite+React+TS+Tailwind+shadcn, `TokenGate`, `ReadOnlyContext`/`ReadOnlyBanner`, `HealthStrip`, `EventFeed`, `PositionsTable`, `EquitySparkline`, dataviz/design system, npm test harness | **BORROW (shell + kit) / REBUILD (pages)** | Component kit, design system, test harness proven (41 green — measured, this repo); `TokenGate`→login flow, `ReadOnlyContext`→roles; all seven §4 pages are new builds on those components. |
| uvicorn-websockets **guard test** | **BORROW verbatim + extend** | §3.7: dependency pin + real-transport WS smoke + Telegram round-trip. The lesson was paid for once; it ships as CI forever. |
| `src/ops/telemetry.py` — session pooling, retry/backoff (3×, exp), `CONFIRM_TTL=30 s` destructive handshake, single-chat allowlist | **ADAPT (ops) / REBUILD (confirmation path)** | Pooling, backoff, TTL handshake, allowlist-first parsing kept. Rebuilt: fire-and-forget `send_message` is forbidden for confirmation-class sends (must return `message_id` → delivery-ack event, §2.3); raw-`requests` long-poll → `python-telegram-bot` app with edit-in-place lifecycle; command dispatch → §8.5 channel with actor identity. |

---

## §8 Board debate log (objections that changed content)

1. **Day Trader vs risk-before-price field order (§1.2).** Wanted the entry level on line 2 ("I think in levels"). Resolution: mock-session walk-through showed veto decisions hinge on risk/spread/context, not the fourth decimal; levels stay block 6. Changed nothing in the machine, everything in the hierarchy. Accepted 8–2 (both traders initially dissenting; Day Trader conceded after the counterfactual review, Swing Trader after gap-stressed risk got line 2).
2. **Strategist vs snooze-as-claim (§1.7).** "Hold cancelling execute-on-timeout lets a distracted human kill good signals." Resolution: an explicit human 'wait' must beat a timer or the button lies; T-2 min re-ping + §5.3 pricing of snooze habits added as mitigation. Carried 9–1.
3. **Backend Architect vs version-pinned approvals (§1.8).** Retry loop under time pressure. Resolution: only material changes bump `card_version`; rejects exempt from pinning. Satisfies the F-001 Auditor condition without a re-read tax on the common path. Signed off.
4. **Swing Trader vs Day Trader on quiet-hours confirmations (§2.5).** Silent-delivery default = "auto with extra steps overnight" vs suppression = "manual-overnight nobody asked for". Resolution: per-child `{deliver, timeout_action}` quiet-hours config, default silent/unchanged, mandatory eyes-open setup notice. Unanimous after wording.
5. **Frontend Architect withdraws optimistic confirmation rendering (§3.4).** Own draft proposal killed on re-reading F-008: an optimistic "approved ✓" that later reverses is a manufactured false model of control. Pending-spinner + event-truth adopted unanimously.
6. **Infra + Frontend vs conflated staleness (§3.5).** A single "stale" banner would teach operators to distrust the breaker display (GUI-link staleness ≠ market-feed staleness). Resolution: two indicators, different visual domains, feed chips link to breaker policy.
7. **Auditor vs counterfactual phrasing (§5.3).** "Your rejections would have made +14R" is a model output dressed as a fact and an accusation dressed as analytics. Resolution: mandatory "modeled/fill-model estimate" labeling; side-by-side realized-vs-modeled framing; banned phrase list in the copy spec.
8. **Quant vs graduation nudges (§6.4).** "Consider AUTO" copy deleted — the system must not recommend reducing its own supervision; evidence display only, friction asymmetry (restrict = one tap, free = filled checklist) adopted.
9. **Auditor vs rate-limited kill paths (§2.7).** Walked the interaction: a throttled `/killswitch` after a fat-fingered command burst violates "kill paths always available". Resolution: red buttons exempt from every limiter at every layer, pinned unit test required.
10. **Networking seat vs Telegram edit-spam (§2.2).** Per-second countdown edits would hit per-chat limits exactly during confirmation bursts (markets make bursts). Resolution: absolute-deadline rendering, ≤ 5 edits/card lifecycle, state-change-only edits.

---

## §9 Findings-resolution table (Pass-5 dispositions)

| Finding | Where resolved | Status |
|---|---|---|
| F-001 (display face) | §1.6 partial-fill card mutation; §1.8 version-pinned approvals (audit "what they saw"); §4 journal card-as-seen | RESOLVED (machine side was pass3 §2.1) |
| F-002 (display duty) | §4 global chrome netting badge + Instruments panel | RESOLVED (default choice remains OPEN-FOR-HUMAN) |
| F-005 / F-011 (display duty) | §1.2 line 2 (gap-stressed on card), §4 Dashboard two-number gauge, WS `positions` channel three-column rows | RESOLVED (k calibration → Pass 7) |
| F-008 (UX face) | §1.8 race-truth rendering; §3.4 no-optimistic-outcomes; §1.9 RESOLVING state | RESOLVED |
| F-009 (UX + delivery protocol face) | §1.5 fail-closed rendering; §2.3 ack ladder; §2.4 degraded modes + dead-man's-channel escalation; §3.2 `card_ack`; §6.4 timeout-degrade graduation criterion | RESOLVED |
| F-013 (display framing) | §5.1 block ribbon + CUSUM track, per-trade cone banned, mid-block cells verdict-free | RESOLVED (statistics themselves → Pass 7) |
| F-016 (interface consequences) | §3.1 topology consumed; §3.7 real-transport guard tests | RESOLVED for interfaces (topology choice OPEN-FOR-HUMAN) |
| F-025 (surfacing) | §3.5 per-instrument calendar-aware chips → breaker link | RESOLVED (thresholds → Pass 4 calendar) |
| F-026 | §5.4 overrides drawer, provenance, YAML-conflict flow, `/overrides` | **RESOLVED** |
| F-031 (interface enforcement) | §2.7 three-layer enforcement + kill-path exemption; §3.2 single mutation path; §7 audit-tape promotion to core | **RESOLVED** (channel mechanism was pass3 §8.5) |
| F-033 (surfacing) | §3.5 clock-health display with threshold states; §1.5/§3.3 client clock-offset use | **RESOLVED** |
| F-036 (display duty) | §4 Config page binding-order report; `/risk` note | RESOLVED |
| F-039 | §2.5 total mapping incl. confirmation class + per-child quiet-hours config | **RESOLVED** (adopts + completes pass1's RESOLVED-HERE) |
| F-037 | Labeling applied throughout this document | APPLIED |

**Constraints exported to Passes 6–8:** Pass 6/7 (validation/learning) — the §5.1 block-ribbon/CUSUM display consumes whatever statistic Pass 7 specs; keep the boundary values renderable as two labeled lines or the display contract breaks. §5.3's decision-value metric needs a Pass-7 definition consistent with the counterfactual fill model. Pass 8 — adopt or reject the `confirm.hold_applied` amendment (§1.7; additive to pass3 §2.1: `held` flag + row-10 guard `∧ ¬held`); put the quiet-hours per-child default (§2.5) and the graduation thresholds (§6.4: 30 decisions, 0.03R — both hypothesis) on the calibration sheet; the copy-spec banned-phrase list (§8-7) belongs in the style guide the implementation inherits.

— End of Pass 5. Card hierarchy, WS contract, and page IA above are normative for implementation; every threshold labeled hypothesis awaits Pass-7 calibration.
