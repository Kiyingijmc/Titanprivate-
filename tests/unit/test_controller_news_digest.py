import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core import system_controller
from src.core.system_controller import SystemController


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Telemetry:
    def __init__(self):
        self.sent = []

    async def send_message(self, text, parse_mode="HTML"):
        self.sent.append(text)


class _News:
    def __init__(self, digest=None, raises=False):
        self._digest = digest or {"date": "2026-07-30", "count": 0, "events": []}
        self.raises = raises
        self.calls = 0

    def digest(self, now=None):
        self.calls += 1
        if self.raises:
            raise RuntimeError("digest exploded")
        return self._digest


class _Logger:
    def log_event(self, *a, **k):
        pass


def _controller(news=None, enabled=True):
    c = object.__new__(SystemController)
    c.telemetry = _Telemetry()
    c.news_manager = news or _News()
    c.logger = _Logger()
    c.config = {"news": {"digest": {"enabled": enabled, "hour": 7, "minute": 0,
                                    "alert_lead_min": 15}}}
    # Edge-triggered dedup marker: the trading-day key this digest was last
    # sent for, or None. Replaces the old level-triggered pair
    # (news_digest_sent_today / news_daily_reset_done).
    c.news_digest_sent_for_key = None
    c.news_alerts_sent = set()
    c._news_alert_cache = None
    c._news_alert_cache_at = None
    return c


AT_7 = datetime(2026, 7, 30, 7, 0)
BEFORE_7 = datetime(2026, 7, 30, 6, 59)
AT_7_20 = datetime(2026, 7, 30, 7, 20)
STALE_18 = datetime(2026, 7, 30, 18, 0)
NEXT_DAY_AT_7 = datetime(2026, 7, 31, 7, 0)


class DailyDigest(unittest.TestCase):
    """The schedule is edge-triggered per trading day (`_trading_day_key`),
    not a one-minute wall-clock window -- see _maybe_send_news_digest's
    docstring for why the old exact-match gate was unsafe."""

    def test_fires_once_when_called_exactly_at_the_scheduled_time(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_does_not_fire_twice_on_the_same_trading_day_key_across_many_calls(self):
        c = _controller()
        for _ in range(25):
            _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_does_not_fire_before_the_scheduled_time(self):
        c = _controller()
        _run(c._maybe_send_news_digest(BEFORE_7))
        self.assertEqual(c.telemetry.sent, [])

    def test_recovers_a_missed_window(self):
        """The whole point of the edge-triggered redesign: a stall that
        parks the loop straight through the scheduled minute (e.g.
        `_wait_for_bridge_connection`'s unbounded `while True`) must not
        silently skip the day. The first call of the day lands at 07:20,
        never at 07:00 -- it must still send. This is the test that FAILS
        against the pre-fix minute-exact gate."""
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7_20))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_stale_catch_up_sends_nothing_but_marks_the_key(self):
        """A restart hours after the schedule (default catch_up_hours: 3)
        must not Telegram a near-end-of-day digest as if it were fresh --
        but it must also not retry later the same day."""
        c = _controller()
        _run(c._maybe_send_news_digest(STALE_18))
        self.assertEqual(c.telemetry.sent, [])
        _run(c._maybe_send_news_digest(STALE_18 + timedelta(hours=1)))
        self.assertEqual(c.telemetry.sent, [])

    def test_a_new_trading_day_key_sends_again(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        _run(c._maybe_send_news_digest(NEXT_DAY_AT_7))
        self.assertEqual(len(c.telemetry.sent), 2)

    def test_empty_day_still_sends_a_message(self):
        """Silence is indistinguishable from a broken job."""
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        self.assertIn("No high-impact", c.telemetry.sent[0])

    def test_disabled_sends_nothing(self):
        c = _controller(enabled=False)
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(c.telemetry.sent, [])

    def test_digest_failure_does_not_raise_into_the_loop(self):
        c = _controller(news=_News(raises=True))
        _run(c._maybe_send_news_digest(AT_7))   # must not raise
        self.assertEqual(c.telemetry.sent, [])


RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
EVENT = {"when_utc": RELEASE.isoformat(), "currency": "USD", "title": "Core PCE",
         "forecast": "0.3%", "previous": "0.2%", "affects": ["EURUSD"]}


class PreEventAlert(unittest.TestCase):
    def _c(self):
        return _controller(news=_News({"date": "2026-07-30", "count": 1,
                                       "events": [EVENT]}))

    def test_alerts_inside_the_lead_window(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.telemetry.sent), 1)
        self.assertIn("Core PCE", c.telemetry.sent[0])

    def test_does_not_alert_before_the_lead_window(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=45)))
        self.assertEqual(c.telemetry.sent, [])

    def test_does_not_alert_after_the_release(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE + timedelta(minutes=5)))
        self.assertEqual(c.telemetry.sent, [])

    def test_alerts_only_once_per_event(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=9)))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_alert_failure_does_not_raise_into_the_loop(self):
        c = _controller(news=_News(raises=True))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(c.telemetry.sent, [])


class HourZeroResetRace(unittest.TestCase):
    """Fix round 1, Finding A (CRITICAL).

    The hour-0 reset lives inline in the main loop's Section F, not in a
    separate method -- so this test mirrors that exact snippet rather than
    calling it, and must be kept in sync with it. This body reflects the
    FIXED (guarded, reset-before-send) ordering; the pre-fix run of this same
    body (with the guard removed and the reset run after the send, matching
    the code as it stood before this round) reproduced the reviewer's
    50-sends failure -- see task-4-report.md for the verbatim RED.
    """

    def test_hour_zero_reset_does_not_repeatedly_wipe_the_alert_dedup(self):
        c = _controller(news=_News({"date": "2026-07-30", "count": 1,
                                    "events": [EVENT]}))
        now_utc = RELEASE - timedelta(minutes=5)  # inside the 15-min lead window

        class _NowUganda:
            hour = 0

        now_uganda = _NowUganda()
        # Local stand-in for what was system_controller.py's inline
        # news_daily_reset_done flag -- that flag (and its sibling
        # news_digest_sent_today) was removed from the controller entirely
        # by the edge-triggered digest rework (news_digest_sent_for_key);
        # this test's assertion was always about news_alerts_sent, which
        # that flag pair never touched, so the guard is reproduced locally
        # to keep the regression coverage without depending on removed
        # controller state.
        reset_done = False

        for _ in range(50):
            # Mirrors the guard shape that used to live in system_controller.py
            # Section F, including its position BEFORE the send (a reset
            # placed after the send wipes the marker the send just wrote, on
            # the first hour-0 tick of the day -- see task-4-report.md fix
            # round 1).
            if now_uganda.hour == 0:
                if not reset_done:
                    c.news_alerts_sent.clear()
                    reset_done = True
            else:
                reset_done = False
            _run(c._maybe_send_news_alerts(now_utc))

        self.assertEqual(len(c.telemetry.sent), 1)


class DigestCaching(unittest.TestCase):
    """Fix round 1, Finding B (Important): digest() must not run every tick."""

    def test_digest_is_cached_for_30_seconds_keyed_on_the_passed_clock(self):
        news = _News({"date": "2026-07-30", "count": 1, "events": [EVENT]})
        c = _controller(news=news)
        base = RELEASE - timedelta(minutes=30)

        _run(c._maybe_send_news_alerts(base))
        _run(c._maybe_send_news_alerts(base + timedelta(seconds=5)))
        _run(c._maybe_send_news_alerts(base + timedelta(seconds=29)))
        self.assertEqual(news.calls, 1)

        _run(c._maybe_send_news_alerts(base + timedelta(seconds=31)))
        self.assertEqual(news.calls, 2)


BAD_EVENT = {"currency": "USD", "title": "Missing when_utc"}  # no 'when_utc' key


class MalformedEventResilience(unittest.TestCase):
    """Fix round 1, Finding C (Minor): one bad event must not eat the rest."""

    def test_a_malformed_event_does_not_block_a_valid_ones_alert(self):
        news = _News({"date": "2026-07-30", "count": 2,
                      "events": [BAD_EVENT, EVENT]})
        c = _controller(news=news)
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.telemetry.sent), 1)
        self.assertIn("Core PCE", c.telemetry.sent[0])


UGANDA_TZ = pytz.timezone("Africa/Kampala")


class MidnightCrossingResetVsPendingMarker(unittest.TestCase):
    """Fix round 2, Finding A residual: the round-1 guard made the reset fire
    once per day, but it still unconditionally cleared news_alerts_sent --
    wiping markers for events that are still pending (not yet released) when
    Kampala midnight (21:00 UTC) falls inside a pre-release lead window.

    Model: step a continuously-advancing UTC clock from 20:50 through 21:15
    UTC (crossing 21:00 UTC = Kampala 00:00) with a HIGH event releasing at
    21:10 UTC and a 15-min lead window (opens 20:55 UTC = Kampala 23:55, i.e.
    before the reset fires). Mirrors system_controller.py Section F exactly
    and must be kept in lockstep with it (see HourZeroResetRace).
    """

    def test_exactly_one_send_across_the_midnight_crossing(self):
        release = datetime(2026, 7, 30, 21, 10, tzinfo=timezone.utc)
        event = {"when_utc": release.isoformat(), "currency": "USD",
                 "title": "Midnight Crossing Event"}
        c = _controller(news=_News({"date": "2026-07-30", "count": 1,
                                    "events": [event]}))

        now_utc = datetime(2026, 7, 30, 20, 50, tzinfo=timezone.utc)
        end = datetime(2026, 7, 30, 21, 15, tzinfo=timezone.utc)
        step = timedelta(minutes=1)
        # Local stand-in for the (now-removed) news_daily_reset_done /
        # news_digest_sent_today pair -- see HourZeroResetRace for why: this
        # test's assertion is entirely about news_alerts_sent, which that
        # digest flag pair never touched, even before it was removed by the
        # edge-triggered digest rework (news_digest_sent_for_key).
        reset_done = False

        while now_utc <= end:
            now_uganda = now_utc.astimezone(UGANDA_TZ)
            # Mirrors the guard shape that used to live in system_controller.py
            # Section F (post fix-round-2: no news_alerts_sent.clear() here --
            # pruning of resolved markers happens inside _maybe_send_news_alerts).
            if now_uganda.hour == 0:
                if not reset_done:
                    reset_done = True
            else:
                reset_done = False
            _run(c._maybe_send_news_alerts(now_utc))
            now_utc += step

        self.assertEqual(len(c.telemetry.sent), 1)


class ResolvedMarkerPruning(unittest.TestCase):
    """Fix round 2: a dedup marker expires once its event releases, not on a
    wall-clock day boundary -- so the set doesn't grow unbounded now that the
    daily .clear() is gone."""

    def test_a_resolved_events_marker_is_pruned(self):
        c = _controller(news=_News({"date": "2026-07-30", "count": 1,
                                    "events": [EVENT]}))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.news_alerts_sent), 1)

        # Long after release -- the marker is no longer needed and must be pruned.
        _run(c._maybe_send_news_alerts(RELEASE + timedelta(hours=2)))
        self.assertEqual(c.news_alerts_sent, set())


BAD_CONFIGS = [
    {"news": {"digest": {"hour": None}}},
    {"news": {"digest": {"hour": "7am"}}},
    {"news": {"digest": {"minute": "x"}}},
    {"news": {"digest": {"alert_lead_min": None}}},
    {"news": {"digest": {"alert_lead_min": "fifteen"}}},
    {"news": "yes"},
    {"news": None},
    {},
]


# DIGEST_OFF_SCHEDULE is BEFORE the default schedule (hour=7, minute=0), so
# the `(now.hour, now.minute) < (hour, minute)` gate returns early for any
# config that resolves hour/minute to their defaults -- e.g. a config that
# only mangles `alert_lead_min` or `catch_up_hours` is irrelevant to the
# digest schedule and must not be forced to "send" just because it happens
# to reach the gate. (Under the new >=-based schedule, a *later* off-schedule
# instant like 07:13 would actually be past the default 07:00 and send --
# unlike the old exact-minute gate, so it can no longer double as "off
# schedule" here.) ALERTS_OUTSIDE_WINDOW is well outside the default 15-min
# alert lead window ahead of RELEASE for the same reason: a config that only
# mangles `hour`/`minute` is irrelevant to the alerts method. The bad-field
# conversions themselves (int(None), int("7am"), ...) are evaluated
# unconditionally while building the comparison, before the time-based gate
# that would otherwise short-circuit them, so the crash (pre-fix) / WARN-
# and-skip (post-fix) still reproduces regardless of what "now" is passed in.
DIGEST_OFF_SCHEDULE = datetime(2026, 7, 30, 6, 0)
ALERTS_OUTSIDE_WINDOW = RELEASE - timedelta(hours=2)


class ConfigResilience(unittest.TestCase):
    """Fix round 3, Item 1 (Important): a bad config value must degrade to a
    WARN + skipped send, never escape as an unhandled exception into the main
    loop -- both hooks run inside `except Exception: raise e`, and this bot
    runs outside systemd, so an escape is a fatal, non-restarting crash."""

    def _controller_with(self, cfg):
        c = object.__new__(SystemController)
        c.telemetry = _Telemetry()
        c.news_manager = _News({"date": "2026-07-30", "count": 1, "events": [EVENT]})
        c.logger = _Logger()
        c.config = cfg
        c.news_digest_sent_for_key = None
        c.news_alerts_sent = set()
        c._news_alert_cache = None
        c._news_alert_cache_at = None
        return c

    def test_digest_survives_bad_config(self):
        for cfg in BAD_CONFIGS:
            with self.subTest(cfg=cfg):
                c = self._controller_with(cfg)
                _run(c._maybe_send_news_digest(DIGEST_OFF_SCHEDULE))  # must not raise
                self.assertEqual(c.telemetry.sent, [])

    def test_alerts_survive_bad_config(self):
        for cfg in BAD_CONFIGS:
            with self.subTest(cfg=cfg):
                c = self._controller_with(cfg)
                _run(c._maybe_send_news_alerts(ALERTS_OUTSIDE_WINDOW))  # must not raise
                self.assertEqual(c.telemetry.sent, [])


CATCH_UP_BAD_CONFIGS = [
    {"news": {"digest": {"catch_up_hours": None}}},
    {"news": {"digest": {"catch_up_hours": "x"}}},
]


class CatchUpHoursConfigResilience(unittest.TestCase):
    """New field, same crash-safety contract as ConfigResilience above: the
    float() coercion of `catch_up_hours` must not escape. Isolated from
    BAD_CONFIGS/DIGEST_OFF_SCHEDULE above because that instant is BEFORE the
    schedule and would return before ever reaching this field's conversion --
    this test uses a `now` past the schedule (AT_7_20) so the code path
    actually gets there."""

    def _controller_with(self, cfg):
        c = object.__new__(SystemController)
        c.telemetry = _Telemetry()
        c.news_manager = _News({"date": "2026-07-30", "count": 1, "events": [EVENT]})
        c.logger = _Logger()
        c.config = cfg
        c.news_digest_sent_for_key = None
        c.news_alerts_sent = set()
        c._news_alert_cache = None
        c._news_alert_cache_at = None
        return c

    def test_malformed_catch_up_hours_does_not_escape(self):
        for cfg in CATCH_UP_BAD_CONFIGS:
            with self.subTest(cfg=cfg):
                c = self._controller_with(cfg)
                _run(c._maybe_send_news_digest(AT_7_20))  # must not raise
                self.assertEqual(c.telemetry.sent, [])


class NewsTopLevelDisableGate(unittest.TestCase):
    """Fix round 3, Item 4 (Minor): `news.enabled: false` must gate both
    hooks, not just `news.digest.enabled`."""

    def _controller_with(self, cfg):
        c = object.__new__(SystemController)
        c.telemetry = _Telemetry()
        c.news_manager = _News({"date": "2026-07-30", "count": 1, "events": [EVENT]})
        c.logger = _Logger()
        c.config = cfg
        c.news_digest_sent_for_key = None
        c.news_alerts_sent = set()
        c._news_alert_cache = None
        c._news_alert_cache_at = None
        return c

    def test_digest_disabled_when_news_top_level_disabled(self):
        c = self._controller_with(
            {"news": {"enabled": False, "digest": {"enabled": True, "hour": 7, "minute": 0}}})
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(c.telemetry.sent, [])

    def test_alerts_disabled_when_news_top_level_disabled(self):
        c = self._controller_with(
            {"news": {"enabled": False, "digest": {"enabled": True, "alert_lead_min": 15}}})
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(c.telemetry.sent, [])


class _CountingDatetime(datetime):
    """Subclass swapped in for system_controller's module-level `datetime`
    name so every other datetime operation (arithmetic, comparisons,
    `datetime.now`) keeps working unchanged -- only `fromisoformat` counts
    its calls."""

    calls = 0

    @classmethod
    def fromisoformat(cls, s):
        cls.calls += 1
        return super().fromisoformat(s)


class ParsedTimestampCaching(unittest.TestCase):
    """Fix round 3, Item 3 (Minor, perf): parsed `when_utc` values must be
    cached alongside the 30s digest cache, not re-parsed on every tick."""

    def test_fromisoformat_runs_once_per_cache_refresh_not_once_per_tick(self):
        news = _News({"date": "2026-07-30", "count": 1, "events": [EVENT]})
        c = _controller(news=news)
        base = RELEASE - timedelta(minutes=30)

        _CountingDatetime.calls = 0
        original = system_controller.datetime
        system_controller.datetime = _CountingDatetime
        try:
            for i in range(100):
                _run(c._maybe_send_news_alerts(base + timedelta(milliseconds=i * 10)))
        finally:
            system_controller.datetime = original

        # 100 ticks within one 30s cache window must parse the event set once.
        self.assertEqual(_CountingDatetime.calls, 1)


if __name__ == "__main__":
    unittest.main()
