"""EventBus -> GUI feed: curated projection, ring-buffer backfill, per-client queues.

Registered on the bus via subscribe_all(handle, name="gui"); the bus's own
circuit-breaker (src/core/bus.py) cuts this subscriber off after repeated
failures, so a GUI bug can never wedge the publisher.
"""
import asyncio
import collections
import time

_SKIP_TOPICS = {"TickReceived"}   # tick firehose stays on the tape, not the GUI feed


def project(event):
    """Event -> feed dict {topic, ts, ...fields}; None for skipped topics."""
    d = event.to_dict()
    topic = d.pop("evt", type(event).__name__)
    if topic in _SKIP_TOPICS:
        return None
    return {"topic": topic, "ts": time.time(), **d}


class BusBridge:
    def __init__(self, ring_size: int = 200):
        self._ring = collections.deque(maxlen=ring_size)
        self._clients: list = []

    def handle(self, event) -> None:
        msg = project(event)
        if msg is None:
            return
        self._ring.append(msg)
        for q in self._clients:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # slow/dead client: drop, never block the publisher

    def attach(self, maxsize: int = 100) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._clients.append(q)
        return q

    def detach(self, q) -> None:
        if q in self._clients:
            self._clients.remove(q)

    def recent(self, limit: int = 200) -> list:
        items = list(self._ring)
        return items[-limit:]
