import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key


class MakeKey(unittest.TestCase):
    def test_same_event_within_five_minutes_gets_one_key(self):
        """Sources disagree by a minute or two; that must not create duplicates."""
        a = make_key("USD", "Core CPI m/m", datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc))
        b = make_key("USD", "core cpi m/m ", datetime(2026, 7, 30, 12, 32, tzinfo=timezone.utc))
        self.assertEqual(a, b)

    def test_different_events_get_different_keys(self):
        a = make_key("USD", "Core CPI m/m", datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc))
        b = make_key("EUR", "Core CPI m/m", datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc))
        self.assertNotEqual(a, b)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            make_key("USD", "Core CPI m/m", datetime(2026, 7, 30, 12, 30))


class Roundtrip(unittest.TestCase):
    def _event(self):
        when = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
        return CalendarEvent(
            key=make_key("USD", "Core PCE", when), when_utc=when, currency="USD",
            importance="HIGH", title="Core PCE", forecast="0.3%", previous="0.2%",
            actual=None, url="https://example.test/1", source="forexfactory")

    def test_to_dict_from_dict_roundtrips(self):
        original = self._event()
        self.assertEqual(CalendarEvent.from_dict(original.to_dict()), original)

    def test_roundtrip_preserves_utc_awareness(self):
        restored = CalendarEvent.from_dict(self._event().to_dict())
        self.assertEqual(restored.when_utc.tzinfo, timezone.utc)

    def test_naive_datetime_raises_valueerror(self):
        """Constructing with naive when_utc must raise ValueError."""
        with self.assertRaises(ValueError):
            CalendarEvent(
                key="test", when_utc=datetime(2026, 7, 30, 12, 30), currency="USD",
                importance="HIGH", title="Test", source="test")

    def test_non_utc_aware_datetime_normalizes_to_utc(self):
        """Constructing with non-UTC tz-aware value normalizes to UTC."""
        utc_plus_3 = timezone(timedelta(hours=3))
        when_plus3 = datetime(2026, 7, 30, 12, 30, tzinfo=utc_plus_3)
        when_utc = datetime(2026, 7, 30, 9, 30, tzinfo=timezone.utc)

        event_plus3 = CalendarEvent(
            key="test", when_utc=when_plus3, currency="USD",
            importance="HIGH", title="Test", source="test")
        event_utc = CalendarEvent(
            key="test", when_utc=when_utc, currency="USD",
            importance="HIGH", title="Test", source="test")

        self.assertEqual(event_plus3.when_utc, event_utc.when_utc)
        self.assertEqual(event_plus3.when_utc.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
