import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.sources.forexfactory import ForexFactoryCsvSource, NewsFetchError
from src.analysis.news.store import CalendarStore

THIS_URL = ForexFactoryCsvSource.URL
NEXT_URL = ForexFactoryCsvSource.NEXT_URL

HEADER = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
THIS_CSV = HEADER + "FOMC Statement,USD,08-05-2026,6:00pm,High,,,https://e.test/1\n"
NEXT_CSV = HEADER + "Non-Farm Employment Change,USD,08-14-2026,12:30pm,High,85K,57K,https://e.test/2\n"
# Rows present, but the date format has drifted -> every row fails to parse.
DRIFTED = HEADER + "CPI m/m,USD,2026/08/05,8:30 AM,High,,,https://e.test/3\n"


class _StubLogger:
    def __init__(self):
        self.events = []

    def log_event(self, level, tag, message):
        self.events.append((level, tag, message))


class _Response:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.content = body.encode("utf-8")


def _router(bodies, failures=()):
    """url -> body. Urls named in `failures` raise, as a dead endpoint would."""
    def _get(url):
        if url in failures:
            raise OSError("connection refused")
        return _Response(200, bodies.get(url, HEADER))
    return _get


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _source(bodies, failures=(), logger=None):
    src = ForexFactoryCsvSource(logger or _StubLogger())
    src.backoff_base_s = 0          # keep the retry ladder instant in tests
    src._get = _router(bodies, failures)
    return src


class UnionCoversBothWeeks(unittest.TestCase):
    def test_returns_events_from_this_week_and_next_week(self):
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: NEXT_CSV})
        events = _run(src.fetch())
        titles = sorted(e.title for e in events)
        self.assertTrue(titles, "fetch returned nothing; the rest of this test is vacuous")
        self.assertEqual(titles, ["FOMC Statement", "Non-Farm Employment Change"])
        self.assertTrue(src.next_week_ok)

    def test_a_boundary_duplicate_shares_one_key_so_the_store_collapses_it(self):
        # The week-boundary overlap: the same release in both CSVs.
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: THIS_CSV})
        events = _run(src.fetch())
        keys = {e.key for e in events}
        self.assertTrue(keys)
        self.assertEqual(len(keys), 1, "make_key must collapse the boundary duplicate")


class ThisWeekGovernsFailure(unittest.TestCase):
    def test_this_week_down_raises_even_when_next_week_is_healthy(self):
        src = _source({NEXT_URL: NEXT_CSV}, failures=(THIS_URL,))
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_next_week_down_returns_this_week_and_flags_truncation(self):
        logger = _StubLogger()
        src = _source({THIS_URL: THIS_CSV}, failures=(NEXT_URL,), logger=logger)
        events = _run(src.fetch())
        self.assertTrue(events)
        self.assertEqual([e.title for e in events], ["FOMC Statement"])
        self.assertFalse(src.next_week_ok)
        self.assertTrue(any(lvl == "WARN" for lvl, _, _ in logger.events))

    def test_a_broken_this_week_is_not_rescued_by_next_week(self):
        # THE load-bearing rule. rows_seen>0 and events==[] is how
        # NewsManager detects a date-format drift; appending next week's
        # events would make `events` non-empty and silence that guard.
        src = _source({THIS_URL: DRIFTED, NEXT_URL: NEXT_CSV})
        events = _run(src.fetch())
        self.assertEqual(events, [])
        self.assertGreater(src.last_rows_seen, 0)

    def test_last_rows_seen_reports_this_week_only(self):
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: NEXT_CSV})
        _run(src.fetch())
        self.assertEqual(src.last_rows_seen, 1)

    def test_a_broken_this_week_does_not_clear_a_known_next_week_failure(self):
        # One long-lived source, two sequential cycles (as the periodic
        # update_calendar() caller would run it).
        src = _source({THIS_URL: THIS_CSV}, failures=(NEXT_URL,))
        events_1 = _run(src.fetch())
        self.assertTrue(events_1)
        self.assertFalse(src.next_week_ok, "cycle 1: next week is genuinely down")

        # Cycle 2: thisweek now drifts (rule 2). Next week is never attempted
        # on this path, so the flag from cycle 1 must survive untouched --
        # NOT be reset to True with zero new evidence.
        src._get = _router({THIS_URL: DRIFTED, NEXT_URL: NEXT_CSV})
        events_2 = _run(src.fetch())
        self.assertEqual(events_2, [])
        self.assertFalse(src.next_week_ok,
                          "rule 2 must not clear a known prior next-week failure")


class FreshnessIsolation(unittest.TestCase):
    """End-to-end: a broken this-week must never stamp the cache fresh."""

    def _manager(self, src):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            path = fh.name
        os.unlink(path)
        return NewsManager(_StubLogger(), config={"news": {"cache_path": path}},
                           source=src, store=CalendarStore(path))

    def test_healthy_next_week_does_not_refresh_a_broken_this_week(self):
        src = _source({THIS_URL: DRIFTED, NEXT_URL: NEXT_CSV})
        mgr = self._manager(src)
        _run(mgr.update_calendar())
        now = datetime.now(timezone.utc)
        self.assertIsNone(mgr.store.age(now),
                          "a broken this-week stamped the cache fresh")
        self.assertEqual(mgr.store.events(), [])

    def test_a_good_refresh_does_stamp(self):
        # The counterpart — without this, the test above passes trivially
        # if update_calendar were broken outright.
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: NEXT_CSV})
        mgr = self._manager(src)
        _run(mgr.update_calendar())
        self.assertIsNotNone(mgr.store.age(datetime.now(timezone.utc)))
        self.assertEqual(len(mgr.store.events()), 2)

    def test_horizon_truncated_follows_the_source(self):
        src = _source({THIS_URL: THIS_CSV}, failures=(NEXT_URL,))
        mgr = self._manager(src)
        _run(mgr.update_calendar())
        self.assertTrue(mgr.horizon_truncated)


if __name__ == "__main__":
    unittest.main()
