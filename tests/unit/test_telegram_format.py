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


if __name__ == "__main__":
    unittest.main()
