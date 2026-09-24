import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
import pandas as pd
from fastapi.testclient import TestClient
from src.research.shadow.store import Store
from src.research.shadow.feed import ReadOnlyTransport
from src.research.shadow.signals import market_epoch,prepare_bars,observe_bars
from src.execution.broker.types import Candle
from src.ops.web.shadow_view import create_app,snapshot


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        persisted={'test_duplicate_and_restart_do_not_add_orders','test_restart_after_gap_censors',
                   'test_changed_manifest_cannot_resume','test_censored_trades_excluded_from_dashboard_gate',
                   'test_dashboard_is_read_only_and_exports'}
        self.path=Path(self.temp.name)/'shadow.sqlite3' if self._testMethodName in persisted else Path(':memory:')
        self.manifest={'symbols':['EURUSD'],'version':1}
        self.store=Store(self.path,self.manifest,100.)
        self.signal=dict(dir='BUY',entry=100.,risk=10.)
        self.store.quote('EURUSD',101.,101.,101.,102.)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def admit(self,signal=None,closed=100.,now=101.):
        return self.store.decision('EURUSD','wider_midpoint',closed,now,'SIGNAL',{},signal=signal or self.signal,commission=.5)

    def row(self,scenario='observed'):
        return dict(self.store.db.execute('SELECT * FROM trades WHERE scenario=?',(scenario,)).fetchone())

    def test_first_observed_executable_touch_and_single_commission(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,99.,100.)
        self.assertEqual(self.row()['status'],'OPEN')
        self.store.quote('EURUSD',103.,103.,121.,122.)
        row=self.row()
        self.assertEqual(row['reason'],'TP')
        self.assertEqual(row['exit_price'],120.)
        self.assertAlmostEqual(row['net_r'],1.95)
        self.assertIsNotNone(row['fill_quote'])
        self.assertIsNotNone(row['exit_quote'])

    def test_sell_uses_bid_entry_and_ask_exit(self):
        self.admit(dict(dir='SELL',entry=100.,risk=10.))
        self.store.quote('EURUSD',102.,102.,100.,101.)
        self.store.quote('EURUSD',103.,103.,110.,111.)
        self.assertEqual(self.row()['reason'],'STOP')
        self.assertAlmostEqual(self.row()['net_r'],-1.15)

    def test_stress_spread_changes_fill(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,99.,100.)
        self.assertEqual(self.row()['status'],'OPEN')
        self.assertEqual(self.row('stress_1_5')['status'],'PENDING')

    def test_no_favorable_limit_improvement(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,95.,96.)
        self.assertEqual(self.row()['entry'],100.)
        self.assertEqual(self.row()['status'],'OPEN')

    def test_gap_through_stop_fills_and_loses(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,80.,81.)
        self.assertEqual(self.row()['reason'],'STOP')
        self.assertAlmostEqual(self.row()['net_r'],-2.05)

    def test_pre_admission_quote_cannot_fill(self):
        self.admit(now=102.)
        self.store.quote('EURUSD',103.,101.,98.,99.)
        self.assertEqual(self.row()['status'],'PENDING')

    def test_observation_gap_censors_before_winning_quote(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,99.,100.)
        self.store.quote('EURUSD',120.,120.,121.,122.)
        row=self.row()
        self.assertEqual(row['status'],'CENSORED')
        self.assertIsNone(row['net_r'])

    def test_pending_gap_cannot_be_called_expired_or_filled(self):
        self.admit()
        self.store.quote('EURUSD',3000.,3000.,99.,100.)
        self.assertEqual(self.row()['status'],'CENSORED')
        self.assertIsNone(self.row()['fill_time'])

    def test_expiry_boundary_exclusive_with_healthy_coverage(self):
        self.admit()
        with self.store.db: self.store.set('last_quote:EURUSD',2799.)
        self.store.quote('EURUSD',2800.,2800.,99.,100.)
        self.assertEqual(self.row()['status'],'EXPIRED')

    def test_holding_deadline_exit_under_healthy_coverage(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,99.,100.)
        with self.store.db: self.store.set('last_quote:EURUSD',10901.)
        self.store.quote('EURUSD',10902.,10902.,105.,106.)
        self.assertEqual(self.row()['reason'],'TIME_EXIT')
        self.assertAlmostEqual(self.row()['net_r'],.45)

    def test_precohort_signal_not_backfilled(self):
        self.assertEqual(self.admit(closed=90.),'BEFORE_COHORT')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM trades').fetchone()[0],0)

    def test_late_discovery_rejected(self):
        self.assertEqual(self.admit(now=191.),'LATE_DISCOVERY')

    def test_fresh_quote_required(self):
        self.assertEqual(self.admit(now=117.),'NO_FRESH_QUOTE')

    def test_observed_cost_gate_independent_scenarios(self):
        self.store.quote('EURUSD',102.,102.,101.,103.)
        self.admit(now=102.)
        self.assertEqual(self.row()['status'],'PENDING')
        self.assertEqual(self.row('stress_1_5')['reason'],'OBSERVED_COST')

    def test_duplicate_and_restart_do_not_add_orders(self):
        self.admit()
        self.store.close()
        self.store=Store(self.path,self.manifest,102.)
        self.assertEqual(self.admit(now=102.),'DUPLICATE')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM trades').fetchone()[0],2)
        self.store.quote('EURUSD',103.,103.,99.,100.)
        self.assertEqual(self.row()['status'],'OPEN')

    def test_daily_cap_survives_missing_earlier_context(self):
        self.admit()
        with self.store.db: self.store.db.execute("UPDATE trades SET status='EXPIRED'")
        self.store.quote('EURUSD',116.,116.,101.,102.)
        self.assertEqual(self.admit(closed=115.,now=116.),'DAILY_CAP')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM trades').fetchone()[0],2)

    def test_restart_after_gap_censors(self):
        self.admit()
        self.store.close()
        self.store=Store(self.path,self.manifest,120.)
        self.store.quote('EURUSD',120.,120.,99.,100.)
        self.assertEqual(self.row()['status'],'CENSORED')

    def test_changed_manifest_cannot_resume(self):
        with self.assertRaises(ValueError): Store(self.path,dict(self.manifest,version=2),102.)

    def test_invalid_and_wrong_clock_quotes_rejected(self):
        self.assertEqual(self.store.quote('EURUSD',102.,102.,101.,100.),'INVALID_QUOTE')
        self.assertEqual(self.store.quote('EURUSD',102.,10000.,99.,100.),'FUTURE_OR_WRONG_CLOCK')
        self.assertEqual(self.store.quote('EURUSD',120.,102.,99.,100.),'STALE_QUOTE')
        self.assertEqual(self.store.quote('EURUSD',102.,100.,99.,100.),'OUT_OF_ORDER_QUOTE')

    def test_stop_censors_active_orders(self):
        self.admit()
        self.store.stop(102.)
        self.assertEqual(self.row()['reason'],'RECORDER_STOPPED')

    def test_censored_trades_excluded_from_dashboard_gate(self):
        self.admit()
        self.store.quote('EURUSD',102.,102.,99.,100.)
        self.store.stop(103.)
        state=snapshot(self.path,104.)
        candidate=state['candidates'][0]
        self.assertEqual(candidate['gate'],'COLLECTING')
        self.assertIsNone(candidate['scenarios'][0]['mean_net_r'])
        self.assertEqual(candidate['scenarios'][0]['counts']['CENSORED'],1)

    def test_dashboard_is_read_only_and_exports(self):
        client=TestClient(create_app(self.path))
        self.assertEqual(client.get('/').status_code,200)
        self.assertEqual(client.get('/api/state').status_code,200)
        self.assertEqual(client.post('/api/state',json={}).status_code,405)
        self.assertEqual(client.get('/api/export/trades.csv').status_code,200)
        self.assertEqual(client.get('/api/export/meta.csv').status_code,404)

    def test_completed_bars_are_immutable(self):
        frame=pd.DataFrame([dict(time=pd.Timestamp('2026-07-01'),open=100.,high=102.,low=99.,close=101.)])
        self.assertTrue(self.store.record_bars('EURUSD',frame,102.))
        frame.loc[0,'high']=103.
        self.assertFalse(self.store.record_bars('EURUSD',frame,103.))
        self.assertEqual(self.store.db.execute('SELECT high FROM bars').fetchone()[0],102.)

    def test_guard_blocks_writes_before_transport(self):
        calls=[]
        def handler(request):
            calls.append(request.method)
            return httpx.Response(200,json={})
        async def check():
            async with httpx.AsyncClient(transport=ReadOnlyTransport(httpx.MockTransport(handler))) as client:
                await client.get('http://bridge/health')
                for method in ('POST','PUT','PATCH','DELETE'):
                    with self.assertRaises(RuntimeError): await client.request(method,'http://bridge/orders')
        asyncio.run(check())
        self.assertEqual(calls,['GET'])

    def test_broker_clock_and_forming_bar(self):
        now=datetime(2026,7,1,7,5,tzinfo=timezone.utc).timestamp()
        self.assertEqual(market_epoch('2026-07-01T10:05:00+00:00'),now)
        bars=[Candle(time=datetime(2026,7,1,10,m,tzinfo=timezone.utc),open=100.,high=102.,low=99.,close=101.,tick_volume=1,spread_points=1) for m in (0,5)]
        completed=prepare_bars(bars,now)
        self.assertEqual(len(completed),1)

    def test_adapter_records_both_frozen_candidates_once(self):
        frame=pd.DataFrame(dict(time=pd.date_range('2026-07-01',periods=69,freq='15min'),
            open=100.,high=101.,low=99.,close=100.))
        frame.loc[66,['open','high','low','close']]=[100.,100.5,98.5,99.5]
        frame.loc[67,['open','high','low','close']]=[99.5,104.5,99.4,104.]
        frame.loc[68,['open','high','low','close']]=[104.,105.,103.,104.5]
        bars=[]
        for row in frame.itertuples(index=False):
            for offset in (0,5,10):
                bars.append(Candle(time=(row.time+pd.Timedelta(minutes=offset)).tz_localize('UTC').to_pydatetime(),
                    open=row.open,high=row.high,low=row.low,close=row.close,tick_volume=1,spread_points=1))
        now=market_epoch(frame.time.iloc[-1]+pd.Timedelta(minutes=15))+1
        self.store.quote('EURUSD',now,now,103.,103.001)
        spec=dict(tick_size=.00001,tick_value=1.)
        self.assertEqual(observe_bars(self.store,'EURUSD',bars,spec,now),'RECORDED')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM trades').fetchone()[0],4)
        observe_bars(self.store,'EURUSD',bars,spec,now+1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM trades').fetchone()[0],4)
        decisions=self.store.db.execute('SELECT reason,details FROM decisions').fetchall()
        self.assertTrue(all(row['reason']=='SIGNAL' for row in decisions))
        self.assertTrue(all('sha256' in json.loads(row['details'])['context'] for row in decisions))


if __name__=='__main__': unittest.main()
