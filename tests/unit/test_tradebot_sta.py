"""Unit tests for tradebot.core.sta (M0-5).

Flat under tests/unit/ for the same shadowing reason as
test_tradebot_events.py / test_tradebot_bus.py.
"""

import asyncio
import unittest

from tradebot.core.bus import EventBus
from tradebot.core.events import Envelope
from tradebot.core.sta import SignalTransitionActor


def _env(index: int) -> Envelope:
    return Envelope(
        schema="test.sta_transition",
        schema_version=1,
        ts_event=index,
        ts_ingest=index,
        actor="sta",
        payload={"index": index},
    )


class TestFifoOrderingAndSingleConsumer(unittest.TestCase):
    def test_single_consumer_serializes_and_preserves_fifo_order(self):
        async def scenario():
            bus = EventBus()
            actor = SignalTransitionActor(bus)
            order_log = []
            first_started = asyncio.Event()
            release_first = asyncio.Event()

            async def apply0():
                order_log.append(0)
                first_started.set()
                await release_first.wait()
                return _env(0)

            def apply_factory(i):
                def _apply():
                    order_log.append(i)
                    return _env(i)
                return _apply

            t0 = asyncio.create_task(actor.submit(lambda: True, apply0))
            t1 = asyncio.create_task(actor.submit(lambda: True, apply_factory(1)))
            t2 = asyncio.create_task(actor.submit(lambda: True, apply_factory(2)))

            await first_started.wait()
            # Request 0 is mid-processing (blocked on release_first) - give the
            # loop a beat and confirm 1 and 2 are still queued, untouched.
            await asyncio.sleep(0)
            self.assertEqual(order_log, [0])

            release_first.set()
            results = await asyncio.gather(t0, t1, t2)
            await actor.aclose()
            return order_log, results

        order_log, results = asyncio.run(scenario())
        self.assertEqual(order_log, [0, 1, 2])
        self.assertTrue(all(r.accepted for r in results))
        self.assertEqual([r.envelope.payload["index"] for r in results], [0, 1, 2])


class TestGuardAndApplyOutcomes(unittest.TestCase):
    def test_guard_fail_resolves_to_race_loser_without_raising_and_apply_never_runs(self):
        async def scenario():
            bus = EventBus()
            actor = SignalTransitionActor(bus)

            def apply_must_not_run():
                raise AssertionError("apply() must not be called when guard fails")

            outcome = await actor.submit(lambda: False, apply_must_not_run)
            await actor.aclose()
            return outcome

        outcome = asyncio.run(scenario())
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.reason, "race_loser")
        self.assertIsNone(outcome.envelope)

    def test_guard_pass_publishes_through_injected_bus_and_subscriber_observes_it(self):
        async def scenario():
            bus = EventBus()
            received = []
            bus.subscribe("test.sta_transition", lambda env: received.append(env))
            actor = SignalTransitionActor(bus)

            outcome = await actor.submit(lambda: True, lambda: _env(7))
            await actor.aclose()
            return outcome, received

        outcome, received = asyncio.run(scenario())
        self.assertTrue(outcome.accepted)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload, {"index": 7})
        self.assertIs(outcome.envelope, received[0])


if __name__ == "__main__":
    unittest.main()
