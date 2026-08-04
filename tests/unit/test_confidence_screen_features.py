import unittest
import numpy as np
import pandas as pd

from scripts.confidence_screen.features import (
    FEATURE_SPECS, PLACEBO_NAMES, build_features,
)

N = 400
IDX = 300


def _h1(n=N):
    rng = np.random.default_rng(7)
    close = 1.10 + np.cumsum(rng.normal(0, 0.0005, n))
    # atr must VARY per bar (not a constant array) — a constant array makes a
    # look-ahead read of it structurally undetectable, since every element is
    # identical and no read (causal or leaking) can change any output.
    # Deterministic and seeded (draws continue from the same rng stream as
    # `close`); kept strictly positive so it stays valid as a denominator.
    atr = 0.0010 + 0.00002 * np.sin(np.arange(n) / 6.0) + 0.000005 * rng.normal(0, 1, n)
    atr = np.abs(atr) + 0.0003
    return {
        "open": close - 0.0001,
        "close": close,
        "high": close + 0.0008,
        "low": close - 0.0008,
        "atr": atr,
        "time": np.array([np.datetime64("2024-01-01T00") + np.timedelta64(i, "h")
                          for i in range(n)]),
    }


def _sig(bar_idx=IDX, direction="BUY", **kw):
    h1 = kw.pop("h1", None) or _h1()
    base = {
        "bar_idx": bar_idx, "time": pd.Timestamp(str(h1["time"][bar_idx])),
        "dir": direction, "entry": float(h1["close"][bar_idx]),
        "atr": 0.0010, "risk": 0.0010, "body_atr": 1.2,
        "bias": "BULLISH", "liq_status": "DISCOUNT",
        "hour": 10, "year": 2024, "symbol": "EURUSD",
    }
    base.update(kw)
    return base


class TestLookAhead(unittest.TestCase):
    def test_appending_future_bars_changes_no_feature(self):
        """The single most important test in this module. A feature that
        reads past bar_idx surfaces only as an impossibly good result."""
        h1 = _h1()
        sig = _sig(h1=h1)
        before = build_features(sig, h1)

        extended = {k: np.concatenate([v, v[-50:]]) for k, v in h1.items()}
        extended["time"] = np.concatenate([
            h1["time"],
            np.array([h1["time"][-1] + np.timedelta64(i + 1, "h") for i in range(50)]),
        ])
        after = build_features(sig, extended)

        for name in FEATURE_SPECS:
            self.assertEqual(before[name], after[name], msg=f"{name} leaked future data")

    @staticmethod
    def _tamper(h1, idx_slice):
        """Perturb EVERY array a feature reads, not just close/high — f4 and
        f7 read `low`, f8 reads `open`, f1/f2 read `atr`. Leaving any one
        field untouched makes a leak through it invisible.

        The perturbation is deliberately asymmetric per field, not a single
        shared constant:
          - `high` is pushed UP and `low` is pushed DOWN. `r_hi`/`pdh` and
            `r_lo`/`pdl` are `.max()`/`.min()` reads; an increase can never
            produce a new *minimum* and a decrease can never produce a new
            *maximum*, so a same-signed shift on both fields would leave a
            leaked min-over-low or max-over-high silently uncaught.
          - `open` and `close` get DIFFERENT magnitudes. `f8` reads
            `close[-1] - open_[-1]` at one shared index; shifting both
            fields by the same constant cancels in that subtraction, which
            would hide a leak that reads a future bar's close/open pair.
        """
        tampered = {k: v.copy() for k, v in h1.items()}
        tampered["open"][idx_slice] += 7.0
        tampered["high"][idx_slice] += 5.0
        tampered["low"][idx_slice] -= 5.0
        tampered["close"][idx_slice] += 3.0
        tampered["atr"][idx_slice] += 5.0
        return tampered

    def test_mutating_bars_after_the_signal_changes_no_feature(self):
        h1 = _h1()
        sig = _sig(h1=h1)
        before = build_features(sig, h1)

        tampered = self._tamper(h1, slice(IDX + 1, None))
        after = build_features(sig, tampered)

        for name in FEATURE_SPECS:
            self.assertEqual(before[name], after[name], msg=f"{name} read a future bar")

    def test_mutating_bars_immediately_after_signal_changes_no_feature(self):
        """An off-by-one leak (e.g. slicing to i+2 instead of i+1) only reads
        the very next bar or two. The far-future append test above wouldn't
        stress that at all — it only catches a leak that reads well past the
        end of the original array. Perturb only bar_idx+1..bar_idx+3."""
        h1 = _h1()
        sig = _sig(h1=h1)
        before = build_features(sig, h1)

        tampered = self._tamper(h1, slice(IDX + 1, IDX + 4))
        after = build_features(sig, tampered)

        for name in FEATURE_SPECS:
            self.assertEqual(before[name], after[name],
                              msg=f"{name} read a bar immediately after bar_idx")


class TestDirectionOrientation(unittest.TestCase):
    def test_range_position_is_inverted_for_buys(self):
        """Higher must always mean 'more favourable to THIS trade'. A BUY is
        better low in the range; a SELL is better high."""
        h1 = _h1()
        buy = build_features(_sig(h1=h1, direction="BUY"), h1)
        sell = build_features(_sig(h1=h1, direction="SELL"), h1)
        self.assertAlmostEqual(buy["f7_range_pos"] + sell["f7_range_pos"], 1.0, places=9)

    def test_return_vol_feature_flips_sign_with_direction(self):
        h1 = _h1()
        buy = build_features(_sig(h1=h1, direction="BUY"), h1)
        sell = build_features(_sig(h1=h1, direction="SELL"), h1)
        self.assertAlmostEqual(buy["f8_ret_vol"], -sell["f8_ret_vol"], places=9)


class TestPlacebos(unittest.TestCase):
    def test_placebos_are_deterministic_across_calls(self):
        h1 = _h1()
        sig = _sig(h1=h1)
        a = build_features(sig, h1)
        b = build_features(sig, h1)
        for name in PLACEBO_NAMES:
            self.assertEqual(a[name], b[name])

    def test_placebos_differ_from_each_other(self):
        h1 = _h1()
        out = build_features(_sig(h1=h1), h1)
        self.assertNotEqual(out[PLACEBO_NAMES[0]], out[PLACEBO_NAMES[1]])

    def test_placebos_differ_across_signals(self):
        h1 = _h1()
        a = build_features(_sig(h1=h1, bar_idx=300), h1)
        b = build_features(_sig(h1=h1, bar_idx=301), h1)
        self.assertNotEqual(a[PLACEBO_NAMES[0]], b[PLACEBO_NAMES[0]])


class TestPrevDayDistance(unittest.TestCase):
    def test_previous_day_survives_a_weekend_gap(self):
        """A fixed 24-bar lookback assumes every day has exactly 24 bars.
        This universe is mostly 24/5 forex: a short Friday close, then no
        bars at all over the weekend. f4 must resolve to Friday's real
        high/low (derived from h1["time"]'s calendar dates), not whatever a
        blind 24-bar-back slice happens to straddle."""
        fri = [np.datetime64("2024-01-05T00") + np.timedelta64(h, "h") for h in range(18)]
        mon = [np.datetime64("2024-01-08T00") + np.timedelta64(h, "h") for h in range(10)]
        times = np.array(fri + mon)
        n = len(times)
        rng = np.random.default_rng(3)
        close = 1.20 + np.cumsum(rng.normal(0, 0.0004, n))
        h1 = {
            "open": close - 0.0001,
            "close": close,
            "high": close + 0.0008,
            "low": close - 0.0008,
            "atr": np.full(n, 0.0012),
            "time": times,
        }
        bar_idx = len(fri) + 2  # a couple of bars into Monday
        sig = _sig(bar_idx=bar_idx, h1=h1)
        out = build_features(sig, h1)

        fri_hi = float(h1["high"][:len(fri)].max())
        fri_lo = float(h1["low"][:len(fri)].min())
        entry = float(h1["close"][bar_idx])
        risk = float(sig["risk"])
        expected = min(abs(entry - fri_hi), abs(entry - fri_lo)) / risk  # BUY: positive

        self.assertAlmostEqual(out["f4_prev_day_dist"], expected, places=9)


class TestSessions(unittest.TestCase):
    def test_every_broker_hour_maps_to_exactly_one_session(self):
        h1 = _h1()
        seen = {build_features(_sig(h1=h1, hour=h), h1)["f5_session"] for h in range(24)}
        self.assertEqual(seen, {"ASIA", "LONDON", "NY_AM", "NY_PM"})


class TestSpecTable(unittest.TestCase):
    def test_panel_has_exactly_eight_candidates_and_two_placebos(self):
        self.assertEqual(len(FEATURE_SPECS), 8)
        self.assertEqual(len(PLACEBO_NAMES), 2)


if __name__ == "__main__":
    unittest.main()
