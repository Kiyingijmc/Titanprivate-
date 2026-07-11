# tests/unit/test_ote_structure.py
import unittest

from src.analysis.ote_structure import (
    is_swing_high, is_swing_low, confirmed_swings, structure_bias,
)
from src.analysis.ote_structure import impulse_leg, ote_zone, zone_invalidation
from src.analysis.ote_structure import precompute_last_swings, mss_confirm
from src.analysis.ote_structure import (
    stop_anchor, advance_setup, AWAIT_ZONE, IN_ZONE, CONFIRMED, DEAD,
)

# lk=2 fixture: confirmed swing high at j=2 (7.0), usable from i>=5 (j+lk<i)
M5H = [5.0, 6.0, 7.0, 6.0, 5.0, 6.0, 7.5]
M5L = [4.0, 5.0, 6.0, 5.0, 4.0, 5.0, 6.5]
M5C = [4.5, 5.5, 6.5, 5.5, 4.5, 5.8, 7.2]

# Shared fixture: lk=1 uptrend with confirmed HH+HL.
# Swing highs at j=2 (10) and j=6 (12); swing lows at j=4 (8) and j=8 (9).
HIGHS = [9.0, 9.5, 10.0, 9.2, 8.5, 9.5, 12.0, 10.0, 9.5, 10.5, 11.0]
LOWS  = [8.5, 9.0,  9.5, 8.8, 8.0, 9.0, 11.0,  9.2, 9.0,  9.8, 10.2]


class TestSwings(unittest.TestCase):
    def test_swing_high_strict(self):
        self.assertTrue(is_swing_high(HIGHS, 2, 1))
        self.assertFalse(is_swing_high(HIGHS, 3, 1))
        # ties are NOT swings (strict inequality)
        self.assertFalse(is_swing_high([1.0, 2.0, 2.0], 1, 1))

    def test_swing_low_strict(self):
        self.assertTrue(is_swing_low(LOWS, 4, 1))
        self.assertFalse(is_swing_low(LOWS, 5, 1))

    def test_confirmed_swings_indices(self):
        his, los = confirmed_swings(HIGHS, LOWS, 1)
        self.assertEqual(his, [2, 6])
        self.assertEqual(los, [4, 8])


class TestStructureBias(unittest.TestCase):
    def test_uptrend_turns_bullish_only_after_confirmation(self):
        bias = structure_bias(HIGHS, LOWS, lk=1)
        # SL@8 confirms at bar 9 (j+lk); before that, <2 confirmed lows -> NEUTRAL
        self.assertEqual(bias[8], "NEUTRAL")
        self.assertEqual(bias[9], "BULLISH")   # HH (12>10) and HL (9>8)
        self.assertEqual(bias[10], "BULLISH")

    def test_downtrend_mirror(self):
        h = [x for x in reversed(HIGHS)]
        l = [x for x in reversed(LOWS)]
        # reversed series trends down; find at least one BEARISH bar at the end
        bias = structure_bias(h, l, lk=1)
        self.assertIn("BEARISH", bias)
        self.assertEqual(bias[-1], "BEARISH")

    def test_short_series_all_neutral(self):
        self.assertEqual(structure_bias([1.0, 2.0], [0.5, 1.5], lk=3),
                         ["NEUTRAL", "NEUTRAL"])


class TestImpulseLeg(unittest.TestCase):
    def test_bullish_leg_found(self):
        # HIGHS/LOWS fixture: SWH 6 (12) broke SWH 2 (10) -> BOS up;
        # origin = most recent confirmed swing low before it = idx 4 (8.0)
        leg = impulse_leg(HIGHS, LOWS, upto=10, lk=1, bias="BULLISH")
        self.assertEqual(leg, (8.0, 12.0, 4, 6))

    def test_fast_path_matches_slow_path(self):
        swh, swl = confirmed_swings(HIGHS, LOWS, 1)
        slow = impulse_leg(HIGHS, LOWS, 10, 1, "BULLISH")
        fast = impulse_leg(HIGHS, LOWS, 10, 1, "BULLISH", swh, swl)
        self.assertEqual(slow, fast)

    def test_fast_path_matches_slow_path_across_confirmation_boundary(self):
        # Guards the cutoff FORMULA (upto - lk), not just fast==slow at the last
        # index. upto=10 alone is non-discriminating: the slow path's
        # highs[:upto+1] truncation is a no-op and cutoff=9 >= every swing index,
        # so a wrong cutoff (e.g. = upto) would still agree.
        # At upto=6 the swing high at index 6 is NOT yet confirmed (needs bar 7),
        # so BOTH paths must exclude it and return None. The fast path can only do
        # so if cutoff = upto - lk (=5) actively drops swh index 6; a wrong cutoff
        # (= upto = 6) would include it, find a BOS leg, and diverge from None.
        swh, swl = confirmed_swings(HIGHS, LOWS, 1)
        for upto in (6, 8, 10):
            slow = impulse_leg(HIGHS, LOWS, upto, 1, "BULLISH")
            fast = impulse_leg(HIGHS, LOWS, upto, 1, "BULLISH", swh, swl)
            self.assertEqual(slow, fast, f"fast/slow diverged at upto={upto}")
        # Pin the discriminating boundary explicitly: at upto=6 the leg is not yet
        # confirmed (None); by upto=8 the same leg is found via the cutoff, not
        # via array truncation (swing low at index 8 is excluded by cutoff=7).
        self.assertIsNone(impulse_leg(HIGHS, LOWS, 6, 1, "BULLISH", swh, swl))
        self.assertEqual(
            impulse_leg(HIGHS, LOWS, 8, 1, "BULLISH", swh, swl),
            (8.0, 12.0, 4, 6),
        )

    def test_no_leg_when_neutral_or_no_bos(self):
        self.assertIsNone(impulse_leg(HIGHS, LOWS, 10, 1, "NEUTRAL"))
        flat_h = [10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0]
        flat_l = [9.0, 10.0, 9.0, 10.0, 9.0, 10.0, 9.0]
        self.assertIsNone(impulse_leg(flat_h, flat_l, 6, 1, "BULLISH"))

    def test_bearish_mirror(self):
        h = [x for x in reversed(HIGHS)]
        l = [x for x in reversed(LOWS)]
        leg = impulse_leg(h, l, upto=10, lk=1, bias="BEARISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high, lo_idx, hi_idx = leg
        self.assertLess(leg_low, leg_high)
        self.assertGreater(lo_idx, hi_idx)   # bear leg: high first, low after


class TestOteZone(unittest.TestCase):
    def test_bull_zone_measured_down_from_high(self):
        z_lo, z_hi = ote_zone(8.0, 12.0, "BULLISH")
        self.assertAlmostEqual(z_lo, 12.0 - 0.79 * 4.0)   # 8.84
        self.assertAlmostEqual(z_hi, 12.0 - 0.62 * 4.0)   # 9.52

    def test_bear_zone_measured_up_from_low(self):
        z_lo, z_hi = ote_zone(8.0, 12.0, "BEARISH")
        self.assertAlmostEqual(z_lo, 8.0 + 0.62 * 4.0)    # 10.48
        self.assertAlmostEqual(z_hi, 8.0 + 0.79 * 4.0)    # 11.16


class TestZoneInvalidation(unittest.TestCase):
    def test_long_below_zone_bottom(self):
        self.assertAlmostEqual(zone_invalidation(8.84, 9.52, 1.0, True), 8.74)

    def test_short_above_zone_top(self):
        self.assertAlmostEqual(zone_invalidation(10.48, 11.16, 1.0, False), 11.26)


class TestMssConfirm(unittest.TestCase):
    def test_precompute_last_swings(self):
        swh, swl = precompute_last_swings(M5H, M5L, 2)
        self.assertEqual(swh, [-1, -1, -1, -1, -1, 2, 2])
        self.assertEqual(swl, [-1, -1, -1, -1, -1, -1, -1])

    def test_bull_mss_fires_only_on_break(self):
        swh, swl = precompute_last_swings(M5H, M5L, 2)
        self.assertFalse(mss_confirm(M5H, M5L, M5C, 5, "BULLISH", swh, swl))
        self.assertTrue(mss_confirm(M5H, M5L, M5C, 6, "BULLISH", swh, swl))

    def test_no_swing_yet_no_mss(self):
        swh, swl = precompute_last_swings(M5H, M5L, 2)
        self.assertFalse(mss_confirm(M5H, M5L, M5C, 4, "BULLISH", swh, swl))

    def test_bear_mirror(self):
        h = [-x for x in M5L]   # mirror the geometry
        l = [-x for x in M5H]
        c = [-x for x in M5C]
        swh, swl = precompute_last_swings(h, l, 2)
        self.assertTrue(mss_confirm(h, l, c, 6, "BEARISH", swh, swl))
        self.assertFalse(mss_confirm(h, l, c, 5, "BEARISH", swh, swl))


class TestStopAnchor(unittest.TestCase):
    def test_long_takes_most_protective(self):
        # floor: 100 - 0.5*2 = 99; pullback 99.5; inval 99.2 -> min = 99.0
        self.assertAlmostEqual(stop_anchor(100.0, 99.5, 99.2, 2.0, True), 99.0)
        # deep pullback dominates
        self.assertAlmostEqual(stop_anchor(100.0, 98.5, 99.2, 2.0, True), 98.5)

    def test_short_mirror(self):
        self.assertAlmostEqual(stop_anchor(100.0, 100.5, 100.8, 2.0, False), 101.0)
        self.assertAlmostEqual(stop_anchor(100.0, 101.5, 100.8, 2.0, False), 101.5)

    def test_distance_never_below_floor(self):
        sl = stop_anchor(100.0, 99.9, 99.95, 2.0, True)
        self.assertGreaterEqual(100.0 - sl, 0.5 * 2.0)


class TestAdvanceSetup(unittest.TestCase):
    # long setup: zone (8.84, 9.52), leg origin 8.0
    Z = dict(is_long=True, z_lo=8.84, z_hi=9.52, leg_origin=8.0)

    def _adv(self, state, hi, lo, close, mss=False):
        return advance_setup(state, self.Z["is_long"], self.Z["z_lo"],
                             self.Z["z_hi"], self.Z["leg_origin"],
                             hi, lo, close, mss)

    def test_waits_above_zone(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.6, 9.8), AWAIT_ZONE)

    def test_touch_enters_zone(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.4, 9.6), IN_ZONE)

    def test_mss_only_counts_in_zone(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.6, 9.8, mss=True), AWAIT_ZONE)
        self.assertEqual(self._adv(IN_ZONE, 10.0, 9.6, 9.8, mss=True), CONFIRMED)

    def test_same_bar_touch_and_mss_confirms(self):
        # documented accepted edge: touch + MSS on one bar -> CONFIRMED
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.4, 9.9, mss=True), CONFIRMED)

    def test_leg_origin_breach_kills(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 9.0, 7.9, 8.2), DEAD)
        self.assertEqual(self._adv(IN_ZONE, 9.0, 7.9, 8.2), DEAD)

    def test_terminal_states_stick(self):
        self.assertEqual(self._adv(DEAD, 10.0, 9.4, 9.6, mss=True), DEAD)
        self.assertEqual(self._adv(CONFIRMED, 10.0, 9.4, 9.6), CONFIRMED)

    def test_short_mirror_touch_and_kill(self):
        # short: zone (10.48, 11.16), origin 12.0
        self.assertEqual(advance_setup(AWAIT_ZONE, False, 10.48, 11.16, 12.0,
                                       10.6, 10.0, 10.3, False), IN_ZONE)
        self.assertEqual(advance_setup(IN_ZONE, False, 10.48, 11.16, 12.0,
                                       12.1, 11.0, 11.5, False), DEAD)


if __name__ == "__main__":
    unittest.main()
