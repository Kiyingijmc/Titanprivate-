---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S023"
date:          "2026-08-09"
slug:          "news-window-must-suspend-resting-limit"
parent_session: "none"
task_domain:   "risk_management"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S023 · 2026-08-09 · "news-window-must-suspend-resting-limit"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** News window must suspend resting Titan-placed pending orders

**Why it matters / what it unblocks:** The per-symbol news gate in `_execute_signal` (system_controller.py:634-637) only runs at signal-send time, so a LIMIT/STOP placed while the window is still clear rests unchecked through a later red-folder release (TTL is 12 bars = up to 12h on H1, `system_controller.py:1345-1351`). The same gate's exception handler (`_news_blocks_symbol`, system_controller.py:624-631) degrades to "not blocked" on ANY internal fault — a symbol-level fail-open the audit (2026-08-07, risk D11) flagged as silently indistinguishable from a quiet calendar.

**Exact scope (what "doing this task" means):**
- Flip `_news_blocks_symbol` (system_controller.py:624-631) to fail CLOSED: on any exception from `self.news_manager.check_symbol(symbol)`, return `(True, <reason>)` instead of `(False, None)`.
- Make that fault loud: send a Telegram alert distinct from the existing per-signal INFO skip log when the gate itself raises, throttled (persistent-fault pattern already used for `DD_CANCEL_ALERT_INTERVAL_S`, system_controller.py:108) so a repeating fault doesn't spam every candle close.
- Add a periodic sweep, run at the same loop cadence as `_cleanup_ghost_orders` (the `now_dt.second == 0` block, system_controller.py:546-547): for every row from `state_manager.get_pending_orders()` (status `PENDING`, has a `symbol` column per the `active_orders` schema), call `_news_blocks_symbol(row['symbol'])`; if blocked, send `CANCEL` for `ticket_id` (mirroring the `_cleanup_ghost_orders` CANCEL+`delete_order` pattern, system_controller.py:1281-1282), delete the DB row, and send a Telegram notice worded distinctly from the `♻️ Auto-Clean` TTL message so operators can tell a news-driven pull apart from a TTL expiry.
- Do not build a re-place-after-window mechanism — the owning strategy's normal `on_new_candle` re-signals on its next candle close if the setup still qualifies once the window clears; the existing send-time gate in `_execute_signal` already blocks a new send during the window.
- Update `tests/unit/test_controller_news_gate.py::PerSymbolGate/... test_a_news_fault_fails_open_and_still_trades`, which currently pins the fail-open contract as documented behavior — rewrite it (or replace with a fail-closed equivalent) to assert the signal is now skipped and no order is sent on a gate fault, plus a companion test for the alert throttle.

**Explicitly OUT of scope (do NOT touch this session):**
- Manually-placed MT5 pendings (no DB row, no `sl` in the heartbeat) — same documented gap as the exposure cap; still uncoverable without an EA change.
- Changing `news.window_pre_min`/`window_post_min` defaults or any other `config/config.yaml` news knobs.
- Any GUI/telemetry `snapshot()`/`digest()` payload changes beyond the new Telegram cancellation notice.
- Reworking `is_globally_blocked`'s stale-cache fail-closed path — already correct and untouched by this session.
- Building any explicit "re-place after window clears" order-resurrection logic.

**Relevant project docs / decisions:** Audit 2026-08-07 risk D11; docs/TRADE_MANAGEMENT.md context for pending-order lifecycle

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `_news_blocks_symbol` returns `(True, reason)` — not `(False, None)` — when `news_manager.check_symbol` raises.
- [ ] A per-symbol gate fault sends a distinct, throttled Telegram alert (not just the existing WARN log line).
- [ ] `test_a_news_fault_fails_open_and_still_trades` is rewritten to assert fail-closed behavior (signal skipped, no order sent); a new test proves the alert throttle suppresses duplicate sends within the window.
- [ ] A new periodic sweep cancels (CANCEL sent + DB row deleted + Telegram notice) any Titan-placed PENDING row whose symbol enters its red-folder blackout window before fill/TTL.
- [ ] Unit test proves a PENDING row for a symbol entering the window is cancelled, and a control-case PENDING row for an unaffected symbol is left untouched.
- [ ] Full unit suite (`tests/unit`) green.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
