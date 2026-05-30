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


class MaBias(unittest.TestCase):
    def test_ma_bias_bull_bear_and_warmup(self):
        # 60 rising closes -> bullish once past warmup; flip to falling -> bearish.
        closes = list(range(1, 61)) + list(range(60, 30, -1))
        df = pd.DataFrame({"close": closes})
        bias = mp.ma_bias(df, ma_len=50)
        self.assertEqual(len(bias), len(closes))
        self.assertEqual(bias[10], "NEUTRAL")        # within warmup (< ma_len)
        self.assertEqual(bias[59], "BULLISH")        # rising, past warmup
        self.assertEqual(bias[-1], "BEARISH")        # falling tail, price below EMA


class ClosedIndexer(unittest.TestCase):
    def test_htf_bar_unused_until_closed(self):
        ts = pd.to_datetime
        htf_times = [ts("2026-01-01 00:00:00"), ts("2026-01-01 04:00:00")]  # 4h bars
        m5_times = [ts("2026-01-01 03:55:00"),   # before 1st bar closes (04:00) -> -1
                    ts("2026-01-01 04:00:00"),   # 1st bar just closed -> idx 0
                    ts("2026-01-01 04:05:00"),   # still only 1st closed -> idx 0
                    ts("2026-01-01 08:00:00")]   # 2nd bar (04:00) closed at 08:00 -> idx 1
        idx = mp.last_closed_indexer(m5_times, htf_times, 4)
        self.assertEqual(idx, [-1, 0, 0, 1])


if __name__ == "__main__":
    unittest.main()
