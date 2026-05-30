# tests/unit/test_mtf_pb.py
import os, sys, unittest
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_mtf_pb as mp


class Resample(unittest.TestCase):
    def test_resample_tf_4h_ohlc(self):
        rows = []
        for h in range(8):
            rows.append({"datetime": f"2026-01-01 {h:02d}:00:00", "open": h, "high": h + 2,
                         "low": h - 1, "close": h + 1})
        h4 = mp.resample_tf(pd.DataFrame(rows), "4h")
        self.assertEqual(len(h4), 2)
        self.assertEqual(list(h4.columns)[0], "time")
        self.assertEqual(h4.iloc[0]["open"], 0)
        self.assertEqual(h4.iloc[0]["high"], 5)   # max high of bars 0..3 = 3+2
        self.assertEqual(h4.iloc[0]["low"], -1)
        self.assertEqual(h4.iloc[0]["close"], 4)  # close of bar 3 = 3+1

    def test_resample_tf_time_col_and_timestamp(self):
        rows = []
        for h in range(8):
            rows.append({"time": f"2026-01-01 {h:02d}:00:00", "open": h, "high": h + 2,
                         "low": h - 1, "close": h + 1})
        h4 = mp.resample_tf(pd.DataFrame(rows), "4h")
        self.assertEqual(len(h4), 2)
        self.assertEqual(h4.iloc[0]["time"], pd.Timestamp("2026-01-01 00:00:00"))
        self.assertEqual(h4.iloc[1]["time"], pd.Timestamp("2026-01-01 04:00:00"))
        self.assertEqual(h4.iloc[0]["close"], 4)
        self.assertEqual(h4.iloc[1]["open"], 4)   # open of bar 4


if __name__ == "__main__":
    unittest.main()
