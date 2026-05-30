# tests/unit/test_mtf_pb2.py
import os, sys, unittest
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_mtf_pb2 as m2


def _zigzag(up=True):
    # lk=1 zigzag: ascending (HH+HL) when up=True, descending (LH+LL) when up=False.
    if up:
        h = [5, 7, 4, 9, 6, 11, 8, 13, 10]
        l = [3, 5, 2, 6, 4,  8, 6, 10,  8]
    else:
        # Descending frame: swing highs 11→9→7 (LH) and swing lows 7→5→3→1 (LL).
        # high >= low at every bar; confirmed BEARISH by bar 5 (lk=1).
        h = [13, 10, 11, 8, 9, 6, 7, 4, 5]
        l = [10,  7,  8, 5, 6, 3, 4, 1, 2]
    return pd.DataFrame({"open": h, "high": h, "low": l, "close": h})


class StructureBias(unittest.TestCase):
    def test_bullish_when_hh_and_hl(self):
        df = _zigzag(up=True)
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(len(bias), len(df))
        self.assertEqual(bias[-1], "BULLISH")

    def test_neutral_during_warmup(self):
        df = _zigzag(up=True)
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(bias[0], "NEUTRAL")  # no confirmed swings yet

    def test_bearish_when_lh_and_ll(self):
        df = _zigzag(up=False)
        # fixture must be valid OHLC (high >= low) and resolve BEARISH at the tail
        self.assertTrue((df["high"] >= df["low"]).all())
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(bias[-1], "BEARISH")


class CombinedBias(unittest.TestCase):
    def test_requires_both_htf_agree(self):
        # 5m bars hourly-spaced; H4 & H1 both built from the same rising frame -> BULLISH tail.
        rows = []
        price = 1.0
        for k in range(600):
            price += 0.01
            ts = pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * k)
            rows.append({"datetime": str(ts), "open": price, "high": price + 0.02,
                         "low": price - 0.02, "close": price})
        m5 = pd.DataFrame(rows)
        h4 = m2.resample_tf(m5, "4h")
        h1 = m2.resample_tf(m5, "1h")
        bias = m2.combined_structure_bias(m5, h4, h1, lk=2)
        self.assertEqual(len(bias), len(m5))
        self.assertIn(bias[-1], ("BULLISH", "NEUTRAL"))  # never BEARISH on a pure uptrend
        self.assertNotEqual(bias[-1], "BEARISH")


class ImpulseLegAndOTE(unittest.TestCase):
    def setUp(self):
        self.highs = [5, 7, 4, 9, 6, 11, 8, 13, 10]
        self.lows = [3, 5, 2, 6, 4, 8, 6, 10, 8]

    def test_bull_leg_is_most_recent_bos_up(self):
        leg = m2.impulse_leg(self.highs, self.lows, upto=8, lk=1, bias="BULLISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high, lo_idx, hi_idx = leg
        self.assertEqual(leg_high, 13)   # BOS up high
        self.assertEqual(leg_low, 6)     # most recent confirmed swing low before it (idx 6)
        self.assertEqual((lo_idx, hi_idx), (6, 7))

    def test_no_leg_when_bias_neutral(self):
        self.assertIsNone(m2.impulse_leg(self.highs, self.lows, 8, 1, "NEUTRAL"))

    def test_ote_zone_bull(self):
        z_lo, z_hi = m2.ote_zone(6, 13, "BULLISH")  # rng=7
        self.assertAlmostEqual(z_hi, 13 - 0.62 * 7, places=6)
        self.assertAlmostEqual(z_lo, 13 - 0.79 * 7, places=6)


if __name__ == "__main__":
    unittest.main()
