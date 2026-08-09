"""Read-only assembly of the /api/news/calendar response (spec 2026-08-08 §3.2).

Deliberately NOT folded into build_snapshot: /api/state is polled every 2s
(useLiveState.ts:97) and a full forward calendar is 46-93 KB of JSON that
changes at most hourly. Serving it there would ship ~2-4 GB/day out of the
live trading process for data with an hourly refresh interval.

Same defensive contract as state_view._news_block: any fault degrades to
"unavailable" rather than propagating to the caller.
"""
from datetime import datetime, timezone


def _unavailable() -> dict:
    # A fresh dict per call -- a shared module constant could be mutated by a
    # caller and would then poison every later response.
    return {"status": "unavailable", "cache_age_min": None,
            "horizon_truncated": False, "events": []}


def build_calendar(controller) -> dict:
    try:
        manager = getattr(controller, "news_manager", None)
        if manager is None:
            return _unavailable()
        now = datetime.now(timezone.utc)
        age = manager.store.age(now)
        symbols = manager.policy.mapped_symbols()

        cache: dict[str, list[str]] = {}

        def affects_for(currency: str) -> list[str]:
            """Memoised per CURRENCY. Without this it is one currencies_for()
            call per (event, symbol) pair -- ~2400 calls on a real 197-event
            cache to produce at most 10 distinct answers."""
            hit = cache.get(currency)
            if hit is None:
                hit = [s for s in symbols
                       if currency in manager.policy.currencies_for(s)]
                cache[currency] = hit
            return hit

        events = []
        for event in manager.store.events():
            if event.when_utc < now:          # forward-only; the store never prunes
                continue
            events.append({
                "when_utc": event.when_utc.isoformat(),
                "currency": event.currency,
                "importance": event.importance,
                "title": event.title,
                "forecast": event.forecast,
                "previous": event.previous,
                "url": event.url,
                "affects": list(affects_for(event.currency)),
            })
        return {
            "status": "stale" if manager.policy.is_stale(age)
                      else ("degraded" if manager.feed_degraded else "ok"),
            "cache_age_min": None if age is None else int(age.total_seconds() // 60),
            "horizon_truncated": bool(getattr(manager, "horizon_truncated", False)),
            "events": events,
        }
    except Exception:  # the GUI must never break on news
        return _unavailable()
