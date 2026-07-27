"""tradebot.core.clock — Clock protocol, LiveClock, SimClock (M0-2).

See docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md §5.1/§5.5 and
pass1-audit.md F-033: comparisons inside the core use a monotonic clock;
wall-clock time is only read at the edges. ``LiveClock`` anchors
``time.monotonic_ns()`` to ``time.time_ns()`` once, at construction, so a
backward jump in system wall-clock (NTP step, operator correction) can never
make ``now_ns()`` go backward. This module does not query NTP itself — NTP
discipline is the OS's job, and offset *monitoring* is a later, unbuilt
``ops/health.py`` (Pass 6).

``SimClock`` is virtual time driven entirely by ``advance_to``/``advance_by``:
it never reads ``time.time()``/``time.monotonic()``, so it replays
deterministically under mocked or frozen wall-clock.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from typing import Callable, Protocol, runtime_checkable

CancelHandle = Callable[[], None]


@runtime_checkable
class Clock(Protocol):
    """The single time source every timer in the core schedules through."""

    def now_ns(self) -> int:
        ...

    def call_at(self, ts_ns: int, cb: Callable[[], None]) -> CancelHandle:
        ...


class LiveClock:
    """Wall time anchored to a monotonic clock once, at construction (F-033)."""

    def __init__(self) -> None:
        self._monotonic_anchor = time.monotonic_ns()
        self._wall_anchor = time.time_ns()

    def now_ns(self) -> int:
        return self._wall_anchor + (time.monotonic_ns() - self._monotonic_anchor)

    def call_at(self, ts_ns: int, cb: Callable[[], None]) -> CancelHandle:
        delay_s = max(0.0, (ts_ns - self.now_ns()) / 1_000_000_000)
        timer = threading.Timer(delay_s, cb)
        timer.daemon = True
        timer.start()
        return timer.cancel


class SimClock:
    """Virtual time, advanced explicitly; independent of the wall clock."""

    def __init__(self, start_ns: int) -> None:
        self._now_ns = start_ns
        self._counter = itertools.count()
        self._heap: list[tuple[int, int, Callable[[], None]]] = []
        self._cancelled: set[int] = set()

    def now_ns(self) -> int:
        return self._now_ns

    def call_at(self, ts_ns: int, cb: Callable[[], None]) -> CancelHandle:
        token = next(self._counter)
        heapq.heappush(self._heap, (ts_ns, token, cb))

        def cancel() -> None:
            self._cancelled.add(token)

        return cancel

    def advance_by(self, delta_ns: int) -> None:
        self.advance_to(self._now_ns + delta_ns)

    def advance_to(self, ts_ns: int) -> None:
        if ts_ns < self._now_ns:
            raise ValueError(f"SimClock cannot advance backward: {ts_ns} < {self._now_ns}")
        while self._heap and self._heap[0][0] <= ts_ns:
            due_ns, token, cb = heapq.heappop(self._heap)
            if token in self._cancelled:
                continue
            self._now_ns = due_ns
            cb()
        self._now_ns = ts_ns
