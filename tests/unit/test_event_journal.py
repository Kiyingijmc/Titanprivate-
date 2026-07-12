import tempfile, unittest
from pathlib import Path
from src.core.bus import EventBus
from src.core.events import BarClosed, TickReceived, SystemStateChanged
from src.ops.event_journal import EventJournal, iter_events

class TestEventJournal(unittest.TestCase):
    def test_bus_roundtrip_golden_tape(self):
        with tempfile.TemporaryDirectory() as d:
            bus, j = EventBus(), EventJournal(d, tick_sample=1)
            j.attach(bus)
            sent = [SystemStateChanged(state="ACTIVE"),
                    BarClosed(symbol="EURUSD", tf="H1", bar_time="t1",
                              open=1.0, high=2.0, low=0.5, close=1.5),
                    TickReceived(symbol="EURUSD", bid=1.5)]
            for e in sent:
                bus.publish(e)
            tape = list(iter_events(next(Path(d).glob("events-*.jsonl"))))
            self.assertEqual(tape, sent)

    def test_tick_sampling_per_symbol(self):
        with tempfile.TemporaryDirectory() as d:
            j = EventJournal(d, tick_sample=10)
            for i in range(25):
                j.record(TickReceived(symbol="A", bid=float(i)))
            j.record(TickReceived(symbol="B", bid=99.0))  # 1st B tick writes
            tape = list(iter_events(next(Path(d).glob("events-*.jsonl"))))
            a_ticks = [e for e in tape if getattr(e, "symbol", "") == "A"]
            b_ticks = [e for e in tape if getattr(e, "symbol", "") == "B"]
            self.assertEqual(len(a_ticks), 3)   # ticks 1, 11, 21
            self.assertEqual(len(b_ticks), 1)

    def test_unknown_event_yields_raw_dict(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events-x.jsonl"
            p.write_text('{"evt": "FutureEvent", "z": 1}\n')
            out = list(iter_events(p))
            self.assertEqual(out, [{"evt": "FutureEvent", "z": 1}])

if __name__ == "__main__":
    unittest.main()
