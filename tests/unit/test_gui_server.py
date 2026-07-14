import unittest
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
from fastapi.testclient import TestClient
from src.core.events import GuiActionExecuted
from src.ops.web import auth
from src.ops.web.server import create_app
from src.ops.web.settings import SettingsStore
from src.ops.web.bus_bridge import BusBridge

DEFAULTS = {"signal_grading": {"enabled": True, "min_grade": "B"},
            "risk": {"drawdown_throttle": {"enabled": False, "trigger_dd_pct": 2.0,
                                           "factor": 0.5}},
            "connection": {"zeromq": {"push_port": 32768}}}
AUTH = {"Authorization": "Bearer sekret"}


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


def _make(tmp):
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    os.environ.pop("TITAN_GUI_READONLY", None)
    auth.THROTTLE.reset()
    ctrl = FakeController()
    store = SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")
    bridge = BusBridge()
    app = create_app(ctrl, store, bridge)
    return TestClient(app), ctrl, bridge


class TestAuthAndState(unittest.TestCase):
    def test_state_requires_auth_and_has_v15_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, _ = _make(d)
            self.assertEqual(client.get("/api/state").status_code, 401)
            body = client.get("/api/state", headers=AUTH).json()
            for key in ("health", "account", "positions", "arbiter", "registry"):
                self.assertIn(key, body)

    def test_events_backfill(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, bridge = _make(d)
            from src.core.events import SystemStateChanged
            bridge.handle(SystemStateChanged(state="PAUSED"))
            rows = client.get("/api/events?limit=10", headers=AUTH).json()["events"]
            self.assertEqual(rows[-1]["topic"], "SystemStateChanged")


class TestMutationsAndAudit(unittest.TestCase):
    def test_command_pause_publishes_audit(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.post("/api/command", json={"command": "pause"}, headers=AUTH)
            self.assertEqual(r.json()["result"], "PAUSED")
            audits = [e for e in ctrl.published if isinstance(e, GuiActionExecuted)]
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].action, "command:pause")
            self.assertEqual(audits[0].outcome, "ok")

    def test_needs_confirm_does_not_publish_audit(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.post("/api/command", json={"command": "panic"}, headers=AUTH)
            self.assertEqual(r.json()["status"], "needs_confirm")
            self.assertEqual(ctrl.published, [])

    def test_patch_safe_setting_applies_live_and_audits(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.patch("/api/settings", headers=AUTH,
                             json={"key": "risk.drawdown_throttle.enabled", "value": True})
            self.assertEqual(r.json()["applied"], "live")
            self.assertIn(("risk.drawdown_throttle.enabled", True), ctrl.applied)
            self.assertEqual(len(ctrl.published), 1)

    def test_patch_invalid_422_no_apply_no_audit(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.patch("/api/settings", headers=AUTH,
                             json={"key": "signal_grading.min_grade", "value": "Z"})
            self.assertEqual(r.status_code, 422)
            self.assertEqual(ctrl.applied, [])
            self.assertEqual(ctrl.published, [])

    def test_patch_restart_key_saved_not_applied(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.patch("/api/settings", headers=AUTH,
                             json={"key": "connection.zeromq.push_port", "value": 40000})
            self.assertTrue(r.json()["restart_required"])
            self.assertEqual(ctrl.applied, [])

    def test_registry_promote_flow(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.post("/api/registry/gyro/promote", json={}, headers=AUTH)
            self.assertEqual(r.json()["status"], "needs_confirm")
            r2 = client.post("/api/registry/gyro/promote",
                             json={"confirm": "gyro"}, headers=AUTH)
            self.assertEqual(r2.json()["result"], "enabled gyro research=True")


class TestReadOnlyMode(unittest.TestCase):
    def test_mutating_routes_403_reads_stay_200(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            os.environ["TITAN_GUI_READONLY"] = "1"
            try:
                self.assertEqual(client.post("/api/command", json={"command": "pause"},
                                             headers=AUTH).status_code, 403)
                self.assertEqual(client.patch("/api/settings", headers=AUTH,
                                              json={"key": "signal_grading.min_grade",
                                                    "value": "A"}).status_code, 403)
                self.assertEqual(client.post("/api/registry/x/disable", json={},
                                             headers=AUTH).status_code, 403)
                self.assertEqual(client.get("/api/state", headers=AUTH).status_code, 200)
                self.assertEqual(ctrl.published, [])
            finally:
                os.environ.pop("TITAN_GUI_READONLY", None)


class TestWebSocketAuth(unittest.TestCase):
    def test_first_frame_token_then_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, _ = _make(d)
            with client.websocket_connect("/ws") as ws:
                ws.send_text("sekret")
                first = ws.receive_json()
                self.assertEqual(first["type"], "state")

    def test_wrong_first_frame_closes_1008(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, _ = _make(d)
            with client.websocket_connect("/ws") as ws:
                ws.send_text("wrong")
                with self.assertRaises(Exception):   # closed by server
                    ws.receive_json()


if __name__ == "__main__":
    unittest.main()
