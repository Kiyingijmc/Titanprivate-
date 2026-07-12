"""Typed in-process event bus (Trading OS B0).

Sync handlers run inline in subscription order — deterministic within a
bar cycle. A misbehaving subscriber can only hurt itself: exceptions are
swallowed, counted, and circuit-broken after `max_failures` consecutive
failures. Async handlers are fire-and-forget fan-out (non-critical
consumers only).
"""
import asyncio
import inspect


class _Sub:
    __slots__ = ("handler", "name", "is_async", "delivered", "failed",
                 "consecutive", "circuit_open")

    def __init__(self, handler, name):
        self.handler = handler
        self.name = name or getattr(handler, "__name__", "anon")
        self.is_async = inspect.iscoroutinefunction(handler)
        self.delivered = 0
        self.failed = 0
        self.consecutive = 0
        self.circuit_open = False


class EventBus:
    def __init__(self, logger=None, max_failures=5):
        self._by_type = {}      # event class -> [_Sub]
        self._all = []          # [_Sub]
        self._logger = logger
        self._max_failures = max_failures
        self.no_loop_drops = 0

    def subscribe(self, event_cls, handler, name=None):
        self._by_type.setdefault(event_cls, []).append(_Sub(handler, name))

    def subscribe_all(self, handler, name=None):
        self._all.append(_Sub(handler, name))

    def publish(self, event) -> int:
        delivered = 0
        for sub in self._by_type.get(type(event), []) + self._all:
            if sub.circuit_open:
                continue
            if sub.is_async:
                try:
                    asyncio.get_running_loop().create_task(sub.handler(event))
                    sub.delivered += 1
                    delivered += 1
                except RuntimeError:
                    self.no_loop_drops += 1
                continue
            try:
                sub.handler(event)
                sub.delivered += 1
                sub.consecutive = 0
                delivered += 1
            except Exception as e:
                sub.failed += 1
                sub.consecutive += 1
                if sub.consecutive >= self._max_failures:
                    sub.circuit_open = True
                    if self._logger:
                        self._logger.log_event(
                            "ERROR", "BUS",
                            f"subscriber '{sub.name}' circuit-opened after "
                            f"{sub.consecutive} failures: {e}")
        return delivered

    def stats(self) -> dict:
        out = {}
        for subs in list(self._by_type.values()) + [self._all]:
            for s in subs:
                out[s.name] = {"delivered": s.delivered, "failed": s.failed,
                               "circuit_open": s.circuit_open}
        return out
