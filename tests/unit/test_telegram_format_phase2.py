import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops import telegram_format as tf


class ExecutionEnrichTests(unittest.TestCase):
    def test_renders_all_fields(self):
        out = tf.execution(555, "XAUUSD", "MARKET", 2000.0, 1990.0, 2025.0, 0.10, "A+", 100.0, "SilverBullet")
        self.assertIn("#555", out)
        self.assertIn("XAUUSD", out)
        self.assertIn("2000.0", out)   # entry
        self.assertIn("1990.0", out)   # sl
        self.assertIn("2025.0", out)   # tp
        self.assertIn("A+", out)       # grade
        self.assertIn("SilverBullet", out)
        self.assertIn("$100.00", out)  # risk-$

    def test_rr_ratio(self):
        # risk=10, reward=25 -> 1:2.5
        out = tf.execution(1, "X", "MARKET", 2000.0, 1990.0, 2025.0, 0.1, "A", 100.0, "S")
        self.assertIn("1:2.5", out)

    def test_rr_dashes_when_sl_or_tp_zero(self):
        self.assertIn("—", tf.execution(1, "X", "MARKET", 2000.0, 0, 2025.0, 0.1, "A", 0.0, "S"))

    def test_risk_dashes_when_zero(self):
        # money=0 means specs unknown -> "—", not "$0.00"
        out = tf.execution(1, "X", "MARKET", 2000.0, 1990.0, 2025.0, 0.1, "A", 0.0, "S")
        self.assertNotIn("$0.00", out)

    def test_escapes_dynamic_fields(self):
        out = tf.execution(1, "A&B", "MARKET", 1, 0, 0, 0.1, "A", 0.0, "S<x>")
        self.assertIn("A&amp;B", out)
        self.assertIn("S&lt;x&gt;", out)


if __name__ == "__main__":
    unittest.main()
