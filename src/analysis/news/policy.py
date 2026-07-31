"""Pure blocking policy: which red-folder events gate which symbols, and when.

No I/O and no ambient clock -- `now_utc` is always passed in. Only HIGH
importance may block; MEDIUM/LOW are carried purely for display.
"""
from datetime import timedelta

# Fiat codes we are willing to infer from a symbol name. XAU/XAG/BTC/ETH are
# deliberately absent: they are instruments, not the currency whose calendar
# moves them, so XAUUSD correctly resolves to USD alone.
_FIAT = frozenset(("USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"))


class NewsPolicy:
    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("news", {}) or {}
        self.window_pre = timedelta(minutes=int(cfg.get("window_pre_min", 60)))
        self.window_post = timedelta(minutes=int(cfg.get("window_post_min", 30)))
        self.max_cache_age = timedelta(hours=int(cfg.get("max_cache_age_hours", 48)))
        self._map = {
            str(k).upper(): [str(c).upper() for c in (v or [])]
            for k, v in (cfg.get("symbol_currencies") or {}).items()
        }
        self._warned: set[str] = set()
        self.logger = None  # optional; set by NewsManager so fallbacks are visible

    def mapped_symbols(self) -> list[str]:
        """The configured symbols, so callers need not reach into private state."""
        return list(self._map.keys())

    def currencies_for(self, symbol: str) -> list[str]:
        name = (symbol or "").upper()
        mapped = self._map.get(name)
        if mapped:
            return mapped
        inferred = [name[i:i + 3] for i in range(0, max(len(name) - 2, 0))
                    if name[i:i + 3] in _FIAT]
        deduped = list(dict.fromkeys(inferred))
        if deduped:
            return deduped
        if name not in self._warned:
            self._warned.add(name)
            if self.logger is not None:
                self.logger.log_event(
                    "WARN", "NEWS",
                    f"No currency mapping for {name}; defaulting to USD. "
                    f"Add it to news.symbol_currencies in config.yaml.")
        return ["USD"]  # never [] -- an empty list would fail OPEN

    def blocking_event(self, events, symbol: str, now_utc):
        """The first red-folder event inside `symbol`'s blackout window, else None."""
        wanted = set(self.currencies_for(symbol))
        for event in events:
            if event.importance != "HIGH" or event.currency not in wanted:
                continue
            if -self.window_post <= (event.when_utc - now_utc) <= self.window_pre:
                return event
        return None

    def reason_for(self, event, now_utc) -> str:
        minutes = (event.when_utc - now_utc).total_seconds() / 60.0
        if minutes > 0:
            return f"{event.currency} {event.title} in {int(minutes)}m"
        return f"{event.currency} {event.title} active ({int(-minutes)}m ago)"

    def is_stale(self, age) -> bool:
        """No successful refresh ever, or older than the ceiling."""
        return age is None or age > self.max_cache_age
