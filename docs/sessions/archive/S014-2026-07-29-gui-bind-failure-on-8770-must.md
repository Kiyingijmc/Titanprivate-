---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S014"
date:          "2026-07-29"
slug:          "gui-bind-failure-on-8770-must"
parent_session: "none"
task_domain:   "infra"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S014 · 2026-07-29 · "gui-bind-failure-on-8770-must"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Make the embedded GUI's uvicorn bind failure genuinely non-fatal and its port configurable

**Why it matters / what it unblocks:** uvicorn's `Config.bind_socket()` calls `sys.exit(1)` on an `OSError` (port in use), and `SystemExit` raised inside an `asyncio.Task` bypasses `Task.__step`'s normal exception handling and crashes the whole event loop — escaping the `except Exception` at `system_controller.py:286` that assumes GUI startup is contained. This has already taken the live demo bot down (2026-07-29) when a stale `scripts/gui_demo_server.py` held `:8770` before boot.

**Exact scope (what "doing this task" means):**
- In `src/ops/web/server.py::start()`: synchronously create, bind, and `listen()` a TCP socket for `(host, port)` *before* creating the uvicorn task. Let a bind `OSError` raise/propagate straight out of `start()` (a plain, catchable exception, not `SystemExit`) so it's caught by the existing `except Exception` at `system_controller.py:286-298` — WARN logged, `_web_task = None`, boot continues — instead of only surfacing later as an uncaught `SystemExit` inside the fire-and-forget task.
- Pass the pre-bound socket into `uvicorn.Server.serve(sockets=[sock])`, bypassing uvicorn's own `Config.bind_socket()` (and its internal `sys.exit(1)`) entirely for this call site — the async task itself can then no longer bind-fail.
- Make the GUI port configurable via a `TITAN_GUI_PORT` env var (default `8770`), read in `server.start()` the same way `TITAN_GUI_BIND` already is — `scripts/gui_demo_server.py` and `system_controller.py` both inherit this for free since they share `start()`.
- Add/extend a unit test (e.g. in `tests/unit/test_gui_server.py`) that: (a) pre-occupies the target port, calls `web_server.start(...)`, and asserts it raises a plain exception rather than crashing the event loop/test runner; (b) asserts `TITAN_GUI_PORT` changes the bound port.

**Explicitly OUT of scope (do NOT touch this session):**
- Any change to what the GUI can control at runtime (safe-subset settings keys, auth, SPA static mount) — untouched.
- Wiring the port into `config.yaml` / `SettingsStore` layered config — like `TITAN_GUI_BIND`, this is a process bind-time value, kept as an env var, not a live-editable setting.
- Fixing or removing `scripts/gui_demo_server.py` itself (already wired per backlog commit `a9e678f`) — only the shared `start()` path changes.
- The health probe (`HealthProbe`, port 8787) — separate code path, already synchronously try/excepted correctly.

**Relevant project docs / decisions:** system_controller.py:286 "optional; must never block trading" contract; no specific Bible volume/ADR located for this gap.

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `src/ops/web/server.py::start()` binds the socket synchronously and raises a normal exception (no `SystemExit`) on bind failure, caught by `system_controller.py:286`'s existing `except Exception`.
- [ ] `server.serve()` is invoked with the pre-bound socket (`sockets=[sock]`); uvicorn's own `bind_socket()`/`sys.exit(1)` path is never reached from this call site.
- [ ] GUI port is configurable via `TITAN_GUI_PORT` (default `8770`), following the existing `TITAN_GUI_BIND` convention.
- [ ] New/updated unit test reproduces the original failure mode (port pre-occupied) and proves no `SystemExit` escapes / the process does not crash.
- [ ] **SEAM test at the controller boot path**, not only at `start()`: with the port pre-occupied, the controller's GUI-startup block must log the WARN, set `_web_task = None`, and CONTINUE booting. A test that only asserts `start()` raises does not prove the engine survives — and the whole defect is that the failure arrived by a route the existing `except Exception` could not see. Assert on the observable outcome (boot continues), not on the exception type alone.
- [ ] Both new tests observed RED before the fix (state how in the commit message), and the bind-failure test must fail if `start()` reverts to `uvicorn.Config(port=...)` + `create_task` without a pre-bound socket.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path, scoped to `src/ops/web/server.py` + its tests (and `system_controller.py` only if the call site needs a change); no unrelated files touched.
