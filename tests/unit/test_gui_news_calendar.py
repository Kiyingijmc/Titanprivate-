import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key
from src.ops.web.news_view import build_calendar

NOW = datetime.now(timezone.utc)
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD"]
CURRENCIES = {"EURUSD": ["EUR", "USD"], "GBPUSD": ["GBP", "USD"],
              "USDJPY": ["USD", "JPY"], "XAUUSD": ["USD"], "USDCAD": ["USD", "CAD"]}


def _event(offset_h, currency, importance, title):
    when = NOW + timedelta(hours=offset_h)
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title,
                         forecast="1.0%", previous="0.9%", url="https://e.test")


class _Policy:
    def __init__(self, stale=False):
        self.calls = []
        self._stale = stale

    def mapped_symbols(self):
        return list(SYMBOLS)

    def currencies_for(self, symbol):
        self.calls.append(symbol)
        return CURRENCIES[symbol]

    def is_stale(self, age):
        return self._stale


class _Store:
    def __init__(self, events, raises=False):
        self._events = events
        self.raises = raises

    def events(self):
        if self.raises:
            raise RuntimeError("store exploded")
        return sorted(self._events, key=lambda e: e.when_utc)

    def age(self, now):
        return timedelta(minutes=42)


class _Manager:
    def __init__(self, events, raises=False, truncated=False, stale=False):
        self.store = _Store(events, raises)
        self.policy = _Policy(stale=stale)
        self.feed_degraded = False
        self.horizon_truncated = truncated

    def snapshot(self, now=None):
        # The real /api/state payload (src/analysis/news/manager.py
        # NewsManager.snapshot): a LEAN block, deliberately without "events" --
        # that key only exists on /api/news/calendar's build_calendar() output.
        return {
            "status": "ok",
            "cache_age_min": 42,
            "sources": {"forexfactory": "ok"},
            "next": None,
            "blocked_symbols": {},
            "today": [],
        }


class _Controller:
    def __init__(self, manager=None):
        if manager is not None:
            self.news_manager = manager


EVENTS = [
    _event(-30, "USD", "HIGH", "Past Release"),
    _event(2, "USD", "HIGH", "Non-Farm Employment Change"),
    _event(3, "EUR", "MEDIUM", "German Factory Orders m/m"),
    _event(4, "CHF", "LOW", "SECO Consumer Climate"),
    _event(5, "USD", "LOW", "Consumer Credit m/m"),
]


class CalendarShape(unittest.TestCase):
    def test_drops_past_events_and_keeps_future_ones(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        self.assertTrue(out["events"], "no events survived; later assertions would be vacuous")
        titles = [e["title"] for e in out["events"]]
        self.assertNotIn("Past Release", titles)
        self.assertEqual(len(titles), 4)

    def test_carries_every_impact_level(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        self.assertEqual({e["importance"] for e in out["events"]},
                         {"HIGH", "MEDIUM", "LOW"})

    def test_events_are_ordered_by_time(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        stamps = [e["when_utc"] for e in out["events"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_affects_lists_every_symbol_the_currency_touches(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        usd = next(e for e in out["events"] if e["title"] == "Non-Farm Employment Change")
        self.assertTrue(usd["affects"])
        self.assertEqual(sorted(usd["affects"]),
                         ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "XAUUSD"])

    def test_affects_is_empty_for_a_currency_this_book_never_trades(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        chf = next(e for e in out["events"] if e["currency"] == "CHF")
        self.assertEqual(chf["affects"], [])

    def test_affects_is_memoised_per_currency_not_per_event(self):
        # 3 distinct forward currencies x 5 symbols = 15 lookups.
        # Without the memo it is 4 events x 5 symbols = 20.
        mgr = _Manager(EVENTS)
        build_calendar(_Controller(mgr))
        self.assertEqual(len(mgr.policy.calls), 15)

    def test_reports_cache_age_and_truncation(self):
        out = build_calendar(_Controller(_Manager(EVENTS, truncated=True)))
        self.assertEqual(out["cache_age_min"], 42)
        self.assertTrue(out["horizon_truncated"])
        self.assertEqual(out["status"], "ok")

    def test_a_stale_cache_reports_stale_but_still_serves_its_events(self):
        # policy.is_stale(None) is True (no successful refresh yet -- a cold
        # start, exactly the state right after a restart). `stale` is also
        # the one condition that halts trading, so it needs its own coverage
        # on both sides of the wire. A stale cache is still SERVED -- it is
        # not the same degraded case as "unavailable" (no manager / raising
        # store), which returns no events at all.
        out = build_calendar(_Controller(_Manager(EVENTS, stale=True)))
        self.assertEqual(out["status"], "stale")
        self.assertTrue(out["events"], "a stale cache must still serve its events")


class CalendarDegrades(unittest.TestCase):
    def test_missing_news_manager_is_unavailable(self):
        out = build_calendar(_Controller())
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["events"], [])

    def test_a_raising_store_is_unavailable_not_an_exception(self):
        out = build_calendar(_Controller(_Manager(EVENTS, raises=True)))
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["events"], [])

    def test_the_unavailable_payload_is_a_fresh_dict_each_call(self):
        first = build_calendar(_Controller())
        first["events"].append("mutated")
        self.assertEqual(build_calendar(_Controller())["events"], [])


class StateEndpointIsUnaffected(unittest.TestCase):
    def test_state_snapshot_does_not_carry_the_calendar(self):
        # The whole point of a separate endpoint: /api/state is polled every
        # 2s and must not grow by 46-93 KB (spec §3.3). The fake manager's
        # snapshot() returns the REAL lean shape (status/cache_age_min/
        # sources/next/blocked_symbols/today) so this test proves the block
        # got a genuine payload rather than passing because the fake had no
        # snapshot() at all and _news_block's except-Exception degraded it
        # to {"status": "unavailable"} -- a payload "events" is trivially
        # never in.
        from src.ops.web.state_view import _news_block
        block = _news_block(_Controller(_Manager(EVENTS)))
        self.assertNotIn("events", block)
        for key in ("status", "cache_age_min", "sources", "next", "blocked_symbols", "today"):
            self.assertIn(key, block)


if __name__ == "__main__":
    unittest.main()
