import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore
from tests.unit.test_risk_manager_exposure_cap import DECISION, _controller

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {"EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"]}}}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _StubNews:
    """Test double for the per-symbol gate consulted by _execute_signal."""

    def __init__(self, blocked=False, reason=None, raise_exc=None):
        self.blocked = blocked
        self.reason = reason
        self.raise_exc = raise_exc

    def check_symbol(self, symbol, now=None):
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.blocked, self.reason


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


def _manager_with_pce():
    store = CalendarStore(os.devnull)
    event = CalendarEvent(key=make_key("USD", "Core PCE", RELEASE), when_utc=RELEASE,
                          currency="USD", importance="HIGH", title="Core PCE")
    store.merge([event], "forexfactory", RELEASE)
    return NewsManager(_StubLogger(), config=CONFIG, source=None, store=store)


class PerSymbolGate(unittest.TestCase):
    """A USD release must stop USD-quoted symbols WITHOUT halting the whole bot."""

    def test_usd_release_blocks_eurusd(self):
        blocked, reason = _manager_with_pce().check_symbol("EURUSD", now=RELEASE)
        self.assertTrue(blocked)
        self.assertIn("Core PCE", reason)

    def test_same_release_leaves_gbpjpy_tradeable(self):
        blocked, _ = _manager_with_pce().check_symbol("GBPJPY", now=RELEASE)
        self.assertFalse(blocked)

    def test_bot_is_not_globally_halted_by_a_symbol_level_block(self):
        halted, _ = _manager_with_pce().is_globally_blocked(now=RELEASE)
        self.assertFalse(halted)


class ControllerWiring(unittest.TestCase):
    def test_controller_imports_the_new_package(self):
        """Note the trailing dot: the OLD module is 'src.analysis.news_manager',
        which would satisfy a bare startswith('src.analysis.news') and let this
        test pass before the change was made."""
        import src.core.system_controller as controller_module
        self.assertEqual(
            controller_module.NewsManager.__module__, "src.analysis.news.manager")


class ExecuteSignalNewsGate(unittest.TestCase):
    """The production invariant: a blocked symbol sends no order, and a news
    fault never stops trading. Reuses test_risk_manager_exposure_cap's
    object.__new__(SystemController) + FakeBridge harness."""

    def test_blocked_symbol_sends_no_order(self):
        c = _controller([])
        c.news_manager = _StubNews(blocked=True, reason="Core PCE in 20m")
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH"))
        self.assertEqual(c.bridge.reliable, [])
        self.assertEqual(c._reserved_risk, {})
        self.assertEqual(c.pending_signal_meta, {})

    def test_unblocked_symbol_sends_an_order(self):
        """Control case: without it, the blocked-symbol test above would pass
        trivially if the harness never sends anything at all."""
        c = _controller([])
        c.news_manager = _StubNews(blocked=False)
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH"))
        self.assertEqual(len(c.bridge.reliable), 1)

    def test_a_news_fault_fails_open_and_still_trades(self):
        """Pins the documented contract: a news fault must not crash or stop
        the trade path -- it degrades to 'not blocked'."""
        c = _controller([])
        c.news_manager = _StubNews(raise_exc=RuntimeError("feed exploded"))
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH"))
        self.assertEqual(len(c.bridge.reliable), 1)


if __name__ == "__main__":
    unittest.main()
