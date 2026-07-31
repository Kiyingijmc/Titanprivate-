# ==============================================================================
# FILE: tests/unit/test_news_manager_timezone.py
# ForexFactory publishes calendar times in UTC. NewsManager parsed them into a
# NAIVE datetime and compared them against datetime.now() -- the host's LOCAL
# clock (Africa/Kampala, UTC+3). Every blackout window therefore fired 3 hours
# early and the real release traded unprotected.
#
# CSV timezone confirmed 2026-07-31 against three known release times:
#   FOMC Statement        6:00pm  = 18:00 UTC (14:00 ET)
#   FOMC Press Conference 6:30pm  = 18:30 UTC (14:30 ET)
#   Advance GDP/Core PCE 12:30pm  = 12:30 UTC (08:30 ET)
# Were the file in US Eastern, FOMC would read 2:00pm.
# ==============================================================================

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news_manager import NewsManager


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


# Real rows from nfs.faireconomy.media/ff_calendar_thisweek.csv (fetched 2026-07-31).
_CSV = (
    "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
    "FOMC Statement,USD,07-29-2026,6:00pm,High,,,https://example.test/1\n"
    "Core PCE Price Index m/m,USD,07-30-2026,12:30pm,High,0.3%,0.2%,https://example.test/2\n"
)


def _loaded_manager():
    manager = NewsManager(_StubLogger())
    assert manager._parse_csv_data(_CSV) is True, "fixture CSV must parse"
    return manager


class ForexFactoryTimesAreUtc(unittest.TestCase):
    def test_six_pm_row_parses_to_1800_utc(self):
        """The FOMC row reads 6:00pm and must land on 18:00Z, tz-aware."""
        manager = _loaded_manager()
        fomc = next(e for e in manager.high_impact_events
                    if e["title"] == "FOMC Statement")
        self.assertEqual(fomc["time"],
                         datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc))


class BlackoutTracksTheRealReleaseTime(unittest.TestCase):
    def test_blocks_thirty_minutes_before_release(self):
        """Core PCE releases 12:30Z, so 12:00Z is inside the 60m pre-window."""
        manager = _loaded_manager()
        blocked, reason = manager.check_news_block(
            now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(blocked)
        self.assertIn("Core PCE", reason)

    def test_does_not_block_three_hours_early(self):
        """The live defect: 09:30Z is 3h before Core PCE and must be clear."""
        manager = _loaded_manager()
        blocked, _ = manager.check_news_block(
            now=datetime(2026, 7, 30, 9, 30, tzinfo=timezone.utc))
        self.assertFalse(blocked)

    def test_still_blocks_just_after_release(self):
        """12:45Z is inside the 30m post-release window."""
        manager = _loaded_manager()
        blocked, _ = manager.check_news_block(
            now=datetime(2026, 7, 30, 12, 45, tzinfo=timezone.utc))
        self.assertTrue(blocked)


if __name__ == "__main__":
    unittest.main()
