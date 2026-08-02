"""RISK-01: the trading-day label must roll over at 23:45 Africa/Kampala,
the same boundary at which SystemController already calls
RiskManager.reset_daily_metrics() (system_controller.py, Uganda report block).

A midnight boundary would disagree with that reset for 15 minutes every night
-- long enough for a restart in that window to resurrect an anchor the reset
had already superseded, or to discard one that was still valid.
"""
import os
import sqlite3
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
        return True          # RS-RISK-01 MEDIUM-3: the real one reports success


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

    def run(self, now=None):
        SystemController._persist_daily_anchor(self, now or datetime.now(EAT))


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

    def test_never_raises_into_the_main_loop(self):
        """_persist_daily_anchor runs inside the main `async while True` loop,
        whose only exception handler Telegrams a FATAL SYSTEM CRASH and exits.
        A bookkeeping write must never be able to stop the trading engine, so
        an unusable day_start_equity is skipped rather than propagated.

        Regression: the first version compared `equity <= 0` directly, which
        raised TypeError on any non-numeric value and broke five existing
        controller tests.
        """
        class _Unusable:
            def __le__(self, other):
                raise TypeError("not comparable")

        for equity in (_Unusable(), None, "abc", object(), float("nan"),
                       float("inf")):
            s = _Stub(0.0)
            s.risk_manager.day_start_equity = equity
            s.run()          # must not raise
            self.assertEqual(s.state_manager.writes, [],
                             msg=f"persisted an unusable anchor {equity!r}")

    def test_writes_under_todays_trading_day_key(self):
        s = _Stub(1000.0)
        s.run()
        expected = SystemController._trading_day_key(datetime.now(EAT))
        self.assertEqual(s.state_manager.writes[0][0], expected)


CFG = {"risk": {"account": {"max_daily_drawdown_pct": 3.0},
                "trade": {"risk_per_trade_pct": 1.0}}}


class _RollStub:
    """Drives the edge-triggered trading-day rollover with a REAL RiskManager,
    so the anchor/equity interactions are the production ones."""

    def __init__(self, seeded_key, equity=0.0):
        from src.risk.risk_manager import RiskManager
        self.risk_manager = RiskManager(CFG)
        if equity:
            self.risk_manager.update_account_info(equity, equity)
        self.state_manager = _FakeStore()
        self.uganda_tz = EAT
        self._last_persisted_anchor = None
        self._current_day_key = seeded_key

    _trading_day_key = SystemController.__dict__["_trading_day_key"]

    def roll(self, now):
        return SystemController._roll_trading_day_if_needed(self, now)

    def persist(self, now):
        SystemController._persist_daily_anchor(self, now)


class TradingDayRollover(unittest.TestCase):
    """RS-RISK-01 MAJOR-1. The anchor's day must roll on the SAME key the
    persisted row is stamped with, edge-triggered — not on the 23:45
    wall-clock minute, which the main loop can miss entirely (it does not run
    during _wait_for_bridge_connection, an unbounded `while True`)."""

    def test_no_roll_within_the_same_trading_day(self):
        s = _RollStub("2026-07-31", equity=1000.0)
        self.assertFalse(s.roll(at(2026, 7, 31, 12, 0)))
        self.assertFalse(s.roll(at(2026, 7, 31, 23, 44, 59)))
        self.assertAlmostEqual(s.risk_manager.day_start_equity, 1000.0)

    def test_rolls_once_when_the_key_changes(self):
        s = _RollStub("2026-07-31", equity=1000.0)
        s.risk_manager.update_account_info(1000.0, 1200.0)   # equity moved
        self.assertTrue(s.roll(at(2026, 7, 31, 23, 45, 0)))
        self.assertAlmostEqual(s.risk_manager.day_start_equity, 1200.0)
        self.assertEqual(s._current_day_key, "2026-08-01")
        # idempotent: a second call in the same new day must not roll again
        self.assertFalse(s.roll(at(2026, 8, 1, 0, 30)))

    def test_roll_without_equity_INVALIDATES_rather_than_keeping_stale(self):
        """The MAJOR-1 core. Restarted across the boundary with no heartbeat
        yet: keeping yesterday's anchor is what let it be persisted under the
        NEW day's key and restored all day. It must be zeroed so
        update_account_info re-anchors on the first heartbeat."""
        s = _RollStub("2026-07-31")
        s.risk_manager.restore_daily_anchor(10000.0)   # yesterday's, restored at boot
        self.assertAlmostEqual(s.risk_manager.day_start_equity, 10000.0)

        s.roll(at(2026, 8, 1, 0, 20))                  # loop's first iteration, next day
        self.assertEqual(s.risk_manager.day_start_equity, 0.0,
                         "stale anchor survived the day rollover")

        # and the next heartbeat anchors fresh from live equity
        s.risk_manager.update_account_info(10300.0, 10300.0)
        self.assertAlmostEqual(s.risk_manager.day_start_equity, 10300.0)

    def test_rollover_does_not_touch_the_report_range_trackers(self):
        """The report-ordering trap. The 23:45 report reads equity_max/min for
        the day it is reporting on, and the rollover fires BEFORE it in the
        same iteration. So the rollover must re-anchor ONLY -- clearing the
        ranges here would make the daily report describe an empty day."""
        s = _RollStub("2026-07-31", equity=1000.0)
        s.risk_manager.track_equity(1500.0)    # day's high
        s.risk_manager.track_equity(900.0)     # day's low
        hi, lo = s.risk_manager.equity_max, s.risk_manager.equity_min

        s.roll(at(2026, 7, 31, 23, 45, 0))

        self.assertAlmostEqual(s.risk_manager.equity_max, hi)
        self.assertAlmostEqual(s.risk_manager.equity_min, lo)

    def test_stale_anchor_is_never_persisted_under_the_new_days_key(self):
        """End-to-end MAJOR-1: the worked scenario from RS-RISK-01.

        Day D anchor 10000 (account grew to 10300). Restart 23:35 restores
        10000 under key D. The EA is down, so the loop's first iteration is
        00:20 on D+1 and the 23:45 window is never observed. The old code then
        wrote (D+1, 10000) to disk -- a 1.94x loss allowance, restored on every
        further restart that day.
        """
        s = _RollStub("2026-07-31")
        s.risk_manager.restore_daily_anchor(10000.0)

        now = at(2026, 8, 1, 0, 20)
        s.roll(now)
        s.persist(now)
        self.assertEqual(s.state_manager.writes, [],
                         "persisted an anchor that belongs to the previous day")

        # once a heartbeat lands, the CORRECT day-D+1 anchor is persisted
        s.risk_manager.update_account_info(10300.0, 10300.0)
        s.persist(now)
        self.assertEqual(s.state_manager.writes, [("2026-08-01", 10300.0)])


class _RecordingLogger:
    def __init__(self):
        self.events = []

    def log_event(self, cat, sub, msg, *a, **kw):
        self.events.append((cat, sub, msg))

    def text(self):
        return " | ".join(m for _, _, m in self.events)


class _BootStore:
    """StateManager stand-in for the boot-restore seam."""

    def __init__(self, row=None, raise_on_read=None):
        self.row = row
        self.raise_on_read = raise_on_read
        self.writes = []

    def get_risk_anchor(self):
        if self.raise_on_read:
            raise self.raise_on_read
        return self.row

    def save_risk_anchor(self, key, equity):
        self.writes.append((key, equity))
        return True


class _BootStub:
    """Drives _restore_daily_anchor_at_boot with a REAL RiskManager."""

    def __init__(self, row=None, raise_on_read=None):
        from src.risk.risk_manager import RiskManager
        self.risk_manager = RiskManager(CFG)
        self.state_manager = _BootStore(row, raise_on_read)
        self.logger = _RecordingLogger()
        self.uganda_tz = EAT
        self._last_persisted_anchor = None
        self._current_day_key = None

    _trading_day_key = SystemController.__dict__["_trading_day_key"]

    def boot(self, now):
        return SystemController._restore_daily_anchor_at_boot(self, now)


NOW = at(2026, 8, 1, 12, 0)          # trading day "2026-08-01"


class BootRestoreIsTestable(unittest.TestCase):
    """RS-RISK-01 MEDIUM-8. The boot-restore block held MAJOR-1 and no test
    could reach it, because nothing constructs SystemController through
    __init__. Extracted to a seam driven by a stub `self`, exactly as
    _persist_daily_anchor already was."""

    def test_restores_todays_anchor(self):
        s = _BootStub({'trading_day_key': '2026-08-01', 'day_start_equity': 1000.0})
        self.assertTrue(s.boot(NOW))
        self.assertAlmostEqual(s.risk_manager.day_start_equity, 1000.0)
        self.assertIn("Restored", s.logger.text())

    def test_stale_row_is_not_restored(self):
        s = _BootStub({'trading_day_key': '2026-07-31', 'day_start_equity': 1000.0})
        self.assertFalse(s.boot(NOW))
        self.assertEqual(s.risk_manager.day_start_equity, 0.0)
        self.assertIn("anchoring fresh", s.logger.text())

    def test_seeds_the_day_key_even_when_nothing_is_restored(self):
        s = _BootStub(None)
        s.boot(NOW)
        self.assertEqual(s._current_day_key, "2026-08-01")

    # --- MEDIUM-4: a READ FAILURE must not look like "never saved" ---

    def test_read_failure_is_logged_loudly_not_silently_swallowed(self):
        s = _BootStub(raise_on_read=sqlite3.DatabaseError("database disk image is malformed"))
        self.assertFalse(s.boot(NOW))
        self.assertTrue(s.logger.events, "a failed read produced NO operator signal")
        self.assertIn("malformed", s.logger.text())

    def test_absent_row_is_logged_distinctly_from_a_failure(self):
        s = _BootStub(None)
        s.boot(NOW)
        self.assertTrue(s.logger.events, "no signal at all on a clean first boot")
        self.assertNotIn("malformed", s.logger.text())

    # --- MINOR-7: never claim a restore that did not happen ---

    def test_rejected_value_does_not_log_a_successful_restore(self):
        """A NULL column makes float(None) raise, so restore is a no-op. The
        old code still logged 'Restored daily DD anchor 0.00 ... (survived
        restart)' -- a false positive in the very log an operator reads to
        diagnose the corruption."""
        s = _BootStub({'trading_day_key': '2026-08-01', 'day_start_equity': None})
        self.assertFalse(s.boot(NOW))
        self.assertNotIn("survived restart", s.logger.text())
        self.assertEqual(s.risk_manager.day_start_equity, 0.0)
        self.assertIsNone(s._last_persisted_anchor,
                          "cached a (key, 0.0) anchor that was never applied")


class ImplausibleAnchorFailsClosed(unittest.TestCase):
    """RS-RISK-01 MEDIUM-2. This change made a FILE ON DISK a control input to
    a safety limit, gated only by `> 0`. A tiny positive anchor makes pnl_pct
    enormously positive, so check_can_trade() returns True forever and the 3%
    breaker plus the throttle are switched off for the whole day."""

    def _rm_with_restored(self, anchor):
        from src.risk.risk_manager import RiskManager
        rm = RiskManager(CFG)
        rm.restore_daily_anchor(anchor)
        return rm

    def test_tiny_anchor_is_rejected_when_the_first_heartbeat_corroborates(self):
        rm = self._rm_with_restored(0.01)
        rm.update_account_info(500.0, 500.0)     # first heartbeat: equity 500
        self.assertAlmostEqual(rm.day_start_equity, 500.0,
                               msg="implausible anchor survived corroboration")
        # and the breaker works again
        rm.update_account_info(500.0, 480.0)     # -4%
        self.assertFalse(rm.check_can_trade())

    def test_the_breaker_would_be_disabled_without_the_check(self):
        """Pins the consequence, so a regression is visible as a safety fact."""
        rm = self._rm_with_restored(0.01)
        rm.update_account_info(500.0, 500.0)
        rm.update_account_info(500.0, 250.0)     # equity HALVED on the day
        self.assertFalse(rm.check_can_trade(),
                         "3% breaker did not halt a 50% drawdown")

    def test_a_plausible_anchor_is_kept(self):
        rm = self._rm_with_restored(1000.0)
        rm.update_account_info(1000.0, 985.0)
        self.assertAlmostEqual(rm.day_start_equity, 1000.0)

    def test_a_real_bad_day_is_not_mistaken_for_corruption(self):
        """A genuine intraday loss must NOT trip the plausibility guard and
        re-anchor -- that would itself be fail-open."""
        rm = self._rm_with_restored(1000.0)
        rm.update_account_info(1000.0, 900.0)    # -10% on the day, plausible
        self.assertAlmostEqual(rm.day_start_equity, 1000.0)
        self.assertFalse(rm.check_can_trade())

    def test_corroboration_happens_once_not_on_every_heartbeat(self):
        rm = self._rm_with_restored(1000.0)
        rm.update_account_info(1000.0, 1000.0)
        for eq in (900.0, 800.0, 700.0, 50.0):   # a catastrophic real day
            rm.update_account_info(1000.0, eq)
        self.assertAlmostEqual(rm.day_start_equity, 1000.0,
                               msg="anchor drifted after corroboration")


class FailedWriteIsRetried(unittest.TestCase):
    """RS-RISK-01 MEDIUM-3. save_risk_anchor swallowed every exception, but the
    caller cached (key, equity) unconditionally -- so one transient 'database
    is locked' left RISK-01 off for the rest of the day, retried never."""

    class _FailingStore:
        def __init__(self, fail_times):
            self.fail_times = fail_times
            self.attempts = 0
            self.writes = []

        def save_risk_anchor(self, key, equity):
            self.attempts += 1
            if self.attempts <= self.fail_times:
                return False
            self.writes.append((key, equity))
            return True

    def _stub(self, store):
        s = _RollStub("2026-08-01", equity=1000.0)
        s.state_manager = store
        return s

    def test_a_failed_write_is_retried_on_the_next_iteration(self):
        store = self._FailingStore(fail_times=3)
        s = self._stub(store)
        for _ in range(10):
            s.persist(NOW)
        self.assertGreaterEqual(store.attempts, 4, "never retried after failure")
        self.assertEqual(store.writes, [("2026-08-01", 1000.0)])

    def test_a_successful_write_still_suppresses_repeats(self):
        store = self._FailingStore(fail_times=0)
        s = self._stub(store)
        for _ in range(50):
            s.persist(NOW)
        self.assertEqual(store.attempts, 1)


if __name__ == "__main__":
    unittest.main()
