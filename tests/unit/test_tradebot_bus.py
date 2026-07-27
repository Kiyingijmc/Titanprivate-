"""Unit tests for tradebot.core.bus (M0-5).

Flat under tests/unit/ (not tests/unit/tradebot/) for the same reason as
test_tradebot_events.py: a test package named `tradebot` would shadow the
real top-level `tradebot` package during `unittest discover -s tests/unit`.
"""

import unittest

from tradebot.core.bus import EventBus
from tradebot.core.events import Envelope


def _env(schema: str, payload: dict | None = None) -> Envelope:
    return Envelope(
        schema=schema,
        schema_version=1,
        ts_event=1,
        ts_ingest=2,
        actor="test",
        payload=payload or {},
    )


class TestSchemaKeyedDispatch(unittest.TestCase):
    def test_typed_delivery_in_order(self):
        bus, seen = EventBus(), []
        bus.subscribe("a.schema", lambda e: seen.append(("first", e.payload)))
        bus.subscribe("a.schema", lambda e: seen.append(("second", e.payload)))
        bus.subscribe("b.schema", lambda e: seen.append(("third", 0)))
        n = bus.publish(_env("a.schema", {"x": 1}))
        self.assertEqual(n, 2)
        self.assertEqual(seen, [("first", {"x": 1}), ("second", {"x": 1})])

    def test_different_schemas_reach_only_their_own_subscribers(self):
        bus, seen_a, seen_b = EventBus(), [], []
        bus.subscribe("a.schema", lambda e: seen_a.append(e.schema))
        bus.subscribe("b.schema", lambda e: seen_b.append(e.schema))
        bus.publish(_env("a.schema"))
        bus.publish(_env("b.schema"))
        self.assertEqual(seen_a, ["a.schema"])
        self.assertEqual(seen_b, ["b.schema"])

    def test_subscribe_all_receives_everything(self):
        bus, seen = EventBus(), []
        bus.subscribe_all(lambda e: seen.append(e.schema))
        bus.publish(_env("a.schema"))
        bus.publish(_env("b.schema"))
        self.assertEqual(seen, ["a.schema", "b.schema"])


class TestNormalTierCircuitBreaking(unittest.TestCase):
    def test_throwing_subscriber_is_isolated_and_circuit_broken(self):
        bus, ok = EventBus(max_failures=3), []

        def bad(e):
            raise RuntimeError("boom")

        bus.subscribe("a.schema", bad, name="bad")
        bus.subscribe("a.schema", lambda e: ok.append(1), name="good")
        for _ in range(5):
            bus.publish(_env("a.schema"))  # must not raise
        self.assertEqual(len(ok), 5)  # good never starved
        st = bus.stats()["bad"]
        self.assertTrue(st["circuit_open"])
        self.assertEqual(st["failed"], 3)  # skipped after 3 failures
        self.assertEqual(st["tier"], "normal")

    def test_success_resets_failure_count(self):
        bus = EventBus(max_failures=3)
        flaky_state = {"n": 0}

        def flaky(e):
            flaky_state["n"] += 1
            if flaky_state["n"] % 2 == 1:
                raise RuntimeError("odd call fails")

        bus.subscribe("a.schema", flaky, name="flaky")
        for _ in range(10):
            bus.publish(_env("a.schema"))
        self.assertFalse(bus.stats()["flaky"]["circuit_open"])


class TestCriticalTierHaltOnException(unittest.TestCase):
    def test_critical_exception_is_reraised_and_halts_remaining_subscribers(self):
        bus, seen = EventBus(), []

        def critical_bad(e):
            raise RuntimeError("critical boom")

        bus.subscribe("a.schema", critical_bad, name="critical_bad", tier="critical")
        bus.subscribe("a.schema", lambda e: seen.append(1), name="after")

        with self.assertRaises(RuntimeError):
            bus.publish(_env("a.schema"))

        self.assertEqual(seen, [])  # subscriber after the critical one never ran

    def test_critical_tier_never_circuit_breaks(self):
        bus = EventBus(max_failures=1)

        def critical_bad(e):
            raise RuntimeError("boom")

        bus.subscribe("a.schema", critical_bad, name="critical_bad", tier="critical")

        for _ in range(5):
            with self.assertRaises(RuntimeError):
                bus.publish(_env("a.schema"))

        st = bus.stats()["critical_bad"]
        self.assertFalse(st["circuit_open"])
        self.assertEqual(st["failed"], 5)
        self.assertEqual(st["tier"], "critical")


class TestSubscribeTierValidation(unittest.TestCase):
    def test_unknown_tier_rejected(self):
        bus = EventBus()
        with self.assertRaises(ValueError):
            bus.subscribe("a.schema", lambda e: None, tier="urgent")


if __name__ == "__main__":
    unittest.main()
