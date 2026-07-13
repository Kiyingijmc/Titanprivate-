# tests/unit/test_gui_settings.py
import unittest
import tempfile
from pathlib import Path
import yaml
from src.ops.web.settings import SettingsStore

DEFAULTS = {
    "signal_grading": {"enabled": True, "min_grade": "B"},
    "risk": {"trade": {"risk_per_trade_pct": 1.0},
             "account": {"max_daily_drawdown_pct": 3.0, "max_global_exposure_pct": 6.0},
             "drawdown_throttle": {"enabled": False, "trigger_dd_pct": 2.0, "factor": 0.5}},
    "trade_management": {"runner": {"enabled": False, "tighten_on_giveback": False,
                                    "giveback_frac": 0.75, "tight_trail_frac": 0.10}},
    "arbiter": {"max_total_positions": 6},
    "connection": {"zeromq": {"push_port": 32768}},
}


def _store(tmp):
    return SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")


class TestSafeSubset(unittest.TestCase):
    def test_whitelisted_keys_are_safe(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            for key in ("signal_grading.min_grade", "risk.trade.risk_per_trade_pct",
                        "risk.drawdown_throttle.enabled",
                        "risk.drawdown_throttle.trigger_dd_pct",
                        "risk.drawdown_throttle.factor",
                        "trade_management.runner.tight_trail_frac"):
                self.assertTrue(s.is_safe(key), key)

    def test_restart_tier_keys_are_not_safe(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            for key in ("connection.zeromq.push_port", "arbiter.max_total_positions",
                        "strategies.silver_bullet.enabled"):   # registry owns lifecycle
                self.assertFalse(s.is_safe(key), key)


class TestValidate(unittest.TestCase):
    def test_min_grade_enum(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("signal_grading.min_grade", "A"))
            self.assertIsNotNone(s.validate("signal_grading.min_grade", "Z"))

    def test_throttle_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("risk.drawdown_throttle.trigger_dd_pct", 2.5))
            self.assertIsNotNone(s.validate("risk.drawdown_throttle.trigger_dd_pct", 0))
            self.assertIsNone(s.validate("risk.drawdown_throttle.factor", 0.5))
            self.assertIsNotNone(s.validate("risk.drawdown_throttle.factor", 1.5))
            self.assertIsNotNone(s.validate("risk.drawdown_throttle.enabled", "yes"))

    def test_risk_pct_bounds_and_bools(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("risk.trade.risk_per_trade_pct", 0.5))
            self.assertIsNotNone(s.validate("risk.trade.risk_per_trade_pct", 0))
            self.assertIsNotNone(s.validate("risk.trade.risk_per_trade_pct", 999))
            self.assertIsNotNone(s.validate("signal_grading.enabled", "yes"))


class TestSetAndDescribe(unittest.TestCase):
    def test_set_safe_key_applies_live_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            res = s.set("risk.drawdown_throttle.enabled", True)
            self.assertEqual(res["applied"], "live")
            self.assertFalse(res["restart_required"])
            written = yaml.safe_load((Path(d) / "overrides.yaml").read_text())
            self.assertTrue(written["risk"]["drawdown_throttle"]["enabled"])

    def test_set_restart_key_flags_restart(self):
        with tempfile.TemporaryDirectory() as d:
            res = _store(d).set("connection.zeromq.push_port", 40000)
            self.assertEqual(res["applied"], "on_restart")
            self.assertTrue(res["restart_required"])

    def test_set_invalid_raises_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            with self.assertRaises(ValueError):
                s.set("signal_grading.min_grade", "Z")
            self.assertFalse((Path(d) / "overrides.yaml").exists())

    def test_describe_tags_source_and_tier(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            s.set("signal_grading.min_grade", "A")
            rows = {r["key"]: r for r in s.describe()}
            self.assertEqual(rows["signal_grading.min_grade"]["source"], "override")
            self.assertEqual(rows["signal_grading.min_grade"]["tier"], "live")
            self.assertEqual(rows["signal_grading.enabled"]["source"], "default")
            self.assertEqual(rows["arbiter.max_total_positions"]["tier"], "restart")


if __name__ == "__main__":
    unittest.main()
