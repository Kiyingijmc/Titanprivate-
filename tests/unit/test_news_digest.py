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
        """Must not shift by the host's offset -- this box is UTC+3.

        Noon ± 3 hours still stays same day, so use 01:00Z. A ±3h shift
        from 01:00 crosses the day boundary, detecting .astimezone() on naive."""
        event = _event("Early", when=datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc))
        manager = _manager([event])
        # Naive datetime is treated as UTC, not local: digest sees 2026-07-31 01:00Z
        d = manager.digest(now=datetime(2026, 7, 31, 1, 0))
        self.assertEqual(d["date"], "2026-07-31")
        self.assertEqual(d["count"], 1)

    def test_unavailable_fallback_also_reports_the_utc_date(self):
        """Fallback returns today's real UTC date (not the bad now parameter)."""
        manager = _manager([_event("Core PCE")])
        manager.store.events = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        local = datetime(2026, 7, 30, 23, 30, tzinfo=timezone(timedelta(hours=-4)))
        d = manager.digest(now=local)
        self.assertEqual(d["status"], "unavailable")
        # Fallback uses datetime.now(timezone.utc), so don't assert a fixed date.
        # Just verify it's a valid ISO date and events is empty.
        self.assertRegex(d["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(d["events"], [])

    def test_garbage_now_degrades_instead_of_raising(self):
        manager = _manager([_event("Core PCE")])
        for bad in ("2026-07-30", 12345, object()):
            with self.subTest(bad=bad):
                d = manager.digest(now=bad)        # must not raise
                self.assertEqual(d["status"], "unavailable")
                self.assertEqual(d["events"], [])


from src.ops.telegram_format import format_news_alert, format_news_digest

_DIGEST = {
    "date": "2026-07-30", "count": 2,
    "events": [
        {"when_utc": "2026-07-30T12:30:00+00:00", "currency": "USD",
         "title": "Core PCE Price Index m/m", "forecast": "0.3%",
         "previous": "0.2%", "affects": ["EURUSD", "XAUUSD"]},
        {"when_utc": "2026-07-30T18:00:00+00:00", "currency": "GBP",
         "title": "BOE Official Bank Rate", "forecast": "4.00%",
         "previous": "4.25%", "affects": ["GBPJPY"]},
    ],
}

_THREE_EVENT_DIGEST = {
    "date": "2026-07-30", "count": 3,
    "events": [
        {"when_utc": "2026-07-30T12:30:00+00:00", "currency": "USD",
         "title": "Core PCE Price Index m/m", "forecast": "0.3%",
         "previous": "0.2%", "affects": ["EURUSD"]},
        {"when_utc": "2026-07-30T18:00:00+00:00", "currency": "GBP",
         "title": "BOE Official Bank Rate", "forecast": "4.00%",
         "previous": "4.25%", "affects": ["GBPJPY"]},
        {"when_utc": "2026-07-30T20:00:00+00:00", "currency": "USD",
         "title": "Chicago PMI", "forecast": "45.0", "previous": "42.5",
         "affects": ["EURUSD"]},
    ],
}


class DigestRendering(unittest.TestCase):
    def test_includes_every_event_title(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("Core PCE Price Index m/m", text)
        self.assertIn("BOE Official Bank Rate", text)

    def test_shows_local_and_utc_times(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("15:30", text)   # 12:30Z at +3
        self.assertIn("12:30Z", text)

    def test_same_currency_events_are_grouped_not_interleaved(self):
        text = format_news_digest(_THREE_EVENT_DIGEST)
        first_usd = text.index("Core PCE Price Index m/m")
        second_usd = text.index("Chicago PMI")
        gbp = text.index("BOE Official Bank Rate")
        self.assertLess(first_usd, second_usd)
        self.assertLess(second_usd, gbp)  # both USD before GBP -> grouped, not interleaved

    def test_shows_forecast_and_previous(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("0.3%", text)
        self.assertIn("0.2%", text)

    def test_names_affected_pairs(self):
        self.assertIn("GBPJPY", format_news_digest(_DIGEST))

    def test_empty_day_says_so_explicitly(self):
        text = format_news_digest({"date": "2026-07-30", "count": 0, "events": []})
        self.assertTrue(text.strip())
        self.assertIn("No high-impact", text)

    def test_malformed_digest_does_not_raise(self):
        self.assertIsInstance(format_news_digest({}), str)
        self.assertIsInstance(format_news_digest({"events": [{}]}), str)


class DigestEscapesHtml(unittest.TestCase):
    def test_ampersand_and_angle_brackets_in_a_title_are_escaped(self):
        digest = {"date": "2026-07-30", "count": 1, "events": [
            {"when_utc": "2026-07-30T12:30:00+00:00", "currency": "USD",
             "title": "Import & Export Price Index <m/m>", "forecast": None,
             "previous": None, "affects": []}]}
        text = format_news_digest(digest)
        self.assertIn("&amp;", text)
        self.assertIn("&lt;m/m&gt;", text)
        self.assertNotIn("Index <m/m>", text)

    def test_alert_escapes_the_same_way(self):
        event = {"when_utc": "2026-07-30T12:30:00+00:00", "currency": "USD",
                 "title": "A & B", "forecast": None, "previous": None,
                 "affects": ["EURUSD"]}
        self.assertIn("&amp;", format_news_alert(event))


class AlertRendering(unittest.TestCase):
    def test_alert_names_event_currency_and_pairs(self):
        text = format_news_alert(_DIGEST["events"][0])
        self.assertIn("Core PCE Price Index m/m", text)
        self.assertIn("USD", text)
        self.assertIn("EURUSD", text)

    def test_alert_shows_forecast_and_previous(self):
        text = format_news_alert(_DIGEST["events"][0])
        self.assertIn("0.3%", text)
        self.assertIn("0.2%", text)

    def test_alert_on_malformed_event_does_not_raise(self):
        self.assertIsInstance(format_news_alert({}), str)


if __name__ == "__main__":
    unittest.main()
