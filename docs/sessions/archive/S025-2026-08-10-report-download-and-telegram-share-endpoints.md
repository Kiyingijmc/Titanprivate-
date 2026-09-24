---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S025"
date:          "2026-08-10"
slug:          "report-download-and-telegram-share-endpoints"
parent_session: "none"
task_domain:   "api"
spec_state:    "draft"          # spec-gate: mig approve <ID> flips to approved (ADR-031 amendment)
needs:         "analytics-report-package-renderers-and-cli"            # advisory cross-track dep (ADR-031)
status:        "DRAFT"
---

# titan-ict-bot — Session S025 · 2026-08-10 · "report-download-and-telegram-share-endpoints"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Report download + Telegram share endpoints, wired to `src/ops/report/`

**Why it matters / what it unblocks:** Titan has trade history but no artifact to get it out of the box; this wires the GUI's read/write auth model onto the report renderer (slice 1) so an operator can download a report or push it to Telegram without opening SQLite. Unblocks the `/reports` frontend page (slice 3).

**Exact scope (what "doing this task" means):**
- Premise check first: confirm `src/ops/report/` (`build_report`, `render(model, fmt)`, `FORMATS`) exists and is importable — it is session S016's deliverable and is currently DRAFT/unbuilt in the tree. If still absent, STOP and report the blocked premise rather than stubbing the renderer.
- `GET /api/report?period=<p>&format=<f>` on the existing FastAPI app in `src/ops/web/server.py`, added under the existing `read = [Depends(auth.require_token)]` dependency list (same pattern as `get_history`/`get_equity`).
  - Resolve `period` via the grammar in the design doc §5.1: `today|7d|30d|90d|all|YYYY-MM-DD:YYYY-MM-DD` → `(start_ts, end_ts)`; anything else → 422. `all` → `(0.0, now)`; custom range is host-local-tz, start inclusive/end exclusive.
  - Validate `format` against `FORMATS` from `src.ops.report`; unknown format → 422.
  - Rows via new `history_rows_between(conn, start, end)` in `src/ops/web/state_view.py`, placed beside `history_rows` (state_view.py:292): `WHERE close_time BETWEEN ? AND ? ORDER BY close_time ASC`, same defensive `try/except -> []` shape.
  - Specs: prefer `controller.risk_manager.symbol_specs` when present, else `data/specs.json`. Commission: `config.yaml`'s per-lot commission key (same one the sizer reads).
  - `build_report(...)` and `render(model, fmt)` both run via `asyncio.to_thread` (hard constraint — the GUI shares the trading process's event loop; see design §7.1).
  - Response is a `StreamingResponse`/raw bytes response with `Content-Type` per the format table (`pdf`→`application/pdf`, `html`→`text/html; charset=utf-8`, `csv`→`text/csv; charset=utf-8`, `json`→`application/json`) and `Content-Disposition: attachment; filename="titan-report-<period>-<YYYYMMDD-HHMM>.<ext>"`.
  - No `_audit(...)` call — this is a pure read.
- `POST /api/report/share {period, format}` under the existing `write = [Depends(auth.require_token), Depends(auth.require_writable)]` list (matches `post_command`).
  - Builds and renders through the identical path as the GET endpoint (same bytes).
  - Single-flight lock (module- or app-state-scoped): a second share while one is in flight returns `{"status": "error", "detail": "already sending"}` (or equivalent), not queued.
  - 20MB size guard on the rendered bytes before calling `send_document`; reject over-limit with a clear message, no upload attempt.
  - Calls `controller.telegram_bot.send_document(filename, data, caption)` (new method, see below); caption per design §8 (period, trade count, net P&L, win rate — pull from `model.summary`).
  - Audit-tape every outcome via the existing `_audit(controller, request, "report:share", {"period": period, "format": format, "bytes": len(data)}, outcome)` where `outcome` is `"ok"` or `f"failed:{reason}"` — **including on failure**, unlike the existing `_audit` call sites in server.py which only tape on `"ok"`.
- `TelegramBot.send_document(self, filename, data, caption) -> tuple[bool, str]` in `src/ops/telemetry.py`, beside `send_message` (telemetry.py:81):
  - `is_active` false → return `(False, "telegram not configured")` immediately (explicit, unlike `send_message`'s silent `return`).
  - Multipart POST to `{self.base_url}/sendDocument` with `chat_id=self.allowed_chat_id`, `document=(filename, data)`, `caption=caption`, on `self.session` (existing keep-alive session), `timeout=20` (not the 5s `send_message` uses).
  - Returns `(True, detail)` / `(False, detail)` synchronously — no `create_task`, no swallow. Wrap the request in `asyncio.to_thread` at the call site (server.py), not inside `send_document` itself, consistent with how `_async_send_retry` already wraps `session.post`.
- `history_rows_between(conn, start, end)` added to `src/ops/web/state_view.py`.
- `telegram_configured: bool` added to the `"health"` block in `build_snapshot` (state_view.py:59), value `controller.telegram_bot.is_active` (or equivalent live attribute) — mirrors the existing `bridge_connected`/`paused` booleans already in that block.

**Explicitly OUT of scope (do NOT touch this session):**
- Building `src/ops/report/` itself (model/builder/stats/chart/render_*, `scripts/report.py`) — that is session S016; this session only calls its public surface (`build_report`, `render`, `FORMATS`).
- Any change to `src/risk/risk_manager.py` (RISKY_DOMAIN) or `trade_history` schema / `state_manager.py`.
- Frontend `/reports` page, `reqBlob`, ⌘K actions, Sidebar entry — session 3 in the design's build order (§13).
- XLSX rendering, hold-time/MAE stats, scheduled reports, arbitrary Telegram recipients (fixed to `TELEGRAM_CHAT_ID` only, no picker).
- Any change to `send_message`'s fire-and-forget behavior or its retry logic — `send_document` is new and independent.
- A confirm-dialog / destructive-action gate on share — explicitly rejected in design §9 (read-only summary to the operator's own already-owned chat).

**Relevant project docs / decisions:** docs/superpowers/specs/2026-07-29-analytics-export-share-design.md §7-9, §13 (slice 2); parent/needs session S016 (analytics-report-package-renderers-and-cli)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] Premise verified: `src/ops/report/` importable with `build_report`, `render`, `FORMATS`; if not, session stops and reports the blocked dependency rather than faking a stub renderer.
- [ ] `GET /api/report?period=&format=` returns 200 with correct `Content-Type` + `Content-Disposition` for all four formats, and stays reachable when the write token is withheld / read-only mode is active (only `require_token`, no `require_writable`).
- [ ] `GET /api/report` with a malformed `period` or unknown `format` returns 422, not a 500 or silently-wrong default.
- [ ] `POST /api/report/share` 403s under `require_writable` in read-only mode (no token / read-only) and 200s with a valid write token.
- [ ] A concurrent second `POST /api/report/share` while one is in flight returns `already sending` (or equivalent) without attempting a second upload.
- [ ] A rendered payload over 20MB is rejected before any `send_document` call.
- [ ] `_audit` is called with action `report:share` on both success and failure paths (verified by a test asserting a tape entry exists after a forced-failure send, e.g. `telegram not configured`).
- [ ] `TelegramBot.send_document` returns `(False, "telegram not configured")` synchronously when `is_active` is `False`, and does not raise.
- [ ] `history_rows_between(conn, start, end)` added to `state_view.py`, mirrors `history_rows`'s `try/except -> []` shape, and is unit-tested against a fixture DB for boundary inclusion/exclusion.
- [ ] `telegram_configured` present in `GET /api/state`'s `health` block and reflects `TelegramBot.is_active`.
- [ ] `build_report`/`render` calls in the GET/POST handlers run via `asyncio.to_thread` (grep- or test-verifiable — e.g. mock `asyncio.to_thread` and assert it wraps the render call).
- [ ] Full unit suite green (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`); `git diff --stat` shows no changes outside `src/ops/web/server.py`, `src/ops/web/state_view.py`, `src/ops/telemetry.py`, and new `tests/unit/test_gui_report_api.py` (or equivalent).
- [ ] Live-drive step per design §11.1: a real browser/`curl` download of at least one format off the running dev server, and one real send to the demo Telegram bot — TestClient alone does not prove `StreamingResponse` headers or a real `api.telegram.org` round-trip.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
