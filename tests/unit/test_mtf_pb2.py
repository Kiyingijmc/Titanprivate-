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


if __name__ == "__main__":
    unittest.main()
