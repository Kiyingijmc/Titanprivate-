import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

import pytz

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
        self.calls = 0

    def digest(self, now=None):
        self.calls += 1
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
    c.news_daily_reset_done = False
    c._news_alert_cache = None
    c._news_alert_cache_at = None
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


class HourZeroResetRace(unittest.TestCase):
    """Fix round 1, Finding A (CRITICAL).

    The hour-0 reset lives inline in the main loop's Section F, not in a
    separate method -- so this test mirrors that exact snippet rather than
    calling it, and must be kept in sync with it. This body reflects the
    FIXED (guarded, reset-before-send) ordering; the pre-fix run of this same
    body (with the guard removed and the reset run after the send, matching
    the code as it stood before this round) reproduced the reviewer's
    50-sends failure -- see task-4-report.md for the verbatim RED.
    """

    def test_hour_zero_reset_does_not_repeatedly_wipe_the_alert_dedup(self):
        c = _controller(news=_News({"date": "2026-07-30", "count": 1,
                                    "events": [EVENT]}))
        now_utc = RELEASE - timedelta(minutes=5)  # inside the 15-min lead window

        class _NowUganda:
            hour = 0

        now_uganda = _NowUganda()

        for _ in range(50):
            # Mirrors system_controller.py Section F's news-reset block exactly,
            # including its position BEFORE the send (a reset placed after the
            # send wipes the marker the send just wrote, on the first hour-0
            # tick of the day -- see task-4-report.md fix round 1).
            if now_uganda.hour == 0:
                if not c.news_daily_reset_done:
                    c.news_digest_sent_today = False
                    c.news_alerts_sent.clear()
                    c.news_daily_reset_done = True
            else:
                c.news_daily_reset_done = False
            _run(c._maybe_send_news_alerts(now_utc))

        self.assertEqual(len(c.telemetry.sent), 1)


class DigestCaching(unittest.TestCase):
    """Fix round 1, Finding B (Important): digest() must not run every tick."""

    def test_digest_is_cached_for_30_seconds_keyed_on_the_passed_clock(self):
        news = _News({"date": "2026-07-30", "count": 1, "events": [EVENT]})
        c = _controller(news=news)
        base = RELEASE - timedelta(minutes=30)

        _run(c._maybe_send_news_alerts(base))
        _run(c._maybe_send_news_alerts(base + timedelta(seconds=5)))
        _run(c._maybe_send_news_alerts(base + timedelta(seconds=29)))
        self.assertEqual(news.calls, 1)

        _run(c._maybe_send_news_alerts(base + timedelta(seconds=31)))
        self.assertEqual(news.calls, 2)


BAD_EVENT = {"currency": "USD", "title": "Missing when_utc"}  # no 'when_utc' key


class MalformedEventResilience(unittest.TestCase):
    """Fix round 1, Finding C (Minor): one bad event must not eat the rest."""

    def test_a_malformed_event_does_not_block_a_valid_ones_alert(self):
        news = _News({"date": "2026-07-30", "count": 2,
                      "events": [BAD_EVENT, EVENT]})
        c = _controller(news=news)
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.telemetry.sent), 1)
        self.assertIn("Core PCE", c.telemetry.sent[0])


UGANDA_TZ = pytz.timezone("Africa/Kampala")


class MidnightCrossingResetVsPendingMarker(unittest.TestCase):
    """Fix round 2, Finding A residual: the round-1 guard made the reset fire
    once per day, but it still unconditionally cleared news_alerts_sent --
    wiping markers for events that are still pending (not yet released) when
    Kampala midnight (21:00 UTC) falls inside a pre-release lead window.

    Model: step a continuously-advancing UTC clock from 20:50 through 21:15
    UTC (crossing 21:00 UTC = Kampala 00:00) with a HIGH event releasing at
    21:10 UTC and a 15-min lead window (opens 20:55 UTC = Kampala 23:55, i.e.
    before the reset fires). Mirrors system_controller.py Section F exactly
    and must be kept in lockstep with it (see HourZeroResetRace).
    """

    def test_exactly_one_send_across_the_midnight_crossing(self):
        release = datetime(2026, 7, 30, 21, 10, tzinfo=timezone.utc)
        event = {"when_utc": release.isoformat(), "currency": "USD",
                 "title": "Midnight Crossing Event"}
        c = _controller(news=_News({"date": "2026-07-30", "count": 1,
                                    "events": [event]}))

        now_utc = datetime(2026, 7, 30, 20, 50, tzinfo=timezone.utc)
        end = datetime(2026, 7, 30, 21, 15, tzinfo=timezone.utc)
        step = timedelta(minutes=1)

        while now_utc <= end:
            now_uganda = now_utc.astimezone(UGANDA_TZ)
            # Mirrors system_controller.py Section F's guarded reset exactly
            # (post fix-round-2: no news_alerts_sent.clear() here -- pruning
            # of resolved markers happens inside _maybe_send_news_alerts).
            if now_uganda.hour == 0:
                if not c.news_daily_reset_done:
                    c.news_digest_sent_today = False
                    c.news_daily_reset_done = True
            else:
                c.news_daily_reset_done = False
            _run(c._maybe_send_news_alerts(now_utc))
            now_utc += step

        self.assertEqual(len(c.telemetry.sent), 1)


class ResolvedMarkerPruning(unittest.TestCase):
    """Fix round 2: a dedup marker expires once its event releases, not on a
    wall-clock day boundary -- so the set doesn't grow unbounded now that the
    daily .clear() is gone."""

    def test_a_resolved_events_marker_is_pruned(self):
        c = _controller(news=_News({"date": "2026-07-30", "count": 1,
                                    "events": [EVENT]}))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.news_alerts_sent), 1)

        # Long after release -- the marker is no longer needed and must be pruned.
        _run(c._maybe_send_news_alerts(RELEASE + timedelta(hours=2)))
        self.assertEqual(c.news_alerts_sent, set())


if __name__ == "__main__":
    unittest.main()
