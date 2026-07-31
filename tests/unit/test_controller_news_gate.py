import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {"EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"]}}}


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
    def test_execute_signal_consults_the_per_symbol_gate(self):
        """_execute_signal must call _news_blocks_symbol before sizing anything."""
        import inspect

        from src.core.system_controller import SystemController
        source = inspect.getsource(SystemController._execute_signal)
        self.assertIn("_news_blocks_symbol", source)

    def test_controller_exposes_the_gate_helper(self):
        from src.core.system_controller import SystemController
        self.assertTrue(hasattr(SystemController, "_news_blocks_symbol"))

    def test_controller_imports_the_new_package(self):
        """Note the trailing dot: the OLD module is 'src.analysis.news_manager',
        which would satisfy a bare startswith('src.analysis.news') and let this
        test pass before the change was made."""
        import src.core.system_controller as controller_module
        self.assertEqual(
            controller_module.NewsManager.__module__, "src.analysis.news.manager")


if __name__ == "__main__":
    unittest.main()
