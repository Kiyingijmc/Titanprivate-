"""ForexFactory weekly CSV — the PRIMARY calendar source.

Times in this feed are UTC. Verified 2026-07-31 against three known releases:
FOMC 6:00pm = 18:00Z (14:00 ET), FOMC presser 6:30pm = 18:30Z, Advance GDP and
Core PCE 12:30pm = 12:30Z (08:30 ET). Were the feed US Eastern, FOMC would read
2:00pm. Treating these as local time is the defect fixed in commit ec883ae.
"""
import csv
import io
from datetime import datetime, timezone

from ..models import CalendarEvent, make_key

_REQUIRED = ("Title", "Country", "Date", "Time", "Impact")
_IMPORTANCE = {"high": "HIGH", "medium": "MEDIUM", "moderate": "MEDIUM", "low": "LOW"}


class ForexFactoryCsvSource:
    NAME = "forexfactory"
    URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv"

    def __init__(self, logger, url: str | None = None, tz=timezone.utc):
        self.logger = logger
        self.url = url or self.URL
        self.tz = tz

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


def _clean(value) -> str | None:
    text = (value or "").strip()
    return text or None
