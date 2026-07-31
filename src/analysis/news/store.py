"""Disk-persisted calendar cache.

One ForexFactory fetch returns the whole week, so persisting it takes the
network off the critical path: a feed outage cannot blind us to Thursday's NFP
when we already learned about it on Monday. Only a cache that has gone stale
for days is dangerous, and that is the sole condition that halts trading.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from .models import CalendarEvent


class CalendarStore:
    def __init__(self, path: str):
        self.path = path
        self._events: dict[str, CalendarEvent] = {}
        self._last_success: dict[str, datetime] = {}

    # --- reading -----------------------------------------------------------
    def events(self) -> list[CalendarEvent]:
        return sorted(self._events.values(), key=lambda e: e.when_utc)

    def last_success(self, source: str) -> datetime | None:
        return self._last_success.get(source)

    def age(self, now_utc: datetime) -> timedelta | None:
        """Time since the most recent successful refresh from ANY source."""
        if not self._last_success:
            return None
        return now_utc - max(self._last_success.values())

    # --- writing -----------------------------------------------------------
    def merge(self, events, source: str, now_utc: datetime) -> None:
        for incoming in events:
            stored = self._events.get(incoming.key)
            self._events[incoming.key] = (
                incoming if stored is None else _prefer(incoming, stored))
        self._last_success[source] = now_utc

    def save(self) -> None:
        payload = {
            "events": [e.to_dict() for e in self.events()],
            "last_success": {k: v.isoformat() for k, v in self._last_success.items()},
        }
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.path)  # atomic: readers never see a partial file
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self) -> None:
        """A missing or corrupt cache is an empty cache, never an exception."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return
        try:
            self._events = {}
            for raw in payload.get("events", []):
                event = CalendarEvent.from_dict(raw)
                self._events[event.key] = event
            self._last_success = {
                k: _as_utc(datetime.fromisoformat(v))
                for k, v in (payload.get("last_success") or {}).items()
            }
        except (TypeError, ValueError, KeyError):
            self._events = {}
            self._last_success = {}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _prefer(incoming: CalendarEvent, stored: CalendarEvent) -> CalendarEvent:
    """Incoming wins on importance and timing; blanks never erase known values."""
    return CalendarEvent(
        key=incoming.key,
        when_utc=incoming.when_utc,
        currency=incoming.currency,
        importance=incoming.importance,
        title=incoming.title,
        forecast=incoming.forecast or stored.forecast,
        previous=incoming.previous or stored.previous,
        actual=incoming.actual or stored.actual,
        url=incoming.url or stored.url,
        source=incoming.source,
    )
