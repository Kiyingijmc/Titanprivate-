# ==============================================================================
# FILE: tests/unit/test_export_history.py
# Tests the pure CSV formatter used by scripts/export_history.py.
#
# The MT5 EA returns history bars as [{"t": epoch_sec, "o","h","l","c"}, ...].
# bars_to_csv must turn that into a CSV that backtest_engine.py can read
# (it recognises a "datetime" column), with bars in chronological order.
# ==============================================================================

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.export_history import bars_to_csv


class BarsToCsv(unittest.TestCase):
    def test_header_and_row_format(self):
        bars = [{"t": 0, "o": 1.5, "h": 2.0, "l": 1.0, "c": 1.75}]
        csv = bars_to_csv(bars)
        lines = csv.strip().splitlines()

        self.assertEqual(lines[0], "datetime,open,high,low,close")
        # t=0 -> 1970-01-01 00:00:00 UTC (timezone-fixed so the test is deterministic)
        self.assertEqual(lines[1], "1970-01-01 00:00:00,1.5,2.0,1.0,1.75")

    def test_sorted_chronologically(self):
        bars = [
            {"t": 200, "o": 2, "h": 2, "l": 2, "c": 2},
            {"t": 100, "o": 1, "h": 1, "l": 1, "c": 1},
        ]
        lines = bars_to_csv(bars).strip().splitlines()
        # Data rows (after header) must be ascending by time.
        self.assertTrue(lines[1].startswith("1970-01-01 00:01:40"))  # t=100
        self.assertTrue(lines[2].startswith("1970-01-01 00:03:20"))  # t=200

    def test_empty_returns_header_only(self):
        self.assertEqual(bars_to_csv([]).strip(), "datetime,open,high,low,close")


if __name__ == "__main__":
    unittest.main()
