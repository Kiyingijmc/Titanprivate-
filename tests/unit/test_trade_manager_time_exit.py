"""TradeManager time-exit hook (Almanac canary).

Config-gated via trade_management.time_exits.<StrategyName>. A position whose
state-DB strategy has a time-exit rule is closed once the shared calendar
(src/analysis/trading_days.py) says the turn-of-month window has passed.
Entirely inert for strategies without a rule and when the config is absent.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.execution.trade_manager import TradeManager


def _epoch(y, mo, d, h=12):
    return datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp()


class _Logger:
    def log_event(self, *a, **k):
        pass


class _State:
    """Stub: ticket 1 = Almanac position placed on 2026-07-31; ticket 2 =
    SilverBullet position. Ratchet state zeroed so ratchet logic stays out."""
    def __init__(self):
        self.meta = {
            1: ("Almanac", _epoch(2026, 7, 31, 18)),
            2: ("SilverBullet", _epoch(2026, 7, 31, 18)),
        }

    def get_order_meta(self, t):
        return self.meta.get(t)

    def get_ratchet_state(self, t):
        return (0, 0.0, 0.0)


class _Risk:
    symbol_specs = {}

    def get_max_risk_amount(self, *a, **k):
        return 0.0

    def normalize_price(self, p, s):
        return p


def make_tm(config=None):
    return TradeManager(_Logger(), _State(), _Risk(), config=config)


def pos(ticket, symbol="US30"):
    return {"t": ticket, "s": symbol, "pf": 0.0, "tp": 0.0, "vol": 1.0, "sl": 0.0}


CFG = {"trade_management": {"time_exits": {"Almanac": {"exit_trading_day": 3}}}}


class TestTimeExit(unittest.TestCase):
    def _sync(self, tm, when, tickets=(1,)):
        with patch("src.execution.trade_manager.time.time", return_value=when):
            return tm.sync_positions([pos(t) for t in tickets], {"US30": 40000.0})

    def test_closes_after_third_trading_day(self):
        cmds = self._sync(make_tm(CFG), _epoch(2026, 8, 6))  # TD4
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["action"], "CLOSE_POS")
        self.assertEqual(cmds[0]["ticket"], 1)
        self.assertEqual(cmds[0]["comment"], "Time Exit")

    def test_holds_through_third_trading_day(self):
        for day in (3, 4, 5):  # TD1..TD3 of August 2026
            cmds = self._sync(make_tm(CFG), _epoch(2026, 8, day))
            self.assertEqual(cmds, [], f"Aug {day} should hold")

    def test_holds_on_entry_day(self):
        self.assertEqual(self._sync(make_tm(CFG), _epoch(2026, 7, 31, 20)), [])

    def test_other_strategies_untouched(self):
        cmds = self._sync(make_tm(CFG), _epoch(2026, 8, 6), tickets=(2,))
        self.assertEqual(cmds, [])

    def test_inert_without_config(self):
        cmds = self._sync(make_tm({}), _epoch(2026, 8, 6))
        self.assertEqual(cmds, [])

    def test_cooldown_prevents_spam(self):
        tm = make_tm(CFG)
        when = _epoch(2026, 8, 6)
        first = self._sync(tm, when)
        self.assertEqual(len(first), 1)
        second = self._sync(tm, when + 1.0)  # inside the 2s ticket cooldown
        self.assertEqual(second, [])

    def test_flat_int_config_form(self):
        tm = make_tm({"trade_management": {"time_exits": {"Almanac": 3}}})
        cmds = self._sync(tm, _epoch(2026, 8, 6))
        self.assertEqual(len(cmds), 1)


if __name__ == "__main__":
    unittest.main()


class _StateGyro(_State):
    def __init__(self):
        super().__init__()
        self.meta[3] = ("Gyroscope", _epoch(2026, 8, 3, 10))


def make_tm_gyro(config=None):
    return TradeManager(_Logger(), _StateGyro(), _Risk(), config=config)


CFG_BARS = {"trade_management": {"time_exits": {
    "Almanac": {"exit_trading_day": 3},
    "Gyroscope": {"max_bars": 48},
}}}


class TestMaxBarsTimeExit(unittest.TestCase):
    """Gyroscope v2b GO (docs/research/2026-08-01-gyroscope2b-gate-results.md):
    duration-based variant — close once held >= max_bars H1 bars (hours)."""

    def _sync(self, tm, when, tickets):
        with patch("src.execution.trade_manager.time.time", return_value=when):
            return tm.sync_positions([pos(t) for t in tickets], {"US30": 40000.0})

    def test_closes_at_48_hours(self):
        cmds = self._sync(make_tm_gyro(CFG_BARS), _epoch(2026, 8, 5, 10), (3,))
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["ticket"], 3)
        self.assertEqual(cmds[0]["comment"], "Time Exit")

    def test_holds_before_48_hours(self):
        cmds = self._sync(make_tm_gyro(CFG_BARS), _epoch(2026, 8, 5, 9), (3,))
        self.assertEqual(cmds, [])

    def test_calendar_rule_still_works_alongside(self):
        cmds = self._sync(make_tm_gyro(CFG_BARS), _epoch(2026, 8, 6), (1, 3))
        self.assertEqual({c["ticket"] for c in cmds}, {1, 3})

    def test_unlisted_strategy_untouched(self):
        cmds = self._sync(make_tm_gyro(CFG_BARS), _epoch(2026, 8, 20), (2,))
        self.assertEqual(cmds, [])

    def test_plain_int_rule_stays_calendar(self):
        cfg = {"trade_management": {"time_exits": {"Almanac": 3}}}
        cmds = self._sync(make_tm_gyro(cfg), _epoch(2026, 8, 6), (1,))
        self.assertEqual(len(cmds), 1)
