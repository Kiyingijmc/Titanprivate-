"""Failure, restart and stale-snapshot coverage for management reconciliation."""
import tempfile
import unittest
from unittest.mock import Mock, patch, AsyncMock

from src.core.state_manager import StateManager
from src.core.system_controller import SystemController
from src.execution.trade_manager import TradeManager
from src.risk.risk_manager import RiskManager
from src.risk.exposure import ExposureManager


class ManagementConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/state.db'
        self.sm = StateManager(self.path)
        self.cfg = {'risk': {'account': {'max_daily_drawdown_pct': 5},
                            'trade': {'risk_per_trade_pct': 1, 'static_commission_usd': 7}},
                    'trade_management': {'runner': {'enabled': True}}}
        self.risk = RiskManager(self.cfg)
        self.risk.update_account_info(1000, 1000)
        self.risk.update_symbol_specs('EURUSD', 1, .00001, .01, .01)
        self.sm.register_order(1, 'EURUSD', 'Test', 'MARKET', status='ACTIVE',
                               entry=1.1, sl=1.09, tp=1.11, lots=1)
        self.tm = TradeManager(Mock(), self.sm, self.risk, self.cfg)
        self.pos = {'t': 1, 's': 'EURUSD', 'type': 0, 'p': 1.1,
                    'sl': 1.09, 'tp': 1.11, 'vol': 1, 'pf': 0}

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def sync(self, price=1.1065):
        self.tm.command_cooldowns.clear()
        return self.tm.sync_positions([self.pos], {'EURUSD': price})

    def test_failed_send_retries_same_target_without_advancing(self):
        first = self.sync()
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 0)
        self.assertEqual(self.sync(), first)
        close = next(c for c in first if c['action'] == 'CLOSE_PARTIAL')
        self.assertAlmostEqual(close['target_volume'], .7)

    def test_restart_retains_unconfirmed_stop_and_partial(self):
        first = self.sync()
        self.sm.close()
        self.sm = StateManager(self.path)
        self.tm = TradeManager(Mock(), self.sm, self.risk, self.cfg)
        self.assertEqual(self.sync(), first)
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 0)

    def test_lost_deal_event_reconciles_from_broker_volume(self):
        self.sync()
        self.pos.update(sl=1.10382, vol=.7)
        self.assertEqual([c['action'] for c in self.sync()], ['MODIFY_CONFIRMED'])
        self.assertEqual(self.sync(), [])
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 2)
        self.assertEqual(self.sm.get_partial_state(1), (1, 1))
        closes = [c for c in self.sync(1.109) if c['action'] == 'CLOSE_PARTIAL']
        self.assertAlmostEqual(closes[0]['volume'], .35)
        self.assertAlmostEqual(closes[0]['target_volume'], .35)

    def test_volume_confirmation_alone_does_not_advance_stop(self):
        self.sync()
        self.pos['vol'] = .7
        cmds = self.sync(1.109)
        self.assertEqual([c['action'] for c in cmds], ['MODIFY'])
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 0)

    def test_stop_confirmation_alone_retries_only_partial(self):
        self.sync()
        self.pos['sl'] = 1.10382
        cmds = self.sync()
        self.assertEqual([c['action'] for c in cmds], ['CLOSE_PARTIAL'])
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 0)

    def test_partial_broker_fill_retries_only_unfilled_remainder(self):
        self.sync()
        self.pos.update(sl=1.10382, vol=.8)
        close = self.sync()[0]
        self.assertAlmostEqual(close['volume'], .1)
        self.assertAlmostEqual(close['target_volume'], .7)

    def test_runner_never_restores_stale_tp(self):
        self.sm.update_ratchet_level(1, 3)
        self.pos['sl'] = 1.10618
        cmd = self.sync(1.1095)[0]
        self.assertEqual(cmd['tp'], 0)
        # Clearing TP is necessary even when the existing stop is tighter.
        self.pos['sl'] = 1.109
        cmd = self.sync(1.1095)[0]
        self.assertEqual(cmd['tp'], 0)
        self.assertEqual(cmd['sl'], 1.109)

    def test_short_threshold_uses_ask(self):
        self.sm.register_order(2, 'EURUSD', 'Test', 'MARKET', status='ACTIVE',
                               entry=1.11, sl=1.12, tp=1.10, lots=1)
        p = dict(self.pos, t=2, type=1, p=1.11, sl=1.12, tp=1.1)
        # Bid has crossed L1, executable ask has not.
        self.assertEqual(self.tm.sync_positions([p], {'EURUSD': 1.106},
                                                {'EURUSD': 1.1063}), [])
        self.assertEqual(self.tm.sync_positions([p], {'EURUSD': 1.106}, {}), [])

    def test_short_runner_trails_ask(self):
        self.sm.register_order(2, 'EURUSD', 'Test', 'MARKET', status='ACTIVE',
                               entry=1.11, sl=1.12, tp=1.10, lots=1)
        self.sm.update_ratchet_level(2, 3)
        p = dict(self.pos, t=2, type=1, p=1.11, sl=1.108, tp=0)
        cmd = self.tm.sync_positions([p], {'EURUSD': 1.10}, {'EURUSD': 1.1005})[0]
        self.assertAlmostEqual(cmd['sl'], 1.10318)

    def test_commission_dominant_stop_respects_budget(self):
        self.risk.update_symbol_specs('TEST', 1, 1, .01, .01)
        lots = self.risk.calculate_lot_size(100, 90, 'TEST', 'BULLISH')
        self.assertGreater(lots, 0)
        self.assertLessEqual(self.risk.risk_to_stop('TEST', 10, lots), 10)

    def test_fine_volume_step_is_not_rounded_up(self):
        self.risk.update_symbol_specs('FINE', 1, 1, .001, .001)
        lots = self.risk.calculate_lot_size(100, 90, 'FINE', 'BULLISH')
        self.assertAlmostEqual(lots, .588)
        self.assertEqual(self.tm._partial_volume('FINE', .015, .3), ('PARTIAL', .004))

    def test_committed_book_deduplicates_pending_and_counts_reservations(self):
        c = SystemController.__new__(SystemController)
        c.state_manager = self.sm
        c.current_open_positions = [self.pos]
        self.sm.register_order(2, 'GBPUSD', 'Test', 'LIMIT', entry=1.2, sl=1.1, tp=1.3, lots=.1)
        c.current_pending_orders = [{'t': 2, 's': 'GBPUSD'}]
        c._reserve_risk('USDJPY', 1)
        book = c._committed_positions()
        self.assertEqual(len(book), 3)
        exposure = ExposureManager(self.cfg, {})
        self.assertFalse(exposure.check_exposure('GBPUSD', book)[0])
        self.assertFalse(exposure.check_exposure('USDJPY', book)[0])
        exposure.max_total_positions = 3
        self.assertFalse(exposure.check_exposure('XAUUSD', book)[0])

    def test_cleanup_runs_after_missed_wall_clock_window(self):
        c = SystemController.__new__(SystemController)
        with patch('src.core.system_controller.time.monotonic', side_effect=[100.123, 159.99, 167.8, 167.9]):
            self.assertTrue(c._pending_sweep_due())
            self.assertFalse(c._pending_sweep_due())
            self.assertTrue(c._pending_sweep_due())
            self.assertFalse(c._pending_sweep_due())


class ManagementDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_close_uses_distinct_idempotent_gateway_action(self):
        c = SystemController.__new__(SystemController)
        c._management_protocol = 2
        c.bridge = Mock(send_command=AsyncMock(return_value=True))
        c.logger = Mock()
        c.telemetry = Mock(notify_partial=AsyncMock())
        await c._dispatch_mgmt_command({'action': 'CLOSE_PARTIAL', 'ticket': 1,
                                       'volume': .3, 'target_volume': .7})
        c.bridge.send_command.assert_awaited_once_with('CLOSE_TO_VOLUME',
                                                     {'ticket': 1, 'volume': .3, 'target_volume': .7})
        c.telemetry.notify_partial.assert_not_awaited()

    async def test_old_gateway_cannot_receive_targeted_partial(self):
        c = SystemController.__new__(SystemController)
        c.bridge = Mock(send_command=AsyncMock(return_value=True))
        c.logger = Mock()
        result = await c._dispatch_mgmt_command({'action': 'CLOSE_PARTIAL', 'ticket': 1,
                                                'volume': .3, 'target_volume': .7})
        self.assertFalse(result)
        c.bridge.send_command.assert_not_awaited()
        c.logger.log_event.assert_called_once()

    async def test_ratchet_request_waits_for_confirmation_to_notify(self):
        c = SystemController.__new__(SystemController)
        c.bridge = Mock(send_command=AsyncMock(return_value=True))
        c.logger = Mock()
        c.telemetry = Mock(notify_management=AsyncMock())
        await c._dispatch_mgmt_command({'action': 'MODIFY', 'ticket': 1, 'symbol': 'EURUSD',
                                       'sl': 1.10382, 'tp': 1.11, 'comment': 'Ratchet L2',
                                       'await_confirmation': True})
        c.telemetry.notify_management.assert_not_awaited()
        c.state_manager = Mock(get_order=Mock(return_value=None))
        await c._dispatch_mgmt_command({'action': 'MODIFY_CONFIRMED', 'ticket': 1,
                                       'symbol': 'EURUSD', 'sl': 1.10382, 'tp': 1.11,
                                       'comment': 'Ratchet L2'})
        self.assertEqual(c.bridge.send_command.await_count, 1)
        c.telemetry.notify_management.assert_awaited_once()

    async def test_failed_modify_does_not_announce_success(self):
        c = SystemController.__new__(SystemController)
        c.bridge = Mock(send_command=AsyncMock(return_value=False))
        c.logger = Mock()
        c.telemetry = Mock(notify_management=AsyncMock())
        result = await c._dispatch_mgmt_command({'action': 'MODIFY', 'ticket': 1,
                                               'symbol': 'EURUSD', 'sl': 1.1, 'tp': 1.2})
        self.assertFalse(result)
        c.telemetry.notify_management.assert_not_awaited()
