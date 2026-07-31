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

    def __init__(self, events=None, error=None, last_rows_seen=0):
        self.events = events or []
        self.error = error
        self.calls = 0
        self.last_rows_seen = last_rows_seen

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


class ZeroEventsFromANonEmptyFeedIsABrokenRefreshNotSuccess(unittest.TestCase):
    """Item 1: a valid-schema fetch that parses ZERO events from a feed that
    clearly had rows must not be blessed as a successful sync -- otherwise the
    cache looks perpetually fresh while every symbol trades through every
    red-folder event with no warning."""

    def test_rows_seen_but_no_events_marks_the_feed_degraded(self):
        manager = _manager(_Source([], last_rows_seen=50))
        _run(manager.update_calendar())
        self.assertTrue(manager.feed_degraded)

    def test_rows_seen_but_no_events_does_not_stamp_last_success(self):
        store = CalendarStore(os.devnull)
        manager = _manager(_Source([], last_rows_seen=50), store)
        _run(manager.update_calendar())
        self.assertIsNone(store.age(RELEASE))  # never refreshed, by design

    def test_rows_seen_but_no_events_merges_nothing(self):
        store = CalendarStore(os.devnull)
        store.merge([_pce()], "forexfactory", RELEASE - timedelta(hours=1))
        manager = _manager(_Source([], last_rows_seen=50), store)
        _run(manager.update_calendar())
        # The pre-existing cached event must survive untouched -- nothing new
        # (and certainly not an emptying merge) was applied.
        self.assertEqual(len(store.events()), 1)

    def test_header_only_feed_zero_rows_zero_events_is_still_a_legitimate_success(self):
        """The existing, correct case: do not regress it."""
        store = CalendarStore(os.devnull)
        manager = _manager(_Source([], last_rows_seen=0), store)
        _run(manager.update_calendar())
        self.assertIsNotNone(store.age(RELEASE))
        self.assertFalse(manager.feed_degraded)


class DiskCacheSurvivesRestart(unittest.TestCase):
    """Item 2: the store persists to disk and NewsManager.__init__ reads it
    back via self.store.load() -- proving a fresh process boots protected
    from a prior day's fetch, with zero network calls."""

    def test_fresh_manager_blocks_from_a_disk_cache_with_no_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            seed = CalendarStore(path)
            seed.merge([_pce()], "forexfactory", RELEASE - timedelta(hours=2))
            seed.save()

            class _ExplodingSource:
                NAME = "forexfactory"

                async def fetch(self):
                    raise AssertionError("must not hit the network")

            manager = NewsManager(_StubLogger(), config=CONFIG,
                                  source=_ExplodingSource(), store=CalendarStore(path))

            blocked, reason = manager.check_symbol("EURUSD", now=RELEASE)
            self.assertTrue(blocked)
            self.assertIn("Core PCE", reason)
            halted, _ = manager.is_globally_blocked(now=RELEASE)
            self.assertFalse(halted)


class CsvTimezoneIsWired(unittest.TestCase):
    """Item 5: an operator-configurable csv_timezone must actually reach the
    default source, so a future feed timezone change is a config edit, not a
    code deploy."""

    def test_configured_timezone_shifts_parsed_times(self):
        cfg = {"news": {"csv_timezone": "America/New_York",
                        "symbol_currencies": {"EURUSD": ["EUR", "USD"]}}}
        manager = NewsManager(_StubLogger(), config=cfg, store=CalendarStore(os.devnull))
        csv_text = (
            "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
            "FOMC Statement,USD,07-29-2026,6:00pm,High,,,https://example.test/1\n"
        )
        events = manager.source.parse(csv_text)
        # 6:00pm America/New_York in July (EDT, UTC-4) -> 22:00 UTC.
        self.assertEqual(events[0].when_utc, datetime(2026, 7, 29, 22, 0, tzinfo=timezone.utc))

    def test_invalid_timezone_name_falls_back_to_utc_without_raising(self):
        cfg = {"news": {"csv_timezone": "Not/AZone"}}
        manager = NewsManager(_StubLogger(), config=cfg, store=CalendarStore(os.devnull))
        self.assertEqual(manager.source.tz, timezone.utc)


class SnapshotDegradesInsteadOfPropagating(unittest.TestCase):
    """Item 6 (2nd half): the GUI payload must never break because of news."""

    def test_snapshot_returns_unavailable_when_an_internal_call_raises(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        manager.policy.mapped_symbols = lambda: (_ for _ in ()).throw(
            RuntimeError("policy exploded"))
        self.assertEqual(manager.snapshot(now=RELEASE), {"status": "unavailable"})


if __name__ == "__main__":
    unittest.main()
