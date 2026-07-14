import unittest
from src.ops.web.registry_view import execute_registry_action, registry_report


class FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "gyroscope", "version": "0.1.0", "family": "kalman",
                 "tf": "H1", "status": "research", "state": "LOADED", "priority": 50}]


class FakeController:
    def __init__(self):
        self.calls = []
        self.registry = FakeRegistry()

    def enable_strategy(self, sid, allow_research=False):
        self.calls.append(("enable", sid, allow_research))
        return f"enabled {sid}" if allow_research else f"refused research {sid}"

    def disable_strategy(self, sid):
        self.calls.append(("disable", sid))
        return f"disabled {sid}"


class TestRegistryActions(unittest.TestCase):
    def test_report_passthrough(self):
        rows = registry_report(FakeController())
        self.assertEqual(rows[0]["id"], "gyroscope")
        self.assertEqual(rows[0]["family"], "kalman")   # full detail, untrimmed

    def test_enable_never_passes_allow_research(self):
        c = FakeController()
        res = execute_registry_action(c, "gyroscope", "enable", {})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(c.calls, [("enable", "gyroscope", False)])

    def test_disable(self):
        c = FakeController()
        res = execute_registry_action(c, "silver_bullet", "disable", {})
        self.assertEqual(res["result"], "disabled silver_bullet")

    def test_promote_without_typed_confirm_never_calls_controller(self):
        c = FakeController()
        for payload in ({}, {"confirm": True}, {"confirm": "wrong_id"}):
            res = execute_registry_action(c, "gyroscope", "promote", payload)
            self.assertEqual(res["status"], "needs_confirm", payload)
        self.assertEqual(c.calls, [])

    def test_promote_with_typed_id_uses_allow_research(self):
        c = FakeController()
        res = execute_registry_action(c, "gyroscope", "promote", {"confirm": "gyroscope"})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(c.calls, [("enable", "gyroscope", True)])

    def test_unknown_action(self):
        res = execute_registry_action(FakeController(), "x", "explode", {})
        self.assertEqual(res["status"], "error")


if __name__ == "__main__":
    unittest.main()
