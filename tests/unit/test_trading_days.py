"""Trading-day calendar utility for the Almanac turn-of-month canary.

Weekday-based (Mon-Fri): exchange holidays are deliberately ignored -- a
documented approximation, acceptable for a canary whose purpose is
live-vs-backtest divergence detection with one deterministic rule on both
sides. Known dates used below:

  2026-07-31 Fri = last trading day of July 2026
  2026-08-03 Mon = trading day 1 of August 2026 (Aug 1-2 are the weekend)
  2026-08-05 Wed = trading day 3, 2026-08-06 Thu = trading day 4
  2026-12-31 Thu = last trading day of December 2026
  2027-01-06 Wed = trading day 4 of January 2027 (Jan 1 Fri counts as TD1)
"""
import unittest
from datetime import date

from src.analysis import trading_days as td


class TestTradingDayIndex(unittest.TestCase):
    def test_first_weekday_of_month_is_index_1(self):
        self.assertEqual(td.trading_day_index(date(2026, 8, 3)), 1)

    def test_mid_month_index(self):
        self.assertEqual(td.trading_day_index(date(2026, 8, 5)), 3)
        self.assertEqual(td.trading_day_index(date(2026, 8, 6)), 4)

    def test_weekend_is_index_0(self):
        self.assertEqual(td.trading_day_index(date(2026, 8, 1)), 0)  # Saturday
        self.assertEqual(td.trading_day_index(date(2026, 8, 2)), 0)  # Sunday

    def test_month_starting_on_weekday(self):
        # January 2027 starts on Friday -> Jan 1 is TD1 (holidays ignored).
        self.assertEqual(td.trading_day_index(date(2027, 1, 1)), 1)
        self.assertEqual(td.trading_day_index(date(2027, 1, 6)), 4)


class TestLastTradingDay(unittest.TestCase):
    def test_month_ending_on_friday(self):
        self.assertEqual(td.last_trading_day(2026, 7), date(2026, 7, 31))
        self.assertTrue(td.is_last_trading_day(date(2026, 7, 31)))

    def test_month_ending_on_weekend_rolls_back(self):
        # May 2026 ends on Sunday the 31st -> last trading day Fri May 29.
        self.assertEqual(td.last_trading_day(2026, 5), date(2026, 5, 29))
        self.assertFalse(td.is_last_trading_day(date(2026, 5, 31)))

    def test_december_rollover(self):
        self.assertEqual(td.last_trading_day(2026, 12), date(2026, 12, 31))

    def test_mid_month_is_not_last(self):
        self.assertFalse(td.is_last_trading_day(date(2026, 7, 15)))


class TestEffectiveTradingDay(unittest.TestCase):
    def test_weekday_is_itself(self):
        self.assertEqual(td.effective_trading_day(date(2026, 8, 5)), date(2026, 8, 5))

    def test_weekend_maps_to_prior_friday(self):
        self.assertEqual(td.effective_trading_day(date(2026, 8, 2)), date(2026, 7, 31))


class TestShouldTimeExit(unittest.TestCase):
    """Entry is the last trading day of its month; exit fires on the first
    check AFTER the close of trading day `exit_trading_day` of the next month
    (i.e. from trading day 4 onward with the default of 3)."""

    ENTRY = date(2026, 7, 31)

    def test_entry_day_holds(self):
        self.assertFalse(td.should_time_exit(date(2026, 7, 31), self.ENTRY, 3))

    def test_weekend_after_entry_holds(self):
        self.assertFalse(td.should_time_exit(date(2026, 8, 1), self.ENTRY, 3))
        self.assertFalse(td.should_time_exit(date(2026, 8, 2), self.ENTRY, 3))

    def test_trading_days_1_to_3_hold(self):
        for d in (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)):
            self.assertFalse(td.should_time_exit(d, self.ENTRY, 3), d)

    def test_trading_day_4_exits(self):
        self.assertTrue(td.should_time_exit(date(2026, 8, 6), self.ENTRY, 3))

    def test_weekend_after_exit_day_exits(self):
        # Sat Aug 8: effective day is Fri Aug 7 = TD5 -> past the window.
        self.assertTrue(td.should_time_exit(date(2026, 8, 8), self.ENTRY, 3))

    def test_runaway_hold_two_months_out_always_exits(self):
        self.assertTrue(td.should_time_exit(date(2026, 9, 15), self.ENTRY, 3))

    def test_year_rollover(self):
        entry = date(2026, 12, 31)
        self.assertFalse(td.should_time_exit(date(2027, 1, 5), entry, 3))  # TD3
        self.assertTrue(td.should_time_exit(date(2027, 1, 6), entry, 3))   # TD4


if __name__ == "__main__":
    unittest.main()
