---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S022"
date:          "2026-08-09"
slug:          "dd-breaker-trip-must-be-loud"
parent_session: "none"
task_domain:   "risk_management"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S022 · 2026-08-09 · "dd-breaker-trip-must-be-loud"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** DD-breaker trip must be loud: distinguish it in the skip log, alert once per trip, cancel resting pendings

**Why it matters / what it unblocks:** A tripped 3% daily-DD breaker (`RiskManager.check_can_trade()`, risk_manager.py:242) currently surfaces only as `calculate_lot_size` returning 0, which `_execute_signal`'s skip log (system_controller.py:628-631) misattributes as "unsizeable stop … or specs missing" — an operator reading the log cannot tell a max-loss-day halt from a data problem. Worse, Titan's own resting LIMIT orders are never cancelled on trip, so they can still fill after the breaker halts new entries, adding exposure on exactly the day risk should be shrinking. This subsumes the alerting half of backlog row `risk-14-daily-limit-trip-is` (trip is completely unlogged/unalerted) and closes audit-2026-08-07 risk finding D9.

**Exact scope (what "doing this task" means):**
- In `SystemController._execute_signal` (system_controller.py:628-631), when `lot <= 0`, call `self.risk_manager.check_can_trade()` to disambiguate the cause and log a distinct, clearly-labeled message when it returns `False` (DD breaker tripped) versus the existing message when it returns `True` (unsizeable stop / specs missing) — keep the existing message text for the non-breaker case.
- Add breaker-trip detection on the `HEARTBEAT` path, right after `self.risk_manager.update_account_info(bal, eq)` (system_controller.py:940), by tracking the previous `check_can_trade()` result and detecting the `True → False` transition (mirror the existing `_uncomputable_alert_at` re-arm pattern at system_controller.py:753-762, adapted to a one-shot-per-trip boolean rather than a time-interval throttle).
- On that transition: send exactly one Telegram message via `self.telemetry.send_message(...)` naming the breaker trip (equity vs. daily anchor), and cancel every row from `self.state_manager.get_pending_orders()` by issuing `await self.bridge.send_command("CANCEL", {"ticket": o['ticket_id']})` followed by `self.state_manager.delete_order(o['ticket_id'])` for each — the same two-call pattern `_cleanup_ghost_orders` already uses (system_controller.py:976-977).
- Re-arm the one-shot flag when `check_can_trade()` next returns `True` (intraday equity recovery above the anchor threshold, or a fresh day via `roll_daily_anchor`), so a later trip on the same day, or a new day, alerts again.
- List the cancelled tickets/symbols in the Telegram message so the operator can see what was pulled.

**Explicitly OUT of scope (do NOT touch this session):**
- Changing `check_can_trade()`'s math, the 3% threshold, or `day_start_equity` anchoring logic itself.
- Manually-placed MT5 pending orders with no Titan DB row (known gap — no `sl` in heartbeat, no ticket in `active_orders`; would need an EA change).
- The v15.2 drawdown throttle (`throttle_factor`) — untouched, this is the hard breaker only.
- Any new bridge/EA command — reuse the existing `CANCEL` PUSH command already used by `_cleanup_ghost_orders` and the panic/closeall paths.
- Polling for the trip outside the existing `HEARTBEAT` cadence (no new timer/loop).
- Editing `docs/sessions/_BACKLOG.md`'s `risk-14-daily-limit-trip-is` row (governance step, not code).

**Relevant project docs / decisions:** audit-2026-08-07 risk finding D9; extends backlog risk-14-daily-limit-trip-is; prior art RS-RISK-01 (risk_manager.py comments) for the fail-closed/re-arm alerting pattern this reuses.

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] Unit test: with `check_can_trade()` stubbed/forced `False` and `lot=0`, `_execute_signal`'s log line names the DD breaker (not "specs missing"/"unsizeable stop").
- [ ] Unit test: with `lot=0` and `check_can_trade()` `True` (specs missing case), the log line is unchanged from today's message.
- [ ] Unit test: a `HEARTBEAT` that flips `check_can_trade()` `True → False` triggers exactly one `telemetry.send_message` call and issues one `CANCEL` + `delete_order` pair per row returned by `state_manager.get_pending_orders()`.
- [ ] Unit test: a second consecutive tripped `HEARTBEAT` (still `False`) sends no additional Telegram message and issues no further cancels for orders already removed.
- [ ] Unit test: after `check_can_trade()` recovers to `True` then trips again `False`, a second Telegram alert fires (re-arm confirmed).
- [ ] Full unit suite green (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`).
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
