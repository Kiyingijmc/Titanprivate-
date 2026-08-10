"""ForexFactory weekly CSV — the PRIMARY calendar source.

Times in this feed are UTC. Verified 2026-07-31 against three known releases:
FOMC 6:00pm = 18:00Z (14:00 ET), FOMC presser 6:30pm = 18:30Z, Advance GDP and
Core PCE 12:30pm = 12:30Z (08:30 ET). Were the feed US Eastern, FOMC would read
2:00pm. Treating these as local time is the defect fixed in commit ec883ae.
"""
import asyncio
import csv
import io
import random
from datetime import datetime, timezone

import requests

from ..models import CalendarEvent, make_key

_REQUIRED = ("Title", "Country", "Date", "Time", "Impact")
_IMPORTANCE = {"high": "HIGH", "medium": "MEDIUM", "moderate": "MEDIUM", "low": "LOW"}


class NewsFetchError(Exception):
    """All retries exhausted. Distinct from 'the feed returned no events'."""


_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
)


class ForexFactoryCsvSource:
    NAME = "forexfactory"
    URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv"
    # Spec 2026-08-08 §3.1. thisweek alone decays to ~0 days of lookahead by
    # Friday, so the expanded view would be empty for much of its life.
    NEXT_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.csv"

    def __init__(self, logger, url: str | None = None, tz=timezone.utc,
                 next_url: str | None = None):
        self.logger = logger
        self.url = url or self.URL
        self.next_url = next_url or self.NEXT_URL
        self.tz = tz
        self.max_retries = 3
        self.backoff_base_s = 1.0
        self.timeout_s = 15
        self.last_rows_seen = 0
        # False only after an OBSERVED next-week failure. Optimistic before any
        # attempt: absence of evidence of truncation, not a claim of success.
        self.next_week_ok = True

    def parse(self, csv_text: str) -> list[CalendarEvent]:
        """Pure: CSV text -> events. Never raises; returns [] on bad input.

        `last_rows_seen` distinguishes a legitimate "no events this week"
        answer (header only, 0 rows) from a broken feed (rows present, but
        every one failed to parse -- e.g. the date/time format changed).
        Only the caller (NewsManager) knows what to do with that distinction.
        """
        if not csv_text or not csv_text.strip():
            self.last_rows_seen = 0
            return []
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            fields = [(f or "").strip() for f in (reader.fieldnames or [])]
            if not all(col in fields for col in _REQUIRED):
                self.logger.log_event("ERROR", "NEWS", f"CSV schema mismatch: {fields}")
                self.last_rows_seen = 0
                return []
            events = []
            rows_seen = 0
            for row in reader:
                rows_seen += 1
                event = self._row_to_event(row)
                if event is not None:
                    events.append(event)
            self.last_rows_seen = rows_seen
            if rows_seen and not events:
                self.logger.log_event(
                    "ERROR", "NEWS",
                    f"Parsed 0 events from {rows_seen} rows -- the feed's date/time format "
                    f"has likely changed. Treating as a failed refresh.")
            return events
        except Exception as exc:  # malformed CSV must never kill the caller
            self.logger.log_event("ERROR", "NEWS", f"Parse error: {exc}")
            self.last_rows_seen = 0
            return []

    def _row_to_event(self, row: dict) -> CalendarEvent | None:
        try:
            stamp = f"{(row.get('Date') or '').strip()} {(row.get('Time') or '').strip()}"
            when = datetime.strptime(stamp, "%m-%d-%Y %I:%M%p").replace(tzinfo=self.tz)
        except (ValueError, TypeError):
            return None  # "All Day", "Tentative", locale drift -> skip this row only
        currency = (row.get("Country") or "").strip().upper()
        title = " ".join((row.get("Title") or "").split())
        if not currency or not title:
            return None
        when = when.astimezone(timezone.utc)
        return CalendarEvent(
            key=make_key(currency, title, when),
            when_utc=when,
            currency=currency,
            importance=_IMPORTANCE.get((row.get("Impact") or "").strip().lower(), "LOW"),
            title=title,
            forecast=_clean(row.get("Forecast")),
            previous=_clean(row.get("Previous")),
            actual=None,
            url=_clean(row.get("URL")),
            source=self.NAME,
        )

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _get(self, url: str):
        """Blocking HTTP. Isolated so tests can substitute it."""
        return requests.get(url, headers=self._headers(), timeout=self.timeout_s)

    async def _fetch_one(self, url: str, *, max_retries: int | None = None,
                          backoff_base_s: float | None = None,
                          timeout_s: int | None = None) -> list[CalendarEvent]:
        """One URL through the retry ladder. Raises if it never answered.

        The three overrides default to the instance's own (load-bearing,
        this-week) settings, so the this-week call site below is untouched.
        They exist for the next-week call in fetch(): that fetch is
        display-only enrichment but runs inline on SystemController's
        trading loop (_check_news_status, ahead of bridge ingestion and
        trade management), so a dead next-week endpoint must not spend the
        same ~48s retry budget as the load-bearing this-week fetch.
        """
        retries = self.max_retries if max_retries is None else max_retries
        backoff = self.backoff_base_s if backoff_base_s is None else backoff_base_s
        timeout = self.timeout_s if timeout_s is None else timeout_s
        last = "no attempt made"
        prev_timeout, self.timeout_s = self.timeout_s, timeout
        try:
            for attempt in range(retries):
                body = None
                try:
                    response = await asyncio.to_thread(self._get, url)
                    if response.status_code == 200:
                        body = response.content.decode("utf-8", "replace")
                    else:
                        last = f"HTTP {response.status_code}"
                except Exception as exc:
                    last = f"{type(exc).__name__}: {exc}"
                if body is not None:
                    # Deliberately outside the except above: a bug in parse()
                    # must surface as itself, never be retried and relabelled
                    # an outage.
                    return self.parse(body)
                self.logger.log_event("WARN", "NEWS", f"Attempt {attempt + 1} ({url}): {last}")
                if attempt < retries - 1 and backoff:
                    await asyncio.sleep(backoff * (2 ** attempt))
            raise NewsFetchError(last)
        finally:
            self.timeout_s = prev_timeout

    async def fetch(self) -> list[CalendarEvent]:
        """This week UNION next week.

        Three rules (spec §3.1), in priority order:
          1. this week fails            -> raise, exactly as before
          2. this week is BROKEN        -> return it alone, so NewsManager's
             (rows>0, events==0)           `if rows_seen and not events` guard fires
          3. next week fails            -> return this week, flag truncation
        """
        events = await self._fetch_one(self.url)     # rule 1: propagates
        this_rows = self.last_rows_seen
        if this_rows and not events:                 # rule 2
            # next week is NOT attempted on this path -- leave next_week_ok
            # untouched. It must keep reflecting the last cycle that actually
            # completed a next-week attempt (spec §3.2: "most recent completed
            # refresh attempt"). Forcing it True here would assert reachability
            # with zero evidence and could silently erase a real prior failure.
            return events
        try:
            # Display-only enrichment on the trading loop's critical path --
            # tighter budget than this week's load-bearing fetch (see
            # _fetch_one's docstring). No retry, no backoff: either it
            # answers in 5s or the horizon truncates.
            upcoming = await self._fetch_one(
                self.next_url, max_retries=1, backoff_base_s=0, timeout_s=5)
        except NewsFetchError as exc:                # rule 3
            self.next_week_ok = False
            self.logger.log_event(
                "WARN", "NEWS",
                f"Next-week calendar unavailable ({exc}); horizon limited to this week.")
            self.last_rows_seen = this_rows
            return events
        self.next_week_ok = True
        # last_rows_seen must describe THIS week only -- it is the input to the
        # broken-feed guard, and next week's row count would mask a drift.
        self.last_rows_seen = this_rows
        return events + upcoming


def _clean(value) -> str | None:
    text = (value or "").strip()
    return text or None
