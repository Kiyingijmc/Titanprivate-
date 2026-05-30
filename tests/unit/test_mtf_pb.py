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


class CombinedBias(unittest.TestCase):
    def test_agreement_required(self):
        ts = pd.to_datetime
        # one closed 4h bar (BULLISH) and one closed 1h bar (BEARISH) -> NEUTRAL (disagree)
        h4 = pd.DataFrame({"time": [ts("2026-01-01 00:00:00")], "close": [10.0]})
        h1 = pd.DataFrame({"time": [ts("2026-01-01 00:00:00")], "close": [10.0]})
        m5 = pd.DataFrame({"time": [ts("2026-01-01 09:00:00")], "open": [1], "high": [1],
                           "low": [1], "close": [1]})
        out = mp.combine_bias_lists(["BULLISH"], ["BEARISH"],
                                    mp.last_closed_indexer(list(m5["time"]), list(h4["time"]), 4),
                                    mp.last_closed_indexer(list(m5["time"]), list(h1["time"]), 1))
        self.assertEqual(out, ["NEUTRAL"])

    def test_both_bullish(self):
        out = mp.combine_bias_lists(["BULLISH"], ["BULLISH"], [0], [0])
        self.assertEqual(out, ["BULLISH"])

    def test_warmup_neutral_when_no_closed_bar(self):
        out = mp.combine_bias_lists(["BULLISH"], ["BULLISH"], [-1], [0])
        self.assertEqual(out, ["NEUTRAL"])


class AttachAtr(unittest.TestCase):
    def test_atr_uses_last_closed_h1(self):
        ts = pd.to_datetime
        # 20 H1 bars, constant 1.0 range -> ATR ~1.0 after warmup.
        h1 = pd.DataFrame({
            "time": [ts("2026-01-01 00:00:00") + pd.Timedelta(hours=i) for i in range(20)],
            "open": [10.0]*20, "high": [10.5]*20, "low": [9.5]*20, "close": [10.0]*20,
        })
        m5 = pd.DataFrame({"time": [ts("2026-01-02 00:00:00")],  # well after all H1 closed
                           "open": [10], "high": [10], "low": [10], "close": [10]})
        atr = mp.attach_atr1h(m5, h1, period=14)
        self.assertEqual(len(atr), 1)
        self.assertAlmostEqual(atr[0], 1.0, places=6)

    def test_atr_zero_before_any_closed_bar(self):
        ts = pd.to_datetime
        h1 = pd.DataFrame({"time": [ts("2026-01-01 05:00:00")], "open": [1.0],
                           "high": [2.0], "low": [0.0], "close": [1.0]})
        m5 = pd.DataFrame({"time": [ts("2026-01-01 04:00:00")],  # before H1 bar closes
                           "open": [1], "high": [1], "low": [1], "close": [1]})
        self.assertEqual(mp.attach_atr1h(m5, h1), [0.0])


class ImpulseLeg(unittest.TestCase):
    def test_bullish_up_leg(self):
        # V-shape: swing low at idx 5, swing high at idx 11; decision at idx 18.
        highs = [10,10,10,10,10, 9,  10,11,12,13,14,15,  14,14,14,14,14,14,14]
        lows  = [ 9, 9, 9, 9, 9, 8,  9,10,11,12,13,14,   13,13,13,13,13,13,13]
        leg = mp.impulse_leg(highs, lows, 18, lk=2, bias="BULLISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high = leg
        self.assertEqual(leg_low, 8)    # lows[5]
        self.assertEqual(leg_high, 15)  # highs[11]

    def test_none_when_leg_wrong_direction_for_bias(self):
        highs = [10,10,10,10,10, 9, 10,11,12,13,14,15, 14,14,14,14,14,14,14]
        lows  = [ 9, 9, 9, 9, 9, 8,  9,10,11,12,13,14, 13,13,13,13,13,13,13]
        # up-leg present (low before high) but bias bearish -> reject
        self.assertIsNone(mp.impulse_leg(highs, lows, 18, lk=2, bias="BEARISH"))


class ConfirmedEntry(unittest.TestCase):
    # leg_low=0, leg_high=10 -> bullish discount zone = [10-0.705*10, 10-0.5*10] = [2.95, 5.0]
    def test_bullish_confirmation(self):
        leg = (0.0, 10.0)
        bar = {"open": 3.0, "high": 4.5, "low": 3.0, "close": 4.0}  # dips into zone, closes up
        self.assertTrue(mp.confirmed_entry(bar, leg, "BULLISH"))

    def test_no_entry_when_not_tagged(self):
        leg = (0.0, 10.0)
        bar = {"open": 6.0, "high": 7.0, "low": 5.5, "close": 6.5}  # low 5.5 never reaches 5.0
        self.assertFalse(mp.confirmed_entry(bar, leg, "BULLISH"))

    def test_no_entry_when_close_not_resuming(self):
        leg = (0.0, 10.0)
        bar = {"open": 4.5, "high": 4.6, "low": 3.0, "close": 3.2}  # tagged but bearish close
        self.assertFalse(mp.confirmed_entry(bar, leg, "BULLISH"))


if __name__ == "__main__":
    unittest.main()
