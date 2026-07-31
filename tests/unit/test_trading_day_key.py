"""RISK-01: the trading-day label must roll over at 23:45 Africa/Kampala,
the same boundary at which SystemController already calls
RiskManager.reset_daily_metrics() (system_controller.py, Uganda report block).

A midnight boundary would disagree with that reset for 15 minutes every night
-- long enough for a restart in that window to resurrect an anchor the reset
had already superseded, or to discard one that was still valid.
"""
import os
import sys
import unittest
from datetime import datetime

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pytz  # noqa: E402

from src.core.system_controller import SystemController  # noqa: E402

EAT = pytz.timezone("Africa/Kampala")


def at(y, m, d, hh, mm, ss=0):
    return EAT.localize(datetime(y, m, d, hh, mm, ss))


class TradingDayKey(unittest.TestCase):
    def test_midday_is_todays_date(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 12, 0)),
                         "2026-07-31")

    def test_just_before_2345_is_still_today(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 23, 44, 59)),
                         "2026-07-31")

    def test_2345_starts_the_next_trading_day(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 23, 45, 0)),
                         "2026-08-01")

    def test_after_midnight_stays_in_the_day_2345_opened(self):
        """00:30 belongs to the trading day the 23:45 reset just started."""
        self.assertEqual(SystemController._trading_day_key(at(2026, 8, 1, 0, 30)),
                         "2026-08-01")

    def test_the_whole_2345_to_midnight_window_is_one_day(self):
        """The 15 minutes a midnight boundary would get wrong."""
        before = SystemController._trading_day_key(at(2026, 7, 31, 23, 50))
        after = SystemController._trading_day_key(at(2026, 8, 1, 0, 10))
        self.assertEqual(before, after)
        self.assertEqual(before, "2026-08-01")

    def test_month_boundary(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 23, 50)),
                         "2026-08-01")

    def test_year_boundary(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 12, 31, 23, 50)),
                         "2027-01-01")

    def test_is_a_staticmethod_needing_no_controller(self):
        """Must be callable without constructing SystemController, which would
        open the live bot's real databases and bind its ports."""
        self.assertIsInstance(
            SystemController.__dict__["_trading_day_key"], staticmethod)


class _FakeRisk:
    def __init__(self, equity):
        self.day_start_equity = equity


class _FakeStore:
    def __init__(self):
        self.writes = []

    def save_risk_anchor(self, key, equity):
        self.writes.append((key, equity))


class _Stub:
    """Enough of SystemController to drive _persist_daily_anchor.

    The real class is never constructed in tests: doing so would open the LIVE
    bot's data/db/trade_state.db and bind its ports. _persist_daily_anchor is a
    plain function on the class, so it can be called with a stub `self`.
    """

    def __init__(self, equity):
        self.risk_manager = _FakeRisk(equity)
        self.state_manager = _FakeStore()
        self.uganda_tz = EAT
        self._last_persisted_anchor = None

    _trading_day_key = SystemController.__dict__["_trading_day_key"]

    def run(self):
        SystemController._persist_daily_anchor(self)


class PersistDailyAnchorIsCached(unittest.TestCase):
    """RISK-01: this sits on the heartbeat path (~every 5s). It must write when
    the anchor CHANGES, not on every pulse."""

    def test_writes_once_then_suppresses_identical_repeats(self):
        s = _Stub(1000.0)
        for _ in range(50):          # 50 heartbeats, one anchor
            s.run()
        self.assertEqual(len(s.state_manager.writes), 1)
        self.assertAlmostEqual(s.state_manager.writes[0][1], 1000.0)

    def test_writes_again_when_the_anchor_changes(self):
        s = _Stub(1000.0)
        s.run()
        s.risk_manager.day_start_equity = 1100.0   # e.g. the 23:45 reset
        s.run()
        s.run()
        self.assertEqual([w[1] for w in s.state_manager.writes], [1000.0, 1100.0])

    def test_never_writes_an_unset_or_negative_anchor(self):
        for equity in (0.0, -1.0):
            s = _Stub(equity)
            s.run()
            self.assertEqual(s.state_manager.writes, [],
                             msg=f"wrote a bad anchor {equity}")

    def test_writes_under_todays_trading_day_key(self):
        s = _Stub(1000.0)
        s.run()
        expected = SystemController._trading_day_key(datetime.now(EAT))
        self.assertEqual(s.state_manager.writes[0][0], expected)


if __name__ == "__main__":
    unittest.main()
