import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops import telegram_format as tf


class EscTests(unittest.TestCase):
    def test_escapes_html_metachars(self):
        self.assertEqual(tf.esc("a<b>&c"), "a&lt;b&gt;&amp;c")

    def test_ampersand_escaped_before_entities(self):
        # & must be escaped first so <>  don't double-encode
        self.assertEqual(tf.esc("<&>"), "&lt;&amp;&gt;")

    def test_markdown_chars_pass_through_safely(self):
        # underscores/asterisks are harmless under HTML parse_mode
        self.assertEqual(tf.esc("SB_v2*"), "SB_v2*")

    def test_coerces_non_strings(self):
        self.assertEqual(tf.esc(123), "123")


class ParseCommandTests(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(tf.parse_command("/status"), ("status", []))

    def test_strips_botname_suffix_and_case(self):
        self.assertEqual(tf.parse_command("/CloseAll@TitanBot"), ("closeall", []))

    def test_returns_args_tail(self):
        self.assertEqual(tf.parse_command("/cancel 12345"), ("cancel", ["12345"]))

    def test_non_slash_word_matches_first_token_only(self):
        # the old substring bug: "don't pause" must NOT resolve to "pause"
        self.assertEqual(tf.parse_command("don't pause"), ("don't", ["pause"]))

    def test_empty_string(self):
        self.assertEqual(tf.parse_command("   "), ("", []))


class BuilderTests(unittest.TestCase):
    def test_signal_escapes_and_marks_side(self):
        out = tf.signal("EUR<USD", "SB_v2", "BUY", 0.02, 1.1, 1.09, 1.12)
        self.assertIn("🟢", out)
        self.assertIn("EUR&lt;USD", out)          # symbol escaped
        self.assertIn("<b>", out)                  # HTML formatting present
        self.assertNotIn("EUR<USD", out)           # no raw metachar leaks

    def test_signal_sell_icon(self):
        self.assertIn("🔴", tf.signal("XAUUSD", "OTE", "SELL", 0.01, 1, 2, 3))

    def test_execution_hides_sl_price(self):
        # Phase 1: execution alert must NOT print SL/price (fed sl=0)
        out = tf.execution(555, "BTCUSD", "MARKET", 0.0, 0, "Unicorn")
        self.assertIn("#555", out)
        self.assertIn("BTCUSD", out)
        self.assertIn("Unicorn", out)
        self.assertNotIn("SL", out)
        self.assertNotIn("0.0", out)

    def test_close_pnl_emoji_thresholds(self):
        self.assertIn("🚀🔥", tf.close(1, 500.01, "X", "s"))   # > 500
        self.assertIn("💰", tf.close(1, 0.01, "X", "s"))       # > 0
        self.assertIn("📉", tf.close(1, -10, "X", "s"))        # 0..-50
        self.assertIn("🩸", tf.close(1, -50.01, "X", "s"))     # <= -50
        # boundary: exactly 0 is not > 0 -> not the 💰 branch
        self.assertIn("📉", tf.close(1, 0.0, "X", "s"))

    def test_close_escapes_symbol(self):
        self.assertIn("A&amp;B", tf.close(1, 5, "A&B", "s"))

    def test_close_escapes_strategy_field(self):
        self.assertIn("A&amp;B", tf.close(1, 5, "XAUUSD", "A&B"))

    def test_management_icon_mapping(self):
        self.assertIn("🔒", tf.management("L1 be", 7))
        self.assertIn("💸", tf.management("L2 bank", 7))
        self.assertIn("🥂", tf.management("L3 bank", 7))
        self.assertIn("👮", tf.management("Risk kill", 7))
        self.assertIn("⚙️", tf.management("something else", 7))

    def test_management_non_string_falls_to_default(self):
        # a non-string action must not crash; it falls to the default icon
        out = tf.management(None, 7)
        self.assertIn("⚙️", out)
        self.assertIn("#7", out)

    def test_help_menu_lists_confirm_and_version(self):
        out = tf.help_menu()
        self.assertIn("/confirm", out)
        self.assertIn("v14.4", out)
        self.assertIn("/closeall", out)
        self.assertIn("/panic", out)


if __name__ == "__main__":
    unittest.main()
