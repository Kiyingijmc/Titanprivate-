import unittest
from src.core.bus import EventBus
from src.core.events import TickReceived, BarClosed

class TestEventBus(unittest.TestCase):
    def test_typed_delivery_in_order(self):
        bus, seen = EventBus(), []
        bus.subscribe(TickReceived, lambda e: seen.append(("a", e.bid)))
        bus.subscribe(TickReceived, lambda e: seen.append(("b", e.bid)))
        bus.subscribe(BarClosed, lambda e: seen.append(("c", 0)))
        n = bus.publish(TickReceived(symbol="X", bid=1.5))
        self.assertEqual(n, 2)
        self.assertEqual(seen, [("a", 1.5), ("b", 1.5)])

    def test_subscribe_all_receives_everything(self):
        bus, seen = EventBus(), []
        bus.subscribe_all(lambda e: seen.append(type(e).name))
        bus.publish(TickReceived(symbol="X", bid=1.0))
        bus.publish(BarClosed(symbol="X", tf="H1"))
        self.assertEqual(seen, ["TickReceived", "BarClosed"])

    def test_throwing_subscriber_is_isolated_and_circuit_broken(self):
        bus, ok = EventBus(max_failures=3), []
        def bad(e): raise RuntimeError("boom")
        bus.subscribe(TickReceived, bad, name="bad")
        bus.subscribe(TickReceived, lambda e: ok.append(1), name="good")
        for _ in range(5):
            bus.publish(TickReceived(symbol="X", bid=1.0))  # must not raise
        self.assertEqual(len(ok), 5)               # good never starved
        st = bus.stats()["bad"]
        self.assertTrue(st["circuit_open"])
        self.assertEqual(st["failed"], 3)          # skipped after 3 failures

    def test_success_resets_failure_count(self):
        bus = EventBus(max_failures=3)
        flaky_state = {"n": 0}
        def flaky(e):
            flaky_state["n"] += 1
            if flaky_state["n"] % 2 == 1:
                raise RuntimeError("odd call fails")
        bus.subscribe(TickReceived, flaky, name="flaky")
        for _ in range(10):
            bus.publish(TickReceived(symbol="X", bid=1.0))
        self.assertFalse(bus.stats()["flaky"]["circuit_open"])

if __name__ == "__main__":
    unittest.main()
