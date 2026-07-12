"""Event journal — the golden tape (Trading OS B0).

Subscribes to ALL bus events and appends them as JSONL. This file is the
replay source for the kernel v15.0 regression harness and the forensic
record for incidents. Ticks are sampled per symbol to bound volume.
"""
import json
from src.core.events import Event, TickReceived
from src.ops.jsonlog import _Writer


class EventJournal:
    def __init__(self, dir_path, tick_sample=50):
        self._w = _Writer(dir_path, "events")
        self._tick_sample = max(1, int(tick_sample))
        self._tick_counts = {}
        self.written = 0

    @property
    def drops(self):
        return self._w.drops

    def attach(self, bus):
        bus.subscribe_all(self.record, name="event_journal")

    def record(self, event):
        if isinstance(event, TickReceived):
            n = self._tick_counts.get(event.symbol, 0)
            self._tick_counts[event.symbol] = n + 1
            if n % self._tick_sample != 0:
                return
        self._w.write(event.to_dict())
        self.written += 1

    def close(self):
        self._w.close()


def iter_events(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            evt = Event.from_dict(d)
            yield evt if evt is not None else d
