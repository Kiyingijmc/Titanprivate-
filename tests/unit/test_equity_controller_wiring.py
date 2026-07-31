# tests/unit/test_equity_controller_wiring.py
"""The recorder is constructed, fed by HEARTBEAT, and pruned on the recon timer."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController
from src.ops.equity_recorder import EquityRecorder


class _NullLogger:
    def log_event(self, *a, **k):
        pass


def _run(coro):
    """Drive a coroutine on a fresh loop.

    Matches tests/unit/test_controller_routing.py:72. Do NOT use
    asyncio.get_event_loop() — this venv is Python 3.12, where calling it with
    no running loop is deprecated and slated to raise.
    """
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _bare_controller(recorder):
    """Controller shell without __init__ — the fixture pattern this repo already uses."""
    c = object.__new__(SystemController)
    c.equity_recorder = recorder
    c.logger = _NullLogger()
    c.risk_manager = type("RM", (), {"update_account_info": lambda *a: None,
                                     "track_equity": lambda *a: None})()
    c.current_open_positions = []
    c.current_pending_orders = []
    c._publish = lambda evt: None
    c.state_manager = type("SM", (), {"exists": lambda *a: True})()
    return c


class HeartbeatFeedsRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # No cadence key: the sample cadence is a structural constant now.
        self.rec = EquityRecorder(os.path.join(self.tmp, "core.db"),
                                  config={"enabled": True})

    def test_heartbeat_records_balance_and_equity(self):
        c = _bare_controller(self.rec)
        msg = {"type": "HEARTBEAT", "bal": 1221.59, "eq": 1327.0, "pos": [], "orders": []}
        _run(c._process_incoming_data(msg))
        self.assertEqual(len(self.rec.buffer), 1)
        self.assertEqual(self.rec.buffer[0].equity, 1327.0)
        self.assertEqual(self.rec.buffer[0].balance, 1221.59)

    def test_zero_equity_heartbeat_records_nothing(self):
        c = _bare_controller(self.rec)
        msg = {"type": "HEARTBEAT", "bal": 1221.59, "eq": 0.0, "pos": [], "orders": []}
        _run(c._process_incoming_data(msg))
        self.assertEqual(self.rec.buffer, [])


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ConfigBlock(unittest.TestCase):
    def test_config_yaml_declares_ops_equity(self):
        import yaml
        # Resolved from THIS FILE, not the cwd: the suite is run from the repo
        # root today, but a worktree/CI runner invoking it from anywhere else
        # would have made this open() fail on a path, not on a contract.
        with open(os.path.join(_REPO_ROOT, "config", "config.yaml")) as fh:
            cfg = yaml.safe_load(fh)
        eq = cfg["ops"]["equity"]
        self.assertTrue(eq["enabled"])
        self.assertEqual(eq["fine_retention_h"], 48)
        self.assertEqual(eq["flush_interval_s"], 60)
        self.assertEqual(eq["max_buffer_samples"], 600)

    def test_config_yaml_does_not_expose_the_structural_constants(self):
        """The sample cadence and the coarse bucket size are baked into every
        row already on disk. Exposing them as knobs let an operator run a week
        at 600 and switch back to 300, leaving the DB permanently holding
        600-aligned rows the view buckets at 300 — spec §3's "a query bucket
        never straddles a fraction of a stored row", violated silently and with
        no migration. They live in equity_recorder as constants instead."""
        import yaml
        with open(os.path.join(_REPO_ROOT, "config", "config.yaml")) as fh:
            eq = yaml.safe_load(fh)["ops"]["equity"]
        self.assertNotIn("fine_cadence_s", eq)
        self.assertNotIn("coarse_bucket_s", eq)


class FakeControllerSeries(unittest.TestCase):
    """The devserver must drive ALL eleven ranges offline (spec §8). Seeding
    only equity_coarse left every range <= 12h with zero points and made the
    phase-2 range selector undrivable with MT5 down."""

    @classmethod
    def setUpClass(cls):
        from src.ops.web.fake_controller import FakeController
        cls.controller = FakeController()

    def test_fake_controller_serves_a_populated_coarse_series(self):
        from src.ops.web.equity_view import equity_series
        out = equity_series(self.controller.equity_recorder.conn, "1d")
        self.assertEqual(out["tier"], "coarse")
        self.assertGreater(len([p for p in out["points"] if p]), 10)

    def test_fake_controller_serves_a_populated_FINE_series(self):
        from src.ops.web.equity_view import equity_series
        for name in ("15m", "30m", "1h", "4h", "12h"):
            out = equity_series(self.controller.equity_recorder.conn, name)
            self.assertEqual(out["tier"], "fine", name)
            self.assertGreater(len([p for p in out["points"] if p]), 10, name)

    def test_fake_controller_reports_gaps_and_coverage(self):
        from src.ops.web.equity_view import equity_series
        out = equity_series(self.controller.equity_recorder.conn, "12h")
        self.assertTrue(out["coverage"]["gaps"], "no gap to drive gap rendering")
        self.assertIsNotNone(out["coverage"]["first_sample_ts"])

    def test_fake_recorder_exposes_the_real_health_surface(self):
        from src.ops.web.state_view import _equity_recorder_health
        health = _equity_recorder_health(self.controller)
        for key in ("enabled", "connected", "buffered", "last_flush_ts",
                    "dropped_stale", "flush_errors"):
            self.assertIn(key, health)
        self.assertTrue(health["enabled"])

    def test_fake_recorder_is_readable_through_the_routes_own_connection(self):
        """The route opens its own read-only connection BY PATH; an in-memory
        fake could never exercise that."""
        from src.ops.web.equity_view import equity_series, read_connection
        conn, owned = read_connection(self.controller.equity_recorder)
        self.assertTrue(owned)
        try:
            out = equity_series(conn, "15m")
            self.assertGreater(len([p for p in out["points"] if p]), 10)
        finally:
            conn.close()


class StateSnapshotEquityHealthWiring(unittest.TestCase):
    """Guard against a typo in state_view's health->equity_recorder wiring.

    Task 6's review noted the brief's test list checks _equity_recorder_health
    directly but nothing exercises the actual /api/state wiring — a wrong key
    or a dropped call there would ship silently. This builds a REAL snapshot
    via build_snapshot(controller) against a controller carrying a live
    recorder, and asserts the four counter keys are present.
    """

    def test_api_state_snapshot_carries_equity_recorder_counters(self):
        from src.ops.web.state_view import build_snapshot

        tmp = tempfile.mkdtemp()
        rec = EquityRecorder(os.path.join(tmp, "core.db"), config={"enabled": True})

        c = object.__new__(SystemController)
        c.equity_recorder = rec
        c.last_heartbeat_time = datetime.now()
        c.is_manual_pause = False
        c.last_error = None
        c.risk_manager = type("RM", (), {
            "starting_balance": 10000.0,
            "current_equity": 10000.0,
            "throttle_factor": staticmethod(lambda: 1.0),
        })()
        c.config = {"risk": {"drawdown_throttle": {"enabled": False}}}
        c.current_open_positions = []
        c.arbiter = type("A", (), {
            "stats": staticmethod(lambda: {"submitted": 0, "approved": 0, "blocked_by": {}}),
        })()
        c.registry = type("Reg", (), {"report": staticmethod(lambda: [])})()
        c.state_manager = type("SM", (), {"get_order": staticmethod(lambda t: None)})()
        c.market_prices = {}

        snapshot = build_snapshot(c)

        health = snapshot["health"]["equity_recorder"]
        self.assertIsNotNone(health)
        for key in ("dropped_stale", "dropped_invalid", "dropped_overflow", "flush_errors"):
            self.assertIn(key, health)


if __name__ == "__main__":
    unittest.main()
