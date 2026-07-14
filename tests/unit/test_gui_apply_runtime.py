# tests/unit/test_gui_apply_runtime.py
import unittest
from src.core.system_controller import _apply_runtime_setting


class Grader:
    def __init__(self):
        self.min_grade = "B"
        self.enabled = True


class FakeController:
    def __init__(self):
        self.config = {"signal_grading": {"min_grade": "B", "enabled": True},
                       "risk": {"trade": {"risk_per_trade_pct": 1.0},
                                "drawdown_throttle": {"enabled": False}}}
        self.signal_grader = Grader()


class TestApplyRuntime(unittest.TestCase):
    def test_min_grade_updates_config_and_cached_attr(self):
        c = FakeController()
        _apply_runtime_setting(c, "signal_grading.min_grade", "A")
        self.assertEqual(c.config["signal_grading"]["min_grade"], "A")
        self.assertEqual(c.signal_grader.min_grade, "A")

    def test_config_dict_mutated_in_place_not_replaced(self):
        c = FakeController()
        risk_ref = c.config["risk"]                 # simulates RiskManager's held ref
        _apply_runtime_setting(c, "risk.drawdown_throttle.enabled", True)
        self.assertTrue(risk_ref["drawdown_throttle"]["enabled"])   # same object saw it

    def test_missing_cached_attr_is_tolerated(self):
        c = FakeController()
        del c.signal_grader.enabled
        _apply_runtime_setting(c, "signal_grading.enabled", False)  # no raise
        self.assertFalse(c.config["signal_grading"]["enabled"])


if __name__ == "__main__":
    unittest.main()
