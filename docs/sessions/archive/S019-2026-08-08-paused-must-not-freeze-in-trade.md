---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S019"
date:          "2026-08-08"
slug:          "paused-must-not-freeze-in-trade"
parent_session: "none"
task_domain:   "order_lifecycle"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S019 · 2026-08-08 · "paused-must-not-freeze-in-trade"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** PAUSED must not freeze in-trade management (TradeManager.sync_positions)

**Why it matters / what it unblocks:** A manual `/pause` or the automatic stale-news-calendar pause (system_controller.py:1173-1182) both flip `BotState` to `PAUSED`, which currently skips the entire `sync_positions`/`_dispatch_mgmt_command` block at system_controller.py:910-917 — the same failure shape that left the 08-03 GBPJPY position stopless and unmanaged for 3h21m. This closes that gap without touching new-entry logic.

**Exact scope (what "doing this task" means):**
- In `src/core/system_controller.py`'s TICK handler (currently system_controller.py:901-925), split the single `if self.state == BotState.ACTIVE:` gate into two independent checks:
  - In-trade management (`sync_positions` + `_dispatch_mgmt_command` loop, current lines 913-917) runs whenever `self.state in (BotState.ACTIVE, BotState.PAUSED)` — mirroring the existing "ready to trade" grouping already used by `_readiness()` (system_controller.py:1444).
  - New-signal generation (candle processing via `market_data[symbol].process_tick`, and the `_run_strategies` call over closed candles, current lines 911, 919-925) stays gated on `self.state == BotState.ACTIVE` only — unchanged behavior for PAUSED.
  - `BotState.BOOTING`, `BotState.WARMUP`, and `BotState.EMERGENCY` continue to skip management (no behavior change for those states) — only `PAUSED` gains management.
- Do not change `_check_news_status` or `set_system_pause` — they still transition to/from `PAUSED` exactly as today; only what happens *while* `PAUSED` is in effect changes.
- Add a regression test (new or appended to an existing controller-routing test file) that: constructs a controller with `state = BotState.PAUSED`, feeds a `TICK` message via `_process_incoming_data` for a symbol with one open position whose ratchet/BE threshold is already crossed at the tick price, and asserts a `MODIFY` (or whichever command `TradeManager.sync_positions` returns for that threshold) is dispatched via `_dispatch_mgmt_command` — i.e. the command reaches the fake bridge — despite the bot being paused.
- Add a companion assertion/test that new-signal generation is still suppressed while PAUSED (e.g. `_run_strategies`/candle processing not invoked, or no new order registered) — proving the split gate didn't also re-enable entries.

**Explicitly OUT of scope (do NOT touch this session):**
- No change to `BotState.BOOTING`, `BotState.WARMUP`, or `BotState.EMERGENCY` gating — management still does not run in those states.
- No change to how/when `_check_news_status` or `set_system_pause` transition state (the stale-news auto-pause and manual `/pause` logic itself is out of scope).
- No change to `TradeManager.sync_positions` internals (BE/partials/runner-trail/kill-switch/time-exit logic itself is untouched — only the caller's gating condition changes).
- No change to pending-order placement, `_execute_signal`, or any new-entry path beyond confirming it remains gated on `ACTIVE`.
- No EA/MQL5 changes.

**Relevant project docs / decisions:** Full-system audit 2026-08-07 (risk layer D10, highest-severity new finding); prior incident precedent: 08-03 stopless-GBPJPY (dead-EA heartbeat, not PAUSED, but same "management silently stops" failure shape).

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `src/core/system_controller.py` TICK handler runs `sync_positions`/`_dispatch_mgmt_command` for `state in (ACTIVE, PAUSED)`, and candle/`_run_strategies` processing only for `state == ACTIVE`.
- [ ] New regression test: PAUSED + open position + crossed ratchet/BE threshold → a management command (e.g. MODIFY) is dispatched.
- [ ] New/extended regression test: PAUSED still suppresses new-signal generation (no new entries emitted from a closed candle while paused).
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
