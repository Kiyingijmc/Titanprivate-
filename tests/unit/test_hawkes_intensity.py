import math
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
        # Warm-up DOWN spike at bar 201 seeds nonzero S- background (s_lo = 0.9726).
        # Probe UP spike at bar 250 arrives at s_minus = 0.7502 < s_lo.
        # This demonstrates strict < inequality with a fresh (cool) signal.
        df = _spike_at(_flat_df(260), 201, up=False)  # warmup
        df = _spike_at(df, 250, up=True)  # probe
        out = eligible_signals(df)
        # Filter for UP events only (the probe); warmup is DOWN
        up_events = out[out["direction"] == 1]
        self.assertEqual(len(up_events), 1)
        row = up_events.iloc[0]
        self.assertEqual(int(row["event_idx"]), 250)
        self.assertEqual(int(row["signal_idx"]), 251)
        self.assertEqual(int(row["direction"]), 1)
        self.assertAlmostEqual(float(row["event_range"]), 10.0)

    def test_unconfirmed_spike_not_eligible(self):
        # Warm-up DOWN spike at 201, probe UP spike at 250.
        # Modify confirm bar (251) to close BELOW the event bar's midpoint -> reject.
        df = _spike_at(_flat_df(260), 201, up=False)
        df = _spike_at(df, 250, up=True)
        df.loc[251, "close"] = 100.0 + 10.0 * 0.3  # below mid (105.0)
        up_events = eligible_signals(df)[eligible_signals(df)["direction"] == 1]
        self.assertEqual(len(up_events), 0)

    def test_hot_s_minus_not_eligible(self):
        # Warm-up DOWN at 201 seeds s_lo = 0.9726.
        # First probe UP at 250: s_minus = 0.7502 < s_lo -> ELIGIBLE.
        # Second probe UP at 255: after event at 250, s_minus = 3.323 > s_lo -> NOT ELIGIBLE.
        df = _spike_at(_flat_df(260), 201, up=False)
        df = _spike_at(df, 250, up=True)  # cool
        df = _spike_at(df, 255, up=True)  # hot (high s_minus from event at 250)
        up_events = eligible_signals(df)[eligible_signals(df)["direction"] == 1]
        self.assertEqual(list(up_events["event_idx"]), [250])

    def test_down_event_direction(self):
        # Warm-up UP at 201, probe DOWN at 250.
        df = _spike_at(_flat_df(260), 201, up=True)  # warmup
        df = _spike_at(df, 250, up=False)  # probe (down)
        down_events = eligible_signals(df)[eligible_signals(df)["direction"] == -1]
        self.assertEqual(len(down_events), 1)
        self.assertEqual(int(down_events.iloc[0]["direction"]), -1)

    def test_s_lo_threshold_is_percentile_after_warmup(self):
        s = pd.Series(np.arange(400, dtype=float))
        # warmup 200 -> population is s[200:400] = 200..399; 20th pctile = 239.8
        self.assertAlmostEqual(s_lo_threshold(s, warmup=200, pctile=20.0), 239.8)


class TestEligibleSignalsHour(unittest.TestCase):
    def test_hour_from_time_column(self):
        df = _spike_at(_flat_df(260), 201, up=False)
        df = _spike_at(df, 250, up=True)
        df["time"] = pd.date_range("2024-01-01", periods=260, freq="h")
        up_events = eligible_signals(df)[eligible_signals(df)["direction"] == 1]
        self.assertEqual(int(up_events.iloc[0]["hour"]), 250 % 24)


class TestBoundaryRegression(unittest.TestCase):
    """Regression tests for boundary conditions: strict > and strict < inequalities."""

    def test_tr_boundary_exactly_equal_not_event(self):
        """TR exactly equal to q * tr_med must NOT trigger is_event (strict >)."""
        # Build 250 bars with constant TR = 2.0, then one bar with TR = 5.0.
        # With q=2.5 and window=200, the trailing-exclusive median at bar 250 is 2.0.
        # Test condition: is_event checks tr > q * tr_med, i.e., 5.0 > 2.5*2.0 = 5.0?
        # Since 5.0 is NOT > 5.0, is_event must be False.
        bars = []
        for _ in range(250):
            bars.append({
                "open": 100.0,
                "high": 101.0,  # TR = 2.0
                "low": 99.0,
                "close": 100.0,
            })
        # Probe bar with TR exactly = 5.0
        bars.append({
            "open": 100.0,
            "high": 102.5,  # TR = 5.0
            "low": 97.5,
            "close": 100.0,
        })
        # Confirm bar (dir 0, not part of check)
        bars.append({
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        })
        df = pd.DataFrame(bars)
        out = flag_events(df, q=2.5, window=200)

        # Verify the setup: probe bar TR and tr_med
        self.assertAlmostEqual(out["tr"].iloc[250], 5.0, places=10)
        self.assertAlmostEqual(out["tr_med"].iloc[250], 2.0, places=10)

        # Assert strict >: 5.0 is NOT > 5.0, so is_event is False
        self.assertFalse(bool(out["is_event"].iloc[250]))

    def test_s_minus_exactly_equal_to_s_lo_not_eligible(self):
        """A probe whose s_minus EXACTLY equals s_lo must be rejected (strict <).

        This is the degenerate case that produced the original `<=` bug: with no
        prior events anywhere in the frame, s_minus is identically 0.0, so
        s_lo (its 20th percentile) is also exactly 0.0. Under the registered
        strict `<` the probe is excluded; under `<=` it would be admitted, so
        this discriminates the two.
        """
        df = _spike_at(_flat_df(260), 250, up=True)  # probe only, NO warm-up event
        flags = flag_events(df, q=2.5, window=200)
        s_minus = excitation(flags["is_event"], half_life=24)
        s_lo = s_lo_threshold(s_minus, warmup=200, pctile=20.0)

        # The probe is a genuine event that clears every other gate...
        self.assertTrue(bool(flags["is_event"].iloc[250]))
        self.assertTrue(bool(flags["closes_beyond_mid"].iloc[250]))
        # ...and sits EXACTLY on the threshold.
        self.assertEqual(s_minus.iloc[250], s_lo)

        # Strict `<` therefore excludes it. `<=` would return one row.
        self.assertEqual(len(eligible_signals(df)), 0)

    def test_s_minus_boundary_at_percentile(self):
        """s_minus >= s_lo bars fail the s_minus < s_lo filter (strict inequality).

        Per registered protocol, s_minus < s_lo (strict <) is required for eligibility.
        This test verifies the boundary: bars with s_minus >= s_lo must be excluded.
        Mutation < to <= would reverse this exclusion at the boundary.
        """
        # Setup: create events that generate s_minus values spanning the s_lo threshold
        df = _spike_at(_flat_df(280), 201, up=False)
        df = _spike_at(df, 240, up=True)

        flags = flag_events(df, q=2.5, window=200)
        s_minus = excitation(flags["is_event"], half_life=24)
        s_lo = s_lo_threshold(s_minus, warmup=200, pctile=20.0)

        out = eligible_signals(df)

        # Collect all events with event_dir != 0 (non-doji events)
        non_doji_events = [i for i in range(200, len(s_minus))
                          if flags["is_event"].iloc[i] and flags["event_dir"].iloc[i] != 0]

        # Partition into "cool" (s_minus < s_lo) and "hot/boundary" (s_minus >= s_lo)
        cool_events = [i for i in non_doji_events if s_minus.iloc[i] < s_lo]
        boundary_events = [i for i in non_doji_events if s_minus.iloc[i] >= s_lo]

        # Verify partition has both types
        self.assertTrue(len(cool_events) > 0, "Test should have cool events (s_minus < s_lo)")
        self.assertTrue(len(boundary_events) > 0, "Test should have boundary/hot events (s_minus >= s_lo)")

        # Key assertion: all boundary_events MUST have s_minus >= s_lo
        for idx in boundary_events:
            self.assertGreaterEqual(s_minus.iloc[idx], s_lo,
                f"Bar {idx} should be in boundary_events only if s_minus >= s_lo")

        # Verify that NO boundary_events pass the s_minus < s_lo filter
        # (they may fail other filters too, but the s_minus filter must stop them)
        eligible_indices = set(out["event_idx"].astype(int))
        for idx in boundary_events:
            # This bar has s_minus >= s_lo, so it should NOT pass the (s_minus < s_lo) check
            # Therefore it should NOT be in eligible (at minimum due to this check)
            if idx in eligible_indices:
                self.fail(f"Bar {idx} with s_minus={s_minus.iloc[idx]:.10f} >= s_lo={s_lo:.10f} "
                         "should NOT pass the strict (s_minus < s_lo) filter")


if __name__ == "__main__":
    unittest.main()
