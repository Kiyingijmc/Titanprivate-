"""Causal swing detection and durable structural trade management."""
import unittest
import tempfile
from unittest.mock import Mock
import numpy as np
import pandas as pd
from src.analysis.structure_management import StructurePolicy, m15_context, management_plan
from src.core.state_manager import StateManager
from src.execution.trade_manager import TradeManager
from src.risk.risk_manager import RiskManager


def context(efficiency=.3, ratio=1):
    return dict(atr=.001, volatility_ratio=ratio, efficiency=efficiency,
                swing_low=dict(price=1.104, time='2026-01-02', continuation=True),
                swing_high=dict(price=1.096, time='2026-01-02', continuation=True))


class PolicyTests(unittest.TestCase):
    def plan(self, **kw):
        args = dict(context=context(), policy=StructurePolicy(), entry=1.1,
                    original_tp=1.11, current_sl=1.09, current_tp=1.11,
                    price=1.106, is_long=True, spread=.0001, tick_size=.00001,
                    since='2026-01-01', level=0)
        args.update(kw)
        return management_plan(**args)

    def test_halfway_trigger_and_dynamic_sizes(self):
        self.assertIsNone(self.plan(price=1.1049))
        self.assertEqual(self.plan(price=1.105)['fraction'], .35)
        for eff, ratio, fraction in [(.3, 1, .35), (.8, 1, .25), (-.1, 1, .5), (.8, 2, .5)]:
            p = self.plan(context=context(eff, ratio))
            self.assertEqual(p['fraction'], fraction)
            self.assertEqual(p['sl'], 1.09)
            self.assertEqual(p['tp'], 1.11)

    def test_long_short_structure_and_monotonic_stop(self):
        p = self.plan(level=2)
        self.assertAlmostEqual(p['sl'], 1.10385)
        self.assertEqual(p['tp'], 0)
        p = self.plan(level=2, is_long=False, original_tp=1.09, current_tp=1.09,
                      current_sl=1.11, price=1.094)
        self.assertAlmostEqual(p['sl'], 1.09625)
        self.assertEqual(p['tp'], 0)
        self.assertIsNone(self.plan(level=3, current_sl=1.105, current_tp=0))

    def test_old_reversal_or_unconfirmed_pivot_keeps_target(self):
        ctx = context(); ctx['swing_low'] = None
        self.assertIsNone(self.plan(context=ctx, level=2))
        ctx = context(); ctx['swing_low']['continuation'] = False
        self.assertIsNone(self.plan(context=ctx, level=2))
        self.assertIsNone(self.plan(level=2, since='2026-01-03'))

    def test_second_partial_once_and_volatility_spacing(self):
        ctx = context(); ctx['swing_low'] = None; ctx['atr'] = .005
        self.assertIsNone(self.plan(level=2, context=ctx, price=1.108))
        self.assertEqual(self.plan(level=2, context=ctx, price=1.109)['fraction'], .25)
        self.assertIsNone(self.plan(level=3, context=ctx, price=1.109))

    def test_future_data_cannot_change_context(self):
        t = pd.date_range('2026-01-01', periods=150, freq='5min')
        p = 100 + np.sin(np.arange(150)/3) + np.arange(150)*.01
        f = pd.DataFrame(dict(time=t, open=p, close=p, high=p+.1, low=p-.1))
        asof = t[120]
        a = m15_context(f, asof)
        self.assertIsNotNone(a)
        f.loc[120:, ['open', 'close', 'high', 'low']] *= 10
        self.assertEqual(a, m15_context(f, asof))
        for name in ('swing_low', 'swing_high'):
            self.assertLessEqual(pd.Timestamp(a[name]['confirmed_at']), asof)
        self.assertIsNone(m15_context(f.iloc[:120], t[-1]+pd.Timedelta(hours=1)))
        self.assertIsNone(m15_context(f.iloc[:50], asof))

    def test_pivot_requires_both_following_bars_to_close(self):
        t = pd.date_range('2026-01-01', periods=135, freq='5min')
        low = 100 + np.sin(np.arange(135)/3)
        low[-15:] = np.repeat([105., 104., 103., 104., 105.], 3)
        f = pd.DataFrame(dict(time=t, open=108., close=108., high=110., low=low))
        before = m15_context(f, t[-1])
        after = m15_context(f, t[-1]+pd.Timedelta(minutes=5))
        expected = str(t[126])
        self.assertNotEqual(before['swing_low']['time'], expected)
        self.assertEqual(after['swing_low']['time'], expected)
        self.assertEqual(after['swing_low']['confirmed_at'], str(t[-1]+pd.Timedelta(minutes=5)))


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name+'/state.db'
        self.sm = StateManager(self.path)
        self.cfg = {'risk': {'account': {'max_daily_drawdown_pct': 5}, 'trade': {'risk_per_trade_pct': 1}}, 'trade_management': {'structure': {'enabled': True, 'strategies': ['Test']}}}
        self.risk = RiskManager(self.cfg)
        self.risk.update_symbol_specs('EURUSD', 1, .00001, .01, .01)
        self.tm = TradeManager(Mock(), self.sm, self.risk, self.cfg)
        self.sm.register_order(1, 'EURUSD', 'Test', 'MARKET', status='ACTIVE',
                               entry=1.1, sl=1.09, tp=1.11, lots=1)
        self.pos = dict(t=1, s='EURUSD', type=0, sl=1.09, tp=1.11, vol=1, pf=0)
        self.tm._structure_context['EURUSD'] = context()

    def tearDown(self):
        self.sm.close(); self.tmp.cleanup()

    def sync(self):
        self.tm.command_cooldowns.clear()
        return self.tm.sync_positions([self.pos], {'EURUSD': 1.106}, {'EURUSD': 1.1061})

    def test_restart_and_regime_change_preserve_exact_volume_target(self):
        first = self.sync()
        self.assertEqual(first[0]['target_volume'], .65)
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 0)
        self.tm._structure_context['EURUSD'] = context(-1, 2)
        self.assertEqual(first, self.sync())
        self.sm.close(); self.sm = StateManager(self.path)
        self.tm = TradeManager(Mock(), self.sm, self.risk, {})
        self.assertTrue(self.tm.structure_enabled)
        self.assertEqual(first, self.sync())
        self.pos['vol'] = .8
        self.assertAlmostEqual(self.sync()[0]['volume'], .15)
        self.pos['vol'] = .65
        self.assertEqual(self.sync()[0]['action'], 'MODIFY_CONFIRMED')
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 2)
        self.assertEqual(self.sync(), [])

    def test_missing_context_does_not_fall_back_to_ratchet(self):
        self.tm._structure_context.clear()
        self.assertEqual(self.sync(), [])
        self.assertEqual(self.sm.get_management_profile(1)['mode'], 'm15_structure_v1')

    def test_preexisting_trade_retains_legacy_profile(self):
        self.tm._started_at += 100
        self.assertTrue(self.sync())
        self.assertEqual(self.sm.get_management_profile(1)['mode'], 'legacy')

    def test_tiny_position_skips_partial_without_full_close(self):
        self.pos['vol'] = .01
        self.assertEqual(self.sync(), [])
        self.assertFalse(self.sm.get_management_intent(1)['partial'])
        self.sync()
        self.assertEqual(self.sm.get_ratchet_state(1)[0], 2)

    def test_confirmed_stage_trails_both_sides_and_never_repeats_partial(self):
        self.sm.save_management_profile(1, dict(mode='m15_structure_v1', settings={}, since='2026-01-01'))
        self.sm.update_ratchet_level(1, 2)
        commands = self.sync()
        self.assertEqual([c['action'] for c in commands], ['MODIFY'])
        self.assertAlmostEqual(commands[0]['sl'], 1.10385)
        self.assertEqual(commands[0]['tp'], 0)
        self.pos.update(sl=commands[0]['sl'], tp=0)
        self.assertEqual(self.sync()[0]['action'], 'MODIFY_CONFIRMED')
        self.assertEqual(self.sync(), [])
        self.sm.register_order(2, 'EURUSD', 'Test', 'MARKET', status='ACTIVE',
                               entry=1.1, sl=1.11, tp=1.09, lots=1)
        self.sm.save_management_profile(2, dict(mode='m15_structure_v1', settings={}, since='2026-01-01'))
        self.sm.update_ratchet_level(2, 2)
        p = dict(self.pos, t=2, type=1, sl=1.11, tp=1.09)
        cmd = self.tm.sync_positions([p], {'EURUSD': 1.094}, {'EURUSD': 1.0941})[0]
        self.assertAlmostEqual(cmd['sl'], 1.09625)
        self.assertEqual(cmd['tp'], 0)

    def test_bad_context_does_not_block_emergency_exit(self):
        self.tm.update_structure_context('EURUSD', pd.DataFrame({'bad': [1]*120}), 1700000000)
        self.assertIsNone(self.tm._structure_context['EURUSD'])
        self.pos['pf'] = -1000000
        self.assertEqual(self.sync()[0]['action'], 'CLOSE_POS')

class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_paused_structure_updates_candles_before_management(self):
        from tests.unit.test_controller_paused_management import make_controller, TICK
        from src.core.system_controller import BotState
        from unittest.mock import AsyncMock
        for state in (BotState.PAUSED, BotState.EMERGENCY, BotState.ACTIVE):
            c = make_controller(state)
            calls = []
            c.market_data['EURUSD'] = Mock()
            c.market_data['EURUSD'].process_tick.side_effect = lambda msg: calls.append('bars') or []
            c.market_data['EURUSD'].get_data.return_value = pd.DataFrame()
            c.trade_manager = Mock(structure_enabled=True)
            c.trade_manager.update_structure_context.side_effect = lambda *args: calls.append('context')
            c.trade_manager.sync_positions.side_effect = lambda *args: calls.append('manage') or []
            c._run_strategies = AsyncMock()
            await c._process_incoming_data(TICK)
            self.assertEqual(calls, ['bars', 'context', 'manage'])
            c.market_data['EURUSD'].process_tick.assert_called_once()
            if state != BotState.ACTIVE:
                c._run_strategies.assert_not_awaited()


class ReplayTests(unittest.TestCase):
    def test_partial_then_reversal_accounts_for_remaining_loss(self):
        from src.research.structure_execution import StructurePosition
        p = StructurePosition(1.1, .01, 1, .0001, .00001, '2026-01-03', context())
        p.opening_quote(0)
        p.segment(0, 1.1)
        self.assertAlmostEqual(p.volume, .65)
        self.assertAlmostEqual(p.realized, .35)
        p.segment(1.1, -1.2)
        self.assertAlmostEqual(p.realized, -.30)
        self.assertEqual(p.outcome, 'STOP')

    def test_gap_stop_executes_before_new_swing(self):
        from src.research.structure_execution import StructurePosition
        p = StructurePosition(1.1, .01, 1, .0001, .00001, '2026-01-01', context())
        p.stage = 2
        p.opening_quote(-1.5)
        self.assertEqual(p.realized, -1.5)
        self.assertFalse(p.running)

    def test_tp_wins_over_second_partial_above_target(self):
        from src.research.structure_execution import StructurePosition
        ctx = context(); ctx['atr'] = .02; ctx['swing_low'] = None
        p = StructurePosition(1.1, .01, 1, .0001, .00001, '2026-01-01', ctx)
        p.segment(0, 3)
        self.assertEqual(p.outcome, 'TP')
        self.assertAlmostEqual(p.realized, .35+.65*2)
