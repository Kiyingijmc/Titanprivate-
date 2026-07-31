import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore

NOW = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)


def _event(title="Core PCE", currency="USD", importance="HIGH", hour=12,
           forecast=None, source="forexfactory"):
    when = datetime(2026, 7, 30, hour, 30, tzinfo=timezone.utc)
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title,
                         forecast=forecast, source=source)


class Persistence(unittest.TestCase):
    def test_events_survive_a_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news", "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()

            reloaded = CalendarStore(path)
            reloaded.load()
            self.assertEqual(len(reloaded.events()), 1)
            self.assertEqual(reloaded.events()[0].title, "Core PCE")

    def test_creates_missing_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deep", "nested", "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()
            self.assertTrue(os.path.isfile(path))

    def test_load_of_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CalendarStore(os.path.join(tmp, "absent.json"))
            store.load()
            self.assertEqual(store.events(), [])

    def test_load_of_corrupt_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            with open(path, "w") as fh:
                fh.write("{not json")
            store = CalendarStore(path)
            store.load()
            self.assertEqual(store.events(), [])

    def test_save_leaves_no_temp_file_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()
            self.assertEqual(sorted(os.listdir(tmp)), ["calendar.json"])

    def test_saved_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()
            with open(path) as fh:
                json.load(fh)


class Merging(unittest.TestCase):
    def test_same_event_twice_stays_one_row(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW)
        store.merge([_event()], "forexfactory", NOW)
        self.assertEqual(len(store.events()), 1)

    def test_incoming_wins_on_importance(self):
        store = CalendarStore("unused")
        store.merge([_event(importance="LOW")], "forexfactory", NOW)
        store.merge([_event(importance="HIGH")], "forexfactory", NOW)
        self.assertEqual(store.events()[0].importance, "HIGH")

    def test_incoming_blank_field_does_not_erase_stored_value(self):
        store = CalendarStore("unused")
        store.merge([_event(forecast="0.3%")], "forexfactory", NOW)
        store.merge([_event(forecast=None)], "forexfactory", NOW)
        self.assertEqual(store.events()[0].forecast, "0.3%")

    def test_events_are_sorted_by_time(self):
        store = CalendarStore("unused")
        store.merge([_event(title="Later", hour=15), _event(title="Earlier", hour=9)],
                    "forexfactory", NOW)
        self.assertEqual([e.title for e in store.events()], ["Earlier", "Later"])


class Staleness(unittest.TestCase):
    def test_age_is_none_before_any_success(self):
        self.assertIsNone(CalendarStore("unused").age(NOW))

    def test_age_measures_from_last_success(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW - timedelta(hours=5))
        self.assertEqual(store.age(NOW), timedelta(hours=5))

    def test_last_success_is_tracked_per_source(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW)
        self.assertEqual(store.last_success("forexfactory"), NOW)
        self.assertIsNone(store.last_success("mt5"))

    def test_age_uses_the_most_recent_source(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW - timedelta(hours=9))
        store.merge([_event()], "mt5", NOW - timedelta(hours=2))
        self.assertEqual(store.age(NOW), timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
