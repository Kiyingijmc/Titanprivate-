import unittest
import os
import tempfile
from pathlib import Path
from datetime import datetime
from fastapi.testclient import TestClient
from src.ops.web import auth
from src.ops.web.server import create_app
from src.ops.web.settings import SettingsStore
from src.ops.web.bus_bridge import BusBridge

DEFAULTS = {"signal_grading": {"enabled": True, "min_grade": "B"},
            "risk": {"drawdown_throttle": {"enabled": False, "trigger_dd_pct": 2.0,
                                           "factor": 0.5}},
            "connection": {"zeromq": {"push_port": 32768}}}


class FakeRisk:
    current_equity = 10000.0
    starting_balance = 10000.0

    @staticmethod
    def throttle_factor():
        return 1.0


class FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 0, "approved": 0, "blocked_by": {}}


class FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "silver_bullet", "version": "14.4.2", "family": "smc",
                 "tf": "H1", "status": "live", "state": "ACTIVE", "priority": 50}]


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now()
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.arbiter = FakeArbiter()
        self.registry = FakeRegistry()
        self.config = {"risk": {"drawdown_throttle": {"enabled": False}}}
        self.current_open_positions = []
        self.state_manager = type("S", (), {"get_order": staticmethod(lambda t: None)})()
        self.applied = []
        self.published = []

    def set_system_pause(self, p):
        self.is_manual_pause = p
        return "PAUSED" if p else "ACTIVE"

    def enable_strategy(self, sid, allow_research=False):
        return f"enabled {sid} research={allow_research}"

    def disable_strategy(self, sid):
        return f"disabled {sid}"

    def apply_runtime_setting(self, key, value):
        self.applied.append((key, value))

    def _publish(self, event):
        self.published.append(event)


def _make(tmp, dist_dir=None):
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    os.environ.pop("TITAN_GUI_READONLY", None)
    auth.THROTTLE.reset()
    ctrl = FakeController()
    store = SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")
    bridge = BusBridge()
    app = create_app(ctrl, store, bridge, dist_dir=dist_dir)
    return TestClient(app), ctrl, bridge


class TestStaticMount(unittest.TestCase):
    def test_spa_served_and_api_still_guarded(self):
        with tempfile.TemporaryDirectory() as d:
            dist = Path(d) / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<!doctype html><title>Titan</title>")
            client, _, _ = _make(d, dist_dir=dist)
            r = client.get("/")
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/html", r.headers["content-type"])
            # api still 401 without a token
            self.assertEqual(client.get("/api/state").status_code, 401)

    def test_spa_fallback_for_unknown_client_route(self):
        with tempfile.TemporaryDirectory() as d:
            dist = Path(d) / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<!doctype html><title>Titan</title>")
            client, _, _ = _make(d, dist_dir=dist)
            r = client.get("/strategies/foo")
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/html", r.headers["content-type"])

    def test_missing_dist_dir_is_headless_noop(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "no-such-dist"
            client, _, _ = _make(d, dist_dir=missing)
            # still builds and API still works with auth
            r = client.get("/api/state", headers={"Authorization": "Bearer sekret"})
            self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
