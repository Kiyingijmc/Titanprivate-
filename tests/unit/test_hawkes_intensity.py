import unittest

import numpy as np
import pandas as pd

from src.analysis.hawkes_intensity import excitation, flag_events, true_range, eligible_signals, s_lo_threshold


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


class TestExcitation(unittest.TestCase):
    def test_zero_without_events(self):
        s = excitation(pd.Series([False] * 10), half_life=24)
        self.assertTrue((s == 0.0).all())

    def test_single_event_closed_form(self):
        # event at index 3: S_minus at index 3+k must be decay**k, k >= 1
        ev = pd.Series([False] * 10)
        ev.iloc[3] = True
        hl = 24
        decay = np.exp(-np.log(2) / hl)
        s = excitation(ev, half_life=hl)
        self.assertAlmostEqual(s.iloc[3], 0.0)  # excludes own bar
        for k in (1, 2, 5):
            self.assertAlmostEqual(s.iloc[3 + k], decay**k, places=12)

    def test_half_life_halves_contribution(self):
        ev = pd.Series([False] * 60)
        ev.iloc[0] = True
        s = excitation(ev, half_life=24)
        self.assertAlmostEqual(s.iloc[24], 0.5, places=12)

    def test_two_events_superpose(self):
        ev = pd.Series([False] * 20)
        ev.iloc[2] = True
        ev.iloc[5] = True
        decay = np.exp(-np.log(2) / 24)
        s = excitation(ev, half_life=24)
        self.assertAlmostEqual(s.iloc[8], decay**6 + decay**3, places=12)


def _spike_at(df, i, up=True, rng=10.0):
    """Overwrite bar i with a directional spike; bar i+1 with a confirm bar."""
    o = 100.0
    if up:
        df.loc[i, ["open", "high", "low", "close"]] = [o, o + rng, o, o + rng * 0.9]
        df.loc[i + 1, ["open", "high", "low", "close"]] = [
            o + rng * 0.9, o + rng, o + rng * 0.6, o + rng * 0.8]
    else:
        df.loc[i, ["open", "high", "low", "close"]] = [o, o, o - rng, o - rng * 0.9]
        df.loc[i + 1, ["open", "high", "low", "close"]] = [
            o - rng * 0.9, o - rng * 0.6, o - rng, o - rng * 0.8]
    return df


class TestEligibleSignals(unittest.TestCase):
    def test_fresh_confirmed_spike_is_eligible(self):
        df = _spike_at(_flat_df(260), 250, up=True)
        out = eligible_signals(df)
        self.assertEqual(len(out), 1)
        row = out.iloc[0]
        self.assertEqual(int(row["event_idx"]), 250)
        self.assertEqual(int(row["signal_idx"]), 251)
        self.assertEqual(int(row["direction"]), 1)
        self.assertAlmostEqual(float(row["event_range"]), 10.0)

    def test_unconfirmed_spike_not_eligible(self):
        # confirm bar closes back BELOW the event bar's midpoint -> reject
        df = _spike_at(_flat_df(260), 250, up=True)
        df.loc[251, "close"] = 100.0 + 10.0 * 0.3  # below mid (105.0)
        self.assertEqual(len(eligible_signals(df)), 0)

    def test_hot_s_minus_not_eligible(self):
        # two spikes close together: the second arrives with S-minus elevated
        df = _spike_at(_flat_df(280), 250, up=True)
        df = _spike_at(df, 255, up=True)
        out = eligible_signals(df)
        self.assertEqual(list(out["event_idx"]), [250])

    def test_down_event_direction(self):
        df = _spike_at(_flat_df(260), 250, up=False)
        out = eligible_signals(df)
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out.iloc[0]["direction"]), -1)

    def test_s_lo_threshold_is_percentile_after_warmup(self):
        s = pd.Series(np.arange(400, dtype=float))
        # warmup 200 -> population is s[200:400] = 200..399; 20th pctile = 239.8
        self.assertAlmostEqual(s_lo_threshold(s, warmup=200, pctile=20.0), 239.8)


class TestEligibleSignalsHour(unittest.TestCase):
    def test_hour_from_time_column(self):
        df = _spike_at(_flat_df(260), 250, up=True)
        df["time"] = pd.date_range("2024-01-01", periods=260, freq="h")
        out = eligible_signals(df)
        self.assertEqual(int(out.iloc[0]["hour"]), 250 % 24)


if __name__ == "__main__":
    unittest.main()
