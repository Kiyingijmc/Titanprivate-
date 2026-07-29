# Analytics Export + Telegram Share — Design

**Date:** 2026-07-29
**Status:** Approved (owner), ready for implementation planning
**Scope:** One composed performance report, rendered server-side into four formats,
downloadable from the control GUI and shareable to the operator's Telegram bot.

---

## 1. Problem

Titan produces trade history but has no way to get it *out*. The operator can watch
live tiles in the GUI and receives per-trade Telegram alerts, but there is no
artifact — nothing to download, archive, or read on a phone away from the desk.
The demo-forward test has been running since 2026-07-28 across 12 pairs and its
results exist only as rows in SQLite.

This adds a single canonical performance report plus two ways to get it: download
in one of four formats, or send it straight to the Telegram bot.

## 2. Decisions taken (owner-answered)

| Question | Decision |
| --- | --- |
| What is in an "analytics document"? | A **composed performance report** — one canonical artifact per period, not raw table dumps. |
| Which formats? | **PDF + HTML + CSV + JSON.** Accepts one new Python dep: `reportlab`. XLSX explicitly deferred. |
| How is "share" gated? | **Write-gated + audit-taped.** Requires the write token, 403s in read-only mode, every send recorded on the tape. |
| Where do R-multiple / hold-time come from? | **Derived read-only** from stored `entry`/`sl`/`lots` + cached specs. No schema change. Hold-time is **out of scope** — open time is not stored anywhere. |
| Render server-side or client-side? | **Server-side.** Both buttons call the same renderer. |

## 3. Approach

Server-side renderer; the GUI download endpoint and the Telegram share endpoint
produce bytes from the identical code path.

**Rejected — client-side render + upload-to-share.** It splits into two renderers
that drift, is invisible to the Python suite, and requires an endpoint that accepts
arbitrary bytes from a client and forwards them off-host. The audit tape could then
record only *that* a file was sent, never *what*.

**Rejected — CLI only.** Does not deliver the requested share button. However, a
thin CLI wrapper is included below, because the builder is pure and the DB is
readable offline, so it costs almost nothing and gives a path to a report while the
bot is stopped.

`scripts/report.py` opens the state DB read-only, loads specs from
`data/specs.json`, and writes to `--out`. With `--share` it constructs a
`TelegramBot` directly (it reads `.env` itself) and calls `send_document`
synchronously, printing the returned `(ok, detail)`. It never binds a port, so it is
safe to run alongside the live bot — unlike the ZMQ `scripts/` tools.

## 4. Module layout

```text
src/ops/report/
  __init__.py       build_report(), render(model, fmt), FORMATS — the only public surface
  model.py          ReportModel dataclasses (period, summary, breakdowns, curve, trades)
  builder.py        rows + specs -> ReportModel.  PURE: no DB, no files, no clock.
  stats.py          win rate, expectancy, R derivation, drawdown, streaks
  chart.py          curve points -> SVG path geometry, shared by html + pdf
  render_json.py    ReportModel -> bytes
  render_csv.py     ReportModel -> bytes
  render_html.py    ReportModel -> bytes  (self-contained: inline CSS + inline SVG)
  render_pdf.py     ReportModel -> bytes  (reportlab)
scripts/report.py   CLI wrapper: --period / --format / --out / --share
```

**The seam that matters:** `builder.py` never touches SQLite, the filesystem, or
`datetime.now()`. It takes a list of dict rows, a specs mapping, an explicit period
tuple, and a commission rate. Everything time- and I/O-dependent lives in the
caller. This is what makes the stats testable against fixed fixtures with no fakes.

Each `render_*` module exposes one function with the identical signature
`render(model) -> bytes`. `__init__.py` holds the private `_RENDERERS` dict mapping
format name to that function and exposes `render(model, fmt)` plus `FORMATS` (the
valid names) — so the endpoint validates against `FORMATS` and dispatches through
one lookup rather than a branch tree. Adding XLSX later is one new file plus one
dict entry.

**Content types**, used for both the HTTP response and the Telegram filename:

| fmt | Content-Type | ext |
| --- | --- | --- |
| `pdf` | `application/pdf` | `.pdf` |
| `html` | `text/html; charset=utf-8` | `.html` |
| `csv` | `text/csv; charset=utf-8` | `.csv` |
| `json` | `application/json` | `.json` |

`chart.py` emits plain SVG path geometry. `render_html` inlines it directly;
`render_pdf` replays the same points through reportlab primitives. One set of
scaling math, so the two charts cannot disagree.

## 5. Data flow

1. **Period → bounds.** The caller resolves the period token into an explicit
   `(start_ts, end_ts)` pair of POSIX timestamps. The clock lives here and nowhere
   deeper. Grammar: `today` | `7d` | `30d` | `90d` | `all` | `YYYY-MM-DD:YYYY-MM-DD`.
   `all` resolves to `(0.0, now)`; a custom range is interpreted in the host's local
   timezone, start inclusive and end exclusive. Anything else is a 422.
2. **Rows.** New `history_rows_between(conn, start, end)` alongside the existing
   `history_rows` in `src/ops/web/state_view.py`:
   `WHERE close_time BETWEEN ? AND ? ORDER BY close_time ASC`. Same defensive
   `try/except -> []` shape as its neighbour.
3. **Specs.** Prefer `controller.risk_manager.symbol_specs` when a live controller
   is present — that is the authoritative copy the sizer actually used. Fall back to
   `data/specs.json` for the CLI / offline path.
4. **Commission.** The caller reads the per-lot commission from `config.yaml` (the
   same key the sizer uses) and passes it in. The builder does not read config.
5. **Build.** `build_report(rows, specs, period, commission_per_lot) -> ReportModel`.
6. **Render.** `render(model, fmt) -> bytes`.

### 5.1 R-multiple derivation

`R = pnl / risk_to_stop`, where `risk_to_stop` uses the same **net-of-commission**
convention as `RiskManager.risk_to_stop()` — because that is how the sizer sized the
trade, and a gross denominator would systematically overstate R.

Side is inferred from SL versus entry (`sl < entry` → BUY).

**`risk_manager.py` is not modified.** It is a RISKY_DOMAIN under mig and this
feature has no business editing the sizer. Instead `stats.py` carries its own copy
of the tick arithmetic, and a **parity test pins it against
`RiskManager.risk_to_stop()`** across a table of cases including the missing-specs
`0.0` sentinel. If the two ever drift, that test goes red.

Note: `data/specs.json` currently holds 11 symbols while 12 pairs trade (XTIUSD was
added 2026-07-29 and is absent). Its R renders as `n/a` until `scripts/cache_specs.py`
refreshes the cache. This is surfaced, not silent — see the coverage note below.

## 6. Report contents

`ReportModel` holds:

- **Summary** — closed trades, win rate, net P&L, avg win, avg loss, profit factor,
  expectancy in R, best and worst trade, longest win/loss streak, max drawdown on
  the closed-trade equity curve.
- **Equity curve** — cumulative P&L by close time. Drives the SVG chart.
- **Breakdowns** — by symbol, by strategy, by grade. Each: trade count, win rate,
  net P&L, avg R.
- **Trade list** — ticket, close time, symbol, strategy, side, grade, lots, entry,
  SL, TP, P&L, R.
- **Coverage note** — e.g. `R unavailable for 14 of 91 trades (no cached specs:
  XTIUSD)`. **Rendered on the report face.** A report that quietly averages R over
  two-thirds of the book is worse than one that admits the gap. This follows the
  same fail-loud rule as the portfolio exposure cap.

**Periods:** Today / 7d / 30d / 90d / All / custom range. Default 30d.

**Format split:** JSON is the full model verbatim. CSV is the **trade list only** —
one flat header row, because a CSV with a summary block glued on top is a file
spreadsheets choke on. HTML and PDF carry everything.

## 7. Endpoints

Both are `async def` on the existing app in `src/ops/web/server.py`.

### `GET /api/report?period=<p>&format=<f>` — read-gated

Streams the rendered bytes with `Content-Type` and `Content-Disposition` set for the
format. Read-gated (token only): generating a report mutates nothing, so it stays
available in read-only mode.

### `POST /api/report/share {period, format}` — write-gated

- `write` deps: `require_token` + `require_writable`, matching `/api/command`.
- Renders the **same bytes** the download path produces, so what was shared is
  provably what would have been downloaded.
- **Single-flight lock.** A second share while one is in flight returns
  `already sending` rather than queueing. Prevents button-mashing from stacking
  uploads and from tripping Telegram's per-chat rate limit.
- **Size guard** before upload — reject anything over **20 MB** with a clear message
  rather than firing a request the Telegram bot API (50 MB ceiling) may drop. Real
  reports are well under 1 MB; the guard exists for a pathological `all`-period run.
- Audit tape via the existing `_audit(...)` helper: action `report:share`, args
  `{period, format, bytes}`, outcome `ok` or `failed:<reason>`. **Recorded on
  failure too** — a share that did not land is exactly the event worth having.

### 7.1 The event-loop constraint

The GUI server runs **inside the trading process**, on the same event loop as the
controller's poll-and-manage cycle. Rendering a 90-day PDF and pushing a multipart
upload are both slow. Run either inline and heartbeat processing and in-trade
management stall behind it — the same failure shape as the "never put slow trade
calls on the REQ path" rule in CLAUDE.md.

**Therefore: build, render, and upload all run via `asyncio.to_thread`.** This is a
hard requirement, not a nicety.

## 8. Telegram send

New method on `TelegramBot` — `send_document(filename, data, caption) -> (ok, detail)`:

- Multipart POST to `{base_url}/sendDocument` with `chat_id`, `document`, `caption`,
  reusing the existing keep-alive `session`. Timeout 20s, not the 5s used for
  messages.
- **Returns its outcome rather than swallowing it.** The existing `send_message` is
  deliberately fire-and-forget (`create_task`, log on failure, caller never knows).
  That is right for a trade alert and wrong for a button someone just pressed — the
  share endpoint needs a real answer for the toast.
- `is_active` false (no token configured) returns an explicit
  `telegram not configured` failure, not the silent early-return `send_message` does.
- **Filename** `titan-report-30d-20260729-1432.<ext>` — sortable and self-describing
  in the Telegram file list.
- **Caption** carries the headline: period, trade count, net P&L, win rate. The chat
  is readable on a phone without opening the attachment.

**Deliberate non-feature:** no arbitrary chat targeting. It sends to
`TELEGRAM_CHAT_ID` and nowhere else — the same single authorized chat the command
interface already trusts. "Share to Telegram" means *your* bot, not a recipient
picker.

## 9. Frontend

New `/reports` route in `frontend/src/routes/router.tsx` plus a `Sidebar.tsx` entry.
`BottomTabs` is left alone — it is a curated three for phone-during-a-market-event.

The page, composed from already-tested components:

- **Period selector** — segmented control.
- **Live preview** — fetches `GET /api/report?format=json` and renders summary tiles
  and the equity curve using the existing `StatTiles` and Recharts patterns. The
  JSON renderer therefore feeds both the preview and the download: one code path,
  and the operator always sees exactly what they are about to export.
- **Download** — format dropdown + button.
- **Share to Telegram** — one button, outcome in a toast.

**New client path for binary.** `api.ts`'s `req<T>` always calls `res.json()` and
cannot carry bytes; auth is a Bearer header so a plain `<a href>` cannot
authenticate either. Add a `reqBlob` sibling that fetches with the same
Authorization header, then object-URL → programmatic anchor click → revoke. This
keeps the token out of a URL, where it would land in logs and browser history.

**No confirm dialog on share.** The palette's confirm-gate exists for destructive
actions. This sends a read-only summary to the single chat the operator already
owns; a modal on every share is friction that teaches people to click through
modals. The toast reporting the real outcome is the correct feedback.

**Two disabled states, both with reasons:**

- **Read-only mode** → share disabled, through the same centralized 403 handling in
  `useMutate` that flips `setReadOnly(true)`. **Download stays enabled** — it is a read.
- **Telegram not configured** → share disabled *before* the click. Requires one
  small additive change: `telegram_configured: bool` in the health block of
  `build_snapshot`. Better a greyed button with a reason than a click that eats a
  failure toast.

**⌘K** gains "Download report (PDF)" and "Share report to Telegram", wired through
the existing command-action plumbing.

## 10. Error handling

| Case | Behaviour |
| --- | --- |
| Zero trades in period | Valid report saying so. Not a 404, not a crash. All four renderers produce a sane empty document. |
| `entry`/`sl` of `0.0` | Not hypothetical — those columns were added to `trade_history` later with `DEFAULT 0.0`, so every pre-migration row has them. R undefined; row excluded from R averages and counted in the coverage note. |
| Missing broker specs | R shown `n/a`; symbol named in the coverage note. |
| `reportlab` import fails | The PDF format alone returns a clear error; HTML/CSV/JSON keep working. A missing optional dep must not take the page down. |
| Telegram send fails | Real reason in the toast, `failed:<reason>` on the audit tape. |
| Concurrent share | Second request rejected with `already sending`. |

## 11. Testing

| File | Covers |
| --- | --- |
| `tests/unit/test_report_stats.py` | win rate, profit factor, expectancy, drawdown, streaks; zero trades; all-losses; single trade |
| `tests/unit/test_report_r_parity.py` | report R math == `RiskManager.risk_to_stop()` across a case table, incl. the missing-specs `0.0` sentinel |
| `tests/unit/test_report_builder.py` | coverage-note counts, `entry=0` rows excluded from R, side inference from SL vs entry |
| `tests/unit/test_report_render.py` | magic bytes (`%PDF-`, `<!doctype html`), exact CSV header, JSON round-trip, empty-report render for all four |
| `tests/unit/test_gui_report_api.py` | 401 without token, 403 share in read-only, content-type + `Content-Disposition`, single-flight rejection, tape entry on both ok and failed |
| frontend vitest | period selection, blob download path, share disabled when read-only or Telegram unconfigured, failure toast |

Suite cost is negligible — these are pure-function tests. Relevant because the
verify suite already runs ~2089s against a 2400s ceiling.

### 11.1 What the suite cannot prove

Phase 1a's `/ws` passed every TestClient test and was completely broken in
production: uvicorn had no websockets library, and TestClient never exercised the
real server. The same trap is open here. TestClient will green a download endpoint
whose real `StreamingResponse` headers are wrong, and it will never touch
api.telegram.org.

**Definition of done therefore includes a live-drive step:** a real browser download
of each of the four formats off the running server, and one real send to the demo
bot. Not optional.

## 12. Out of scope

- **XLSX** — deferred; the renderer registry makes it a one-file addition later.
- **Hold-time / MAE statistics** — open time is not persisted; would require a
  `trade_history` schema change (RISKY_DOMAIN).
- **Scheduled/automatic reports** — this is on-demand only.
- **Raw per-table dumps** — explicitly rejected in favour of the composed report.
- **Arbitrary Telegram recipients** — fixed to `TELEGRAM_CHAT_ID`.
- **Any change to `risk_manager.py` or the DB schema.**

## 13. Suggested build order

One coherent feature, but it should be planned in three sequenced slices so each is
independently verifiable:

1. **`src/ops/report/` + `scripts/report.py`** — the pure builder, stats, parity
   test, and all four renderers. Provable by the unit suite and by eyeballing real
   PDF/HTML output from the CLI against the live demo-forward data, with no GUI and
   no MT5 involved.
2. **Endpoints + `send_document`** — download, share, single-flight, audit tape,
   `telegram_configured` in the snapshot.
3. **`/reports` page + `reqBlob` + ⌘K** — then the live-drive step in §11.1.

Slice 1 carries the real risk (PDF layout, R correctness) and depends on nothing, so
getting it done and reviewed first keeps the later slices mechanical.

## 14. New dependency

`reportlab` — pure Python, no system libraries. Added to `requirements.txt`.
Imported lazily inside `render_pdf.py` so its absence degrades one format rather
than breaking the module.
