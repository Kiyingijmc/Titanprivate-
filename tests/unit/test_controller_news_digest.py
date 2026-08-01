import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Telemetry:
    def __init__(self):
        self.sent = []

    async def send_message(self, text, parse_mode="HTML"):
        self.sent.append(text)


class _News:
    def __init__(self, digest=None, raises=False):
        self._digest = digest or {"date": "2026-07-30", "count": 0, "events": []}
        self.raises = raises

    def digest(self, now=None):
        if self.raises:
            raise RuntimeError("digest exploded")
        return self._digest


class _Logger:
    def log_event(self, *a, **k):
        pass


def _controller(news=None, enabled=True):
    c = object.__new__(SystemController)
    c.telemetry = _Telemetry()
    c.news_manager = news or _News()
    c.logger = _Logger()
    c.config = {"news": {"digest": {"enabled": enabled, "hour": 7, "minute": 0,
                                    "alert_lead_min": 15}}}
    c.news_digest_sent_today = False
    c.news_alerts_sent = set()
    return c


AT_7 = datetime(2026, 7, 30, 7, 0)
AT_8 = datetime(2026, 7, 30, 8, 0)


class DailyDigest(unittest.TestCase):
    def test_sends_at_the_configured_time(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_does_not_send_twice_in_one_day(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_does_not_send_at_other_times(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_8))
        self.assertEqual(c.telemetry.sent, [])

    def test_empty_day_still_sends_a_message(self):
        """Silence is indistinguishable from a broken job."""
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        self.assertIn("No high-impact", c.telemetry.sent[0])

    def test_disabled_sends_nothing(self):
        c = _controller(enabled=False)
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(c.telemetry.sent, [])

    def test_digest_failure_does_not_raise_into_the_loop(self):
        c = _controller(news=_News(raises=True))
        _run(c._maybe_send_news_digest(AT_7))   # must not raise
        self.assertEqual(c.telemetry.sent, [])


RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
EVENT = {"when_utc": RELEASE.isoformat(), "currency": "USD", "title": "Core PCE",
         "forecast": "0.3%", "previous": "0.2%", "affects": ["EURUSD"]}


class PreEventAlert(unittest.TestCase):
    def _c(self):
        return _controller(news=_News({"date": "2026-07-30", "count": 1,
                                       "events": [EVENT]}))

    def test_alerts_inside_the_lead_window(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.telemetry.sent), 1)
        self.assertIn("Core PCE", c.telemetry.sent[0])

    def test_does_not_alert_before_the_lead_window(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=45)))
        self.assertEqual(c.telemetry.sent, [])

    def test_does_not_alert_after_the_release(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE + timedelta(minutes=5)))
        self.assertEqual(c.telemetry.sent, [])

    def test_alerts_only_once_per_event(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=9)))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_alert_failure_does_not_raise_into_the_loop(self):
        c = _controller(news=_News(raises=True))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(c.telemetry.sent, [])


if __name__ == "__main__":
    unittest.main()
