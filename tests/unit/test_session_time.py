import unittest

from src.analysis.session_time import (
    infer_ny_shift, ny_bucket, KILLZONES, OUTSIDE,
)


class TestShiftInference(unittest.TestCase):
    def test_week_opening_at_broker_midnight_gives_shift_17(self):
        # the FX week opens Sunday 17:00 NY; if that lands on broker hour 0
        # then broker 00:00 IS 17:00 NY -> shift = +17.
        # This is the real measured value for FBS.
        self.assertEqual(infer_ny_shift([0] * 50), 17)

    def test_shift_tracks_the_open_hour(self):
        # a feed whose week opens at broker 01:00 (metals behave this way)
        self.assertEqual(infer_ny_shift([1] * 50), 16)

    def test_tolerates_a_minority_of_odd_weeks(self):
        # 49 of 50 at hour 0 - holidays and short weeks must not derail it
        self.assertEqual(infer_ny_shift([0] * 49 + [23]), 17)

    def test_rejects_an_unstable_open_hour(self):
        # a 50/50 split means the anchor is not identifiable
        with self.assertRaises(ValueError):
            infer_ny_shift([0] * 25 + [1] * 25)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            infer_ny_shift([])


class TestBuckets(unittest.TestCase):
    def test_three_killzones_plus_outside(self):
        self.assertEqual(set(KILLZONES), {"London KZ", "NY AM", "NY PM"})
        self.assertEqual(OUTSIDE, "Outside")

    def test_london_killzone(self):
        # broker 09:00 with shift 17 -> (9+17)%24 = 02:00 NY -> London KZ
        self.assertEqual(ny_bucket(9, 17), "London KZ")

    def test_ny_am(self):
        # broker 15:00 -> 08:00 NY
        self.assertEqual(ny_bucket(15, 17), "NY AM")

    def test_ny_pm(self):
        # broker 20:00 -> 13:00 NY
        self.assertEqual(ny_bucket(20, 17), "NY PM")

    def test_outside(self):
        # broker 05:00 -> 22:00 NY
        self.assertEqual(ny_bucket(5, 17), "Outside")

    def test_boundaries_are_end_exclusive(self):
        # every window's END hour falls OUTSIDE it.
        # (broker + 17) % 24 = NY hour
        self.assertEqual(ny_bucket(17, 17), "NY AM")    # 34%24 = 10, inside (8,11)
        self.assertEqual(ny_bucket(18, 17), "Outside")  # 35%24 = 11, end-exclusive
        self.assertEqual(ny_bucket(11, 17), "London KZ")  # 28%24 =  4, inside (2,5)
        self.assertEqual(ny_bucket(12, 17), "Outside")  # 29%24 =  5, end-exclusive
        self.assertEqual(ny_bucket(22, 17), "NY PM")    # 39%24 = 15, inside (13,16)
        self.assertEqual(ny_bucket(23, 17), "Outside")  # 40%24 = 16, end-exclusive
