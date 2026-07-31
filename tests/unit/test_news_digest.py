import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore

DAY = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {
    "EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"], "XAUUSD": ["USD"]}}}


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


def _event(title, currency="USD", importance="HIGH", when=DAY,
           forecast=None, previous=None):
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title,
                         forecast=forecast, previous=previous)


def _manager(events):
    store = CalendarStore(os.devnull)
    store.merge(events, "forexfactory", DAY)
    return NewsManager(_StubLogger(), config=CONFIG, source=object(), store=store)


class DigestContents(unittest.TestCase):
    def test_lists_todays_high_impact_events(self):
        d = _manager([_event("Core PCE", forecast="0.3%", previous="0.2%")]).digest(now=DAY)
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["events"][0]["title"], "Core PCE")
        self.assertEqual(d["events"][0]["forecast"], "0.3%")
        self.assertEqual(d["events"][0]["previous"], "0.2%")

    def test_excludes_medium_and_low(self):
        d = _manager([_event("ifo", importance="MEDIUM"),
                      _event("M3", importance="LOW")]).digest(now=DAY)
        self.assertEqual(d["count"], 0)

    def test_excludes_other_days(self):
        d = _manager([_event("Tomorrow", when=DAY + timedelta(days=1))]).digest(now=DAY)
        self.assertEqual(d["count"], 0)

    def test_events_are_sorted_by_time(self):
        d = _manager([_event("Later", when=DAY + timedelta(hours=3)),
                      _event("Earlier", when=DAY - timedelta(hours=3))]).digest(now=DAY)
        self.assertEqual([e["title"] for e in d["events"]], ["Earlier", "Later"])

    def test_affects_lists_only_exposed_symbols(self):
        d = _manager([_event("Core PCE")]).digest(now=DAY)
        self.assertEqual(sorted(d["events"][0]["affects"]), ["EURUSD", "XAUUSD"])

    def test_gbp_event_affects_gbpjpy_only(self):
        d = _manager([_event("BOE Rate", currency="GBP")]).digest(now=DAY)
        self.assertEqual(d["events"][0]["affects"], ["GBPJPY"])

    def test_empty_day_is_a_valid_digest(self):
        d = _manager([]).digest(now=DAY)
        self.assertEqual(d["count"], 0)
        self.assertEqual(d["events"], [])
        self.assertEqual(d["date"], "2026-07-30")


class DigestNeverRaises(unittest.TestCase):
    def test_internal_error_degrades_to_unavailable(self):
        manager = _manager([_event("Core PCE")])

        def boom():
            raise RuntimeError("store exploded")

        manager.store.events = boom
        d = manager.digest(now=DAY)
        self.assertEqual(d["status"], "unavailable")
        self.assertEqual(d["events"], [])


class DigestDayIsAlwaysUtc(unittest.TestCase):
    def test_non_utc_aware_now_selects_the_utc_day(self):
        """23:30 at -04:00 is 03:30 UTC the NEXT day; the event that day must appear."""
        when = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
        manager = _manager([_event("Overnight", when=when)])
        local = datetime(2026, 7, 30, 23, 30, tzinfo=timezone(timedelta(hours=-4)))
        d = manager.digest(now=local)
        self.assertEqual(d["date"], "2026-07-31")
        self.assertEqual(d["count"], 1)

    def test_naive_now_is_treated_as_utc_not_local_time(self):
        """Must not shift by the host's offset -- this box is UTC+3."""
        manager = _manager([_event("Core PCE")])          # event at 2026-07-30 12:30Z
        d = manager.digest(now=datetime(2026, 7, 30, 12, 30))
        self.assertEqual(d["date"], "2026-07-30")
        self.assertEqual(d["count"], 1)

    def test_unavailable_fallback_also_reports_the_utc_date(self):
        manager = _manager([_event("Core PCE")])
        manager.store.events = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        local = datetime(2026, 7, 30, 23, 30, tzinfo=timezone(timedelta(hours=-4)))
        d = manager.digest(now=local)
        self.assertEqual(d["status"], "unavailable")
        self.assertEqual(d["date"], "2026-07-31")


if __name__ == "__main__":
    unittest.main()
