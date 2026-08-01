"""Façade composing source + store + policy, and the failure ladder.

  feed OK                      -> normal, cache refreshed
  feed down, cache fresh       -> TRADING CONTINUES, blackouts from cache
  feed down, cache stale/empty -> fail closed globally
"""
import zoneinfo
from datetime import datetime, timezone

from .policy import NewsPolicy
from .sources.forexfactory import ForexFactoryCsvSource
from .store import CalendarStore

_DEFAULT_CACHE = "data/news/calendar.json"


class NewsManager:
    def __init__(self, logger, config=None, source=None, store=None):
        cfg = (config or {}).get("news", {}) or {}
        self.logger = logger
        self.enabled = bool(cfg.get("enabled", True))
        self.refresh_interval_s = float(cfg.get("refresh_interval_min", 60)) * 60.0
        self.stale_retry_interval_s = float(cfg.get("stale_retry_interval_min", 1)) * 60.0
        self.policy = NewsPolicy(config)
        self.policy.logger = logger
        self.source = source or ForexFactoryCsvSource(
            logger, tz=self._resolve_tz(cfg.get("csv_timezone", "UTC")))
        self.store = store or CalendarStore(cfg.get("cache_path", _DEFAULT_CACHE))
        self.store.load()
        self.feed_degraded = False
        self._last_attempt = None

    def _resolve_tz(self, name):
        """Spec §2.2/§3: an operator hotfix for a feed timezone change, so a
        drift doesn't need a code deploy. A typo'd name must never crash --
        it falls back to UTC (the verified-correct default) and is logged."""
        text = str(name or "UTC").strip()
        if text.upper() == "UTC":
            return timezone.utc
        try:
            return zoneinfo.ZoneInfo(text)
        except Exception as exc:
            self.logger.log_event(
                "ERROR", "NEWS",
                f"Invalid csv_timezone '{text}' ({exc}); falling back to UTC.")
            return timezone.utc

    async def update_calendar(self) -> None:
        now = datetime.now(timezone.utc)
        # While the cache is stale the book is HALTED -- and a halted bot also
        # stops managing open positions -- so retry every minute instead of
        # every hour. (Retrying on every loop iteration, as the retired module
        # did while failed-closed, would hammer the endpoint.)
        halted, _ = self.is_globally_blocked(now)
        interval = self.stale_retry_interval_s if halted else self.refresh_interval_s
        if self._last_attempt is not None:
            if (now - self._last_attempt).total_seconds() < interval:
                return
        self._last_attempt = now
        try:
            events = await self.source.fetch()
        except Exception as exc:
            self.feed_degraded = True
            self.logger.log_event(
                "WARN", "NEWS",
                f"Refresh failed ({exc}); serving cached calendar "
                f"(age {self._age_text(now)}).")
            return
        rows_seen = getattr(self.source, "last_rows_seen", 0)
        if rows_seen and not events:
            # A valid-schema fetch that parsed to zero events despite having
            # rows is a BROKEN feed (date/time format drift), not a quiet
            # week -- do not stamp last_success or the cache would look
            # perpetually fresh while every symbol trades through every
            # red-folder event with no warning.
            self.feed_degraded = True
            self.logger.log_event(
                "ERROR", "NEWS",
                "Refresh produced no usable events from a non-empty feed; NOT marking the "
                "calendar as refreshed. If this persists the cache will age out and halt "
                "trading.")
            return
        self.store.merge(events, getattr(self.source, "NAME", "forexfactory"), now)
        try:
            self.store.save()
        except Exception as exc:  # a cache we cannot persist is still usable in RAM
            self.logger.log_event("WARN", "NEWS", f"Cache write failed: {exc}")
        self.feed_degraded = False
        self.logger.log_event("INFO", "NEWS", f"Sync success. {len(events)} events loaded.")

    # --- decisions ---------------------------------------------------------
    def is_globally_blocked(self, now=None):
        """Only ONE genuinely global condition: a cache too stale to trust."""
        if not self.enabled:
            return False, None
        now = now or datetime.now(timezone.utc)
        age = self.store.age(now)
        if self.policy.is_stale(age):
            return True, (
                f"News calendar is stale ({self._age_text(now)}) and the feed is "
                f"unreachable -- trading halted until it refreshes.")
        return False, None

    def check_symbol(self, symbol: str, now=None):
        if not self.enabled:
            return False, None
        now = now or datetime.now(timezone.utc)
        halted, reason = self.is_globally_blocked(now)
        if halted:
            return True, reason
        event = self.policy.blocking_event(self.store.events(), symbol, now)
        if event is None:
            return False, None
        return True, self.policy.reason_for(event, now)

    # --- presentation (consumed by Session 2) ------------------------------
    def digest(self, now=None) -> dict:
        """Today's red-folder events as plain data, for Telegram and the GUI.
        Never raises -- a rendering aid must not be able to break a caller."""
        try:
            now = now or datetime.now(timezone.utc)
            if now.tzinfo is None:
                # Treat a naive value as UTC, consistent with CalendarEvent.from_dict and
                # CalendarStore._as_utc. Do NOT use .astimezone() on a naive datetime -- it
                # would assume LOCAL time and shift by the host offset.
                now = now.replace(tzinfo=timezone.utc)
            now = now.astimezone(timezone.utc)
            day = now.date()
            symbols = self.policy.mapped_symbols()
            events = []
            for event in self.store.events():
                if event.importance != "HIGH" or event.when_utc.date() != day:
                    continue
                events.append({
                    "when_utc": event.when_utc.isoformat(),
                    "currency": event.currency,
                    "title": event.title,
                    "forecast": event.forecast,
                    "previous": event.previous,
                    "affects": [s for s in symbols
                                if event.currency in self.policy.currencies_for(s)],
                })
            return {"date": day.isoformat(), "count": len(events), "events": events}
        except Exception as exc:
            self.logger.log_event("WARN", "NEWS", f"Digest failed: {exc}")
            return {"date": datetime.now(timezone.utc).date().isoformat(), "count": 0, "events": [],
                    "status": "unavailable"}

    def snapshot(self, now=None) -> dict:
        try:
            now = now or datetime.now(timezone.utc)
            age = self.store.age(now)
            upcoming = [e for e in self.store.events()
                        if e.importance == "HIGH" and e.when_utc >= now]
            nxt = upcoming[0] if upcoming else None
            symbols = self.policy.mapped_symbols()
            # Evaluate the gate ONCE per symbol -- calling check_symbol twice per
            # entry (once for the test, once for the value) doubles the work and
            # can disagree with itself if `now` is not pinned.
            gates = {s: self.check_symbol(s, now) for s in symbols}
            return {
                "status": "stale" if self.policy.is_stale(age)
                          else ("degraded" if self.feed_degraded else "ok"),
                "cache_age_min": None if age is None else int(age.total_seconds() // 60),
                "sources": {getattr(self.source, "NAME", "forexfactory"):
                            "degraded" if self.feed_degraded else "ok"},
                "next": None if nxt is None else {
                    "in_min": int((nxt.when_utc - now).total_seconds() // 60),
                    "title": nxt.title, "currency": nxt.currency,
                    "importance": nxt.importance, "forecast": nxt.forecast,
                    "previous": nxt.previous,
                    "affects": [s for s in symbols
                                if nxt.currency in self.policy.currencies_for(s)],
                },
                "blocked_symbols": {
                    s: reason for s, (blocked, reason) in gates.items() if blocked
                },
            }
        except Exception as exc:  # the GUI payload must never break on news
            self.logger.log_event("WARN", "NEWS", f"Snapshot failed: {exc}")
            return {"status": "unavailable"}

    def _age_text(self, now) -> str:
        age = self.store.age(now)
        return "never refreshed" if age is None else f"{int(age.total_seconds() // 60)}m old"
