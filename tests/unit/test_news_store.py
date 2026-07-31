import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news import store as store_module
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


class SourceAwareMergePrecedence(unittest.TestCase):
    """Spec Sec 2.3: ForexFactory is authoritative. It always wins on
    importance/when_utc/title/currency/source; a lower-priority source may
    only fill in fields ForexFactory left blank."""

    def _ff_event(self, importance="HIGH", forecast=None):
        when = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
        return CalendarEvent(key=make_key("USD", "Core PCE", when), when_utc=when,
                             currency="USD", importance=importance, title="Core PCE",
                             forecast=forecast, source="forexfactory")

    def test_forexfactory_stored_event_keeps_its_importance_over_another_source(self):
        store = CalendarStore("unused")
        ff = self._ff_event(importance="HIGH")
        store.merge([ff], "forexfactory", NOW)

        other = CalendarEvent(key=ff.key, when_utc=ff.when_utc, currency=ff.currency,
                              importance="LOW", title=ff.title, source="mt5")
        store.merge([other], "mt5", NOW)

        self.assertEqual(store.events()[0].importance, "HIGH")
        self.assertEqual(store.events()[0].source, "forexfactory")

    def test_forexfactory_stored_event_keeps_its_when_utc_over_another_source(self):
        store = CalendarStore("unused")
        ff = self._ff_event()
        store.merge([ff], "forexfactory", NOW)

        drifted = CalendarEvent(key=ff.key, when_utc=ff.when_utc + timedelta(minutes=3),
                                currency=ff.currency, importance=ff.importance,
                                title=ff.title, source="mt5")
        store.merge([drifted], "mt5", NOW)

        self.assertEqual(store.events()[0].when_utc, ff.when_utc)

    def test_other_source_fills_a_field_forexfactory_left_blank(self):
        store = CalendarStore("unused")
        ff = self._ff_event(forecast=None)
        store.merge([ff], "forexfactory", NOW)

        other = CalendarEvent(key=ff.key, when_utc=ff.when_utc, currency=ff.currency,
                              importance=ff.importance, title=ff.title,
                              forecast="0.4%", source="mt5")
        store.merge([other], "mt5", NOW)

        self.assertEqual(store.events()[0].forecast, "0.4%")
        # Filling a blank field must not hand authority to the other source.
        self.assertEqual(store.events()[0].source, "forexfactory")

    def test_other_source_cannot_overwrite_a_field_forexfactory_already_set(self):
        store = CalendarStore("unused")
        ff = self._ff_event(forecast="0.3%")
        store.merge([ff], "forexfactory", NOW)

        other = CalendarEvent(key=ff.key, when_utc=ff.when_utc, currency=ff.currency,
                              importance=ff.importance, title=ff.title,
                              forecast="0.4%", source="mt5")
        store.merge([other], "mt5", NOW)

        self.assertEqual(store.events()[0].forecast, "0.3%")

    def test_non_forexfactory_stored_event_is_overwritten_normally(self):
        """The authority rule is specific to a STORED ForexFactory row; two
        non-FF sources (or FF arriving after another source) behave exactly
        as before -- incoming wins."""
        store = CalendarStore("unused")
        first = CalendarEvent(key=make_key("USD", "Core PCE", NOW), when_utc=NOW,
                              currency="USD", importance="LOW", title="Core PCE",
                              source="mt5")
        store.merge([first], "mt5", NOW)

        second = CalendarEvent(key=first.key, when_utc=NOW, currency="USD",
                               importance="HIGH", title="Core PCE", source="mt5")
        store.merge([second], "mt5", NOW)

        self.assertEqual(store.events()[0].importance, "HIGH")

    def test_forexfactory_incoming_over_non_forexfactory_stored_still_wins_as_incoming(self):
        """FF arriving AFTER another source is the normal (non-authority)
        path: incoming (FF) simply wins, same as any other incoming update."""
        store = CalendarStore("unused")
        stored_mt5 = CalendarEvent(key=make_key("USD", "Core PCE", NOW), when_utc=NOW,
                                   currency="USD", importance="LOW", title="Core PCE",
                                   source="mt5")
        store.merge([stored_mt5], "mt5", NOW)

        incoming_ff = CalendarEvent(key=stored_mt5.key, when_utc=NOW, currency="USD",
                                    importance="HIGH", title="Core PCE",
                                    source="forexfactory")
        store.merge([incoming_ff], "forexfactory", NOW)

        self.assertEqual(store.events()[0].importance, "HIGH")
        self.assertEqual(store.events()[0].source, "forexfactory")


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


class LoadIsTotal(unittest.TestCase):
    """A cache file must never be able to crash startup, whatever it contains."""

    def _load_from(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            with open(path, "w") as fh:
                fh.write(text)
            store = CalendarStore(path)
            store.load()          # must not raise
            return store

    def test_non_dict_root_is_treated_as_empty(self):
        for text in ("[]", "[1,2,3]", "5", '"hello"', "null"):
            with self.subTest(text=text):
                self.assertEqual(self._load_from(text).events(), [])

    def test_non_dict_last_success_is_treated_as_empty(self):
        store = self._load_from('{"events": [], "last_success": [1,2,3]}')
        self.assertEqual(store.events(), [])
        self.assertIsNone(store.age(NOW))

    def test_events_not_a_list_is_treated_as_empty(self):
        store = self._load_from('{"events": "abc", "last_success": {}}')
        self.assertEqual(store.events(), [])


class AtomicWriteSurvivesACrash(unittest.TestCase):
    """Spec Sec 7: save() writes to a temp file and os.replace()s it into
    place so a crash mid-write can never corrupt or truncate the file a
    reader might load next. Prove it by making json.dump blow up mid-save
    on a store whose file already holds good data."""

    def test_original_file_intact_and_no_tmp_file_left_when_dump_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            good_store = CalendarStore(path)
            good_store.merge([_event()], "forexfactory", NOW)
            good_store.save()
            with open(path, encoding="utf-8") as fh:
                original_bytes = fh.read()

            crashing_store = CalendarStore(path)
            crashing_store.merge([_event(title="A Different Event")], "forexfactory", NOW)

            with mock.patch.object(store_module.json, "dump",
                                   side_effect=RuntimeError("disk exploded mid-write")):
                with self.assertRaises(RuntimeError):
                    crashing_store.save()

            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original_bytes)
            json.loads(original_bytes)  # sanity: the surviving file is valid JSON
            self.assertEqual(sorted(os.listdir(tmp)), ["calendar.json"])  # no *.tmp left


if __name__ == "__main__":
    unittest.main()
