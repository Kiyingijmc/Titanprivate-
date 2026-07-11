# Telegram Layer Improvements — Design

**Date:** 2026-07-11
**Branch:** feat/trade-mgmt-pipeline
**Status:** Approved (Phase 1 detailed); Phases 2–3 scoped, deferred to their own specs/plans.

## Goal

Improve the Telegram telemetry layer on three fronts the user prioritised: richer
notifications, better command UX & safety, and formatting polish. Correctness fixes
(fragile command parsing, brittle Markdown) fold in as the Phase 1 foundation because
safe commands and clean formatting depend on them.

## Current state (baseline)

- `src/ops/telemetry.py` — `TelegramBot` holds inline f-string message builders,
  `parse_mode: "Markdown"` (legacy), long-poll command loop, and `_process` that
  matches commands with `"/x" in text` substring tests on lowercased text.
- Controller-side report/action methods live in `src/core/system_controller.py`
  (`get_status_report`, `get_balance_report`, `get_pending_orders_report`,
  `set_system_pause`, `trigger_panic`, `close_all_market_orders`,
  `close_specific_market_order`, `cancel_pending_orders`).

### Known defects the redesign addresses

1. **Substring command matching** — e.g. a message containing "pause" fires `/pause`;
   `/close` vs `/closeall` needs a special-case guard.
2. **Brittle Markdown** — unescaped dynamic values (symbols, strategy names with `_`/`*`)
   can trigger Telegram 400 errors that silently retry-fail.
3. **Thin execution alert** — `notify_execution` is always called with `sl=0`; no SL/TP/RR.
4. **No confirmation** on destructive `/closeall` (single-tap flattens everything).

## Architecture decision

**Separation of concerns (chosen over in-place, and over a command-framework/library).**

- New `src/ops/telegram_format.py`: pure message-builder functions, no network, no `self`.
  Fully unit-testable — the TDD anchor.
- `TelegramBot` remains the poll / dispatch / confirm / network layer, delegating all
  string building to `telegram_format`.
- The **controller** owns summary scheduling + stat tracking (Phase 3) — it already owns
  the async loop and the data.

Rejected: piling everything into `telemetry.py` (balloons past 500 lines, hard to test);
a command-framework/library like python-telegram-bot (overkill, needs a dependency ADR).

## Phasing

Each phase is delivered as its own implementation plan.

- **Phase 1 — Foundation** (detailed below): formatter module + HTML escaping +
  exact-match dispatch + `/help` + two-step `/confirm` for `/closeall`.
- **Phase 2 — Richer per-trade alerts** (deferred): real SL/TP/RR + lot on execution,
  reason + hold-time + R-multiple on close, ratchet alert shows new SL & locked-in amount.
- **Phase 3 — Proactive & scheduled** (deferred): lot-size=0 / specs-not-loaded skip
  alerts, DD-limit approach warning (debounced), feed-desync, daily P/L recap + session
  open/close summaries (controller-side stat tracking + a scheduler tick).

---

## Phase 1 — detailed design

### New file: `src/ops/telegram_format.py`

Pure functions; each takes plain data and returns a ready-to-send string.

- `esc(v) -> str` — HTML-escape a dynamic value (`&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`).
  Applied to every interpolated symbol / strategy / comment value.
- Message builders, migrated from the current inline strings and switched to HTML tags
  (`<b>`, `<code>`):
  - `signal(symbol, strategy, side, size, price, sl, tp)`
  - `execution(ticket, symbol, type, price, sl, strategy)`
  - `close(ticket, pnl, symbol, strategy)` — keeps existing P/L emoji thresholds
    (`>500` 🚀🔥, `>0` 💰, `>-50` 📉, else 🩸).
  - `management(action_comment, ticket)` — keeps existing L1/L2/L3/Risk icon mapping.
  - `help_menu()` — replaces the `HELP_MENU` constant.

**Scope note:** Phase 1 creates exactly these five builders (`signal`, `execution`,
`close`, `management`, `help_menu`) plus `esc()`, since those are what `TelegramBot` owns
and calls. `status` / `balance` / `pending` builders are NOT created in Phase 1 — the
controller's `get_*_report` methods keep returning their own strings, and consolidating
them into `telegram_format` is deferred (would be unused otherwise — YAGNI). This keeps
Phase 1 bounded to the bot.

### `TelegramBot` changes (`src/ops/telemetry.py`)

- `parse_mode` → `"HTML"` in `_async_send_retry`.
- `notify_signal` / `notify_execution` / `notify_close` / `notify_management` delegate to
  the corresponding `telegram_format` builders instead of inline f-strings.
- `HELP_MENU` constant replaced by `telegram_format.help_menu()`.

**Dispatch table (`_process` rewrite):** extract the command explicitly:

```python
raw = text.strip().split()
if not raw:
    return
cmd = raw[0].lstrip('/').split('@')[0].lower()   # "/CloseAll@Bot" -> "closeall"
args = raw[1:]
```

Look `cmd` up in a `{ "status": ..., "balance": ..., "pending": ..., "pause": ...,
"resume": ..., "cancel": ..., "close": ..., "closeall": ..., "panic": ..., "confirm": ...,
"help": ... }` dispatch dict. Unknown or empty → `help_menu()`. This removes every
`"/x" in text` substring test and the `/close`-vs-`/closeall` special case. Auth check
(sender id == allowed chat id) is unchanged and still runs first.

### Two-step confirm for `/closeall`

- Add `self._pending_confirm = None` — holds `(action_name: str, expiry_ts: float)` or `None`.
- `/closeall` no longer executes. It sets `_pending_confirm = ("closeall", time.time()+30)`
  and replies with the position count + open P/L:
  *"⚠️ Close N positions ($X open)? Reply /confirm within 30s."*
- `/confirm`:
  - if `_pending_confirm` is set and unexpired → clear it, run
    `controller.close_all_market_orders()`, report the flattened count.
  - if expired → clear it, reply *"⌛ Confirmation expired."*
  - if none → reply *"Nothing to confirm."*
- `/panic` stays **instant** (its existing path is unchanged) — it is the genuine
  emergency button and confirmation would defeat its purpose.
- Single-slot only: a new confirmable command overwrites any prior pending one. No
  multi-action queue (YAGNI).

### Explicitly NOT in Phase 1

Controller report-method consolidation (beyond trivial), SL/TP enrichment, scheduling,
stat tracking, risk/DD alerts. Those are Phases 2–3.

### Testing / verification

- New `tests/unit/test_telegram_format.py` (TDD anchor), covering:
  - `esc()` on values containing `<`, `>`, `&` (and that `_`/`*` pass through safely under HTML).
  - `close()` P/L emoji thresholds at the boundaries (500, 0, -50).
  - `management()` icon mapping for L1/L2/L3/Risk and the default.
  - `help_menu()` renders and lists the commands.
- Command-dispatch unit coverage: extracting `cmd` from inputs like `/CloseAll@Bot`,
  `/status`, `don't pause` (must NOT fire pause), empty string.
- Confirm FSM: `/closeall` sets pending; `/confirm` within window executes exactly once;
  expired/absent confirm is a no-op with the right reply. (Bot methods that need a
  controller use a stub/fake controller — no live bridge.)
- Full `tests/unit` suite stays green (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`).

### Risks / notes

- HTML parse_mode: builders must NOT emit raw `<`/`>`/`&` outside intended tags — enforced
  by routing all dynamic values through `esc()`.
- `_process` runs per-update via `asyncio.create_task`; `_pending_confirm` is single-writer
  from the one poll loop, so no locking needed.
- No new dependencies. No EA/bridge change. No config schema change in Phase 1.
