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
    return {
        "open": close - 0.0001,
        "close": close,
        "high": close + 0.0008,
        "low": close - 0.0008,
        "atr": np.full(n, 0.0010),
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

    def test_mutating_bars_after_the_signal_changes_no_feature(self):
        h1 = _h1()
        sig = _sig(h1=h1)
        before = build_features(sig, h1)

        tampered = {k: v.copy() for k, v in h1.items()}
        tampered["close"][IDX + 1:] += 5.0
        tampered["high"][IDX + 1:] += 5.0
        after = build_features(sig, tampered)

        for name in FEATURE_SPECS:
            self.assertEqual(before[name], after[name], msg=f"{name} read a future bar")


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
