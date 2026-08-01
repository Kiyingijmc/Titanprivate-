import unittest

import numpy as np
import pandas as pd

from src.analysis.hawkes_intensity import flag_events, true_range


def _flat_df(n, price=100.0, spread=1.0):
    """n quiet bars: range `spread`, close == open (dir 0)."""
    return pd.DataFrame({
        "open": [price] * n,
        "high": [price + spread / 2] * n,
        "low": [price - spread / 2] * n,
        "close": [price] * n,
    })


class TestTrueRange(unittest.TestCase):
    def test_first_bar_is_high_minus_low(self):
        df = _flat_df(3)
        tr = true_range(df)
        self.assertAlmostEqual(tr.iloc[0], 1.0)

    def test_gap_uses_prev_close(self):
        # bar 1 gaps up: high=112, low=111, prev close=100 -> TR = 12
        df = pd.DataFrame({
            "open": [100.0, 111.0],
            "high": [100.5, 112.0],
            "low": [99.5, 111.0],
            "close": [100.0, 111.5],
        })
        tr = true_range(df)
        self.assertAlmostEqual(tr.iloc[1], 12.0)


class TestFlagEvents(unittest.TestCase):
    def _spike_df(self, n_warm=250, spike_range=10.0):
        """Quiet bars (range 1.0) then one big up bar closing above mid."""
        df = _flat_df(n_warm)
        spike = pd.DataFrame({
            "open": [100.0], "high": [100.0 + spike_range],
            "low": [100.0], "close": [100.0 + spike_range * 0.9],
        })
        return pd.concat([df, spike], ignore_index=True)

    def test_spike_after_warmup_is_event(self):
        out = flag_events(self._spike_df(), q=2.5, window=200)
        self.assertTrue(bool(out["is_event"].iloc[-1]))
        self.assertEqual(int(out["event_dir"].iloc[-1]), 1)
        self.assertTrue(bool(out["closes_beyond_mid"].iloc[-1]))

    def test_no_events_during_warmup(self):
        # spike at index 100 < window 200 must NOT be an event
        df = self._spike_df(n_warm=100)
        out = flag_events(df, q=2.5, window=200)
        self.assertFalse(out["is_event"].any())

    def test_median_excludes_current_bar(self):
        # Small window + distinct TR values: TRs=[1,2,3,4,5], window=3.
        # At last bar: trailing-exclusive median = median(2,3,4) = 3.0.
        # If buggy (no shift), would be median(3,4,5) = 4.0.
        # Build bars with open=close=100 to avoid gaps; high/low set TR.
        bars = []
        for tr_val in [1.0, 2.0, 3.0, 4.0, 5.0]:
            bars.append({
                "open": 100.0,
                "high": 100.0 + tr_val / 2.0,
                "low": 100.0 - tr_val / 2.0,
                "close": 100.0,
            })
        df = pd.DataFrame(bars)
        out = flag_events(df, q=2.5, window=3)
        # At the last bar, tr_med must be median of the previous 3 TRs (2, 3, 4) = 3.0
        self.assertAlmostEqual(out["tr_med"].iloc[-1], 3.0)

    def test_quiet_bars_are_not_events(self):
        out = flag_events(_flat_df(300), q=2.5, window=200)
        self.assertFalse(out["is_event"].any())

    def test_doji_event_dir_zero(self):
        # spike bar with close == open -> dir 0, closes_beyond_mid False
        df = _flat_df(250)
        spike = pd.DataFrame({
            "open": [100.0], "high": [105.0], "low": [95.0], "close": [100.0],
        })
        df = pd.concat([df, spike], ignore_index=True)
        out = flag_events(df, q=2.5, window=200)
        self.assertTrue(bool(out["is_event"].iloc[-1]))
        self.assertEqual(int(out["event_dir"].iloc[-1]), 0)
        self.assertFalse(bool(out["closes_beyond_mid"].iloc[-1]))


if __name__ == "__main__":
    unittest.main()
