# Telegram Phase 2 (Richer per-trade alerts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the per-trade Telegram alerts with real SL/TP/RR/lots/grade/risk-$ on entry, hold-time + R-multiple on close, and finally surface in-trade ratchet moves (break-even / banks / risk-guard) that fire silently today.

**Architecture:** Reuse the Phase 1 pattern — pure builders in `src/ops/telegram_format.py` do all string/number formatting (unit-tested, no I/O); `TelegramBot.notify_*` delegate to them; `SystemController` supplies the data. One new $-conversion primitive, `RiskManager.money_for_move()`, is the single source for R-multiple and locked-in $. No EA change, no live bridge needed to build or test.

**Tech Stack:** Python 3.10+, stdlib `unittest` (NO pytest), `asyncio`. Spec: `docs/superpowers/specs/2026-07-11-telegram-phase2-design.md`.

## Global Constraints

- **Tests are stdlib `unittest`**, class-based, run via `.venv/bin/python -m unittest tests.unit.<module> -v`. No pytest. Each new test module starts with the two-levels-up `sys.path.insert(0, ...)` shim used across `tests/unit/`.
- **No new dependencies. No EA/bridge change. No config schema change.** (The one `trade_manager` edit adds a `comment` to an existing command dict — not a protocol change.)
- **Builders stay pure**: no network, no `self`, no access to `risk_manager`/specs. Dollar amounts are computed by the controller and passed in; RR (pure arithmetic) is computed inside the builder.
- **All dynamic values through `esc()`** (HTML parse_mode, per Phase 1). Unknown/missing values render `"—"` (or the line is omitted) — never raise, never block a trade or alert.
- **`money_for_move` fails safe to `0.0`** when specs are missing (same discipline as `calculate_lot_size`); callers treat `0.0` as "unknown".
- Commit after every task. End commit messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- **Modify** `src/risk/risk_manager.py` — add `money_for_move` (Task 1).
- **Modify** `src/ops/telegram_format.py` — enrich `execution`/`close`/`management`, add `format_duration`, `partial`, and two small format helpers (Tasks 2–4).
- **Modify** `src/ops/telemetry.py` — update `notify_execution`/`notify_close`/`notify_management` signatures, add `notify_partial` (Tasks 2–4).
- **Modify** `src/core/system_controller.py` — pass enriched data at `EXECUTION:OPENED`/`CLOSED`; wire ratchet/partial notifications in `_dispatch_mgmt_command` (Tasks 2–4).
- **Modify** `src/execution/trade_manager.py` — label the `CLOSE_PARTIAL` command with a `comment` (Task 4).
- **Create** `tests/unit/test_money_for_move.py`, `tests/unit/test_telegram_format_phase2.py`; extend existing controller/telemetry tests as noted.

---

## Task 1: `RiskManager.money_for_move()` helper

**Files:**
- Modify: `src/risk/risk_manager.py`
- Test: `tests/unit/test_money_for_move.py`

**Interfaces:**
- Produces: `RiskManager.money_for_move(symbol, price_distance, lots) -> float` — the account-currency value of a `price_distance` move at `lots`, from broker specs; `0.0` if specs missing/invalid.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_money_for_move.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.risk.risk_manager import RiskManager


def _rm():
    rm = RiskManager({"risk": {"account": {"max_daily_drawdown_pct": 3.0}, "trade": {"risk_per_trade_pct": 1.0}}})
    rm.update_account_info(10000.0, 10000.0)
    return rm


class MoneyForMoveTests(unittest.TestCase):
    def test_no_specs_fails_safe_to_zero(self):
        self.assertEqual(_rm().money_for_move("XAUUSD", 1.5, 0.10), 0.0)

    def test_with_specs_computes_dollars(self):
        rm = _rm()
        # tick_value=1.0 per tick, tick_size=0.01 -> 150 ticks over a 1.5 move; * 0.10 lots = $15.00
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
        self.assertAlmostEqual(rm.money_for_move("XAUUSD", 1.5, 0.10), 15.0, places=6)

    def test_uses_absolute_distance(self):
        rm = _rm()
        rm.update_symbol_specs("EURUSD", val=1.0, size=0.0001, v_min=0.01, v_step=0.01)
        pos = rm.money_for_move("EURUSD", 0.0050, 1.0)
        neg = rm.money_for_move("EURUSD", -0.0050, 1.0)
        self.assertGreater(pos, 0.0)
        self.assertEqual(pos, neg)

    def test_zero_lots_is_zero(self):
        rm = _rm()
        rm.update_symbol_specs("EURUSD", val=1.0, size=0.0001, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.money_for_move("EURUSD", 0.0050, 0.0), 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_money_for_move -v`
Expected: FAIL — `AttributeError: 'RiskManager' object has no attribute 'money_for_move'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/risk/risk_manager.py` (place it near `calculate_lot_size`):

```python
    def money_for_move(self, symbol, price_distance, lots) -> float:
        """Account-currency value of a `price_distance` move at `lots`, from broker specs.

        Mirrors calculate_lot_size's spec discipline: without real tick_value/tick_size
        it returns 0.0 (caller treats 0.0 as 'unknown') rather than guessing.
        """
        spec = self.symbol_specs.get(symbol)
        if not (spec and spec['val'] > 0 and spec['ts'] > 0):
            return 0.0
        try:
            ticks = abs(float(price_distance)) / spec['ts']
            return ticks * spec['val'] * float(lots)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_money_for_move -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/risk/risk_manager.py tests/unit/test_money_for_move.py
git commit -m "feat(risk): money_for_move() spec-driven $-conversion (fails safe to 0)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Execution alert enrichment

**Files:**
- Modify: `src/ops/telegram_format.py` (add `_fmt_rr`, `_fmt_money`; enrich `execution`)
- Modify: `src/ops/telemetry.py` (`notify_execution` signature)
- Modify: `src/core/system_controller.py` (`EXECUTION:OPENED` pass-through)
- Test: `tests/unit/test_telegram_format_phase2.py`

**Interfaces:**
- Consumes: `esc`, `_RULE` (existing); `RiskManager.money_for_move` (Task 1).
- Produces: `execution(ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money, strategy) -> str` (RR computed inside; renders Entry/SL/TP/RR/Lots/Grade/Risk-$/Logic). `notify_execution(self, ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money, strategy)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_telegram_format_phase2.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops import telegram_format as tf


class ExecutionEnrichTests(unittest.TestCase):
    def test_renders_all_fields(self):
        out = tf.execution(555, "XAUUSD", "MARKET", 2000.0, 1990.0, 2025.0, 0.10, "A+", 100.0, "SilverBullet")
        self.assertIn("#555", out)
        self.assertIn("XAUUSD", out)
        self.assertIn("2000.0", out)   # entry
        self.assertIn("1990.0", out)   # sl
        self.assertIn("2025.0", out)   # tp
        self.assertIn("A+", out)       # grade
        self.assertIn("SilverBullet", out)
        self.assertIn("$100.00", out)  # risk-$

    def test_rr_ratio(self):
        # risk=10, reward=25 -> 1:2.5
        out = tf.execution(1, "X", "MARKET", 2000.0, 1990.0, 2025.0, 0.1, "A", 100.0, "S")
        self.assertIn("1:2.5", out)

    def test_rr_dashes_when_sl_or_tp_zero(self):
        self.assertIn("—", tf.execution(1, "X", "MARKET", 2000.0, 0, 2025.0, 0.1, "A", 0.0, "S"))

    def test_risk_dashes_when_zero(self):
        # money=0 means specs unknown -> "—", not "$0.00"
        out = tf.execution(1, "X", "MARKET", 2000.0, 1990.0, 2025.0, 0.1, "A", 0.0, "S")
        self.assertNotIn("$0.00", out)

    def test_escapes_dynamic_fields(self):
        out = tf.execution(1, "A&B", "MARKET", 1, 0, 0, 0.1, "A", 0.0, "S<x>")
        self.assertIn("A&amp;B", out)
        self.assertIn("S&lt;x&gt;", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format_phase2.ExecutionEnrichTests -v`
Expected: FAIL — current `execution()` has signature `(ticket, symbol, order_type, price, sl, strategy)`; the new call raises `TypeError` (too many args) / missing fields.

- [ ] **Step 3: Write minimal implementation**

In `src/ops/telegram_format.py`, add two helpers (near the top, after `_RULE`):

```python
def _fmt_rr(entry, sl, tp) -> str:
    """Reward:risk as '1:2.5'; '—' when any leg is missing/zero."""
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
        risk, reward = abs(entry - sl), abs(tp - entry)
        if entry == 0 or sl == 0 or tp == 0 or risk <= 0 or reward <= 0:
            return "—"
        return f"1:{reward / risk:.1f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"


def _fmt_money(amount) -> str:
    """'$1,234.50'; '—' when unknown (0.0 sentinel from money_for_move)."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return "—"
    return "—" if amt == 0 else f"${amt:,.2f}"
```

Replace the `execution` builder with:

```python
def execution(ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money, strategy) -> str:
    return (
        "⚡ <b>EXECUTION CONFIRMED</b>\n"
        f"{_RULE}\n"
        f"🎫 <b>Ticket:</b> <code>#{esc(ticket)}</code>\n"
        f"💱 <b>Pair:</b> {esc(symbol)} · {esc(order_type)}\n"
        f"📍 <b>Entry:</b> <code>{esc(entry)}</code>\n"
        f"🛡️ <b>SL:</b> <code>{esc(sl)}</code>   🎯 <b>TP:</b> <code>{esc(tp)}</code>\n"
        f"⚖️ <b>RR:</b> <code>{_fmt_rr(entry, sl, tp)}</code>   📦 <b>Lots:</b> <code>{esc(lots)}</code>\n"
        f"🏅 <b>Grade:</b> <code>{esc(grade)}</code>   💵 <b>Risk:</b> <code>{_fmt_money(risk_money)}</code>\n"
        f"⚙️ <b>Logic:</b> <i>{esc(strategy)}</i>"
    )
```

In `src/ops/telemetry.py`, update `notify_execution`:

```python
    async def notify_execution(self, ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money, strategy):
        await self.send_message(
            telegram_format.execution(ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money, strategy)
        )
```

In `src/core/system_controller.py`, replace the `EXECUTION:OPENED` notify block (currently `await self.telemetry.notify_execution(ticket, sym, msg.get('cmd'), entry_p, 0, msg.get('strat', 'Auto'))`). After the `if meta: … else: …` registration branch sets `entry_p`, add the field extraction and enriched call:

```python
                if meta:
                    reg_status = "PENDING" if meta['cmd'] == "LIMIT" else "ACTIVE"
                    self.state_manager.register_order(
                        ticket, sym, meta['strat'], meta['cmd'], status=reg_status,
                        entry=meta['entry'], tp=meta['tp'], sl=meta['sl'],
                        lots=meta['lots'], grade=meta['grade']
                    )
                    entry_p = meta['entry']
                    sl_v, tp_v, lots_v, grade_v, strat_v = meta['sl'], meta['tp'], meta['lots'], meta['grade'], meta['strat']
                else:
                    entry_p = float(msg.get('price', 0))
                    self.state_manager.register_order(
                        ticket, sym, msg.get('strat', 'Manual'), msg.get('cmd'),
                        status="ACTIVE", entry=entry_p, tp=0.0
                    )
                    sl_v, tp_v, lots_v, grade_v, strat_v = 0.0, 0.0, 0.0, '', msg.get('strat', 'Auto')

                risk_money = self.risk_manager.money_for_move(sym, abs(entry_p - sl_v), lots_v)
                await self.telemetry.notify_execution(
                    ticket, sym, msg.get('cmd'), entry_p, sl_v, tp_v, lots_v, grade_v, risk_money, strat_v
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format_phase2 -v`
Expected: PASS (ExecutionEnrichTests)

Run: `.venv/bin/python -c "import src.core.system_controller; import src.ops.telemetry"`
Expected: exit 0 (no syntax/signature error)

Run the full suite: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK (any Phase-1 execution test that constructed the old signature must be updated to the new one — if a test in `test_telegram_format.py` fails, update its `execution(...)` call to the new arg list and re-run).

- [ ] **Step 5: Commit**

```bash
git add src/ops/telegram_format.py src/ops/telemetry.py src/core/system_controller.py tests/unit/test_telegram_format_phase2.py tests/unit/test_telegram_format.py
git commit -m "feat(telegram): execution alert shows SL/TP/RR/lots/grade/risk-\$

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Close alert enrichment (hold-time + R-multiple)

**Files:**
- Modify: `src/ops/telegram_format.py` (add `format_duration`; enrich `close`)
- Modify: `src/ops/telemetry.py` (`notify_close` signature)
- Modify: `src/core/system_controller.py` (`EXECUTION:CLOSED` compute)
- Test: `tests/unit/test_telegram_format_phase2.py`

**Interfaces:**
- Consumes: `esc`, `_RULE`; `state_manager.get_order`; `RiskManager.money_for_move`.
- Produces: `format_duration(seconds) -> str`; `close(ticket, pnl, symbol="???", strategy="Unknown", hold_seconds=None, r_multiple=None) -> str` (formats hold_seconds internally). `notify_close(self, ticket, pnl, symbol="???", strategy="Unknown", hold_seconds=None, r_multiple=None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_telegram_format_phase2.py`:

```python
class FormatDurationTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(tf.format_duration(45), "45s")

    def test_minutes(self):
        self.assertEqual(tf.format_duration(125), "2m")

    def test_hours(self):
        self.assertEqual(tf.format_duration(3 * 3600 + 15 * 60), "3h 15m")

    def test_days(self):
        self.assertEqual(tf.format_duration(2 * 86400 + 5 * 3600), "2d 5h")

    def test_zero_and_negative(self):
        self.assertEqual(tf.format_duration(0), "0s")
        self.assertEqual(tf.format_duration(-10), "0s")


class CloseEnrichTests(unittest.TestCase):
    def test_hold_and_r_shown(self):
        out = tf.close(7, 250.0, "XAUUSD", "OTE", hold_seconds=3 * 3600 + 15 * 60, r_multiple=1.8)
        self.assertIn("3h 15m", out)
        self.assertIn("+1.8R", out)
        self.assertIn("$250.00", out)

    def test_negative_r_sign(self):
        self.assertIn("-1.0R", tf.close(1, -100.0, "X", "S", hold_seconds=60, r_multiple=-1.0))

    def test_hold_omitted_when_none(self):
        out = tf.close(1, 5.0, "X", "S", hold_seconds=None, r_multiple=None)
        self.assertNotIn("Hold", out)
        self.assertNotIn("R:", out)

    def test_backward_compatible_defaults(self):
        # still callable with the Phase-1 arg list
        out = tf.close(1, 5.0, "X", "S")
        self.assertIn("#1", out)
        self.assertIn("$5.00", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format_phase2.FormatDurationTests tests.unit.test_telegram_format_phase2.CloseEnrichTests -v`
Expected: FAIL — `format_duration` missing; `close()` has no `hold_seconds`/`r_multiple` params.

- [ ] **Step 3: Write minimal implementation**

Add `format_duration` to `src/ops/telegram_format.py`:

```python
def format_duration(seconds) -> str:
    """'2d 5h' / '3h 15m' / '2m' / '45s'. Negative clamps to 0s."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        s = 0
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{s}s"
```

Replace the `close` builder with (preserve the exact emoji thresholds):

```python
def close(ticket, pnl, symbol="???", strategy="Unknown", hold_seconds=None, r_multiple=None) -> str:
    pnl = float(pnl)
    if pnl > 500:
        icon = "🚀🔥"
    elif pnl > 0:
        icon = "💰"
    elif pnl > -50:
        icon = "📉"
    else:
        icon = "🩸"
    lines = [
        f"{icon} <b>POSITION CLOSED</b>",
        _RULE,
        f"🎫 <code>#{esc(ticket)}</code> <b>{esc(symbol)}</b>",
        f"🧠 Strat: <code>{esc(strategy)}</code>",
        f"💵 <b>PnL:</b> <code>${pnl:,.2f}</code>",
    ]
    if r_multiple is not None:
        lines.append(f"📐 <b>R:</b> <code>{r_multiple:+.1f}R</code>")
    if hold_seconds is not None:
        lines.append(f"⏱ <b>Hold:</b> <code>{format_duration(hold_seconds)}</code>")
    return "\n".join(lines)
```

In `src/ops/telemetry.py`, update `notify_close`:

```python
    async def notify_close(self, ticket, pnl, symbol="???", strategy="Unknown", hold_seconds=None, r_multiple=None):
        await self.send_message(telegram_format.close(ticket, pnl, symbol, strategy, hold_seconds, r_multiple))
```

In `src/core/system_controller.py`, replace the `EXECUTION:CLOSED` branch (currently uses `exists(tid)` + a `SELECT strategy …`) with a `get_order` read that also yields hold-time + R-multiple, taken **before** `archive_trade`:

```python
            elif status == 'CLOSED':
                tid = msg.get('ticket')
                row = self.state_manager.get_order(tid)
                if row:
                    pnl = float(msg.get('pn', 0.0))
                    strat_name = row.get('strategy') or "Manual"
                    sym = msg.get('s') or row.get('symbol')

                    placed = row.get('time_placed') or 0
                    hold_seconds = (time.time() - placed) if placed else None

                    planned_risk = self.risk_manager.money_for_move(
                        sym, abs((row.get('initial_entry') or 0) - (row.get('initial_sl') or 0)), row.get('lots') or 0
                    )
                    r_mult = (pnl / planned_risk) if planned_risk > 0 else None

                    self.daily_closed_trades.append({'ticket': tid, 'sym': sym, 'pnl': pnl, 'strat': strat_name})
                    self.state_manager.archive_trade(tid, pnl)
                    await self.telemetry.notify_close(tid, pnl, sym, strat_name, hold_seconds, r_mult)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format_phase2 -v`
Expected: PASS (FormatDuration + CloseEnrich)

Run the full suite: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK (update any Phase-1 `close()`/`notify_close` test that asserts an exact whole-message string; the added lines are opt-in via defaults, so calls with the old arg list still work).

- [ ] **Step 5: Commit**

```bash
git add src/ops/telegram_format.py src/ops/telemetry.py src/core/system_controller.py tests/unit/test_telegram_format_phase2.py
git commit -m "feat(telegram): close alert shows hold-time + R-multiple

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Ratchet + partial notification wiring

**Files:**
- Modify: `src/ops/telegram_format.py` (enrich `management`; add `partial`)
- Modify: `src/ops/telemetry.py` (`notify_management` signature; add `notify_partial`)
- Modify: `src/core/system_controller.py` (`_dispatch_mgmt_command` wiring)
- Modify: `src/execution/trade_manager.py` (label `CLOSE_PARTIAL` with a `comment`)
- Test: `tests/unit/test_telegram_format_phase2.py` (builders) + `tests/unit/test_mgmt_dispatch_notify.py` (controller wiring)

**Interfaces:**
- Consumes: `esc`, `_RULE`; `state_manager.get_order`; `RiskManager.money_for_move`; `notify_management`/`notify_partial`.
- Produces: `management(action_comment, ticket, new_sl=None, locked_money=None) -> str`; `partial(comment, ticket, volume) -> str`. `notify_management(self, action_comment, ticket, new_sl=None, locked_money=None)`; `notify_partial(self, comment, ticket, volume)`.
- Routing rules in `_dispatch_mgmt_command`:
  - `MODIFY` + comment `Ratchet L1/L2/L3` → notify with new SL + signed locked-in $.
  - `MODIFY` + comment `Runner Trail` → **suppressed** (no notify).
  - `CLOSE_PARTIAL` → `notify_partial` (comment now carries `Bank NN%`).
  - `CLOSE_POS` + comment `Risk Guard` → `notify_management` (kill; no SL/locked). `Dust Guard Exit` and unlabeled closes → no mgmt notify (the CLOSED alert covers them).

- [ ] **Step 1: Write the failing builder tests**

Append to `tests/unit/test_telegram_format_phase2.py`:

```python
class ManagementEnrichTests(unittest.TestCase):
    def test_ratchet_shows_new_sl_and_locked(self):
        out = tf.management("Ratchet L2", 9, new_sl=1995.0, locked_money=42.5)
        self.assertIn("💸", out)              # L2 icon preserved
        self.assertIn("1995.0", out)          # new SL
        self.assertIn("+42.50", out)          # signed locked-in

    def test_negative_locked_sign(self):
        self.assertIn("-10.00", tf.management("Ratchet L1", 1, new_sl=1.0, locked_money=-10.0))

    def test_risk_guard_without_sl(self):
        out = tf.management("Risk Guard", 3)
        self.assertIn("👮", out)
        self.assertNotIn("SL", out)           # no SL line when new_sl is None

    def test_partial_builder(self):
        out = tf.partial("Bank 30%", 9, 0.03)
        self.assertIn("Bank 30%", out)
        self.assertIn("#9", out)
        self.assertIn("0.03", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format_phase2.ManagementEnrichTests -v`
Expected: FAIL — `management()` takes only `(action_comment, ticket)`; `partial` missing.

- [ ] **Step 3: Write the builders**

Replace `management` in `src/ops/telegram_format.py` (keep the coerce-then-test icon mapping from Phase 1) and add `partial`:

```python
def management(action_comment, ticket, new_sl=None, locked_money=None) -> str:
    comment = str(action_comment)
    icon, desc = "⚙️", comment
    if "L1" in comment:
        icon, desc = "🔒", "Ratchet L1 (Break-Even)"
    elif "L2" in comment:
        icon, desc = "💸", "Ratchet L2 (Bank 30%)"
    elif "L3" in comment:
        icon, desc = "🥂", "Ratchet L3 (Bank 50%)"
    elif "Risk" in comment:
        icon, desc = "👮", "RISK GUARD KILL"
    lines = [f"{icon} <b>Auto-Pilot:</b> {esc(desc)}", f"🎫 Trade <code>#{esc(ticket)}</code>"]
    if new_sl is not None:
        lines.append(f"🛡️ <b>SL→</b> <code>{esc(new_sl)}</code>")
    if locked_money is not None:
        lines.append(f"🔐 <b>Locked:</b> <code>{locked_money:+,.2f}</code>")
    return "\n".join(lines)


def partial(comment, ticket, volume) -> str:
    label = esc(comment) if comment else "Partial Close"
    return (
        f"💰 <b>Partial Bank:</b> {label}\n"
        f"🎫 Trade <code>#{esc(ticket)}</code>   📦 <code>{esc(volume)}</code> lots"
    )
```

- [ ] **Step 4: Run builder tests + write the controller-wiring test**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format_phase2.ManagementEnrichTests -v`
Expected: PASS

Create `tests/unit/test_mgmt_dispatch_notify.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController


class _FakeBridge:
    async def send_command(self, *a, **k):
        pass


class _FakeTelemetry:
    def __init__(self):
        self.mgmt = []
        self.partials = []

    async def notify_management(self, comment, ticket, new_sl=None, locked_money=None):
        self.mgmt.append((comment, ticket, new_sl, locked_money))

    async def notify_partial(self, comment, ticket, volume):
        self.partials.append((comment, ticket, volume))


class _FakeRisk:
    def money_for_move(self, symbol, distance, lots):
        return 100.0  # non-zero so locked-in is computable


class _FakeState:
    def get_order(self, ticket):
        # long trade: initial_sl < initial_entry
        return {"initial_entry": 2000.0, "initial_sl": 1990.0, "lots": 0.10}


def _controller():
    c = SystemController.__new__(SystemController)   # bypass __init__/live sockets
    c.bridge = _FakeBridge()
    c.telemetry = _FakeTelemetry()
    c.risk_manager = _FakeRisk()
    c.state_manager = _FakeState()

    class _L:
        def log_event(self, *a, **k):
            pass
    c.logger = _L()
    return c


class MgmtDispatchNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_ratchet_modify_notifies_with_sl_and_locked(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "MODIFY", "ticket": 9, "symbol": "XAUUSD", "sl": 2005.0, "tp": 2025.0, "comment": "Ratchet L2"})
        self.assertEqual(len(c.telemetry.mgmt), 1)
        comment, ticket, new_sl, locked = c.telemetry.mgmt[0]
        self.assertEqual((comment, ticket, new_sl), ("Ratchet L2", 9, 2005.0))
        self.assertGreater(locked, 0)   # sl 2005 > entry 2000 on a long -> profit locked

    async def test_runner_trail_suppressed(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "MODIFY", "ticket": 9, "symbol": "XAUUSD", "sl": 2005.0, "tp": 2025.0, "comment": "Runner Trail"})
        self.assertEqual(c.telemetry.mgmt, [])

    async def test_partial_notifies(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "CLOSE_PARTIAL", "ticket": 9, "volume": 0.03, "comment": "Bank 30%"})
        self.assertEqual(len(c.telemetry.partials), 1)
        self.assertEqual(c.telemetry.partials[0], ("Bank 30%", 9, 0.03))

    async def test_risk_guard_close_notifies(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "CLOSE_POS", "ticket": 9, "comment": "Risk Guard"})
        self.assertEqual(len(c.telemetry.mgmt), 1)
        self.assertEqual(c.telemetry.mgmt[0][0], "Risk Guard")

    async def test_plain_close_does_not_notify_mgmt(self):
        c = _controller()
        await c._dispatch_mgmt_command({"action": "CLOSE_POS", "ticket": 9, "comment": "Dust Guard Exit"})
        self.assertEqual(c.telemetry.mgmt, [])
```

Run: `.venv/bin/python -m unittest tests.unit.test_mgmt_dispatch_notify -v`
Expected: FAIL — dispatch doesn't notify yet; `notify_partial` missing.

- [ ] **Step 5: Wire the controller + telemetry + trade_manager, then verify & commit**

In `src/ops/telemetry.py`, update `notify_management` and add `notify_partial`:

```python
    async def notify_management(self, action_comment, ticket, new_sl=None, locked_money=None):
        await self.send_message(telegram_format.management(action_comment, ticket, new_sl, locked_money))

    async def notify_partial(self, comment, ticket, volume):
        await self.send_message(telegram_format.partial(comment, ticket, volume))
```

In `src/execution/trade_manager.py`, label the partial command in `_partial_actions` (the only trade_manager change):

```python
        if mode == "PARTIAL":
            return [{"action": "CLOSE_PARTIAL", "ticket": ticket, "volume": close_vol,
                     "comment": f"Bank {int(pct * 100)}%"}]
```

In `src/core/system_controller.py`, extend `_dispatch_mgmt_command` so each branch notifies after sending (keep the existing `send_command` + `log_event` calls intact):

```python
        action = c.get('action')
        if action == "MODIFY":
            await self.bridge.send_command("MODIFY", {
                "ticket": int(c['ticket']), "symbol": c.get('symbol', ''),
                "sl": float(c.get('sl', 0.0)), "tp": float(c.get('tp', 0.0))
            })
            self.logger.log_event("MGMT", "TRADE_MGR",
                                  f"MODIFY #{c['ticket']} sl={c.get('sl')} tp={c.get('tp')} "
                                  f"({c.get('comment', '')}) sent")
            comment = c.get('comment', '')
            if comment != "Runner Trail" and any(k in comment for k in ("Ratchet L1", "Ratchet L2", "Ratchet L3")):
                new_sl = float(c.get('sl', 0.0))
                locked = None
                row = self.state_manager.get_order(int(c['ticket']))
                if row and new_sl:
                    init_entry = row.get('initial_entry') or 0
                    init_sl = row.get('initial_sl') or 0
                    lots = row.get('lots') or 0
                    if init_entry:
                        is_long = init_sl < init_entry
                        dist = (new_sl - init_entry) if is_long else (init_entry - new_sl)
                        mag = self.risk_manager.money_for_move(c.get('symbol', ''), dist, lots)
                        locked = mag if dist >= 0 else -mag
                await self.telemetry.notify_management(comment, int(c['ticket']), new_sl, locked)
        elif action == "CLOSE_PARTIAL":
            await self.bridge.send_command("CLOSE_POS", {"ticket": int(c['ticket']),
                                                         "volume": float(c['volume'])})
            self.logger.log_event("MGMT", "TRADE_MGR",
                                  f"PARTIAL #{c['ticket']} vol={c['volume']}")
            await self.telemetry.notify_partial(c.get('comment', ''), int(c['ticket']), c['volume'])
        elif action == "CLOSE_POS":
            await self.bridge.send_command("CLOSE_POS", {"ticket": int(c['ticket'])})
            self.logger.log_event("MGMT", "TRADE_MGR",
                                  f"CLOSE #{c['ticket']} ({c.get('comment', '')})")
            if c.get('comment', '') == "Risk Guard":
                await self.telemetry.notify_management("Risk Guard", int(c['ticket']))
```

Run: `.venv/bin/python -m unittest tests.unit.test_mgmt_dispatch_notify tests.unit.test_telegram_format_phase2 -v`
Expected: PASS

Run the full suite: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK — no regressions.

```bash
git add src/ops/telegram_format.py src/ops/telemetry.py src/core/system_controller.py src/execution/trade_manager.py tests/unit/test_telegram_format_phase2.py tests/unit/test_mgmt_dispatch_notify.py
git commit -m "feat(telegram): surface ratchet moves + partial banks (Runner Trail suppressed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `money_for_move` fail-safe primitive → Task 1. ✓
- Execution: entry/SL/TP/RR/lots/grade/risk-$, graceful degrade on missing meta → Task 2. ✓ (Logic line retained — additive to the spec's field list, avoids losing the strategy name.)
- Close: hold-time + R-multiple, read before archive, no reason → Task 3. ✓
- Ratchet: L1/L2/L3 new-SL + signed locked-in; Runner Trail suppressed; partial banks labeled; Risk Guard (CLOSE_POS) notifies as a kill → Task 4. ✓ (Spec listed Risk Guard under MODIFY; it is actually a `CLOSE_POS` per trade_manager.py:75 — handled correctly in the CLOSE_POS branch.)

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `money_for_move(symbol, price_distance, lots) -> float` used identically in Tasks 2–4; `execution`/`close`/`management` signatures match between builder, `notify_*`, and controller call sites; `hold_seconds`/`r_multiple`/`new_sl`/`locked_money` are the same names throughout; `format_duration` used only inside `close`.

**Note for the executor:** Tasks 2 and 3 change `execution()`/`close()` signatures, so a Phase-1 test in `tests/unit/test_telegram_format.py` (or `test_telemetry_*`) that constructs the old signatures may fail — update those call sites to the new arg lists as part of the same task (the step notes call this out). `close()` stays back-compatible via defaults; `execution()` does not (required new args).
