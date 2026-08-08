---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S021"
date:          "2026-08-08"
slug:          "trade-management-math-uses-intended-entry"
parent_session: "none"
task_domain:   "order_lifecycle"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S021 · 2026-08-08 · "trade-management-math-uses-intended-entry"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Trade-management math uses intended entry, not the actual fill price

**Why it matters / what it unblocks:** BE stops, every ratchet pct threshold, and the close-time R-multiple all key off `initial_entry`, which is currently frozen at the send-time intended price and never corrected to the broker's actual fill — so MARKET-order slippage (EA `deviation=20`, Titan_Gateway.mq5:123) can put the L1 break-even stop at a price that locks in a loss, and silently skews every trade-management decision and reported R after it.

**Exact scope (what "doing this task" means):**
- Change `state_manager.py`'s heartbeat-sync path so `active_orders.initial_entry` is overwritten with the HEARTBEAT position's actual fill price (`msg['pos'][i]['p']` = `POSITION_PRICE_OPEN`, sent by `Titan_Gateway.mq5` ~line 197) the first time a ticket is confirmed ACTIVE — today `backfill_position_state` (state_manager.py:164-178) only fills `initial_entry` `WHEN initial_entry = 0`, so the non-zero value `system_controller.py`'s `pending_signal_meta` already wrote (system_controller.py:680-683, applied at ~856-865) is never replaced.
- Scope the correction to MARKET fills only (the case that can slip); do it exactly once per ticket so a later ratchet-modified SL is never misread as the "init" price on a subsequent heartbeat.
- Confirm (via test, not new code) that `trade_manager.py`'s `get_ratchet_state`/pct math (trade_manager.py:173-176) and the close-time R-multiple calc (system_controller.py:892-895) both read the corrected value automatically, since both read the same `initial_entry` column — no separate change needed there unless the test shows otherwise.
- Add a `tests/unit` case for `state_manager.backfill_position_state` (or its replacement) proving: (a) a non-zero `initial_entry` gets overwritten by the heartbeat fill price on first sighting, (b) a second heartbeat with a further-changed price does NOT re-overwrite it.
- Add/extend a `system_controller` unit test that sends an OPENED with intended price P1, then a HEARTBEAT with fill price P2 != P1, and asserts `state_manager.get_ratchet_state(ticket)` returns P2.

**Explicitly OUT of scope (do NOT touch this session):**
- No MQL5/EA change — do not attempt to carry fill price on the `OPENED` push; the fix uses the HEARTBEAT `POSITION_PRICE_OPEN` field that's already sent.
- No change to LIMIT/STOP pending-order fill handling (they fill at their specified resting price, not subject to this slippage class).
- No change to `initial_tp` backfill semantics (stays fill-if-zero) or to the ratchet percentage thresholds (0.382/0.618/0.886).
- No change to sizing/exposure code (`risk_manager.py`) or the offline backtest engine — this is a live/paper ZMQ-bridge correctness fix only.

**Relevant project docs / decisions:** docs/TRADE_MANAGEMENT.md; audit 2026-08-07 exec finding D3 (full-system-audit-2026-08-07 memory)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `active_orders.initial_entry` reflects the HEARTBEAT's `POSITION_PRICE_OPEN` (not the send-time intended price) once a MARKET position is first confirmed ACTIVE — proven by a failing-then-passing unit test.
- [ ] A second/later heartbeat for the same ticket does not re-overwrite `initial_entry` after the first correction.
- [ ] `trade_manager`'s ratchet pct math and BE stop are shown (by test) to compute off the corrected fill price when send price != fill price.
- [ ] Close-time R-multiple (system_controller.py:892-895) is shown to use the corrected `initial_entry` via the same test data path, with no code change required there, or the code change is made if the test proves otherwise.
- [ ] `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` green.
- [ ] No files under `mql5_bridge/` touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
