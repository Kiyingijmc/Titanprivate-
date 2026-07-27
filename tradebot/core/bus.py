"""tradebot.core.bus — schema-keyed sync event bus (M0-5).

Adapts ``src/core/bus.py``'s ``EventBus`` (Trading OS B0) onto
``tradebot.core.events.Envelope``: every tradebot event is an ``Envelope``
instance differentiated by its ``.schema`` string, not a distinct Python
class, so dispatch keys on ``envelope.schema`` instead of ``type(event)``.

Sync handlers run inline in subscription order — deterministic within a
call to ``publish``. Two subscriber tiers:

- ``"normal"`` (the src/core/bus.py behavior, verbatim): an exception is
  swallowed and counted; the subscriber's circuit opens after
  ``max_failures`` consecutive failures and is skipped thereafter.
  ``publish`` never raises because of a normal-tier subscriber.
- ``"critical"``: never circuit-broken and never swallowed — an exception
  is logged at CRITICAL and re-raised out of ``publish``, halting delivery
  to any remaining subscribers for that call (pass3-systems.md's
  "halt+alert" semantics).

There is no async fire-and-forget path here (unlike src/core/bus.py):
nothing under ``tradebot/`` has an event loop yet.
"""

from __future__ import annotations

import logging
from typing import Callable

from tradebot.core.events import Envelope

logger = logging.getLogger(__name__)

_TIERS = ("normal", "critical")

Handler = Callable[[Envelope], None]


class _Sub:
    __slots__ = ("handler", "name", "tier", "delivered", "failed",
                 "consecutive", "circuit_open")

    def __init__(self, handler: Handler, name: str, tier: str):
        self.handler = handler
        self.name = name
        self.tier = tier
        self.delivered = 0
        self.failed = 0
        self.consecutive = 0
        self.circuit_open = False


class EventBus:
    def __init__(self, max_failures: int = 5) -> None:
        self._by_schema: dict[str, list[_Sub]] = {}
        self._all: list[_Sub] = []
        self._max_failures = max_failures
        self._name_counts: dict[str, int] = {}

    def _unique_name(self, handler: Handler, name: str | None) -> str:
        """Resolve the subscriber name and deduplicate: 'x', 'x#2', 'x#3', ..."""
        resolved = name or getattr(handler, "__name__", "anon")
        count = self._name_counts.get(resolved, 0) + 1
        self._name_counts[resolved] = count
        return resolved if count == 1 else f"{resolved}#{count}"

    def subscribe(self, schema: str, handler: Handler, name: str | None = None,
                  tier: str = "normal") -> None:
        if tier not in _TIERS:
            raise ValueError(f"unknown subscriber tier {tier!r}")
        self._by_schema.setdefault(schema, []).append(
            _Sub(handler, self._unique_name(handler, name), tier))

    def subscribe_all(self, handler: Handler, name: str | None = None) -> None:
        self._all.append(_Sub(handler, self._unique_name(handler, name), "normal"))

    def publish(self, envelope: Envelope) -> int:
        delivered = 0
        for sub in self._by_schema.get(envelope.schema, []) + self._all:
            if sub.circuit_open:
                continue
            try:
                sub.handler(envelope)
                sub.delivered += 1
                sub.consecutive = 0
                delivered += 1
            except Exception as e:
                sub.failed += 1
                if sub.tier == "critical":
                    logger.critical(
                        "critical subscriber '%s' raised on schema '%s': %s",
                        sub.name, envelope.schema, e)
                    raise
                sub.consecutive += 1
                if sub.consecutive >= self._max_failures:
                    sub.circuit_open = True
                    logger.error(
                        "subscriber '%s' circuit-opened after %d failures: %s",
                        sub.name, sub.consecutive, e)
        return delivered

    def stats(self) -> dict:
        out = {}
        for subs in list(self._by_schema.values()) + [self._all]:
            for s in subs:
                out[s.name] = {"delivered": s.delivered, "failed": s.failed,
                               "circuit_open": s.circuit_open, "tier": s.tier}
        return out
