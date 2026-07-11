# Telegram Layer — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract Telegram message building into a pure, unit-tested formatter; make the network layer render HTML safely per-call; replace substring command matching with exact-token dispatch; add a two-step `/confirm` guard for `/closeall`.

**Architecture:** A new pure module `src/ops/telegram_format.py` holds all message-builder functions plus an `esc()` HTML escaper and a `parse_command()` tokenizer — no `self`, no network, fully testable. `TelegramBot` (`src/ops/telemetry.py`) keeps owning polling/dispatch/confirm/network and delegates all string building to the formatter. `send_message` gains a per-call `parse_mode` (default `"HTML"`); the ~9 un-migrated controller callers that still emit Markdown pass `parse_mode="Markdown"` so the single shared send pipe doesn't break them.

**Tech Stack:** Python 3.10+, stdlib `unittest` (no pytest), `requests`, `asyncio`. Spec: `docs/superpowers/specs/2026-07-11-telegram-improvements-design.md`.

## Global Constraints

- **Tests are stdlib `unittest`**, class-based, run via `.venv/bin/python -m unittest tests.unit.<module> -v`. No pytest. Each test module starts with the `sys.path.insert(0, ...)` two-levels-up shim used across `tests/unit/`.
- **No new dependencies. No EA/bridge change. No config schema change.**
- **Phase 1 is bounded to the bot.** Do NOT migrate the controller `get_*_report` methods, do NOT render SL/TP on execution alerts, do NOT add scheduling or stat tracking — those are Phases 2–3.
- **`/panic` stays instant** — do not add confirmation to it.
- **HTML escaping applies only to the five migrated builders.** Un-migrated callers stay on `parse_mode="Markdown"`.
- Commit after every task with the shown message. End commit messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- **Create** `src/ops/telegram_format.py` — pure functions: `esc`, `parse_command`, `signal`, `execution`, `close`, `management`, `help_menu`. One responsibility: turn data into ready-to-send strings + tokenize commands.
- **Create** `tests/unit/test_telegram_format.py` — unit tests for the formatter + tokenizer.
- **Create** `tests/unit/test_telegram_commands.py` — unit tests for `TelegramBot` dispatch + confirm FSM (fake controller, no network).
- **Modify** `src/ops/telemetry.py` — delegate builders, per-call `parse_mode`, `_build_payload`, dispatch rewrite, confirm FSM.
- **Modify** `src/core/system_controller.py` — append `parse_mode="Markdown"` to the 9 un-migrated `send_message` calls.

---

## Task 1: Formatter module — `esc()` + `parse_command()`

**Files:**
- Create: `src/ops/telegram_format.py`
- Test: `tests/unit/test_telegram_format.py`

**Interfaces:**
- Produces: `esc(v) -> str` (HTML-escapes `&`,`<`,`>` on `str(v)`); `parse_command(text) -> tuple[str, list[str]]` (first token lowercased, `/` and `@suffix` stripped, plus remaining args).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_telegram_format.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops import telegram_format as tf


class EscTests(unittest.TestCase):
    def test_escapes_html_metachars(self):
        self.assertEqual(tf.esc("a<b>&c"), "a&lt;b&gt;&amp;c")

    def test_ampersand_escaped_before_entities(self):
        # & must be escaped first so <>  don't double-encode
        self.assertEqual(tf.esc("<&>"), "&lt;&amp;&gt;")

    def test_markdown_chars_pass_through_safely(self):
        # underscores/asterisks are harmless under HTML parse_mode
        self.assertEqual(tf.esc("SB_v2*"), "SB_v2*")

    def test_coerces_non_strings(self):
        self.assertEqual(tf.esc(123), "123")


class ParseCommandTests(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(tf.parse_command("/status"), ("status", []))

    def test_strips_botname_suffix_and_case(self):
        self.assertEqual(tf.parse_command("/CloseAll@TitanBot"), ("closeall", []))

    def test_returns_args_tail(self):
        self.assertEqual(tf.parse_command("/cancel 12345"), ("cancel", ["12345"]))

    def test_non_slash_word_matches_first_token_only(self):
        # the old substring bug: "don't pause" must NOT resolve to "pause"
        self.assertEqual(tf.parse_command("don't pause"), ("don't", ["pause"]))

    def test_empty_string(self):
        self.assertEqual(tf.parse_command("   "), ("", []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.telegram_format'`

- [ ] **Step 3: Write minimal implementation**

Create `src/ops/telegram_format.py`:

```python
"""Pure message builders + command tokenizer for the Telegram layer.

No network, no state, no ``self`` -- every function is a plain data->string
transform so it can be unit-tested in isolation. Dynamic values are
HTML-escaped via ``esc`` because the bot sends these with parse_mode="HTML".
"""

from __future__ import annotations


def esc(v) -> str:
    """HTML-escape a dynamic value for Telegram parse_mode="HTML"."""
    s = str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_command(text) -> tuple[str, list[str]]:
    """Tokenize an incoming message into (command, args).

    First token only: strips a leading '/', drops any '@botname' suffix, and
    lowercases. Everything after the first whitespace token is returned as args.
    """
    raw = str(text).strip().split()
    if not raw:
        return "", []
    cmd = raw[0].lstrip("/").split("@")[0].lower()
    return cmd, raw[1:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/telegram_format.py tests/unit/test_telegram_format.py
git commit -m "feat(telegram): add telegram_format esc() + parse_command() foundation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Formatter module — message builders

**Files:**
- Modify: `src/ops/telegram_format.py`
- Test: `tests/unit/test_telegram_format.py`

**Interfaces:**
- Consumes: `esc()` from Task 1.
- Produces: `signal(symbol, strategy, side, size, price, sl, tp) -> str`; `execution(ticket, symbol, type, price, sl, strategy) -> str` (renders ticket/pair/type/logic only — NOT price/sl); `close(ticket, pnl, symbol="???", strategy="Unknown") -> str`; `management(action_comment, ticket) -> str`; `help_menu() -> str`. All return HTML-tagged strings.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_telegram_format.py` (before the `if __name__` block):

```python
class BuilderTests(unittest.TestCase):
    def test_signal_escapes_and_marks_side(self):
        out = tf.signal("EUR<USD", "SB_v2", "BUY", 0.02, 1.1, 1.09, 1.12)
        self.assertIn("🟢", out)
        self.assertIn("EUR&lt;USD", out)          # symbol escaped
        self.assertIn("<b>", out)                  # HTML formatting present
        self.assertNotIn("EUR<USD", out)           # no raw metachar leaks

    def test_signal_sell_icon(self):
        self.assertIn("🔴", tf.signal("XAUUSD", "OTE", "SELL", 0.01, 1, 2, 3))

    def test_execution_hides_sl_price(self):
        # Phase 1: execution alert must NOT print SL/price (fed sl=0)
        out = tf.execution(555, "BTCUSD", "MARKET", 0.0, 0, "Unicorn")
        self.assertIn("#555", out)
        self.assertIn("BTCUSD", out)
        self.assertIn("Unicorn", out)
        self.assertNotIn("SL", out)
        self.assertNotIn("0.0", out)

    def test_close_pnl_emoji_thresholds(self):
        self.assertIn("🚀🔥", tf.close(1, 500.01, "X", "s"))   # > 500
        self.assertIn("💰", tf.close(1, 0.01, "X", "s"))       # > 0
        self.assertIn("📉", tf.close(1, -10, "X", "s"))        # 0..-50
        self.assertIn("🩸", tf.close(1, -50.01, "X", "s"))     # <= -50
        # boundary: exactly 0 is not > 0 -> not the 💰 branch
        self.assertIn("📉", tf.close(1, 0.0, "X", "s"))

    def test_close_escapes_symbol(self):
        self.assertIn("A&amp;B", tf.close(1, 5, "A&B", "s"))

    def test_management_icon_mapping(self):
        self.assertIn("🔒", tf.management("L1 be", 7))
        self.assertIn("💸", tf.management("L2 bank", 7))
        self.assertIn("🥂", tf.management("L3 bank", 7))
        self.assertIn("👮", tf.management("Risk kill", 7))
        self.assertIn("⚙️", tf.management("something else", 7))

    def test_help_menu_lists_confirm_and_version(self):
        out = tf.help_menu()
        self.assertIn("/confirm", out)
        self.assertIn("v14.4", out)
        self.assertIn("/closeall", out)
        self.assertIn("/panic", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format.BuilderTests -v`
Expected: FAIL — `AttributeError: module 'src.ops.telegram_format' has no attribute 'signal'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/ops/telegram_format.py`:

```python
_RULE = "➖➖➖➖➖➖➖➖"


def signal(symbol, strategy, side, size, price, sl, tp) -> str:
    icon = "🟢" if "BUY" in str(side).upper() else "🔴"
    return (
        "📨 <b>SMC SIGNAL GENERATED</b>\n"
        f"{_RULE}\n"
        f"🧠 <b>Model:</b> <code>{esc(strategy)}</code>\n"
        f"{icon} <b>{esc(symbol)}</b> {esc(side)}\n"
        f"⚖️ <b>Size:</b> <code>{esc(size)} Lots</code>\n"
        f"📍 <b>Entry:</b> <code>{esc(price)}</code>\n"
        f"🛡️ <b>SL:</b> <code>{esc(sl)}</code>\n"
        f"🎯 <b>TP:</b> <code>{esc(tp)}</code>"
    )


def execution(ticket, symbol, type, price, sl, strategy) -> str:
    # Phase 1: mirror the legacy fields exactly -- ticket/pair/type/logic.
    # price/sl are accepted but NOT rendered (still fed sl=0). SL/TP is Phase 2.
    return (
        "⚡ <b>EXECUTION CONFIRMED</b>\n"
        f"{_RULE}\n"
        f"🎫 <b>Ticket:</b> <code>#{esc(ticket)}</code>\n"
        f"💱 <b>Pair:</b> {esc(symbol)}\n"
        f"🕹️ <b>Type:</b> {esc(type)}\n"
        f"⚙️ <b>Logic:</b> <i>{esc(strategy)}</i>"
    )


def close(ticket, pnl, symbol="???", strategy="Unknown") -> str:
    pnl = float(pnl)
    if pnl > 500:
        icon = "🚀🔥"
    elif pnl > 0:
        icon = "💰"
    elif pnl > -50:
        icon = "📉"
    else:
        icon = "🩸"
    return (
        f"{icon} <b>POSITION CLOSED</b>\n"
        f"{_RULE}\n"
        f"🎫 <code>#{esc(ticket)}</code> <b>{esc(symbol)}</b>\n"
        f"🧠 Strat: <code>{esc(strategy)}</code>\n"
        f"💵 <b>PnL:</b> <code>${pnl:,.2f}</code>"
    )


def management(action_comment, ticket) -> str:
    icon, desc = "⚙️", str(action_comment)
    if "L1" in action_comment:
        icon, desc = "🔒", "Ratchet L1 (Break-Even)"
    elif "L2" in action_comment:
        icon, desc = "💸", "Ratchet L2 (Bank 30%)"
    elif "L3" in action_comment:
        icon, desc = "🥂", "Ratchet L3 (Bank 50%)"
    elif "Risk" in action_comment:
        icon, desc = "👮", "RISK GUARD KILL"
    return f"{icon} <b>Auto-Pilot:</b> {esc(desc)}\n🎫 Trade <code>#{esc(ticket)}</code>"


def help_menu() -> str:
    return (
        "🤖 <b>TITAN SMC COMMANDER v14.4</b>\n"
        f"{_RULE}\n"
        "📊 <code>/status</code>   - Strategy Dashboard\n"
        "💰 <code>/balance</code>  - Account Equity\n"
        "📋 <code>/pending</code>  - View Pending Orders\n"
        "🛑 <code>/pause</code>    - Freeze Execution\n"
        "▶️ <code>/resume</code>   - Resume Trading\n"
        "🗑️ <code>/cancel ID</code> - Cancel Pending Order\n"
        "✂️ <code>/close ID</code> - Close Active Trade\n"
        "☠️ <code>/closeall</code> - Close All (needs /confirm)\n"
        "✅ <code>/confirm</code>  - Confirm pending action\n"
        "🚨 <code>/panic</code>    - EMERGENCY FLATTEN"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_format -v`
Expected: PASS (all Task 1 + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/telegram_format.py tests/unit/test_telegram_format.py
git commit -m "feat(telegram): add HTML message builders to telegram_format

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Bot network layer — per-call parse_mode + builder delegation

**Files:**
- Modify: `src/ops/telemetry.py` (imports, `HELP_MENU` removal, `notify_*`, `send_message`, `_async_send_retry`, add `_build_payload`)
- Modify: `src/core/system_controller.py` (9 send_message call sites)
- Test: `tests/unit/test_telegram_commands.py`

**Interfaces:**
- Consumes: `telegram_format.signal/execution/close/management/help_menu` (Tasks 1–2).
- Produces: `TelegramBot._build_payload(text, parse_mode="HTML") -> dict`; `send_message(text, parse_mode="HTML")` and `_async_send_retry(text, retries=3, parse_mode="HTML")` accept per-call `parse_mode`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_telegram_commands.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.telemetry import TelegramBot


class _FakeLogger:
    def log_event(self, *a, **k):
        pass


def _bot():
    """A TelegramBot with no live token; network is never hit in these tests."""
    b = TelegramBot(_FakeLogger())
    b.token = "test"
    b.allowed_chat_id = "42"
    b.is_active = True
    return b


class PayloadTests(unittest.TestCase):
    def test_build_payload_defaults_to_html(self):
        b = _bot()
        p = b._build_payload("hi")
        self.assertEqual(p["parse_mode"], "HTML")
        self.assertEqual(p["chat_id"], "42")
        self.assertEqual(p["text"], "hi")

    def test_build_payload_honors_override(self):
        b = _bot()
        self.assertEqual(b._build_payload("hi", "Markdown")["parse_mode"], "Markdown")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_commands -v`
Expected: FAIL — `AttributeError: 'TelegramBot' object has no attribute '_build_payload'`

- [ ] **Step 3: Write minimal implementation**

In `src/ops/telemetry.py`:

(a) Add the formatter import near the top (after `from dotenv import load_dotenv`):

```python
from src.ops import telegram_format
```

(b) Delete the `HELP_MENU = ( ... )` class constant block entirely.

(c) Replace the bodies of the four `notify_*` methods to delegate (keep their signatures):

```python
    async def notify_signal(self, symbol, strategy, side, size, price, sl, tp):
        await self.send_message(telegram_format.signal(symbol, strategy, side, size, price, sl, tp))

    async def notify_execution(self, ticket, symbol, type, price, sl, strategy):
        await self.send_message(telegram_format.execution(ticket, symbol, type, price, sl, strategy))

    async def notify_close(self, ticket, pnl, symbol="???", strategy="Unknown"):
        await self.send_message(telegram_format.close(ticket, pnl, symbol, strategy))

    async def notify_management(self, action_comment, ticket):
        await self.send_message(telegram_format.management(action_comment, ticket))
```

(d) Replace `send_message` and `_async_send_retry`, and add `_build_payload`:

```python
    async def send_message(self, text, parse_mode="HTML"):
        if not self.is_active:
            return
        asyncio.create_task(self._async_send_retry(text, parse_mode=parse_mode))

    def _build_payload(self, text, parse_mode="HTML"):
        return {"chat_id": self.allowed_chat_id, "text": text, "parse_mode": parse_mode}

    async def _async_send_retry(self, text, retries=3, parse_mode="HTML"):
        """Sends message with exponential-backoff retry."""
        payload = self._build_payload(text, parse_mode)
        for attempt in range(retries):
            try:
                await asyncio.to_thread(
                    self.session.post,
                    f"{self.base_url}/sendMessage",
                    json=payload,
                    timeout=5,
                )
                return
            except requests.RequestException as e:
                if attempt == retries - 1:
                    self.logger.log_event("ERROR", "TELEMETRY", f"Failed to send: {e}")
                else:
                    await asyncio.sleep(0.5 * (2 ** attempt))
```

In `src/core/system_controller.py`, append `, parse_mode="Markdown"` to each of the 9 un-migrated `send_message` calls so they keep rendering under the new HTML default. Exact edits:

- Line ~157 (multi-line): change the closing `)` of the `send_message(` call so its last argument line is followed by `, parse_mode="Markdown"` before the `)`. Result:
```python
        await self.telemetry.send_message(
            f"🚀 **Titan V14.3 Pro Online**\n"
            f"📍 Clock (NY): `{self.time_engine.get_current_ny_string()}`\n"
            f"📡 Sync Guard: ACTIVE",
            parse_mode="Markdown",
        )
```
- `send_message(f"☠️ **FATAL SYSTEM CRASH**\nError: `{str(e)}`")` → add `, parse_mode="Markdown"` before `)`
- `send_message(f"⚠️ **Sync Guard:** Resolved Ticket `#{tid}` (Closed externally)")` → `, parse_mode="Markdown"`
- `send_message(f"♻️ **Auto-Clean:** Expired {o['strategy']} Order `#{o['ticket_id']}`")` → `, parse_mode="Markdown"`
- `send_message(report)` → `send_message(report, parse_mode="Markdown")`
- `send_message(f"🛑 **NEWS BLOCK**: {reason}")` → `, parse_mode="Markdown"`
- `send_message("✅ News Cleared. Resuming.")` → `, parse_mode="Markdown"`
- `send_message("🚨 **PANIC PROTOCOL ENGAGED** 🚨")` → `, parse_mode="Markdown"`
- `send_message(f"✅ **Global Flatten:** Closed `{m_count}` | Cancelled `{p_count}`")` → `, parse_mode="Markdown"`

Verify none were missed:

Run: `grep -n "telemetry.send_message" src/core/system_controller.py | grep -v "parse_mode"`
Expected: no output (every call now passes parse_mode).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_commands -v`
Expected: PASS (PayloadTests)

Run: `.venv/bin/python -c "import src.core.system_controller"`
Expected: no output, exit 0 (module still imports; no syntax error from the edits)

- [ ] **Step 5: Commit**

```bash
git add src/ops/telemetry.py src/core/system_controller.py tests/unit/test_telegram_commands.py
git commit -m "feat(telegram): per-call parse_mode (HTML default) + delegate notify_* to builders

Un-migrated controller callers pass parse_mode=Markdown so the shared send
pipe keeps rendering; notify_* now build HTML via telegram_format.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Exact-token command dispatch

**Files:**
- Modify: `src/ops/telemetry.py` (`_process` rewrite)
- Test: `tests/unit/test_telegram_commands.py`

**Interfaces:**
- Consumes: `telegram_format.parse_command`, `telegram_format.help_menu`.
- Produces: `_process(update)` routes on the exact parsed command token; unknown/empty → help menu. Auth check unchanged (runs first). `/closeall` and `/confirm` handlers are stubbed here and fully implemented in Task 5 (this task wires them to methods `_prompt_closeall_confirm` / `_handle_confirm`, defined in Task 5).

> NOTE: This task defines the two confirm methods as minimal stubs so the dispatch is testable in isolation; Task 5 replaces the stubs with the real FSM. If executing tasks strictly in order, add the stubs here and flesh them out in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_telegram_commands.py` (before `if __name__`):

```python
import asyncio


class _FakeController:
    def __init__(self):
        self.paused = None
        self.status_calls = 0

    def get_status_report(self):
        self.status_calls += 1
        return "STATUS"

    def get_balance_report(self):
        return "BALANCE"

    def get_pending_orders_report(self):
        return "PENDING"

    def set_system_pause(self, p):
        self.paused = p
        return "PAUSED" if p else "ACTIVE"


def _sent_recorder(bot):
    """Replace send_message with an async recorder; returns the capture list."""
    sent = []

    async def _fake_send(text, parse_mode="HTML"):
        sent.append((text, parse_mode))

    bot.send_message = _fake_send
    return sent


def _update(text, sender="42"):
    return {"message": {"from": {"id": sender}, "text": text}}


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_routes_to_report(self):
        b = _bot()
        c = _FakeController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/status"))
        self.assertEqual(c.status_calls, 1)
        self.assertEqual(sent[0][0], "STATUS")
        self.assertEqual(sent[0][1], "Markdown")   # controller report stays Markdown

    async def test_wrong_sender_is_ignored(self):
        b = _bot()
        c = _FakeController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/status", sender="999"))
        self.assertEqual(sent, [])
        self.assertEqual(c.status_calls, 0)

    async def test_non_command_shows_help(self):
        b = _bot()
        b.register_controller(_FakeController())
        sent = _sent_recorder(b)
        await b._process(_update("don't pause"))
        self.assertEqual(b.controller_ref.paused, None)   # pause NOT fired
        self.assertIn("TITAN SMC COMMANDER", sent[0][0])   # help shown

    async def test_pause_and_resume(self):
        b = _bot()
        c = _FakeController()
        b.register_controller(c)
        _sent_recorder(b)
        await b._process(_update("/pause"))
        self.assertTrue(c.paused)
        await b._process(_update("/resume"))
        self.assertFalse(c.paused)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_commands.DispatchTests -v`
Expected: FAIL — old `_process` uses substring matching / lowercases whole text; `test_non_command_shows_help` fails because `"pause" in "don't pause"` fired pause (and/or the Markdown assertion on `/status` fails).

- [ ] **Step 3: Write minimal implementation**

In `src/ops/telemetry.py`, replace the entire `_process` method with:

```python
    async def _process(self, update):
        """Route one authenticated update to its command handler."""
        try:
            msg = update.get("message", {})

            sender_id = str(msg.get("from", {}).get("id"))
            if sender_id != str(self.allowed_chat_id):
                return

            cmd, args = telegram_format.parse_command(msg.get("text", ""))
            print(f"[CMD] {cmd} {args}")

            c = self.controller_ref
            if not c:
                return

            if cmd == "status":
                await self.send_message(c.get_status_report(), parse_mode="Markdown")
            elif cmd == "balance":
                await self.send_message(c.get_balance_report(), parse_mode="Markdown")
            elif cmd == "pending":
                await self.send_message(c.get_pending_orders_report(), parse_mode="Markdown")
            elif cmd == "pause":
                await self.send_message(f"⏸️ System: {c.set_system_pause(True)}", parse_mode="Markdown")
            elif cmd == "resume":
                await self.send_message(f"▶️ System: {c.set_system_pause(False)}", parse_mode="Markdown")
            elif cmd == "cancel":
                if not args:
                    await self.send_message("⚠️ Usage: `/cancel 123456` or `/cancel all`", parse_mode="Markdown")
                else:
                    target = args[0] if "all" not in args[0].lower() else None
                    res = await c.cancel_pending_orders(target)
                    await self.send_message(f"🗑️ Result: {res}", parse_mode="Markdown")
            elif cmd == "close":
                if not args:
                    await self.send_message("⚠️ Usage: `/close 123456` (Active Ticket ID)", parse_mode="Markdown")
                else:
                    try:
                        target_id = int(args[0])
                    except ValueError:
                        await self.send_message("⚠️ Ticket must be a number.", parse_mode="Markdown")
                        return
                    res = await c.close_specific_market_order(target_id)
                    await self.send_message(res, parse_mode="Markdown")
            elif cmd == "closeall":
                await self._prompt_closeall_confirm()
            elif cmd == "confirm":
                await self._handle_confirm()
            elif cmd == "panic":
                await c.trigger_panic()
                await self.send_message("🚨 <b>PANIC PROTOCOL EXECUTED</b> 🚨")
            else:
                await self.send_message(telegram_format.help_menu())

        except Exception as e:
            self.logger.log_event("ERROR", "TELEMETRY", f"Cmd Process Fail: {e}")
```

Add these two **temporary stubs** as methods on `TelegramBot` (Task 5 replaces them):

```python
    async def _prompt_closeall_confirm(self):
        await self.send_message("closeall stub", parse_mode="Markdown")

    async def _handle_confirm(self):
        await self.send_message("confirm stub", parse_mode="Markdown")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_commands -v`
Expected: PASS (PayloadTests + DispatchTests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/telemetry.py tests/unit/test_telegram_commands.py
git commit -m "feat(telegram): exact-token command dispatch (kills substring matching)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Two-step `/confirm` guard for `/closeall`

**Files:**
- Modify: `src/ops/telemetry.py` (`__init__`, class const, replace the two stubs from Task 4)
- Test: `tests/unit/test_telegram_commands.py`

**Interfaces:**
- Consumes: dispatch wiring to `_prompt_closeall_confirm` / `_handle_confirm` (Task 4).
- Produces: `self._pending_confirm` slot holding `(action:str, expiry_ts:float)` or `None`; `_prompt_closeall_confirm()` sets it and previews count + open P/L without executing; `_handle_confirm()` captures-and-clears BEFORE awaiting the close, guaranteeing exactly-once. `CONFIRM_TTL = 30` seconds.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_telegram_commands.py` (before `if __name__`):

```python
class _FakeCloseController(_FakeController):
    def __init__(self):
        super().__init__()
        self.current_open_positions = [
            {"t": 1, "pf": 12.5}, {"t": 2, "pf": -4.0},
        ]
        self.close_all_calls = 0

    async def close_all_market_orders(self):
        self.close_all_calls += 1
        return len(self.current_open_positions)


class ConfirmFsmTests(unittest.IsolatedAsyncioTestCase):
    async def test_closeall_prompts_without_executing(self):
        b = _bot()
        c = _FakeCloseController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/closeall"))
        self.assertEqual(c.close_all_calls, 0)          # did NOT flatten
        self.assertIsNotNone(b._pending_confirm)
        self.assertIn("/confirm", sent[0][0])
        self.assertIn("2", sent[0][0])                  # position count shown

    async def test_confirm_executes_once_then_slot_empty(self):
        b = _bot()
        c = _FakeCloseController()
        b.register_controller(c)
        _sent_recorder(b)
        await b._process(_update("/closeall"))
        await b._process(_update("/confirm"))
        self.assertEqual(c.close_all_calls, 1)          # flattened exactly once
        self.assertIsNone(b._pending_confirm)           # slot cleared
        await b._process(_update("/confirm"))           # second confirm
        self.assertEqual(c.close_all_calls, 1)          # NOT executed again

    async def test_confirm_without_pending_is_noop(self):
        b = _bot()
        c = _FakeCloseController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/confirm"))
        self.assertEqual(c.close_all_calls, 0)
        self.assertIn("Nothing to confirm", sent[0][0])

    async def test_expired_confirm_does_not_execute(self):
        import time
        b = _bot()
        c = _FakeCloseController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        b._pending_confirm = ("closeall", time.time() - 1)   # already expired
        await b._process(_update("/confirm"))
        self.assertEqual(c.close_all_calls, 0)
        self.assertIsNone(b._pending_confirm)
        self.assertIn("expired", sent[-1][0].lower())

    async def test_closeall_with_no_positions(self):
        b = _bot()
        c = _FakeCloseController()
        c.current_open_positions = []
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/closeall"))
        self.assertIsNone(b._pending_confirm)           # nothing to arm
        self.assertIn("No open positions", sent[0][0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_commands.ConfirmFsmTests -v`
Expected: FAIL — stubs return "closeall stub"/"confirm stub"; `b._pending_confirm` attribute does not exist.

- [ ] **Step 3: Write minimal implementation**

In `src/ops/telemetry.py`:

(a) Add a class constant near the top of `TelegramBot` (next to where `HELP_MENU` used to be):

```python
    CONFIRM_TTL = 30  # seconds a destructive-action confirmation stays valid
```

(b) In `__init__`, add the slot (e.g. next to `self.controller_ref = None`):

```python
        self._pending_confirm = None  # (action:str, expiry_ts:float) | None
```

(c) Replace the two stub methods from Task 4 with the real implementation:

```python
    async def _prompt_closeall_confirm(self):
        c = self.controller_ref
        positions = getattr(c, "current_open_positions", None) or []
        n = len(positions)
        if n == 0:
            await self.send_message("📭 No open positions to close.", parse_mode="Markdown")
            return
        open_pnl = 0.0
        for p in positions:
            try:
                open_pnl += float(p.get("pf", 0.0))
            except (TypeError, ValueError):
                pass
        self._pending_confirm = ("closeall", time.time() + self.CONFIRM_TTL)
        await self.send_message(
            f"⚠️ Close *{n}* positions (`${open_pnl:,.2f}` open)?\n"
            f"Reply `/confirm` within {self.CONFIRM_TTL}s.",
            parse_mode="Markdown",
        )

    async def _handle_confirm(self):
        pending = self._pending_confirm
        self._pending_confirm = None  # capture-and-clear BEFORE await => exactly-once
        if pending and pending[1] >= time.time():
            if pending[0] == "closeall":
                count = await self.controller_ref.close_all_market_orders()
                await self.send_message(f"☠️ *Flattened* `{count}` positions.", parse_mode="Markdown")
        elif pending:
            await self.send_message("⌛ Confirmation expired.", parse_mode="Markdown")
        else:
            await self.send_message("Nothing to confirm.", parse_mode="Markdown")
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_telegram_commands -v`
Expected: PASS (PayloadTests + DispatchTests + ConfirmFsmTests)

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK — full unit suite green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/ops/telemetry.py tests/unit/test_telegram_commands.py
git commit -m "feat(telegram): two-step /confirm guard for /closeall (exactly-once)

/closeall previews count + open P/L and arms a 30s confirm slot; /confirm
captures-and-clears before awaiting the close so concurrent _process tasks
cannot double-flatten. /panic stays instant.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Formatter module + `esc()` → Task 1. ✓
- Five builders (signal/execution/close/management/help_menu) → Task 2. ✓
- HTML parse_mode per-call + un-migrated callers pass Markdown → Task 3. ✓
- `notify_execution` keeps today's fields, no SL → Task 2 (`test_execution_hides_sl_price`) + Task 3 delegation. ✓
- `help_menu()` adds `/confirm` + v14.4 → Task 2 (`test_help_menu_lists_confirm_and_version`). ✓
- Exact-token dispatch (kills substring bug + `/close` vs `/closeall`) → Task 4. ✓
- Bare-word first-token-only behavior → Task 1 (`test_non_slash_word...`) + Task 4 (`test_non_command_shows_help`). ✓
- Two-step `/confirm` for `/closeall`, single slot, capture-and-clear-before-await, TTL → Task 5. ✓
- `/panic` stays instant → Task 4 dispatch (`panic` handler executes immediately, no confirm). ✓

**Placeholder scan:** The Task 4 confirm stubs are intentional and explicitly replaced in Task 5 (not a placeholder left dangling). No TBD/TODO/"handle edge cases" remain. All code steps show full code.

**Type consistency:** `_pending_confirm` is `(str, float)|None` everywhere; `parse_command` returns `(str, list)` used consistently; `_build_payload(text, parse_mode)`, `send_message(text, parse_mode)`, `_async_send_retry(text, retries, parse_mode)` signatures match across tasks; `_prompt_closeall_confirm` / `_handle_confirm` names match between Task 4 wiring and Task 5 implementation.
