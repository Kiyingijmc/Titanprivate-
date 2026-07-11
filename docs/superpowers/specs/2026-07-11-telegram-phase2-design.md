# Telegram Layer — Phase 2 (Richer per-trade alerts) Design

**Status:** Approved design, pending plan.
**Depends on:** Phase 1 (`telegram_format.py` builders + per-call `parse_mode`, shipped `ea54f39..a9d889d`).
**Parent spec:** `docs/superpowers/specs/2026-07-11-telegram-improvements-design.md` (Phase 2 outline).

## Goal

Make the per-trade Telegram alerts actually informative: show real SL/TP/RR/lot/grade/risk-$ on
entry, hold-time + R-multiple on close, and finally surface in-trade ratchet moves (break-even,
banks, risk-guard) that today fire silently. All Python-side — **no EA recompile, no live bridge
needed to build or test.**

## Scope

**In:**
- A `RiskManager.money_for_move()` helper (one source of truth for $ conversions).
- Execution alert enrichment: entry, SL, TP, RR, lots, grade, planned risk-$.
- Close alert enrichment: hold-time, R-multiple.
- Ratchet alert wiring: L1/L2/L3 + Risk-Guard (new SL + locked-in $) and partial banks
  (banked volume); Runner Trail suppressed.

**Out (explicitly):**
- **Close "reason" (TP-hit / SL-hit / manual).** The EA's `CLOSED` message carries only
  `pn` (pnl) + `s` (symbol) — no close price, no reason (`Titan_Gateway.mq5:364`). Deriving
  reason needs an EA protocol change + Windows recompile; deferred, not attempted (no crude
  pnl-sign guess — the pnl emoji already conveys win/loss).
- Scheduled summaries, DD/lot=0/desync proactive alerts — those are **Phase 3**.

## Component 1 — `RiskManager.money_for_move(symbol, price_distance, lots)`

The single $-conversion primitive, in `src/risk/risk_manager.py` (where broker specs live).

```
money = (abs(price_distance) / spec['ts']) * spec['val'] * lots
```

- `spec = self.symbol_specs.get(symbol)`; keys are `'val'` (tick value), `'ts'` (tick size).
- **Fails safe to `0.0`** when specs are missing or invalid — same guard as `calculate_lot_size`:
  `if not (spec and spec['val'] > 0 and spec['ts'] > 0): return 0.0`. Callers treat `0.0` as
  "unknown" and render "—".
- Pure arithmetic over stored specs; returns a float. Own unit test (with-specs value + no-specs
  fail-safe). Used by both R-multiple and locked-in $.

## Component 2 — Execution alert enrichment

`telegram_format.execution()` new signature:
`execution(ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money)`.

Renders: Ticket / Pair / Type / **Entry / SL / TP / RR / Lots / Grade / Risk-$**. All dynamic
values through `esc()` (HTML, per Phase 1). Rules:
- **RR** = `abs(tp - entry) / abs(entry - sl)`, formatted `1:2.5`. If `sl == 0` or `tp == 0` or
  `entry == 0` → "—". RR is computed **inside the builder** from entry/sl/tp — the builder stays
  pure (no specs/risk_manager access), so RR (pure arithmetic) belongs there and is unit-tested there.
- **Risk-$** is **passed pre-computed** as `risk_money` (the builder can't reach broker specs).
  The controller computes it via `money_for_move(symbol, abs(entry - sl), lots)`; `0.0` → "—".
- **Grade** shows the confluence grade (A++…C) already captured in meta.

Controller (`system_controller.py`, `EXECUTION:OPENED`): pass `meta['entry']`, `meta['sl']`,
`meta['tp']`, `meta['lots']`, `meta['grade']`. When `meta is None` (manual/unknown order): pass
entry from the message and `sl=tp=lots=0`, `grade=''` → alert degrades gracefully (entry shown,
SL/TP/RR/Risk dashed). Risk-$ computed controller-side via `money_for_move` (it holds the
`risk_manager` ref).

## Component 3 — Close alert enrichment

`telegram_format.close()` new signature:
`close(ticket, pnl, symbol, strategy, hold_time_str, r_multiple)`.

Renders the Phase-1 fields (emoji, ticket, symbol, strat, pnl) **plus**:
- `⏱ Hold: 2h 14m` — from a `format_duration(seconds)` helper (in `telegram_format`), rendering
  `Xd Yh` / `Xh Ym` / `Xm` / `Xs`. `None`/unknown → omit the line.
- `📐 R: +1.8R` — one decimal, signed. `None`/unknown → "—".

Controller (`EXECUTION:CLOSED`): the existing `SELECT strategy FROM active_orders WHERE
ticket_id=?` is **extended** to also read `time_placed, initial_entry, initial_sl, lots`, and this
read happens **before `archive_trade`** removes the row. Then:
- `hold_seconds = now - time_placed` (seconds; `time_placed` is epoch REAL). Guard `time_placed
  == 0` → hold unknown.
- `planned_risk = money_for_move(sym, abs(initial_entry - initial_sl), lots)`;
  `r_multiple = pnl / planned_risk` if `planned_risk > 0` else `None`.

## Component 4 — Ratchet alert wiring

Wire the currently-dead `notify_management` into `_dispatch_mgmt_command`
(`system_controller.py:278`). Dispatch already receives the command dict `{action, ticket,
symbol, sl, tp, comment}`.

- **SL-move milestones** — `action == "MODIFY"` and comment in {`Ratchet L1`, `Ratchet L2`,
  `Ratchet L3`}: look up `initial_entry, initial_sl, lots` from `active_orders` by
  ticket. **Direction** is inferred from the stored stop: `is_long = initial_sl < initial_entry`.
  **Signed locked-in distance** = `(new_sl - initial_entry)` for a long, `(initial_entry - new_sl)`
  for a short (positive once the stop is past entry into profit; negative while still below).
  `locked = copysign(money_for_move(symbol, locked_distance, lots), locked_distance)` — magnitude
  from `money_for_move` (which takes `abs`), sign from the directional distance; a break-even stop
  lands near `+$0`. Call `notify_management(comment, ticket, new_sl, locked)`.
  `management()` renders icon (existing L1/L2/L3/Risk mapping) + new SL + locked-in $.
- **Runner Trail** — `comment == "Runner Trail"`: **suppressed** (no notification), avoiding spam
  on trending runners.
- **Partial banks** — `action == "CLOSE_PARTIAL"`: notify via a new `telegram_format.partial()`
  builder showing banked volume + ticket. To label the % (30%/50%), `trade_manager._partial_actions`
  adds `"comment": f"Bank {int(pct*100)}%"` to the `CLOSE_PARTIAL` command (currently unlabeled);
  the notification renders that comment. This is the only `trade_manager` change.

`management()` new signature: `management(action_comment, ticket, new_sl, locked_money)` — keeps
the existing icon mapping (with the Phase-1 non-string coercion), appends `SL→<new_sl>` and
`Locked <±$>`. `partial(comment, ticket, volume)` — new sibling builder.

## Error handling / degradation

- Missing specs → `money_for_move` returns `0.0` → RR/Risk-$/R-multiple/locked render "—". Never
  raises, never blocks a trade or an alert.
- Missing `meta` (manual order) → execution alert shows entry only.
- `time_placed == 0` (legacy row) → hold-time line omitted.
- All new dynamic values routed through `esc()`; controller inline replies unaffected (Phase 1
  parse_mode contract unchanged).

## Testing

- `money_for_move`: with-specs computes correct $; no-specs → `0.0`.
- `execution()`: RR math + divide-by-zero → "—"; risk-$ rendering; graceful degradation
  (sl=tp=0); grade shown; esc on symbol/strategy.
- `close()`: hold-time formatting across ranges (s/m/h/d); R-multiple sign + one-decimal;
  unknown → "—"/omitted.
- `format_duration`: boundary cases (0, <1m, exactly 1h, multi-day).
- `management()` / `partial()`: new-SL + signed locked-in render; partial volume + % label; icon
  mapping preserved.
- Controller wiring: `EXECUTION:CLOSED` computes hold/R from the extended SELECT before archive;
  `_dispatch_mgmt_command` notifies on milestones/partials and suppresses Runner Trail (fake
  bridge/telemetry, no live sockets).
- Full `tests/unit` suite stays green.

## Task breakdown (for the plan)

1. `money_for_move` helper + test.
2. `format_duration` + execution alert enrichment (builder + controller pass-through) + tests.
3. Close alert enrichment (builder + controller SELECT extension + compute) + tests.
4. Ratchet/partial wiring (`management()`/`partial()` builders + `_dispatch_mgmt_command` +
   `trade_manager` partial-comment) + tests.

Each task is independently shippable and offline-testable.

## Explicitly NOT in Phase 2

Close reason (needs EA change), scheduled summaries, daily/session recaps, DD-limit / lot=0 /
feed-desync proactive alerts (all Phase 3), and any migration of the controller `get_*_report`
methods to HTML.
