---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S015"
date:          "2026-07-29"
slug:          "gui-websocket-double-close-raises-runtimeerror"
parent_session: "none"
task_domain:   "api"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S015 · 2026-07-29 · "gui-websocket-double-close-raises-runtimeerror"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Guard GUI WS auth-reject close against an already-closed connection

**Why it matters / what it unblocks:** The unauthenticated-first-frame reject path calls `websocket.close(code=1008)` unconditionally; when the client has already disconnected, uvicorn raises "Unexpected ASGI message 'websocket.close', after sending 'websocket.close'", dumping a full ASGI traceback into the operator log with no functional impact on trading.

**Evidence (verified 2026-07-29, operator):** ONE confirmed occurrence — `data/logs/titan_live_stdout.log:29-77` (`ERROR: Exception in ASGI application` → `RuntimeError: Unexpected ASGI message 'websocket.close' …`), in the demo-bot session booted 11:37 2026-07-29. The drafted spec originally claimed "5x/2h"; that rate is NOT supported by any log in `data/logs/` (`grep -c` across all logs = 1). Treat this as a low-frequency log-hygiene defect, not a hot loop — it does not justify widening scope.

**Exact scope (what "doing this task" means):**
- In `src/ops/web/server.py`'s `ws()` handler, guard the auth-reject `await websocket.close(code=1008)` call (currently line 96) so it cannot raise when the connection is already closed/disconnecting — check `websocket.application_state`/`client_state` (`starlette.websockets.WebSocketState`) before calling `close()`, or wrap the call and catch `RuntimeError` (log at debug, do not propagate).
- Cover the actual race: the client disconnects while `_WS_AUTH_TIMEOUT_S` `receive_text()` is pending, or in the instant between the reject decision and the `close()` call. Note the concrete mechanism — the `except Exception:` at `src/ops/web/server.py:92-93` swallows starlette's `WebSocketDisconnect` into `token = None`, so a *disconnect* is indistinguishable from a *bad token* and falls straight through to the unconditional `close()` on line 96. Distinguishing those two is in scope; changing what counts as a valid token is not.
- Add a regression test in `tests/unit/test_gui_server.py` next to `test_wrong_first_frame_closes_1008` that reproduces the already-closed race (e.g. close the TestClient websocket, or drive/patch server-side state to already-closed, before the reject path executes) and asserts the handler does not raise/propagate `RuntimeError`.
- Preserve current behavior on the normal 1008-reject and successful-auth paths.

**Explicitly OUT of scope (do NOT touch this session):**
- The auth token-check logic itself (`auth.token_ok`, `_WS_AUTH_TIMEOUT_S` value).
- The accepted-connection event/send loop (lines 98-107) and bridge attach/detach.
- Investigating or explaining the 07-29 ~9h demo-bot outage or other open S013/S014 items.
- Any uvicorn/ASGI transport configuration change.

**Relevant project docs / decisions:** `CLAUDE.md` (Control GUI = embedded FastAPI+WS on :8770, WS first-frame auth); S014 / `RS014.md` (the sibling GUI-robustness session — a GUI fault must never reach the trading engine); `tests/unit/test_gui_server.py` (existing WS auth coverage, lines 180-195).

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] The auth-reject `websocket.close(code=1008)` path no longer raises `RuntimeError` when the connection is already closed/disconnected.
- [ ] New unit test reproduces the double-close race, fails on pre-fix code, and passes after the fix. It must drive the race **through the `ws()` handler's reject path** — a test that merely calls `close()` twice on a transport, or that asserts on timing/ordering rather than on what the handler did, does not count. State in the session report the exact pre-fix failure output that proves the test bites.
- [ ] `test_wrong_first_frame_closes_1008` and `test_first_frame_token_then_snapshot` still pass unchanged.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
