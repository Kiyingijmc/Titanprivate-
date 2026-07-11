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
