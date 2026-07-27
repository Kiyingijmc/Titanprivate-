"""Unit tests for tradebot.core.clock (M0-2).

Covers the Clock protocol, LiveClock (monotonic-anchored wall time, F-033),
and SimClock (deterministic virtual time) from docs/trading-bot-brainstorm/
brainstorm-v2/pass3-systems.md §5.1/§5.5 and pass1-audit.md F-033.

NOTE ON LOCATION: this file lives directly under tests/unit/ (flat, like every
other test module here) rather than under tests/unit/tradebot/. A test package
named `tradebot` would shadow the real top-level `tradebot` package during
`unittest discover -s tests/unit`, so `import tradebot.core.clock` would
resolve to the test package (which has no `core`) and every case here would
error out. Keeping the file flat lets the import resolve to the real package
via the repo root on sys.path. (Same precedent as tests/unit/test_config_schema.py,
S001/M0-1.)
"""

import unittest
from unittest import mock

from tradebot.core.clock import Clock, LiveClock, SimClock


class TestClockProtocol(unittest.TestCase):
    def test_live_and_sim_clock_satisfy_the_protocol(self):
        self.assertIsInstance(LiveClock(), Clock)
        self.assertIsInstance(SimClock(0), Clock)


class TestLiveClockMonotonicInsulation(unittest.TestCase):
    def test_now_ns_survives_a_backward_wall_clock_jump(self):
        clock = LiveClock()
        t1 = clock.now_ns()

        # LiveClock anchors monotonic-to-wall once at construction (F-033);
        # a wall-clock step backward (NTP correction, operator edit) after
        # that must never be re-read, so now_ns() stays non-decreasing.
        with mock.patch("time.time_ns", return_value=0), mock.patch("time.time", return_value=0.0):
            t2 = clock.now_ns()

        self.assertGreaterEqual(t2, t1)

    def test_now_ns_is_wall_clock_shaped_at_construction(self):
        real_wall_ns = 1_700_000_000_000_000_000
        with mock.patch("time.time_ns", return_value=real_wall_ns), mock.patch(
            "time.monotonic_ns", return_value=0
        ):
            clock = LiveClock()

        with mock.patch("time.monotonic_ns", return_value=5_000_000):
            self.assertEqual(clock.now_ns(), real_wall_ns + 5_000_000)


class TestSimClockDeterministicOrdering(unittest.TestCase):
    @staticmethod
    def _build_schedule(log):
        clock = SimClock(start_ns=0)
        # Registered deliberately out of chronological order.
        clock.call_at(300, lambda: log.append(300))
        clock.call_at(100, lambda: log.append(100))
        clock.call_at(200, lambda: log.append(200))
        clock.call_at(100, lambda: log.append("100b"))  # tie -> insertion order
        return clock

    def test_fires_in_ts_then_insertion_order(self):
        log = []
        clock = self._build_schedule(log)
        clock.advance_to(1_000)
        self.assertEqual(log, [100, "100b", 200, 300])

    def test_reproducible_across_two_fresh_instances(self):
        log_a: list = []
        log_b: list = []
        clock_a = self._build_schedule(log_a)
        clock_b = self._build_schedule(log_b)

        clock_a.advance_to(1_000)
        clock_b.advance_to(1_000)

        self.assertEqual(log_a, log_b)

    def test_never_touches_the_wall_clock(self):
        with mock.patch("time.time", side_effect=AssertionError("touched wall clock")), mock.patch(
            "time.monotonic", side_effect=AssertionError("touched monotonic clock")
        ), mock.patch("time.time_ns", side_effect=AssertionError("touched wall clock (ns)")), mock.patch(
            "time.monotonic_ns", side_effect=AssertionError("touched monotonic clock (ns)")
        ):
            log: list = []
            clock = self._build_schedule(log)
            clock.advance_to(1_000)

        self.assertEqual(log, [100, "100b", 200, 300])

    def test_now_ns_reflects_virtual_time(self):
        clock = SimClock(start_ns=1_000)
        self.assertEqual(clock.now_ns(), 1_000)
        clock.advance_to(5_000)
        self.assertEqual(clock.now_ns(), 5_000)

    def test_cancelled_callback_does_not_fire(self):
        log: list = []
        clock = SimClock(start_ns=0)
        cancel = clock.call_at(100, lambda: log.append("should-not-fire"))
        clock.call_at(200, lambda: log.append("fires"))
        cancel()
        clock.advance_to(1_000)
        self.assertEqual(log, ["fires"])

    def test_advance_backward_raises(self):
        clock = SimClock(start_ns=1_000)
        with self.assertRaises(ValueError):
            clock.advance_to(500)


if __name__ == "__main__":
    unittest.main()
