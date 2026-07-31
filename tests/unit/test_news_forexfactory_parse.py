import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.sources.forexfactory import ForexFactoryCsvSource


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


CSV = (
    "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
    "FOMC Statement,USD,07-29-2026,6:00pm,High,,,https://example.test/1\n"
    "Core PCE Price Index m/m,USD,07-30-2026,12:30pm,High,0.3%,0.2%,https://example.test/2\n"
    "German ifo Business Climate,EUR,07-27-2026,8:00am,Low,86.1,85.6,https://example.test/3\n"
    "BOE Rate Decision,GBP,07-30-2026,11:00am,High,4.00%,4.25%,https://example.test/4\n"
    "Bank Holiday,JPY,07-28-2026,All Day,Holiday,,,https://example.test/5\n"
)


def _parse():
    return ForexFactoryCsvSource(_StubLogger()).parse(CSV)


class ParsesTimesAsUtc(unittest.TestCase):
    def test_six_pm_becomes_1800z(self):
        fomc = next(e for e in _parse() if e.title == "FOMC Statement")
        self.assertEqual(fomc.when_utc, datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc))


class KeepsEverythingThePolicyMightNeed(unittest.TestCase):
    def test_keeps_non_usd_currencies(self):
        self.assertIn("GBP", {e.currency for e in _parse()})

    def test_keeps_non_high_impact_rows(self):
        self.assertIn("LOW", {e.importance for e in _parse()})

    def test_captures_forecast_previous_and_url(self):
        pce = next(e for e in _parse() if e.title.startswith("Core PCE"))
        self.assertEqual(pce.forecast, "0.3%")
        self.assertEqual(pce.previous, "0.2%")
        self.assertEqual(pce.url, "https://example.test/2")

    def test_blank_forecast_becomes_none_not_empty_string(self):
        fomc = next(e for e in _parse() if e.title == "FOMC Statement")
        self.assertIsNone(fomc.forecast)


class HandlesMalformedInput(unittest.TestCase):
    def test_unparseable_time_row_is_skipped_not_fatal(self):
        """'All Day' has no clock time; drop that row, keep the rest."""
        titles = {e.title for e in _parse()}
        self.assertNotIn("Bank Holiday", titles)
        self.assertIn("FOMC Statement", titles)

    def test_wrong_schema_returns_empty_list(self):
        bad = ForexFactoryCsvSource(_StubLogger()).parse("Foo,Bar\n1,2\n")
        self.assertEqual(bad, [])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(ForexFactoryCsvSource(_StubLogger()).parse(""), [])


class RowsPresentButUnparseableIsABrokenFeedNotAnEmptyWeek(unittest.TestCase):
    """A header-only CSV is a legitimate 'no events this week' answer. Rows
    that are present but every one fails strptime means the feed's date/time
    format changed underneath us -- that must be distinguishable so the
    caller can treat it as a failed refresh, not a fresh empty cache."""

    def test_identical_header_with_iso_dates_and_24h_clock_parses_to_zero_events(self):
        src = ForexFactoryCsvSource(_StubLogger())
        iso_csv = (
            "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
            "FOMC Statement,USD,2026-07-29,18:00,High,,,https://example.test/1\n"
            "Core PCE Price Index m/m,USD,2026-07-30,12:30,High,0.3%,0.2%,"
            "https://example.test/2\n"
        )
        events = src.parse(iso_csv)
        self.assertEqual(events, [])

    def test_identical_header_with_iso_dates_records_rows_were_seen(self):
        src = ForexFactoryCsvSource(_StubLogger())
        iso_csv = (
            "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
            "FOMC Statement,USD,2026-07-29,18:00,High,,,https://example.test/1\n"
        )
        src.parse(iso_csv)
        self.assertGreater(src.last_rows_seen, 0)

    def test_header_only_csv_is_still_a_legitimate_empty_result(self):
        src = ForexFactoryCsvSource(_StubLogger())
        header_only = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
        events = src.parse(header_only)
        self.assertEqual(events, [])
        self.assertEqual(src.last_rows_seen, 0)


if __name__ == "__main__":
    unittest.main()
