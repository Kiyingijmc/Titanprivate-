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

    def __init__(self, logger, url: str | None = None, tz=timezone.utc):
        self.logger = logger
        self.url = url or self.URL
        self.tz = tz
        self.max_retries = 3
        self.backoff_base_s = 1.0
        self.timeout_s = 15

    def parse(self, csv_text: str) -> list[CalendarEvent]:
        """Pure: CSV text -> events. Never raises; returns [] on bad input."""
        if not csv_text or not csv_text.strip():
            return []
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            fields = [(f or "").strip() for f in (reader.fieldnames or [])]
            if not all(col in fields for col in _REQUIRED):
                self.logger.log_event("ERROR", "NEWS", f"CSV schema mismatch: {fields}")
                return []
            events = []
            for row in reader:
                event = self._row_to_event(row)
                if event is not None:
                    events.append(event)
            return events
        except Exception as exc:  # malformed CSV must never kill the caller
            self.logger.log_event("ERROR", "NEWS", f"Parse error: {exc}")
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

    def _get(self):
        """Blocking HTTP. Isolated so tests can substitute it."""
        return requests.get(self.url, headers=self._headers(), timeout=self.timeout_s)

    async def fetch(self) -> list[CalendarEvent]:
        """Returns parsed events, or raises NewsFetchError if the feed never answered."""
        last = "no attempt made"
        for attempt in range(self.max_retries):
            body = None
            try:
                response = await asyncio.to_thread(self._get)
                if response.status_code == 200:
                    body = response.content.decode("utf-8", "replace")
                else:
                    last = f"HTTP {response.status_code}"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            if body is not None:
                # Deliberately outside the except above: a bug in parse() must
                # surface as itself, never be retried and relabelled an outage.
                return self.parse(body)
            self.logger.log_event("WARN", "NEWS", f"Attempt {attempt + 1}: {last}")
            if attempt < self.max_retries - 1 and self.backoff_base_s:
                await asyncio.sleep(self.backoff_base_s * (2 ** attempt))
        raise NewsFetchError(last)


def _clean(value) -> str | None:
    text = (value or "").strip()
    return text or None
