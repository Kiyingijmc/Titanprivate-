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

- **Per-call `parse_mode`, default `"HTML"`.** `send_message` / `_async_send_retry` gain a
  `parse_mode="HTML"` parameter threaded into the payload. The five migrated bot builders
  send HTML (default). **All not-yet-migrated Markdown callers must pass
  `parse_mode="Markdown"`** so they keep rendering correctly and don't hit the new 400
  surface. This is required because `send_message` is a single shared pipe: ~10 controller
  call sites still emit `**bold**`/`` `code` `` Markdown with unescaped dynamic data —
  `system_controller.py` lines 157, 215 (`str(e)`), 233, 417 (order strategy), 436
  (`get_*_report` output), 534 (news `reason`), 537, 616, 619 — plus the bot's own inline
  `_process` error replies (`❌ Error: {e}` at telemetry.py:237,249). A *global* flip to
  HTML would (a) render their `**`/backticks literally and (b) 400 on any `&`/`<`/`>` in an
  exception, news reason, or broker comment — none of which route through `esc()` in Phase 1.
  The per-call override keeps Phase 1 bounded to the bot without silently breaking them.
- `notify_signal` / `notify_execution` / `notify_close` / `notify_management` delegate to
  the corresponding `telegram_format` builders (HTML) instead of inline f-strings.
- `notify_execution` **renders the same fields it does today** (ticket / pair / type /
  logic) — it carries `price`/`sl` params but does NOT display SL, since it is still fed
  `sl=0` (system_controller.py:346). Rendering real SL/TP/RR is Phase 2; Phase 1 must not
  print "SL: 0".
- `HELP_MENU` constant replaced by `telegram_format.help_menu()`, which **adds `/confirm`**
  and updates the title `v14.3` → `v14.4`.

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
- `/confirm` — **capture-and-clear before any `await`** to guarantee exactly-once:
  ```python
  pending = self._pending_confirm
  self._pending_confirm = None          # clear FIRST, before awaiting the close
  if pending and pending[1] >= time.time():
      count = await controller.close_all_market_orders()   # safe: slot already cleared
      ...report count...
  elif pending:   # was set but expired
      reply "⌛ Confirmation expired."
  else:
      reply "Nothing to confirm."
  ```
  Clearing before the `await` is required: `_process` is dispatched as an independent task
  (`asyncio.create_task(self._process(u))`, telemetry.py:190), so two `/confirm` updates
  could otherwise both pass the check and double-close.
- `/panic` stays **instant** (its existing path is unchanged) — it is the genuine
  emergency button and confirmation would defeat its purpose.
- Single-slot only: a new confirmable command overwrites any prior pending one. No
  multi-action queue (YAGNI).
- Bare non-slash words dispatch too: after `raw[0].lstrip('/')`, `"pause"` == `"/pause"`.
  This is **intended** — and the real hazard from the old substring matcher is gone, because
  only the *first token* is inspected (`"don't pause"` → first token `"don't"` → no match).

### Explicitly NOT in Phase 1

Controller report-method consolidation (beyond trivial), SL/TP enrichment, scheduling,
stat tracking, risk/DD alerts. Those are Phases 2–3.

### Testing / verification

- New `tests/unit/test_telegram_format.py` (TDD anchor), covering:
  - `esc()` on values containing `<`, `>`, `&` (and that `_`/`*` pass through safely under HTML).
  - `close()` P/L emoji thresholds at the boundaries (500, 0, -50).
  - `management()` icon mapping for L1/L2/L3/Risk and the default.
  - `help_menu()` renders, lists the commands, **includes `/confirm`**, and shows `v14.4`.
- Command-dispatch unit coverage: extracting `cmd` from inputs like `/CloseAll@Bot`,
  `/status`, `don't pause` (must NOT fire pause), empty string.
- Confirm FSM: `/closeall` sets pending; `/confirm` within window executes exactly once;
  expired/absent confirm is a no-op with the right reply. (Bot methods that need a
  controller use a stub/fake controller — no live bridge.)
- Full `tests/unit` suite stays green (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`).

### Risks / notes

- HTML parse_mode: the five migrated builders must NOT emit raw `<`/`>`/`&` outside intended
  tags — enforced by routing all dynamic values through `esc()`. Un-migrated callers stay on
  `parse_mode="Markdown"` (see bot changes) and are out of scope for Phase 1 escaping.
- `_process` runs per-update via `asyncio.create_task`, so tasks CAN interleave across an
  `await`. The confirm FSM does not rely on single-writer serialization — it captures and
  clears `_pending_confirm` before awaiting the close, which is what makes execution
  exactly-once. No lock needed given that ordering.
- No new dependencies. No EA/bridge change. No config schema change in Phase 1.
