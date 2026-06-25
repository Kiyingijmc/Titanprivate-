# tests/unit/test_mtf_pb2_perf.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_mtf_pb2 as m2


def _series():
    # deterministic pseudo-random-ish OHLC with plenty of swings
    import math
    highs, lows, closes = [], [], []
    for k in range(400):
        base = 100 + 8 * math.sin(k / 5.0) + 3 * math.sin(k / 1.7) + (k % 11) * 0.3
        hi = base + 1.0 + (k % 3) * 0.2
        lo = base - 1.0 - (k % 4) * 0.2
        cl = base + ((k % 5) - 2) * 0.3
        highs.append(hi); lows.append(lo); closes.append(cl)
    return highs, lows, closes


class MssFastEquivalence(unittest.TestCase):
    def test_fast_mss_matches_slow_for_every_bar(self):
        highs, lows, closes = _series()
        lk = 2
        last_swh, last_swl = m2.precompute_last_swings(highs, lows, lk)
        for bias in ("BULLISH", "BEARISH"):
            for i in range(len(highs)):
                slow = m2.mss_confirm(highs, lows, closes, i, bias, lk)
                fast = m2.mss_confirm(highs, lows, closes, i, bias, lk,
                                      last_swh=last_swh, last_swl=last_swl)
                self.assertEqual(slow, fast, f"mismatch bias={bias} i={i}: {slow} != {fast}")


class ImpulseLegFastEquivalence(unittest.TestCase):
    def test_fast_leg_matches_slow_for_every_upto(self):
        highs, lows, _ = _series()
        lk = 2
        SWH, SWL = m2.confirmed_swing_seq(highs, lows, lk)
        for bias in ("BULLISH", "BEARISH"):
            for upto in range(lk + 1, len(highs)):
                slow = m2.impulse_leg(highs, lows, upto, lk, bias)
                fast = m2.impulse_leg(highs, lows, upto, lk, bias, SWH, SWL)
                self.assertEqual(slow, fast, f"mismatch bias={bias} upto={upto}: {slow} != {fast}")


if __name__ == "__main__":
    unittest.main()
