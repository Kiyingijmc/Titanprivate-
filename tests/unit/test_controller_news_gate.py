import ast
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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


class _CountingNews(_PerSymbolNews):
    """Records every calendar consultation, so a per-ROW walk is visible."""

    def __init__(self, blocked_symbols, reason="Core PCE in 20m"):
        super().__init__(blocked_symbols, reason)
        self.calls = []

    def check_symbol(self, symbol, now=None):
        self.calls.append(symbol)
        return super().check_symbol(symbol, now)


class _StaleCalendarNews:
    """The global halt: a cache too old to trust blocks EVERY symbol with no
    event involved at all (manager.py is_globally_blocked)."""

    REASON = ("News calendar is stale (3h 10m) and the feed is unreachable -- "
              "trading halted until it refreshes.")

    def is_globally_blocked(self, now=None):
        return True, self.REASON

    def check_symbol(self, symbol, now=None):
        return True, self.REASON


class _SweepBridge:
    """FakeBridge only speaks the reliable REQ path; the sweep uses PUSH.

    `send_ok=False` is the wire error ZMQBridge.send_command reports by
    returning False (bridge_zmq.py:74-81) -- the failure mode the sweep must
    not mistake for a completed cancel.
    """

    def __init__(self, send_ok=True):
        self.reliable = []
        self.commands = []
        self.send_ok = send_ok

    async def send_order_reliable(self, payload, timeout=2500):
        self.reliable.append(dict(payload))
        return True

    async def send_command(self, cmd, payload=None):
        self.commands.append((cmd, dict(payload or {})))
        return self.send_ok


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


def _sweep_controller(rows, news, resting=None, positions=None, send_ok=True):
    """A controller whose broker book agrees with the DB unless told otherwise.

    `resting` is the heartbeat's `orders` list (what the broker still reports);
    it defaults to every row, because a cancel is only ever confirmed by a
    ticket LEAVING that list. `positions` is the heartbeat's `pos` list.
    """
    c = _controller(positions or [])
    c.bridge = _SweepBridge(send_ok=send_ok)
    c.state_manager = _SweepStateManager(rows)
    c.news_manager = news
    c.current_pending_orders = (
        [{"t": r["ticket_id"]} for r in rows] if resting is None else resting)
    c.last_heartbeat_time = datetime.now()   # a live EA feed
    # The sweep certifies the BOOK, not generic traffic: only a HEARTBEAT
    # rewrites `current_pending_orders`, so freshness rides its own stamp
    # (RS023 R2-MINOR-1).
    c.last_book_snapshot_at = datetime.now()
    return c


def _broker_no_longer_reports(c, ticket):
    """The heartbeat proof a CANCEL landed."""
    c.current_pending_orders = [
        o for o in c.current_pending_orders if o["t"] != ticket]


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

    def test_blocked_symbols_pending_is_cancelled(self):
        c = _sweep_controller([_pending(111, "EURUSD")], _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [("CANCEL", {"ticket": 111})])

    def test_unaffected_symbols_pending_is_left_untouched(self):
        """Control case: without it, a sweep that cancelled EVERY pending row
        would pass the test above."""
        c = _sweep_controller(
            [_pending(111, "EURUSD"), _pending(222, "GBPJPY")],
            _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [("CANCEL", {"ticket": 111})])
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(
            [r["ticket_id"] for r in c.state_manager.get_pending_orders()], [111, 222])

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


class NewsCancelIsVerifiedNotAssumed(unittest.TestCase):
    """RS023 CRITICAL-1 -- the same defect RS022 MAJOR-1 was remediated for,
    re-introduced 200 lines from its fix and with a far bigger blast radius
    (this sweep fires for ANY blocked symbol, and a gate fault or a stale
    calendar blocks EVERY symbol at once).

    CANCEL is fire-and-forget on PUSH: send_command returns False on a wire
    error and an EA-side reject never reaches Python at all. Deleting the DB
    row on the strength of the send therefore loses a still-resting order --
    nothing can re-register a swept PENDING row, so it fills into the very
    release this sweep exists to prevent, invisible to the portfolio cap.
    """

    def _blocked(self, **kw):
        return _sweep_controller([_pending(111, "EURUSD")],
                                 _PerSymbolNews(["EURUSD"]), **kw)

    def test_row_survives_the_first_cancel(self):
        """The broker still reports it resting: the send proves nothing yet."""
        c = self._blocked()
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(
            [r["ticket_id"] for r in c.state_manager.get_pending_orders()], [111])

    def test_row_is_deleted_only_once_the_broker_stops_reporting_it(self):
        c = self._blocked()
        _run(c._sweep_news_blocked_pendings())
        _broker_no_longer_reports(c, 111)
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [111])
        # ...and the confirmed pull is announced, not just the attempt: the
        # only DB-row remover that said nothing was RS022 round-2 MINOR-3.
        self.assertTrue(
            any(e[1] == "NEWS" and "confirmed" in e[2] for e in c.logger.events),
            c.logger.events)

    def test_a_confirmed_cancel_is_not_re_sent(self):
        c = self._blocked()
        _run(c._sweep_news_blocked_pendings())
        _broker_no_longer_reports(c, 111)
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [("CANCEL", {"ticket": 111})])

    def test_unsent_cancel_keeps_the_row_and_is_retried(self):
        """send_command returned False: the CANCEL never left the process."""
        c = self._blocked(send_ok=False)
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [])
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(len(c.bridge.commands), 2, c.bridge.commands)
        self.assertEqual(c.state_manager.deleted, [])

    def test_a_failed_send_is_not_announced_as_a_pull(self):
        c = self._blocked(send_ok=False)
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.telemetry.messages, [])

    def test_cancel_that_did_not_take_is_resent_on_the_next_tick(self):
        """The send landed on the wire but the EA refused it (10018 market
        closed): the ticket is still in the heartbeat's `orders`."""
        c = self._blocked()
        _run(c._sweep_news_blocked_pendings())
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands,
                         [("CANCEL", {"ticket": 111})] * 2)
        self.assertEqual(c.state_manager.deleted, [])

    def test_confirmation_is_not_believed_on_a_stale_feed(self):
        """After a restart inside a news window the DB still holds PENDING
        rows while `current_pending_orders` is an empty list no heartbeat has
        filled in yet. Absence from THAT list is not proof of anything."""
        c = self._blocked()
        _run(c._sweep_news_blocked_pendings())
        c.current_pending_orders = []
        c.last_book_snapshot_at = datetime.now() - timedelta(
            seconds=c.NEWS_CANCEL_CONFIRM_MAX_FEED_AGE_S + 5)
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [])

    def test_a_tick_does_not_refresh_the_book_snapshot(self):
        """RS023 R2-MINOR-1: only a HEARTBEAT rewrites `current_pending_orders`,
        so only a HEARTBEAT may certify it fresh. A TICK routed through the real
        dispatcher bumps the generic `last_heartbeat_time` — if the guard reads
        that, a heartbeat-specific stall with ticks still flowing deletes the DB
        row of an order that is still resting at the broker."""
        c = self._blocked()
        _run(c._sweep_news_blocked_pendings())
        c.current_pending_orders = []          # stale: no heartbeat wrote this
        c.last_book_snapshot_at = datetime.now() - timedelta(
            seconds=c.NEWS_CANCEL_CONFIRM_MAX_FEED_AGE_S + 5)
        c.state = controller_module.BotState.PAUSED  # ticks route, no candles
        _run(c._process_incoming_data({"type": "TICK", "s": "EURUSD", "b": 1.1}))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [])

    def test_operator_notice_is_edge_triggered_per_ticket(self):
        """The row now survives an unconfirmed cancel, so an un-edge-triggered
        notice would Telegram the same order every 60s forever."""
        c = self._blocked()
        for _ in range(3):
            _run(c._sweep_news_blocked_pendings())
        self.assertEqual(len(c.telemetry.messages), 1, c.telemetry.messages)

    def test_a_stuck_cancel_escalates_to_telegram(self):
        """The operator was told the order is being cancelled; an EA that keeps
        refusing leaves it resting into the release (RS022 round-2 MAJOR-1)."""
        c = self._blocked()
        for _ in range(c.NEWS_CANCEL_ESCALATE_AFTER_SENDS + 1):
            _run(c._sweep_news_blocked_pendings())
        self.assertEqual(len(c.telemetry.messages), 2, c.telemetry.messages)
        self.assertIn("STILL RESTING", c.telemetry.messages[1])

    def test_escalation_is_throttled(self):
        c = self._blocked()
        for _ in range(c.NEWS_CANCEL_ESCALATE_AFTER_SENDS + 4):
            _run(c._sweep_news_blocked_pendings())
        self.assertEqual(len(c.telemetry.messages), 2, c.telemetry.messages)

    def test_escalation_re_arms_once_the_cancel_confirms(self):
        """Control case for the throttle: a fresh stuck ticket must alert
        afresh rather than be swallowed by a timer still running."""
        c = self._blocked()
        for _ in range(c.NEWS_CANCEL_ESCALATE_AFTER_SENDS + 1):
            _run(c._sweep_news_blocked_pendings())
        _broker_no_longer_reports(c, 111)
        _run(c._sweep_news_blocked_pendings())
        self.assertIsNone(c._news_cancel_alert_at)

    def test_a_cleared_window_stops_the_retry(self):
        """Once the symbol is tradeable again we no longer want the order
        gone: stop re-sending, and leave any late-landing cancel to the Sync
        Guard rather than deleting a row we cannot prove is dead."""
        news = _PerSymbolNews(["EURUSD"])
        c = _sweep_controller([_pending(111, "EURUSD")], news)
        _run(c._sweep_news_blocked_pendings())
        news.blocked_symbols.clear()
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(len(c.bridge.commands), 1, c.bridge.commands)
        self.assertEqual(c.state_manager.deleted, [])


class NewsSweepLeavesFilledTicketsAlone(unittest.TestCase):
    """RS023 MAJOR-1 (the RS022 MINOR-4 case). A limit that filled seconds ago
    is STILL a PENDING row until the next heartbeat's adoption pass flips it,
    and fills cluster on exactly the volatility this sweep reacts to. Cancelling
    and deleting there strips the DB row off a LIVE position: TradeManager
    never manages it (BE/partials/ratchet need initial_entry/initial_tp on the
    row), the risk cap cannot count it, and every ordinary health check reports
    it as fine -- the 2026-08-03 stopless-GBPJPY class."""

    def _filled(self):
        return _sweep_controller(
            [_pending(111, "EURUSD")], _PerSymbolNews(["EURUSD"]),
            resting=[], positions=[{"t": 111, "s": "EURUSD"}])

    def test_ticket_that_filled_is_left_to_the_adoption_path(self):
        c = self._filled()
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands, [])
        self.assertEqual(c.state_manager.deleted, [])
        self.assertEqual(
            [r["ticket_id"] for r in c.state_manager.get_pending_orders()], [111])

    def test_a_fill_after_a_cancel_was_sent_is_not_deleted_either(self):
        """The dangerous ordering: cancel sent on tick 1, the limit fills
        before it lands, so on tick 2 the ticket is absent from `orders` --
        which the confirmation branch would otherwise read as proof."""
        c = _sweep_controller([_pending(111, "EURUSD")], _PerSymbolNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        c.current_pending_orders = []
        c.current_open_positions = [{"t": 111, "s": "EURUSD"}]
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.state_manager.deleted, [])


class NewsPullNoticeTellsTheTruth(unittest.TestCase):
    """RS023 MAJOR-2. Three conditions reach the pull notice and only one of
    them is a red-folder window: a gate fault and a stale calendar are feed
    failures with no event and no end time. Asserting a window there
    contradicts the `reason` printed one line above and sends the operator
    looking for an event that does not exist -- in precisely the two cases
    where a correct diagnosis matters most."""

    def _notice(self, news):
        """The pull notice itself -- a faulting gate also fires its own
        (correct, and separately tested) fail-closed alarm."""
        c = _sweep_controller([_pending(111, "EURUSD")], news)
        _run(c._sweep_news_blocked_pendings())
        pulls = [m for m in c.telemetry.messages if "News Pull" in m]
        self.assertEqual(len(pulls), 1, c.telemetry.messages)
        return pulls[0]

    def test_a_real_event_names_the_window(self):
        """Control case: the claim below must be absent for the RIGHT reason,
        not because it was deleted from every path."""
        msg = self._notice(_PerSymbolNews(["EURUSD"]))
        self.assertIn("red-folder window", msg)
        self.assertIn("re-signals", msg)

    def test_a_gate_fault_claims_no_scheduled_event(self):
        msg = self._notice(_StubNews(raise_exc=RuntimeError("feed exploded")))
        self.assertNotIn("red-folder window", msg)
        self.assertIn("no scheduled event", msg.lower())
        self.assertIn("feed exploded", msg)

    def test_a_stale_calendar_claims_no_scheduled_event(self):
        msg = self._notice(_StaleCalendarNews())
        self.assertNotIn("red-folder window", msg)
        self.assertIn("no scheduled event", msg.lower())
        self.assertIn("stale", msg)

    def test_the_notice_does_not_assert_the_order_is_already_gone(self):
        """CANCEL is fire-and-forget; the earlier wording announced the pull as
        a completed fact (RS022 round-2 MINOR-3's lesson, inverted)."""
        msg = self._notice(_PerSymbolNews(["EURUSD"]))
        self.assertIn("confirmed only when the broker", msg)


class NewsSweepCalendarCost(unittest.TestCase):
    """RS023 MINOR-2: the verdict is per SYMBOL, not per row."""

    def test_calendar_is_consulted_once_per_symbol_not_once_per_row(self):
        news = _CountingNews(["EURUSD"])
        c = _sweep_controller(
            [_pending(111, "EURUSD"), _pending(222, "EURUSD"),
             _pending(333, "GBPJPY")], news)
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(sorted(news.calls), ["EURUSD", "GBPJPY"])

    def test_every_row_on_a_blocked_symbol_is_still_cancelled(self):
        """Control case: memoising the verdict must not memoise the ACTION."""
        c = _sweep_controller(
            [_pending(111, "EURUSD"), _pending(222, "EURUSD")],
            _CountingNews(["EURUSD"]))
        _run(c._sweep_news_blocked_pendings())
        self.assertEqual(c.bridge.commands,
                         [("CANCEL", {"ticket": 111}), ("CANCEL", {"ticket": 222})])


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
