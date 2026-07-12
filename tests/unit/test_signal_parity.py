# tests/unit/test_signal_parity.py
# Plan 03 / Task 1: locks the PRE-refactor signal stream. capture_stream drives
# the REAL SystemController._run_strategies over test_data.csv H1 bars; the
# committed golden fixture is the frozen truth. Any refactor of the signal
# path (FeatureBus extraction etc.) must keep this byte-identical.
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.capture_parity_golden import capture_stream

GOLDEN = Path(__file__).resolve().parents[1] / "backtest" / "fixtures" / "parity_golden_h1.json"


class TestSignalParity(unittest.TestCase):
    def test_signal_stream_matches_golden(self):
        got = capture_stream("test_data.csv")
        want = json.loads(GOLDEN.read_text())
        self.assertEqual(len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            self.assertEqual(g, w, f"divergence at element {i}")


if __name__ == "__main__":
    unittest.main()
