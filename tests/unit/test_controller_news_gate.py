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


class _PerSymbolNews:
    """Blocks only the named symbols, so a sweep test can carry a control row."""

    def __init__(self, blocked_symbols, reason="Core PCE in 20m"):
        self.blocked_symbols = set(blocked_symbols)
        self.reason = reason

    def check_symbol(self, symbol, now=None):
        if symbol in self.blocked_symbols:
            return True, self.reason
        return False, None


class _SweepBridge:
    """FakeBridge only speaks the reliable REQ path; the sweep uses PUSH."""

    def __init__(self):
        self.reliable = []
        self.commands = []

    async def send_order_reliable(self, payload, timeout=2500):
        self.reliable.append(dict(payload))
        return True

    async def send_command(self, cmd, payload=None):
        self.commands.append((cmd, dict(payload or {})))
        return True


class _SweepStateManager:
    """Only the surface the pending sweep touches."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.deleted = []

    def get_pending_orders(self):
        return [dict(r) for r in self.rows]

    def delete_order(self, ticket):
        self.deleted.append(ticket)
        self.rows = [r for r in self.rows if r['ticket_id'] != ticket]


def _pending(ticket, symbol, strategy="SilverBullet"):
    return {"ticket_id": ticket, "symbol": symbol, "strategy": strategy,
            "order_type": "LIMIT", "time_placed": 0.0, "status": "PENDING"}


def _sweep_controller(rows, news):
    c = _controller([])
    c.bridge = _SweepBridge()
    c.state_manager = _SweepStateManager(rows)
    c.news_manager = news
    return c


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
    """The production invariant: a blocked symbol sends no order, and a gate
    that cannot answer blocks too. Reuses test_risk_manager_exposure_cap's
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

    def test_a_news_fault_fails_closed_and_sends_no_order(self):
        """Replaces test_a_news_fault_fails_open_and_still_trades, which pinned
        the OLD contract (a fault degraded to 'not blocked'). A gate that
        cannot answer must block: a broken gate was indistinguishable from a
        quiet calendar and let signals through a red-folder release
        (audit-2026-08-07 D11). The fault must not crash the trade path
        either -- _execute_signal still returns normally."""
        c = _controller([])
        c.news_manager = _StubNews(raise_exc=RuntimeError("feed exploded"))
        _run(c._execute_signal("EURUSD", DECISION, "SilverBullet", "BULLISH"))
        self.assertEqual(c.bridge.reliable, [])
        self.assertEqual(c._reserved_risk, {})
        self.assertEqual(c.pending_signal_meta, {})

    def test_a_news_fault_returns_a_reason_naming_the_fault(self):
        """A fail-closed block must be distinguishable from a real release --
        otherwise the skip log reads as 'Core PCE' when nothing is scheduled."""
        c = _controller([])
        c.news_manager = _StubNews(raise_exc=RuntimeError("feed exploded"))
        blocked, reason = _run(c._news_blocks_symbol("EURUSD"))
        self.assertTrue(blocked)
        self.assertIn("fault", reason.lower())
        self.assertIn("feed exploded", reason)


class NewsGateFaultAlert(unittest.TestCase):
    """A fail-closed gate is a SILENT trading stop unless the fault is
    announced -- the same failure mode _alert_uncomputable_book exists for."""

    def _faulting(self):
        c = _controller([])
        c.news_manager = _StubNews(raise_exc=RuntimeError("feed exploded"))
        return c

    def test_gate_fault_telegrams_the_operator(self):
        c = self._faulting()
        _run(c._news_blocks_symbol("EURUSD"))
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        self.assertIn("feed exploded", c.telemetry.messages[0])

    def test_alert_is_distinct_from_the_per_signal_skip_log(self):
        """The old behaviour was a WARN log line only. Keep the log AND add
        the Telegram, so grepping the audit log still shows the fault."""
        c = self._faulting()
        _run(c._news_blocks_symbol("EURUSD"))
        self.assertTrue(any(e[0] == "WARN" and e[1] == "NEWS" for e in c.logger.events),
                        c.logger.events)

    def test_repeat_faults_are_throttled_within_the_window(self):
        """12 symbols x every candle close would otherwise spam the operator
        off the channel, exactly as DD_CANCEL_ALERT_INTERVAL_S prevents."""
        c = self._faulting()
        for symbol in ("EURUSD", "GBPJPY", "XAUUSD", "EURUSD"):
            _run(c._news_blocks_symbol(symbol))
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)

    def test_alert_re_arms_once_the_window_elapses(self):
        """Control case for the throttle: without it, a permanently faulting
        gate would alert once at boot and then stay silent forever."""
        c = self._faulting()
        _run(c._news_blocks_symbol("EURUSD"))
        c._news_fault_alert_at -= (c.NEWS_FAULT_ALERT_INTERVAL_S + 1)
        _run(c._news_blocks_symbol("EURUSD"))
        self.assertEqual(len(c.telemetry.messages), 2, c.telemetry.messages)

    def test_a_healthy_gate_alerts_nothing(self):
        c = _controller([])
        c.news_manager = _StubNews(blocked=True, reason="Core PCE in 20m")
        _run(c._news_blocks_symbol("EURUSD"))
        self.assertEqual(c.telemetry.messages, [])


class NewsSweepOfRestingPendings(unittest.TestCase):
    """The send-time gate runs ONCE, at placement. A LIMIT rests for 12 bars
    of its strategy's timeframe (up to 12h on H1), so an order placed on a
    clear calendar can sit through a later red-folder release and fill into
    it. The sweep pulls it first."""

    def test_blocked_symbols_pending_is_cancelled_and_deleted(self):
        c = _sweep_controller([_pending(111, "EURUSD")], _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [("CANCEL", {"ticket": 111})])
        self.assertEqual(c.state_manager.deleted, [111])
        self.assertEqual(c.state_manager.get_pending_orders(), [])

    def test_unaffected_symbols_pending_is_left_untouched(self):
        """Control case: without it, a sweep that cancelled EVERY pending row
        would pass the test above."""
        c = _sweep_controller(
            [_pending(111, "EURUSD"), _pending(222, "GBPJPY")],
            _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [111])
        self.assertEqual(
            [r["ticket_id"] for r in c.state_manager.get_pending_orders()], [222])

    def test_quiet_calendar_cancels_nothing(self):
        c = _sweep_controller([_pending(111, "EURUSD")], _PerSymbolNews([]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [])
        self.assertEqual(c.state_manager.deleted, [])

    def test_operator_notice_is_worded_apart_from_the_ttl_auto_clean(self):
        """A news-driven pull and a TTL expiry must not read the same in
        Telegram -- one means 'the market got dangerous', the other means
        'the setup went stale'."""
        c = _sweep_controller([_pending(111, "EURUSD")], _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)
        msg = c.telemetry.messages[0]
        self.assertNotIn("Auto-Clean", msg)
        self.assertIn("#111", msg)
        self.assertIn("EURUSD", msg)
        self.assertIn("Core PCE", msg)

    def test_gate_fault_pulls_the_book(self):
        """Fail-closed is one contract, not two: if the gate cannot say a
        resting order is safe, the order does not rest through the unknown."""
        c = _sweep_controller([_pending(111, "EURUSD")],
                              _StubNews(raise_exc=RuntimeError("feed exploded")))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [("CANCEL", {"ticket": 111})])

    def test_rows_without_a_symbol_are_skipped_not_crashed(self):
        row = _pending(111, "EURUSD")
        row.pop("symbol")
        c = _sweep_controller([row], _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [])

    def test_sweep_is_called_from_run_and_is_locally_guarded(self):
        """Wiring guard: the sweep is dead code unless run() calls it, and it
        reaches the news feed -- so like every other news call site in the
        loop it must be try/except'd short of the loop's own re-raise."""
        self.assertTrue(
            _call_site_is_guarded(_run_method_node(), "_sweep_news_blocked_pendings"))


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
