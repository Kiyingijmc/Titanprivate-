---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S026"
date:          "2026-08-10"
slug:          "emergency-state-freezes-in-trade-management"
parent_session: "none"
task_domain:   "infra"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S026 · 2026-08-10 · "emergency-state-freezes-in-trade-management"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** EMERGENCY state must keep managing open trades and verify a panic flatten before reporting success

**Why it matters / what it unblocks:** A failed `/panic` (market closed, EA offline, REQ/PUSH wedge) currently leaves any surviving position with zero BE/kill-switch/time-exit protection and reports false success — the operator has no signal the book is still exposed. This closes the highest-severity gap identified in the S019 follow-up review.

**Exact scope (what "doing this task" means):**
- Add `BotState.EMERGENCY` to the management gate at `system_controller.py:1566` (`if self.state in (BotState.ACTIVE, BotState.PAUSED):` → include `EMERGENCY`) so `sync_positions`/`_dispatch_mgmt_command` (BE, ratchet, partials, kill-switch, time-exit) keep running for any position still open after a panic — mirrors the S019 `PAUSED` carve-out. The new-signal gate at `system_controller.py:1575` (`if self.state == BotState.ACTIVE:`) already excludes `EMERGENCY`, so no new entries occur — confirm this stays unchanged.
- In `trigger_panic` (`system_controller.py:2223-2228`), after issuing `CLOSE_POS`/`CANCEL`, wait for the next 1-2 heartbeats (bounded timeout) and re-check `self.current_open_positions`/pending orders against the tickets it attempted to close/cancel.
- Replace the blind "✅ Global Flatten: Closed X | Cancelled Y" message with a heartbeat-verified outcome report, and send a distinct escalation alert naming any ticket/order still present after the verification window.
- Fix `telemetry.py`'s `/panic` handler (~line 193-195): stop sending its own unconditional "PANIC PROTOCOL EXECUTED" success message independent of `trigger_panic`'s real outcome — there must be exactly one source of truth for panic success/failure, not two possibly-contradictory messages.
- Update `tests/unit/test_controller_paused_management.py::test_non_trading_states_still_skip_management` so it no longer asserts `EMERGENCY` skips management (it should now assert `BOOTING`/`WARMUP` still skip, `EMERGENCY` does not).
- Add unit tests: (a) a position that survives the verification window triggers the escalation alert; (b) a position that actually closes reports verified success with no escalation; (c) `EMERGENCY` state dispatches management commands for an open position on TICK.

**Explicitly OUT of scope (do NOT touch this session):**
- `ctrl-02-panic-closeall-and-cancel` itself — general `/closeall`/`/cancel` outcome verification is a separate, not-yet-promoted backlog item; this session only fixes `trigger_panic`'s own verification.
- Redesigning `set_system_pause` UX/confirmation semantics or adding a dedicated "clear emergency" operator command — worth a follow-up backlog idea, not built here.
- Any EA-side protocol change (CLOSE_POS acks/retcodes) — requires a manual MetaEditor recompile on Windows, out of scope for this session.
- Automatic state transition out of `EMERGENCY` (e.g. auto-resume once flattened) — the operator still explicitly calls `/resume`; this session only makes behavior *inside* `EMERGENCY` safer and observable.

**Relevant project docs / decisions:** S019 (docs/sessions/archive/S019-2026-08-08-paused-must-not-freeze-in-trade.md); backlog item ctrl-02-panic-closeall-and-cancel; audit-2026-07-30 §8 Control

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `system_controller.py:1566` management gate includes `BotState.EMERGENCY`; positions still receive BE/ratchet/kill-switch/time-exit management while the bot is in `EMERGENCY`
- [ ] New-signal gate (`system_controller.py:1575`) confirmed unchanged — still excludes `EMERGENCY`, no new entries during panic
- [ ] `trigger_panic` waits for heartbeat-confirmed state before reporting Closed/Cancelled counts, using observed `current_open_positions`/pending-order state rather than commands-sent counts
- [ ] `trigger_panic` sends a distinct escalation Telegram alert naming any ticket/order still open after the verification window
- [ ] `telemetry.py`'s `/panic` handler no longer sends an unconditional success message independent of `trigger_panic`'s verified outcome
- [ ] `test_controller_paused_management.py`'s `EMERGENCY` assertion flipped to reflect management now running in `EMERGENCY` (while `BOOTING`/`WARMUP` still skip)
- [ ] New unit test: panic with a simulated non-closing position triggers the escalation path
- [ ] New unit test: panic with a cleanly-closing position reports verified success, no escalation
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
