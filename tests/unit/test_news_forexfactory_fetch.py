import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.sources.forexfactory import ForexFactoryCsvSource, NewsFetchError


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


CSV = (
    "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
    "FOMC Statement,USD,07-29-2026,6:00pm,High,,,https://example.test/1\n"
)


class _Response:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.content = body.encode("utf-8")


def _run(coro):
    """The repo's fresh-loop idiom: py3.12 deprecates get_event_loop()."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FetchSucceeds(unittest.TestCase):
    def test_returns_parsed_events_on_first_try(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src._get = lambda: _Response(200, CSV)
        events = _run(src.fetch())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "FOMC Statement")

    def test_retries_then_succeeds(self):
        src = ForexFactoryCsvSource(_StubLogger())
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("boom")
            return _Response(200, CSV)

        src._get = flaky
        src.backoff_base_s = 0  # keep the test fast
        self.assertEqual(len(_run(src.fetch())), 1)
        self.assertEqual(calls["n"], 3)


class FetchFails(unittest.TestCase):
    def test_raises_after_all_retries_exhausted(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0

        def dead():
            raise ConnectionError("down")

        src._get = dead
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_http_error_status_raises(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0
        src._get = lambda: _Response(503)
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_empty_event_list_is_success_not_failure(self):
        """A week with no parseable rows is data, not an outage."""
        src = ForexFactoryCsvSource(_StubLogger())
        header_only = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
        src._get = lambda: _Response(200, header_only)
        self.assertEqual(_run(src.fetch()), [])


if __name__ == "__main__":
    unittest.main()
