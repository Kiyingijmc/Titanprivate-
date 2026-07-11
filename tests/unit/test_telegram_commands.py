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


class _FakeErrorController(_FakeController):
    """A controller whose mgmt calls always blow up, to exercise error replies."""

    async def cancel_pending_orders(self, target):
        raise RuntimeError("boom")

    async def close_specific_market_order(self, target_id):
        raise RuntimeError("boom")


class ErrorReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_failure_replies_with_error(self):
        b = _bot()
        c = _FakeErrorController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/cancel 123"))
        self.assertTrue(sent, "expected an operator reply on cancel failure")
        self.assertIn("❌ Error", sent[-1][0])
        self.assertIn("boom", sent[-1][0])

    async def test_close_failure_replies_with_error(self):
        b = _bot()
        c = _FakeErrorController()
        b.register_controller(c)
        sent = _sent_recorder(b)
        await b._process(_update("/close 123"))
        self.assertTrue(sent, "expected an operator reply on close failure")
        self.assertIn("❌ Error", sent[-1][0])
        self.assertIn("boom", sent[-1][0])


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


if __name__ == "__main__":
    unittest.main()
