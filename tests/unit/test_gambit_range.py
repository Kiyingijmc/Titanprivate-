import unittest
from datetime import datetime, timedelta
import pytz

from src.strategies.models.gambit_setups import compute_presession_range

NY = pytz.timezone("US/Eastern")


def bars(start_ny, n, step_min=5):
    """n bar-open datetimes from start (NY wall clock), M5 spacing."""
    t0 = NY.localize(start_ny)
    return [t0 + timedelta(minutes=step_min * i) for i in range(n)]


class TestPresessionRange(unittest.TestCase):
    def test_ny_am_range_basic(self):
        # Bars 02:00 .. 08:55 NY; last bar inside the NY-AM window (09:00).
        ts = bars(datetime(2026, 7, 15, 2, 0), 85)   # 02:00 .. 09:00
        highs = [10.0 + i for i in range(85)]
        lows = [5.0 - i for i in range(85)]
        # range 02:00 (120) -> 08:30 (510): bars idx 0..77 (opens < 08:30)
        out = compute_presession_range(ts, highs, lows, 120, 510)
        self.assertIsNotNone(out)
        hi, lo, n = out
        self.assertEqual(n, 78)
        self.assertEqual(hi, 10.0 + 77)
        self.assertEqual(lo, 5.0 - 77)

    def test_bar_at_range_end_excluded(self):
        # A bar opening exactly at 08:30 belongs to the session, not the range.
        ts = bars(datetime(2026, 7, 15, 8, 25), 3)   # 08:25, 08:30, 08:35
        out = compute_presession_range(ts, [1, 99, 99], [0, -99, -99],
                                       120, 510, min_bars=1)
        hi, lo, n = out
        self.assertEqual(n, 1)
        self.assertEqual(hi, 1)

    def test_london_range_crosses_midnight(self):
        # 18:00 prev day -> 02:00: start > end. Bars 18:00 Jul14 .. 03:00 Jul15.
        ts = bars(datetime(2026, 7, 14, 18, 0), 109)  # 18:00 .. 03:00 next day
        highs = [float(i) for i in range(109)]
        lows = [float(-i) for i in range(109)]
        # range bars: opens in [18:00 Jul14, 02:00 Jul15) = idx 0..95 (96 bars)
        out = compute_presession_range(ts, highs, lows, 18 * 60, 120)
        hi, lo, n = out
        self.assertEqual(n, 96)
        self.assertEqual(hi, 95.0)

    def test_too_few_bars_returns_none(self):
        ts = bars(datetime(2026, 7, 15, 8, 0), 8)    # only 6 bars before 08:30
        out = compute_presession_range(ts, [1] * 8, [0] * 8, 120, 510)
        self.assertIsNone(out)

    def test_anchor_is_most_recent_boundary(self):
        # Two days of bars: the range must come from TODAY's pre-session,
        # not yesterday's.
        ts = (bars(datetime(2026, 7, 14, 2, 0), 78)          # yesterday's range bars
              + bars(datetime(2026, 7, 15, 2, 0), 79))       # today's range + 08:30 bar
        highs = [1.0] * 78 + [50.0] * 79
        lows = [-1.0] * 78 + [-50.0] * 79
        out = compute_presession_range(ts, highs, lows, 120, 510)
        hi, lo, n = out
        self.assertEqual(hi, 50.0)
        self.assertEqual(lo, -50.0)
        self.assertEqual(n, 78)


if __name__ == "__main__":
    unittest.main()
