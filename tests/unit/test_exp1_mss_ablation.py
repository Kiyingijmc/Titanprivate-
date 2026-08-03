"""EXP-1 MSS-ablation rig — the pre-registration's verification tier (§3).

Covers the four places the pairing can silently go wrong: touch-bar
resolution, the confirmation window boundary at H1 bar i+12, the B1/B2
anchoring arithmetic, and the drop rules that keep all four gate cells on an
identical pair set.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts.exp1_mss_ablation import (  # noqa: E402
    m5_subrange, find_touch, find_mss, build_variant, resolve_from,
    paired_bootstrap, verdict, RR, LK_M5,
)
from src.analysis.ict_structure import precompute_last_swings  # noqa: E402


def _t5(n, start="2026-01-01T00:00"):
    """n consecutive M5 timestamps."""
    return np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(5 * n, "m"),
                     np.timedelta64(5, "m"))


def _t1h(n, start="2026-01-01T00:00"):
    return np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(60 * n, "m"),
                     np.timedelta64(60, "m"))


class TestSubrange(unittest.TestCase):
    def test_maps_each_h1_bar_to_its_twelve_m5_bars(self):
        h1, m5 = _t1h(3), _t5(36)
        self.assertEqual(m5_subrange(h1, m5, 0), (0, 12))
        self.assertEqual(m5_subrange(h1, m5, 1), (12, 24))

    def test_last_h1_bar_runs_to_end_of_m5(self):
        h1, m5 = _t1h(3), _t5(30)      # last H1 bar only partly filled
        self.assertEqual(m5_subrange(h1, m5, 2), (24, 30))

    def test_gap_between_h1_bars_yields_empty_range(self):
        # Weekend: H1 bars exist either side, no M5 bars in between.
        h1 = np.array([np.datetime64("2026-01-02T20:00"),
                       np.datetime64("2026-01-05T00:00")])
        m5 = np.array([np.datetime64("2026-01-05T00:00")])
        self.assertEqual(m5_subrange(h1, m5, 0), (0, 0))


class TestFindTouch(unittest.TestCase):
    def test_returns_first_m5_bar_spanning_entry(self):
        lows = np.array([10.0, 9.0, 8.0, 7.0])
        highs = np.array([11.0, 10.0, 9.0, 8.0])
        self.assertEqual(find_touch(lows, highs, 0, 4, 9.5), 1)

    def test_none_when_no_single_bar_spans_entry(self):
        # H1 extremes bracket 9.5, but the M5 path gaps straight over it.
        lows = np.array([10.0, 5.0])
        highs = np.array([11.0, 6.0])
        self.assertIsNone(find_touch(lows, highs, 0, 2, 9.5))

    def test_respects_the_search_window(self):
        lows = np.array([10.0, 9.0, 8.0])
        highs = np.array([11.0, 10.0, 9.0])
        self.assertIsNone(find_touch(lows, highs, 2, 3, 9.5))


class TestFindMssWindow(unittest.TestCase):
    """The window boundary is the registered TTL horizon; an MSS one bar late
    must not be accepted, or arm B silently gets lookahead arm A never had."""

    def _series(self):
        # Rising staircase with one pullback, so a confirmed swing high exists
        # and a later close breaks it.
        highs = [10, 11, 12, 11, 10, 11, 12, 13, 14, 15]
        lows = [9, 10, 11, 10, 9, 10, 11, 12, 13, 14]
        closes = [9.5, 10.5, 11.5, 10.5, 9.5, 10.5, 11.5, 12.5, 13.5, 14.5]
        swh, swl = precompute_last_swings(highs, lows, LK_M5)
        return highs, lows, closes, swh, swl

    def test_finds_a_shift_inside_the_window(self):
        h, l, c, swh, swl = self._series()
        k = find_mss(h, l, c, 0, len(c), "BULLISH", swh, swl)
        self.assertIsNotNone(k)

    def test_shift_one_bar_past_the_window_is_rejected(self):
        h, l, c, swh, swl = self._series()
        k = find_mss(h, l, c, 0, len(c), "BULLISH", swh, swl)
        self.assertIsNone(find_mss(h, l, c, 0, k, "BULLISH", swh, swl))
        self.assertEqual(find_mss(h, l, c, 0, k + 1, "BULLISH", swh, swl), k)

    def test_window_that_ends_before_it_starts_finds_nothing(self):
        h, l, c, swh, swl = self._series()
        self.assertIsNone(find_mss(h, l, c, 5, 5, "BULLISH", swh, swl))


class TestAnchoringArithmetic(unittest.TestCase):
    def setUp(self):
        self.sig_buy = {"dir": "BUY", "atr": 2.0}
        self.sig_sell = {"dir": "SELL", "atr": 2.0}
        # Arm A: BUY at 100, ATR10 stop 1.0*ATR below.
        self.tr_buy = {"entry": 100.0, "sl": 98.0, "risk": 2.0}
        self.tr_sell = {"entry": 100.0, "sl": 102.0, "risk": 2.0}

    def test_b1_freezes_the_stop_price_and_widens_risk(self):
        geom, err = build_variant("B1", self.sig_buy, self.tr_buy, 100.6)
        self.assertIsNone(err)
        self.assertEqual(geom["sl"], 98.0)                  # frozen
        self.assertAlmostEqual(geom["risk"], 2.6)           # widened
        self.assertAlmostEqual(geom["tp"], 100.6 + RR * 2.6)

    def test_b2_freezes_risk_at_one_atr_and_moves_the_stop(self):
        geom, err = build_variant("B2", self.sig_buy, self.tr_buy, 100.6)
        self.assertIsNone(err)
        self.assertAlmostEqual(geom["risk"], 2.0)           # frozen
        self.assertAlmostEqual(geom["sl"], 98.6)            # moved up with entry
        self.assertAlmostEqual(geom["tp"], 100.6 + RR * 2.0)

    def test_sell_side_mirrors(self):
        b1, _ = build_variant("B1", self.sig_sell, self.tr_sell, 99.4)
        self.assertEqual(b1["sl"], 102.0)
        self.assertAlmostEqual(b1["risk"], 2.6)
        self.assertAlmostEqual(b1["tp"], 99.4 - RR * 2.6)
        b2, _ = build_variant("B2", self.sig_sell, self.tr_sell, 99.4)
        self.assertAlmostEqual(b2["sl"], 101.4)
        self.assertAlmostEqual(b2["tp"], 99.4 - RR * 2.0)

    def test_b1_rejects_an_entry_past_the_frozen_stop(self):
        # MSS printed only after price already ran through arm A's stop:
        # there is no coherent stop-anchored counterfactual.
        geom, err = build_variant("B1", self.sig_buy, self.tr_buy, 97.0)
        self.assertIsNone(geom)
        self.assertEqual(err, "B1_STOP_CROSSED")

    def test_b1_rejects_entry_exactly_on_the_stop(self):
        geom, err = build_variant("B1", self.sig_buy, self.tr_buy, 98.0)
        self.assertIsNone(geom)
        self.assertEqual(err, "B1_STOP_CROSSED")

    def test_b2_zero_atr_is_rejected(self):
        geom, err = build_variant("B2", {"dir": "BUY", "atr": 0.0},
                                  self.tr_buy, 100.6)
        self.assertIsNone(geom)
        self.assertEqual(err, "ZERO_RISK")


class TestResolveFrom(unittest.TestCase):
    def _bars(self, highs, lows):
        return {"high": np.array(highs, dtype=float),
                "low": np.array(lows, dtype=float)}

    def test_same_bar_sl_and_tp_resolves_to_sl(self):
        """Arm A's pessimistic convention; arm B must not get a better one."""
        bars = self._bars([106.0], [98.0])
        outcome, r, _ = resolve_from(bars, 0, 100.0, 99.0, 102.0, True)
        self.assertEqual(outcome, "SL")
        self.assertEqual(r, -1.0)

    def test_take_profit_pays_rr(self):
        bars = self._bars([100.5, 102.5], [99.5, 101.0])
        outcome, r, idx = resolve_from(bars, 0, 100.0, 99.0, 102.0, True)
        self.assertEqual((outcome, r, idx), ("TP", RR, 1))

    def test_short_side_mirrors(self):
        bars = self._bars([100.5, 100.2], [99.5, 97.5])
        outcome, r, idx = resolve_from(bars, 0, 100.0, 101.0, 98.0, False)
        self.assertEqual((outcome, r, idx), ("TP", RR, 1))

    def test_unresolved_by_end_of_data_is_open(self):
        bars = self._bars([100.5, 100.4], [99.5, 99.6])
        outcome, r, _ = resolve_from(bars, 0, 100.0, 99.0, 102.0, True)
        self.assertEqual(outcome, "OPEN")

    def test_starts_at_the_given_bar_not_bar_zero(self):
        # Bar 0 would have stopped out; arm B entered at bar 1 and must not
        # inherit price action that predates its entry hour.
        bars = self._bars([100.0, 100.5, 102.5], [95.0, 99.5, 101.0])
        outcome, _, _ = resolve_from(bars, 1, 100.0, 99.0, 102.0, True)
        self.assertEqual(outcome, "TP")


class TestGateMechanics(unittest.TestCase):
    def _cells(self, delta, lo, hi):
        return {k: {"delta": delta, "ci": (lo, hi)}
                for k in (("FIXED", "B1"), ("FIXED", "B2"),
                          ("RUNNER", "B1"), ("RUNNER", "B2"))}

    def test_bootstrap_is_deterministic_and_brackets_the_mean(self):
        deltas = list(np.linspace(-1.0, 1.0, 400))
        a = paired_bootstrap(deltas)
        self.assertEqual(a, paired_bootstrap(deltas))
        self.assertLess(a[0], np.mean(deltas))
        self.assertGreater(a[1], np.mean(deltas))

    def test_outcome_a_needs_every_cell_negative(self):
        self.assertIn("OUTCOME A", verdict(self._cells(-0.10, -0.15, -0.05), 800))

    def test_outcome_b_when_ci_spans_zero(self):
        self.assertIn("OUTCOME B", verdict(self._cells(-0.10, -0.20, 0.02), 800))

    def test_outcome_c_needs_every_cell_positive(self):
        self.assertIn("OUTCOME C", verdict(self._cells(0.10, 0.05, 0.15), 800))

    def test_one_disagreeing_cell_forces_inconclusive(self):
        cells = self._cells(-0.10, -0.15, -0.05)
        cells[("RUNNER", "B2")] = {"delta": 0.10, "ci": (0.05, 0.15)}
        self.assertIn("INCONCLUSIVE", verdict(cells, 800))

    def test_below_five_hundred_pairs_is_directional_only(self):
        v = verdict(self._cells(-0.10, -0.15, -0.05), 400)
        self.assertIn("OUTCOME A", v)
        self.assertIn("DIRECTIONAL ONLY", v)

    def test_below_three_hundred_pairs_yields_no_verdict(self):
        v = verdict(self._cells(-0.10, -0.15, -0.05), 299)
        self.assertIn("INCONCLUSIVE", v)
        self.assertNotIn("OUTCOME", v)


if __name__ == "__main__":
    unittest.main()
