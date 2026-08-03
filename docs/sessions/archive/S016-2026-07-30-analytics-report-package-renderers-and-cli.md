---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S016"
date:          "2026-07-30"
slug:          "analytics-report-package-renderers-and-cli"
parent_session: "none"
task_domain:   "data"
spec_state:    "draft"          # spec-gate: mig approve <ID> flips to approved (ADR-031 amendment)
status:        "DRAFT"
---

# titan-ict-bot — Session S016 · 2026-07-30 · "analytics-report-package-renderers-and-cli"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Analytics report package: pure builder, stats, chart geometry, four renderers, and CLI

**Why it matters / what it unblocks:** Titan has trade history but no artifact to download, archive, or read off-desk; this is slice 1 of the approved analytics-export-share design and unblocks the two chained sessions (endpoints, `/reports` page) with a dependency-free, DB/clock/filesystem-free core that is fully testable now.

**Exact scope (what "doing this task" means):**
- Create `src/ops/report/` per design doc §4-6 (`docs/superpowers/specs/2026-07-29-analytics-export-share-design.md`):
  - `model.py` — `ReportModel` dataclasses: period, summary (closed trades, win rate, net P&L, avg win, avg loss, profit factor, expectancy in R, best/worst trade, longest win/loss streak, max drawdown on closed-trade equity curve), equity curve points, breakdowns (by symbol / strategy / grade — each: count, win rate, net P&L, avg R), trade list rows (ticket, close time, symbol, strategy, side, grade, lots, entry, SL, TP, P&L, R), coverage note string.
  - `builder.py` — `build_report(rows: list[dict], specs: dict, period: tuple[float, float], commission_per_lot: float) -> ReportModel`. PURE: no SQLite, no filesystem, no `datetime.now()`/clock reads — caller supplies explicit `(start_ts, end_ts)` and commission. Side inferred from `sl < entry` → BUY. Rows with `entry == 0.0` or `sl == 0.0` excluded from R and counted in the coverage note (design §5.1, §10 — these are real rows: `trade_history` columns were added later with `DEFAULT 0.0`). Missing-specs rows: R rendered as unavailable and named in the coverage note, never silently dropped from the trade list.
  - `stats.py` — win rate, profit factor, expectancy-in-R, max drawdown, longest win/loss streaks, and a private tick-arithmetic copy for `R = pnl / risk_to_stop` using the **same net-of-commission convention** as `RiskManager.risk_to_stop()` (`src/risk/risk_manager.py:251`) — gross `money_for_move` plus `abs(lots) * comm_per_lot`, returning the `0.0` sentinel when specs are missing (mirrors `_row_risk`, `src/risk/risk_manager.py:272`).
  - `chart.py` — pure function(s) turning equity-curve points into SVG path geometry (`<path d=...>` string + viewbox/scaling numbers), with no rendering-library dependency, so `render_html.py` and `render_pdf.py` replay the identical points.
  - `render_json.py`, `render_csv.py`, `render_html.py`, `render_pdf.py` — each exposes `render(model) -> bytes`. CSV emits the trade list only (one flat header row, per design §6 format split) — no summary block. HTML/PDF carry the full model (summary, curve via `chart.py`, breakdowns, trade list, coverage note) and are self-contained (HTML inlines CSS + the SVG string). `render_pdf.py` lazy-imports `reportlab` inside the function so import failure raises a caught, callable error rather than an ImportError at module load.
  - `__init__.py` — `build_report`, `render(model, fmt)` dispatching through a private `_RENDERERS: dict[str, Callable]`, and `FORMATS` (the valid format-name tuple/set) as the only public surface re-exported.
- Add `reportlab` to `requirements.txt`.
- Add `scripts/report.py` — CLI wrapper (`--period {today,7d,30d,90d,all,YYYY-MM-DD:YYYY-MM-DD} --format {pdf,html,csv,json} --out PATH [--share]`): resolves the period grammar to `(start_ts, end_ts)` itself (this is the one place the clock lives), opens `data/db/trade_state.db` **read-only**, loads specs from `data/specs.json`, reads `static_commission_usd` from `config/config.yaml`, calls `build_report` + `render`, writes `--out`. `--share` constructs `TelegramBot` directly (reads `.env` itself) and calls `send_document` synchronously if that method already exists on the class at the time of this session — otherwise `--share` is stubbed to a clear "not yet available" message rather than reaching into telemetry internals (the `send_document` method itself is out of scope here, see OUT). Binds no port.
- Unit tests (new files under `tests/unit/`, per design §11):
  - `test_report_stats.py` — win rate, profit factor, expectancy, drawdown, streaks; zero-trades, all-losses, single-trade cases.
  - `test_report_r_parity.py` — report R math equals `RiskManager.risk_to_stop()` output across a shared case table, including the missing-specs `0.0` sentinel case.
  - `test_report_builder.py` — coverage-note counts, `entry=0`/`sl=0` rows excluded from R, side inference from SL vs entry.
  - `test_report_render.py` — magic-byte / shape checks per format (`%PDF-` header, `<!doctype html`, exact CSV header row, JSON round-trip via `json.loads`), and an empty-report (zero trades) render succeeding for all four formats.

**Explicitly OUT of scope (do NOT touch this session):**
- Any change to `src/risk/risk_manager.py` (RISKY_DOMAIN) — `stats.py` carries its own pinned copy, never imports the sizer's internals.
- Any change to the `trade_history` schema or `src/core/state_manager.py`.
- GUI/HTTP endpoints (`/api/report`, `/api/report/share`), `telegram_configured` snapshot field, single-flight lock, audit-tape wiring — that is the next chained session (report-download-and-telegram-share-endpoints).
- `TelegramBot.send_document` implementation — belongs to the endpoints session; this session's CLI `--share` degrades gracefully if it isn't present yet.
- Frontend `/reports` page, `reqBlob`, ⌘K actions — the third chained session.
- XLSX rendering, hold-time/MAE stats, scheduled reports, arbitrary Telegram recipients — explicitly out per design §12.
- Live-drive browser verification and a real Telegram send — not applicable, no endpoint/UI exists yet in this slice; CLI output is instead eyeballed against real demo-forward data.

**Relevant project docs / decisions:** docs/superpowers/specs/2026-07-29-analytics-export-share-design.md §4-6, §10-11, §13 (slice 1); CLAUDE.md risk/sizing section (RiskManager fail-closed spec discipline, RISKY_DOMAIN boundary)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `src/ops/report/{__init__,model,builder,stats,chart,render_json,render_csv,render_html,render_pdf}.py` exist; `builder.py` contains no `sqlite3`, `open(`, or `datetime.now()`/`time.time()` calls (grep-verifiable).
- [ ] `reportlab` added to `requirements.txt` and importable only inside `render_pdf.py`'s render function (module import of `src.ops.report` with `reportlab` absent from the venv does not raise).
- [ ] `render(model, fmt)` dispatches via a private `_RENDERERS` dict; calling with an fmt outside `FORMATS` raises a clear error (e.g. `ValueError`).
- [ ] `test_report_r_parity.py` passes and demonstrably pins `stats.py`'s R math to `RiskManager.risk_to_stop()` across a case table that includes the missing-specs `0.0` sentinel.
- [ ] `test_report_builder.py` proves rows with `entry == 0.0` or `sl == 0.0` are excluded from R and reflected in the coverage-note count.
- [ ] `test_report_render.py` passes for all four formats, including a zero-trade `ReportModel`.
- [ ] Full unit suite green (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`), no modification to any file outside `src/ops/report/`, `scripts/report.py`, `requirements.txt`, and `tests/unit/test_report_*.py`.
- [ ] `scripts/report.py` run by hand against the live demo-forward `data/db/trade_state.db` for at least one real period/format combination produces a plausible non-empty artifact at `--out` (eyeballed, not just exit-code-0).
- [ ] `git diff --stat` confirms `src/risk/risk_manager.py` and `src/core/state_manager.py` are untouched.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
