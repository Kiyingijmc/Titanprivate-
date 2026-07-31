import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.sources.forexfactory import NewsFetchError
from src.analysis.news.store import CalendarStore

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {"EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"]}}}


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


class _Source:
    NAME = "forexfactory"

    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.events


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _pce():
    return CalendarEvent(key=make_key("USD", "Core PCE", RELEASE), when_utc=RELEASE,
                         currency="USD", importance="HIGH", title="Core PCE")


def _manager(source, store=None):
    manager = NewsManager(_StubLogger(), config=CONFIG, source=source,
                          store=store or CalendarStore(os.devnull))
    return manager


class HealthyFeed(unittest.TestCase):
    def test_blocks_the_matching_symbol(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        blocked, reason = manager.check_symbol("EURUSD", now=RELEASE)
        self.assertTrue(blocked)
        self.assertIn("Core PCE", reason)

    def test_does_not_block_an_unrelated_symbol(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        blocked, _ = manager.check_symbol("GBPJPY", now=RELEASE)
        self.assertFalse(blocked)


class FeedDownButCacheFresh(unittest.TestCase):
    """The whole point: an outage must not halt the book."""

    def _primed_store(self):
        store = CalendarStore(os.devnull)
        store.merge([_pce()], "forexfactory", RELEASE - timedelta(hours=2))
        return store

    def test_trading_is_not_globally_halted(self):
        manager = _manager(_Source(error=NewsFetchError("down")), self._primed_store())
        _run(manager.update_calendar())
        halted, _ = manager.is_globally_blocked(now=RELEASE)
        self.assertFalse(halted)

    def test_blackouts_are_still_enforced_from_cache(self):
        manager = _manager(_Source(error=NewsFetchError("down")), self._primed_store())
        _run(manager.update_calendar())
        blocked, _ = manager.check_symbol("EURUSD", now=RELEASE)
        self.assertTrue(blocked)

    def test_degraded_flag_is_raised(self):
        manager = _manager(_Source(error=NewsFetchError("down")), self._primed_store())
        _run(manager.update_calendar())
        self.assertTrue(manager.feed_degraded)


class FeedDownAndCacheStale(unittest.TestCase):
    def test_halts_globally_when_cache_exceeds_the_ceiling(self):
        store = CalendarStore(os.devnull)
        store.merge([_pce()], "forexfactory", RELEASE - timedelta(hours=72))
        manager = _manager(_Source(error=NewsFetchError("down")), store)
        _run(manager.update_calendar())
        halted, reason = manager.is_globally_blocked(now=RELEASE)
        self.assertTrue(halted)
        self.assertIn("stale", reason.lower())

    def test_halts_when_nothing_was_ever_fetched(self):
        manager = _manager(_Source(error=NewsFetchError("down")))
        _run(manager.update_calendar())
        halted, _ = manager.is_globally_blocked(now=RELEASE)
        self.assertTrue(halted)

    def test_stale_cache_also_blocks_every_symbol(self):
        manager = _manager(_Source(error=NewsFetchError("down")))
        _run(manager.update_calendar())
        blocked, _ = manager.check_symbol("GBPJPY", now=RELEASE)
        self.assertTrue(blocked)


class Snapshot(unittest.TestCase):
    def test_reports_next_event_and_source_health(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        snap = manager.snapshot(now=RELEASE - timedelta(minutes=45))
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["next"]["title"], "Core PCE")
        self.assertIn("EURUSD", snap["next"]["affects"])


class HaltedRetriesQuickly(unittest.TestCase):
    """A halted bot must not wait out the hourly interval to recover."""

    def test_retries_within_the_hour_while_halted(self):
        source = _Source(error=NewsFetchError("down"))
        manager = _manager(source)          # empty store -> stale -> halted
        _run(manager.update_calendar())
        manager._last_attempt = datetime.now(timezone.utc) - timedelta(seconds=90)
        calls_before = source.calls
        _run(manager.update_calendar())
        self.assertGreater(source.calls, calls_before)
        self.assertTrue(manager.is_globally_blocked()[0])
        self.assertIsNotNone(manager._last_attempt)

    def test_does_not_hammer_while_halted(self):
        source = _Source(error=NewsFetchError("down"))
        manager = _manager(source)
        _run(manager.update_calendar())
        stamped = manager._last_attempt
        _run(manager.update_calendar())      # immediately again
        self.assertEqual(manager._last_attempt, stamped)  # skipped, not retried


if __name__ == "__main__":
    unittest.main()
