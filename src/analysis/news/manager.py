"""Façade composing source + store + policy, and the failure ladder.

  feed OK                      -> normal, cache refreshed
  feed down, cache fresh       -> TRADING CONTINUES, blackouts from cache
  feed down, cache stale/empty -> fail closed globally
"""
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
        self.policy = NewsPolicy(config)
        self.policy.logger = logger
        self.source = source or ForexFactoryCsvSource(logger)
        self.store = store or CalendarStore(cfg.get("cache_path", _DEFAULT_CACHE))
        self.store.load()
        self.feed_degraded = False
        self._last_attempt = None

    async def update_calendar(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_attempt is not None:
            if (now - self._last_attempt).total_seconds() < self.refresh_interval_s:
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
