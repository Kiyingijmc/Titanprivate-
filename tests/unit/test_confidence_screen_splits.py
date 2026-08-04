import unittest
import numpy as np
import pandas as pd

from scripts.confidence_screen.splits import split_masks, week_clusters


def _times(n, start="2024-01-01", freq="6h"):
    return pd.to_datetime(pd.date_range(start, periods=n, freq=freq)).values


class TestSplit(unittest.TestCase):
    def test_cut_is_a_calendar_date_not_a_row_index(self):
        """Symbols with denser signal counts must not dominate the training
        period. A has 90 signals, B has 10, both over the same span; the cut
        must sit at a time, so B's early rows land in IS too."""
        times = np.concatenate([_times(90, freq="6h"), _times(10, freq="54h")])
        symbols = np.array(["A"] * 90 + ["B"] * 10)
        out = split_masks(times, symbols)
        self.assertTrue(out["is_mask"][symbols == "B"].any())
        self.assertTrue((times[out["is_mask"]] <= out["cut_time"]).all())

    def test_masks_are_disjoint_and_cover_everything_with_purged(self):
        times = _times(200)
        symbols = np.array(["A"] * 200)
        out = split_masks(times, symbols)
        total = out["is_mask"].astype(int) + out["oos_mask"].astype(int) + \
            out["purged_mask"].astype(int)
        np.testing.assert_array_equal(total, np.ones(200, dtype=int))

    def test_signals_whose_window_crosses_the_cut_are_in_neither_set(self):
        """H_BARS + EMBARGO_BUFFER_BARS = 16 H1 bars of forward window. Any
        signal inside that band before the cut leaks into OOS."""
        times = _times(400, freq="1h")
        symbols = np.array(["A"] * 400)
        out = split_masks(times, symbols)
        cut = out["cut_time"]
        band = (times > cut - np.timedelta64(16, "h")) & (times <= cut)
        self.assertTrue(out["purged_mask"][band].all())
        self.assertFalse(out["is_mask"][band].any())
        self.assertFalse(out["oos_mask"][band].any())

    def test_roughly_seventy_percent_lands_in_train(self):
        times = _times(1000, freq="1h")
        symbols = np.array(["A"] * 1000)
        out = split_masks(times, symbols)
        self.assertGreater(out["is_mask"].mean(), 0.60)
        self.assertLess(out["is_mask"].mean(), 0.72)


class TestWeekClusters(unittest.TestCase):
    def test_same_week_shares_a_label(self):
        times = pd.to_datetime(["2024-01-02", "2024-01-04"]).values
        labels = week_clusters(times)
        self.assertEqual(labels[0], labels[1])

    def test_different_weeks_differ(self):
        times = pd.to_datetime(["2024-01-02", "2024-01-12"]).values
        labels = week_clusters(times)
        self.assertNotEqual(labels[0], labels[1])

    def test_all_symbols_in_one_week_share_the_cluster(self):
        times = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]).values
        self.assertEqual(len(set(week_clusters(times))), 1)


if __name__ == "__main__":
    unittest.main()
