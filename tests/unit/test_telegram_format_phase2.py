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


class FormatDurationTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(tf.format_duration(45), "45s")

    def test_minutes(self):
        self.assertEqual(tf.format_duration(125), "2m")

    def test_hours(self):
        self.assertEqual(tf.format_duration(3 * 3600 + 15 * 60), "3h 15m")

    def test_days(self):
        self.assertEqual(tf.format_duration(2 * 86400 + 5 * 3600), "2d 5h")

    def test_zero_and_negative(self):
        self.assertEqual(tf.format_duration(0), "0s")
        self.assertEqual(tf.format_duration(-10), "0s")


class CloseEnrichTests(unittest.TestCase):
    def test_hold_and_r_shown(self):
        out = tf.close(7, 250.0, "XAUUSD", "OTE", hold_seconds=3 * 3600 + 15 * 60, r_multiple=1.8)
        self.assertIn("3h 15m", out)
        self.assertIn("+1.8R", out)
        self.assertIn("$250.00", out)

    def test_negative_r_sign(self):
        self.assertIn("-1.0R", tf.close(1, -100.0, "X", "S", hold_seconds=60, r_multiple=-1.0))

    def test_hold_omitted_when_none(self):
        out = tf.close(1, 5.0, "X", "S", hold_seconds=None, r_multiple=None)
        self.assertNotIn("Hold", out)
        self.assertNotIn("R:", out)

    def test_backward_compatible_defaults(self):
        # still callable with the Phase-1 arg list
        out = tf.close(1, 5.0, "X", "S")
        self.assertIn("#1", out)
        self.assertIn("$5.00", out)


class ManagementEnrichTests(unittest.TestCase):
    def test_ratchet_shows_new_sl_and_locked(self):
        out = tf.management("Ratchet L2", 9, new_sl=1995.0, locked_money=42.5)
        self.assertIn("💸", out)              # L2 icon preserved
        self.assertIn("1995.0", out)          # new SL
        self.assertIn("+42.50", out)          # signed locked-in

    def test_negative_locked_sign(self):
        self.assertIn("-10.00", tf.management("Ratchet L1", 1, new_sl=1.0, locked_money=-10.0))

    def test_risk_guard_without_sl(self):
        out = tf.management("Risk Guard", 3)
        self.assertIn("👮", out)
        self.assertNotIn("SL", out)           # no SL line when new_sl is None

    def test_partial_builder(self):
        out = tf.partial("Bank 30%", 9, 0.03)
        self.assertIn("Bank 30%", out)
        self.assertIn("#9", out)
        self.assertIn("0.03", out)


if __name__ == "__main__":
    unittest.main()
