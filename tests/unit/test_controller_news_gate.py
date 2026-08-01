import ast
import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import src.core.system_controller as controller_module
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


def _run_method_node():
    """The AST node for SystemController.run() -- the main loop whose bare
    `except Exception` re-raises and kills the process (item 3's premise)."""
    tree = ast.parse(Path(controller_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SystemController":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "run":
                    return item
    raise AssertionError("SystemController.run() not found in system_controller.py")


def _call_site_is_guarded(root, call_substring):
    """True if the NEAREST enclosing Try around a call matching
    `call_substring` catches Exception and does not itself re-raise.

    A naive "is there SOME surrounding Try with an Exception handler"
    check is fooled by the loop's own outer `except Exception as e: ...
    raise e`, which textually wraps every call site in run() yet is
    precisely the re-raise this item exists to keep news faults away from.
    So this walks the tree tracking the innermost enclosing Try (via an
    explicit stack, entering only its `body`, not its handlers/orelse/
    finally) and requires that Try's handler to both catch Exception and
    contain no `raise` statement anywhere in its handler body.
    """
    stack = []
    nearest_for_matches = []

    class _Visitor(ast.NodeVisitor):
        def visit_Try(self, node):
            stack.append(node)
            for stmt in node.body:
                self.visit(stmt)
            stack.pop()
            for handler in node.handlers:
                self.visit(handler)
            for stmt in node.orelse:
                self.visit(stmt)
            for stmt in node.finalbody:
                self.visit(stmt)

        def visit_Call(self, node):
            if call_substring in ast.dump(node):
                nearest_for_matches.append(stack[-1] if stack else None)
            self.generic_visit(node)

    _Visitor().visit(root)
    if not nearest_for_matches:
        raise AssertionError(f"no call site matching {call_substring!r} found in run()")

    def _catches_exception(try_node) -> bool:
        for handler in try_node.handlers:
            if handler.type is None:
                return True
            if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                return True
        return False

    def _handler_reraises(try_node) -> bool:
        for handler in try_node.handlers:
            for stmt in ast.walk(handler):
                if isinstance(stmt, ast.Raise):
                    return True
        return False

    return all(
        try_node is not None and _catches_exception(try_node) and not _handler_reraises(try_node)
        for try_node in nearest_for_matches
    )


class NewsFaultsCannotReachTheLoopsReraise(unittest.TestCase):
    """Item 3: the main loop's `except Exception` RE-RAISES and kills the
    process. The boot fetch and the per-tick news status check are the only
    two unguarded news call sites reachable from that loop; both must be
    locally try/except'd (matching how GUI start is guarded) so a news fault
    degrades instead of taking the whole bot down."""

    def test_boot_calendar_fetch_call_site_is_locally_guarded(self):
        self.assertTrue(_call_site_is_guarded(_run_method_node(), "update_calendar"))

    def test_check_news_status_call_site_is_locally_guarded(self):
        self.assertTrue(_call_site_is_guarded(_run_method_node(), "_check_news_status"))


if __name__ == "__main__":
    unittest.main()
