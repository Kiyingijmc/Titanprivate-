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


HEADER_ONLY = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"


def _only_this_week(body, status=200):
    """Answer the this-week URL with `body`; next-week gets an empty calendar.

    Keeps these tests about the retry ladder rather than the union -- a stub
    that returned the same CSV for both URLs would double every event count.
    """
    def _get(url):
        if url == ForexFactoryCsvSource.URL:
            return _Response(status, body)
        return _Response(200, HEADER_ONLY)
    return _get


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
        src._get = _only_this_week(CSV)
        events = _run(src.fetch())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "FOMC Statement")

    def test_retries_then_succeeds(self):
        src = ForexFactoryCsvSource(_StubLogger())
        calls = {"n": 0}

        def flaky(url):
            if url != ForexFactoryCsvSource.URL:
                return _Response(200, HEADER_ONLY)
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

        def dead(url):
            if url != ForexFactoryCsvSource.URL:
                return _Response(200, HEADER_ONLY)
            raise ConnectionError("down")

        src._get = dead
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_http_error_status_raises(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0
        src._get = _only_this_week("", status=503)
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_empty_event_list_is_success_not_failure(self):
        """A week with no parseable rows is data, not an outage."""
        src = ForexFactoryCsvSource(_StubLogger())
        header_only = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
        src._get = _only_this_week(header_only)
        self.assertEqual(_run(src.fetch()), [])


class NextWeekBudgetIsTighter(unittest.TestCase):
    def test_a_dead_next_week_is_not_retried_and_this_week_is_unaffected(self):
        """Next week is display-only enrichment, but fetch() runs inline on
        SystemController's trading loop ahead of bridge ingestion and trade
        management (_check_news_status). A dead next-week endpoint must not
        spend the same retry ladder as the load-bearing this-week fetch."""
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0  # keep this-week's own ladder instant if hit
        calls = {ForexFactoryCsvSource.URL: 0, ForexFactoryCsvSource.NEXT_URL: 0}

        def router(url):
            calls[url] = calls.get(url, 0) + 1
            if url == ForexFactoryCsvSource.URL:
                return _Response(200, CSV)
            raise ConnectionError("next week dead")

        src._get = router
        events = _run(src.fetch())

        self.assertEqual(len(events), 1)  # this week alone survives
        self.assertEqual(calls[ForexFactoryCsvSource.URL], 1,
                          "this week succeeded first try -- its own ladder is untouched")
        self.assertEqual(calls[ForexFactoryCsvSource.NEXT_URL], 1,
                          "next week must not retry on its tighter budget")
        self.assertFalse(src.next_week_ok)


class ParseBugsAreNotOutages(unittest.TestCase):
    def test_parse_error_propagates_and_is_not_retried(self):
        """A programming error in parse() must not masquerade as a feed outage."""
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0
        calls = {"n": 0}

        def counted(url):
            if url != ForexFactoryCsvSource.URL:
                return _Response(200, HEADER_ONLY)
            calls["n"] += 1
            return _Response(200, CSV)

        src._get = counted

        def boom(_text):
            raise TypeError("bug in parse")

        src.parse = boom
        with self.assertRaises(TypeError):
            _run(src.fetch())
        self.assertEqual(calls["n"], 1)  # not retried


if __name__ == "__main__":
    unittest.main()
