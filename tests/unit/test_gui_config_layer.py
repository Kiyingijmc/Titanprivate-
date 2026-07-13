import unittest
import tempfile
from pathlib import Path
from src.ops.web.config_layer import deep_merge, load_layered_config


class TestDeepMerge(unittest.TestCase):
    def test_nested_override_wins_and_defaults_survive(self):
        base = {"risk": {"trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0}},
                "signal_grading": {"min_grade": "B"}}
        override = {"risk": {"trade": {"risk_per_trade_pct": 0.5}}}
        merged = deep_merge(base, override)
        self.assertEqual(merged["risk"]["trade"]["risk_per_trade_pct"], 0.5)
        self.assertEqual(merged["risk"]["trade"]["hard_max_lots"], 5.0)
        self.assertEqual(merged["signal_grading"]["min_grade"], "B")
        self.assertEqual(base["risk"]["trade"]["risk_per_trade_pct"], 1.0)  # base unmutated

    def test_list_value_is_replaced_not_merged(self):
        merged = deep_merge({"pairs": ["A", "B"]}, {"pairs": ["C"]})
        self.assertEqual(merged["pairs"], ["C"])


class TestLoadLayered(unittest.TestCase):
    def test_missing_overrides_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            defaults = Path(d) / "config.yaml"
            defaults.write_text("signal_grading:\n  min_grade: B\n")
            cfg = load_layered_config(defaults, Path(d) / "overrides.yaml")
            self.assertEqual(cfg["signal_grading"]["min_grade"], "B")

    def test_overrides_applied_on_top(self):
        with tempfile.TemporaryDirectory() as d:
            defaults = Path(d) / "config.yaml"
            defaults.write_text("signal_grading:\n  min_grade: B\n  enabled: true\n")
            overrides = Path(d) / "overrides.yaml"
            overrides.write_text("signal_grading:\n  min_grade: A\n")
            cfg = load_layered_config(defaults, overrides)
            self.assertEqual(cfg["signal_grading"]["min_grade"], "A")
            self.assertTrue(cfg["signal_grading"]["enabled"])


if __name__ == "__main__":
    unittest.main()
