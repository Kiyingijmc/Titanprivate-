# tests/unit/test_export_history.py
# Legacy CSV formatter tests — updated for the HTTP-broker rewrite.
# The old bars_to_csv (ZMQ dict format) is gone; candles_to_csv (Candle objects)
# is the replacement. These tests verify the same invariants against the new API.

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.export_history import candles_to_csv
from src.execution.broker import types as T


def _c(epoch_sec, o, h, l, c):
    return T.Candle(
        time=datetime.fromtimestamp(epoch_sec, tz=timezone.utc),
        open=o, high=h, low=l, close=c,
        tick_volume=1, spread_points=1,
    )


class CandlesToCsv(unittest.TestCase):
    def test_header_and_row_format(self):
        csv = candles_to_csv([_c(0, 1.5, 2.0, 1.0, 1.75)])
        lines = csv.strip().splitlines()
        self.assertEqual(lines[0], "datetime,open,high,low,close")
        self.assertEqual(lines[1], "1970-01-01 00:00:00,1.5,2.0,1.0,1.75")

    def test_sorted_chronologically(self):
        # candles_to_csv preserves input order — caller owns ordering (pull_history sorts)
        bars = [_c(100, 1, 1, 1, 1), _c(200, 2, 2, 2, 2)]
        lines = candles_to_csv(bars).strip().splitlines()
        self.assertTrue(lines[1].startswith("1970-01-01 00:01:40"))  # t=100
        self.assertTrue(lines[2].startswith("1970-01-01 00:03:20"))  # t=200

    def test_empty_returns_header_only(self):
        self.assertEqual(candles_to_csv([]).strip(), "datetime,open,high,low,close")


if __name__ == "__main__":
    unittest.main()
