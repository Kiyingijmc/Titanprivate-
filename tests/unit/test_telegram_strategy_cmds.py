import os
import sys
import unittest
from unittest.mock import MagicMock

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


def _sent_recorder(bot):
    """Replace send_message with an async recorder; returns the capture list."""
    sent = []

    async def _fake_send(text, parse_mode="HTML"):
        sent.append((text, parse_mode))

    bot.send_message = _fake_send
    return sent


def _update(text, sender="42"):
    return {"message": {"from": {"id": sender}, "text": text}}


class StrategyCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_strategies_routes_to_report(self):
        b = _bot()
        c = MagicMock()
        c.get_strategies_report.return_value = "🧩 **STRATEGY REGISTRY**"
        b.register_controller(c)
        sent = _sent_recorder(b)

        await b._process(_update("/strategies"))

        c.get_strategies_report.assert_called_once_with()
        self.assertEqual(sent[0], ("🧩 **STRATEGY REGISTRY**", "Markdown"))

    async def test_enable_with_arg_calls_controller(self):
        b = _bot()
        c = MagicMock()
        c.enable_strategy.return_value = "✅ silver_bullet enabled"
        b.register_controller(c)
        sent = _sent_recorder(b)

        await b._process(_update("/enable silver_bullet"))

        c.enable_strategy.assert_called_once_with("silver_bullet")
        self.assertEqual(sent[0], ("✅ silver_bullet enabled", "Markdown"))

    async def test_enable_without_arg_sends_usage_and_skips_controller(self):
        b = _bot()
        c = MagicMock()
        b.register_controller(c)
        sent = _sent_recorder(b)

        await b._process(_update("/enable"))

        c.enable_strategy.assert_not_called()
        self.assertEqual(sent[0], ("⚠️ Usage: `/enable silver_bullet`", "Markdown"))

    async def test_disable_unknown_id_passes_through_error_text(self):
        b = _bot()
        c = MagicMock()
        c.disable_strategy.return_value = "❌ Unknown strategy id: xyz"
        b.register_controller(c)
        sent = _sent_recorder(b)

        await b._process(_update("/disable xyz"))

        c.disable_strategy.assert_called_once_with("xyz")
        self.assertEqual(sent[0], ("❌ Unknown strategy id: xyz", "Markdown"))


if __name__ == "__main__":
    unittest.main()
