# tests/unit/test_gyro2_gate.py
# The gyro2 gate's accounting engine is a COPY of the validated
# poc_sb_stops managed replay (+ time-stop). These tests pin the copy to the
# originals on randomized trades so any divergence turns red, and verify the
# time-stop and ATR helpers.
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from scripts.gyro2_gate import _replay_managed_c_ts, atr_series
from scripts.poc_sb_stops import replay_managed, replay_overlay
from src.analysis.atr_simple import last_atr


def _random_case(rng):
    """A random-walk bar series + a trade opened early in it."""
    n = 120
    px = 100.0
    highs, lows, closes = [], [], []
    for _ in range(n):
        o = px
        px += rng.gauss(0, 0.6)
        hi = max(o, px) + abs(rng.gauss(0, 0.4))
        lo = min(o, px) - abs(rng.gauss(0, 0.4))
        highs.append(hi)
        lows.append(lo)
        closes.append(px)
    is_long = rng.random() < 0.5
    entry = closes[4]
    risk = 0.8 + rng.random() * 1.5
    sl = entry - risk if is_long else entry + risk
    tp = entry + 2 * risk if is_long else entry - 2 * risk
    tr = {"entry": entry, "sl": sl, "tp": tp, "risk": risk,
          "dir": "BUY" if is_long else "SELL", "fill_idx": 5}
    return tr, highs, lows, closes


class TestReplayParity(unittest.TestCase):
    def test_matches_replay_managed_runner_when_untightened_unbounded(self):
        rng = random.Random(2026)
        for case in range(300):
            tr, highs, lows, closes = _random_case(rng)
            bars = {"high": highs, "low": lows}
            want = replay_managed(tr, bars, runner=True)
            got, _, expired = _replay_managed_c_ts(
                tr, highs, lows, closes, max_bars=10**9, tighten=False)
            self.assertFalse(expired)
            self.assertAlmostEqual(got, want, places=12, msg=f"case {case}")

    def test_matches_replay_overlay_arm_c_when_unbounded(self):
        rng = random.Random(777)
        for case in range(300):
            tr, highs, lows, closes = _random_case(rng)
            bars = {"high": highs, "low": lows}
            want, extra = replay_overlay(tr, bars, arm="C")
            self.assertEqual(extra, 0.0)
            got, _, expired = _replay_managed_c_ts(
                tr, highs, lows, closes, max_bars=10**9, tighten=True)
            self.assertFalse(expired)
            self.assertAlmostEqual(got, want, places=12, msg=f"case {case}")


class TestTimeStop(unittest.TestCase):
    def test_stagnant_trade_expires_at_close(self):
        # price pinned between SL and TP forever -> time-stop at fill+48
        n = 200
        highs = [100.4] * n
        lows = [99.6] * n
        closes = [100.1] * n
        tr = {"entry": 100.0, "sl": 99.0, "tp": 102.0, "risk": 1.0,
              "dir": "BUY", "fill_idx": 5}
        r, exit_idx, expired = _replay_managed_c_ts(
            tr, highs, lows, closes, max_bars=48)
        self.assertTrue(expired)
        self.assertEqual(exit_idx, 5 + 48)
        self.assertAlmostEqual(r, 0.1, places=9)  # closed flat at 100.1

    def test_sl_beats_time_stop_on_the_boundary_bar(self):
        n = 200
        highs = [100.4] * n
        lows = [99.6] * n
        closes = [100.1] * n
        lows[53] = 98.9  # SL hit exactly on the would-be expiry bar
        tr = {"entry": 100.0, "sl": 99.0, "tp": 102.0, "risk": 1.0,
              "dir": "BUY", "fill_idx": 5}
        r, exit_idx, expired = _replay_managed_c_ts(
            tr, highs, lows, closes, max_bars=48)
        self.assertFalse(expired)
        self.assertEqual(exit_idx, 53)
        self.assertAlmostEqual(r, -1.0, places=9)


class TestAtrSeries(unittest.TestCase):
    def test_matches_last_atr_at_every_index(self):
        rng = random.Random(9)
        rows = []
        px = 50.0
        for k in range(60):
            o = px
            px += rng.gauss(0, 0.3)
            rows.append({"open": o, "high": max(o, px) + 0.1,
                         "low": min(o, px) - 0.1, "close": px})
        df = pd.DataFrame(rows)
        fast = atr_series(df["high"].tolist(), df["low"].tolist(),
                          df["close"].tolist())
        for i in range(60):
            self.assertAlmostEqual(fast[i], last_atr(df.iloc[:i + 1]),
                                   places=12, msg=f"i={i}")


if __name__ == "__main__":
    unittest.main()
