import unittest
from src.core.events import (Event, EVENT_TYPES, BarClosed, TickReceived,
                             HeartbeatReceived, ExecutionReceived,
                             SpecsUpdated, SystemStateChanged)

class TestEvents(unittest.TestCase):
    def test_bar_closed_roundtrip(self):
        e = BarClosed(symbol="EURUSD", tf="H1", bar_time="2026-07-12 10:00",
                      open=1.1, high=1.2, low=1.05, close=1.15)
        d = e.to_dict()
        self.assertEqual(d["evt"], "BarClosed")
        e2 = Event.from_dict(d)
        self.assertEqual(e, e2)

    def test_all_types_registered_and_frozen(self):
        for name, cls in EVENT_TYPES.items():
            self.assertEqual(cls.name, name)
        t = TickReceived(symbol="XAUUSD", bid=2400.5)
        with self.assertRaises(Exception):
            t.bid = 1.0  # frozen

    def test_from_dict_unknown_returns_none(self):
        self.assertIsNone(Event.from_dict({"evt": "NoSuchEvent", "x": 1}))

    def test_every_concrete_event_roundtrips(self):
        samples = [
            TickReceived(symbol="A", bid=1.0),
            HeartbeatReceived(balance=100.0, equity=99.0, n_positions=1, n_orders=0),
            ExecutionReceived(status="OPENED", ticket=7, symbol="A", pnl=0.0),
            SpecsUpdated(symbol="A"),
            SystemStateChanged(state="ACTIVE"),
        ]
        for e in samples:
            self.assertEqual(Event.from_dict(e.to_dict()), e)

if __name__ == "__main__":
    unittest.main()
