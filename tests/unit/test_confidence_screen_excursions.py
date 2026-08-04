import unittest
import numpy as np
import pandas as pd

from scripts.confidence_screen.excursions import excursions

ENTRY = 1.1000
RISK = 0.0010  # 1R
T0 = pd.Timestamp("2024-01-02 10:00:00")


def _sig(direction="BUY"):
    return {"entry": ENTRY, "risk": RISK, "dir": direction,
            "time": T0, "symbol": "EURUSD"}


def _m5(bars, start=T0, step_min=5):
    """bars: list of (high, low) starting one M5 bar AFTER the signal time."""
    times = [start + pd.Timedelta(minutes=step_min * (i + 1)) for i in range(len(bars))]
    return {
        "time": np.array([t.to_datetime64() for t in times]),
        "high": np.array([b[0] for b in bars], dtype=float),
        "low": np.array([b[1] for b in bars], dtype=float),
    }


class TestTruncation(unittest.TestCase):
    def test_adverse_1r_first_truncates_the_favourable_path(self):
        """MAE reaches 1R, THEN price runs 3R favourable. The +3R is
        unrealizable — the position was already stopped. skew must be -1.0,
        not +2.0."""
        m5 = _m5([
            (ENTRY, ENTRY),                          # touch the limit
            (ENTRY, ENTRY - 1.0 * RISK),             # -1R adverse
            (ENTRY + 3.0 * RISK, ENTRY),             # +3R AFTER the stop
        ])
        out = excursions(_sig(), m5)
        self.assertTrue(out["filled"])
        self.assertAlmostEqual(out["mae"], 1.0, places=6)
        self.assertAlmostEqual(out["mfe"], 0.0, places=6)
        self.assertAlmostEqual(out["skew"], -1.0, places=6)

    def test_favourable_first_is_kept_in_full(self):
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY + 3.0 * RISK, ENTRY),             # +3R first
            (ENTRY, ENTRY - 1.0 * RISK),             # then stopped
        ])
        out = excursions(_sig(), m5)
        self.assertAlmostEqual(out["mfe"], 3.0, places=6)
        self.assertAlmostEqual(out["mae"], 1.0, places=6)
        self.assertAlmostEqual(out["skew"], 2.0, places=6)
        self.assertTrue(out["hit_2r_before_1r"])

    def test_same_bar_ambiguity_resolves_adverse_first(self):
        """A bar containing both +3R and -1R cannot be ordered. Resolve
        pessimistically, matching poc_sb_stops.resolve's SL-first rule."""
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY + 3.0 * RISK, ENTRY - 1.0 * RISK),
        ])
        out = excursions(_sig(), m5)
        self.assertAlmostEqual(out["mfe"], 0.0, places=6)
        self.assertAlmostEqual(out["mae"], 1.0, places=6)
        self.assertFalse(out["hit_2r_before_1r"])

    def test_sell_direction_mirrors_the_geometry(self):
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY, ENTRY - 3.0 * RISK),             # favourable for a SELL
            (ENTRY + 1.0 * RISK, ENTRY),             # adverse for a SELL
        ])
        out = excursions(_sig(direction="SELL"), m5)
        self.assertAlmostEqual(out["mfe"], 3.0, places=6)
        self.assertAlmostEqual(out["mae"], 1.0, places=6)

    def test_exact_2r_boundary_sets_hit_2r_flag(self):
        """Regression test for floating-point precision at the 2.0R boundary.
        Using RISK=0.0005 produces a 2.0R level that rounds BELOW 2.0 due to
        IEEE 754 precision (1.9999999999997797). The tolerance check
        (favourable >= 2.0 - _R_EPS) must catch this; strict >= 2.0 would fail."""
        risk_2r = 0.0005
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY + 2.0 * risk_2r, ENTRY),  # Rounds below 2.0
        ], start=T0, step_min=5)
        # Compute expected: (ENTRY + 2.0*risk_2r - ENTRY) / risk_2r
        expected_fav = (ENTRY + 2.0 * risk_2r - ENTRY) / risk_2r
        self.assertLess(expected_fav, 2.0, "Sanity check: 2R should round below 2.0")

        sig_local = {"entry": ENTRY, "risk": risk_2r, "dir": "BUY",
                     "time": T0, "symbol": "EURUSD"}
        out = excursions(sig_local, m5, h_bars=12, w_bars=12)
        self.assertTrue(out["filled"])
        self.assertTrue(out["hit_2r_before_1r"],
                       "hit_2r_before_1r should be True even when favourable < 2.0")
        self.assertAlmostEqual(out["mfe"], 2.0, places=4)


class TestUnfilled(unittest.TestCase):
    def test_untouched_level_scores_zero_and_is_still_returned(self):
        """Never touched within W. The realizable outcome of a signal that
        never becomes a position is exactly 0 — and it must NOT be dropped,
        because dropping it selects on a post-signal event."""
        m5 = _m5([(ENTRY + 5 * RISK, ENTRY + 4 * RISK)] * 200)
        out = excursions(_sig(), m5)
        self.assertFalse(out["filled"])
        self.assertIsNone(out["touch_idx"])
        self.assertEqual(out["skew"], 0.0)
        self.assertEqual(out["mfe"], 0.0)
        self.assertEqual(out["mae"], 0.0)

    def test_touch_after_the_wait_window_does_not_count(self):
        """W_BARS = 12 H1 bars = 144 M5 bars. A touch at bar 200 is too late."""
        bars = [(ENTRY + 5 * RISK, ENTRY + 4 * RISK)] * 200
        bars.append((ENTRY, ENTRY))
        out = excursions(_sig(), _m5(bars))
        self.assertFalse(out["filled"])


class TestLookAhead(unittest.TestCase):
    def test_bars_beyond_the_horizon_do_not_change_skew(self):
        """The horizon is as leakable as the features. H_BARS = 12 H1 bars
        = 144 M5 bars from the touch; anything past that is the future."""
        head = [(ENTRY, ENTRY)] + [(ENTRY, ENTRY)] * 200
        short = excursions(_sig(), _m5(head))
        long = excursions(_sig(), _m5(head + [(ENTRY + 99 * RISK, ENTRY)] * 50))
        self.assertAlmostEqual(short["skew"], long["skew"], places=9)
        self.assertAlmostEqual(short["mfe"], long["mfe"], places=9)


if __name__ == "__main__":
    unittest.main()
