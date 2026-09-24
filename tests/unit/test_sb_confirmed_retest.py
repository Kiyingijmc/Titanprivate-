import unittest
import numpy as np
from src.research.sb_confirmed_retest import retest_order


class ConfirmedRetestTests(unittest.TestCase):
    def setUp(self):
        self.signal=dict(time='2026-07-01T09:45',dir='BUY',entry=100.,risk=10.)
        self.bars=dict(time=np.arange(np.datetime64('2026-07-01T09:55'),
                                     np.datetime64('2026-07-01T14:05'),np.timedelta64(5,'m')).astype('datetime64[ns]'))
        for key,value in [('open',103.),('high',104.),('low',102.),('close',103.)]:
            self.bars[key]=np.full(len(self.bars['time']),value)
        self.bars['low'][1]=98.
        self.bars['high'][1]=106.
        self.bars['close'][1]=105.

    def run_order(self,**kwargs):
        return retest_order(self.signal,self.bars,path='OHLC',spread=1.,commission=.5,**kwargs)

    def test_preconfirmation_touch_cannot_fill(self):
        row=self.run_order()
        self.assertEqual(row['outcome'],'EXPIRED')
        self.assertIsNone(row['fill_idx'])
        self.assertEqual(np.datetime64(row['confirmation_close']),np.datetime64('2026-07-01T10:05'))

    def test_fresh_touch_fills_original_geometry(self):
        self.bars['low'][3]=99.
        row=self.run_order()
        self.assertEqual(row['fill_idx'],3)
        self.assertEqual(row['entry'],100.)
        self.assertEqual(row['risk'],10.)
        self.assertEqual(row['risk_ratio'],1.)
        self.assertAlmostEqual(row['net_r'],.25)

    def test_sell_fills_bid_and_exits_ask(self):
        self.signal['dir']='SELL'
        b=self.bars
        b['open'],b['close']=200-b['open'],200-b['close']
        b['high'],b['low']=200-b['low'],200-b['high']
        b['high'][3]=100.
        row=self.run_order()
        self.assertEqual(row['fill_idx'],3)
        self.assertEqual(row['entry']+row['risk'],110.)
        self.assertAlmostEqual(row['net_r'],.15)

    def test_expiry_remains_parent_deadline(self):
        self.bars['low'][10]=99.
        row=self.run_order()
        self.assertEqual(row['outcome'],'EXPIRED')
        self.assertEqual(np.datetime64(row['release']),np.datetime64('2026-07-01T10:45'))

    def test_late_confirmation_gets_only_remaining_time(self):
        self.bars['close'][1]=103.
        self.bars['high'][8]=108.
        self.bars['close'][8]=107.
        self.bars['low'][10]=99.
        row=self.run_order()
        self.assertEqual(np.datetime64(row['confirmation_close']),np.datetime64('2026-07-01T10:40'))
        self.assertEqual(row['outcome'],'EXPIRED')

    def test_confirmation_at_expiry_is_too_late(self):
        self.bars['close'][1]=103.
        self.bars['high'][9]=108.
        self.bars['close'][9]=107.
        self.assertEqual(self.run_order()['outcome'],'NO_CONFIRMATION')

    def test_preconfirmation_stop_invalidates(self):
        self.bars['low'][1]=89.
        self.assertEqual(self.run_order()['outcome'],'INVALIDATED')

    def test_postsubmission_gap_loss_not_avoided(self):
        for key in ('open','high','low','close'): self.bars[key][2]=80.
        row=self.run_order()
        self.assertEqual(row['outcome'],'STOP')
        self.assertEqual(row['fill_idx'],2)
        self.assertAlmostEqual(row['net_r'],-2.05)

    def test_cost_ceiling_uses_original_risk(self):
        row=retest_order(self.signal,self.bars,path='OHLC',spread=1.,commission=2.)
        self.assertEqual(row['outcome'],'ENTRY_COST')
        self.assertIsNone(row['fill_idx'])

    def test_buy_bid_touch_does_not_fill_ask_limit(self):
        self.bars['low'][3]=99.5
        self.assertEqual(self.run_order()['outcome'],'EXPIRED')

    def test_gap_in_holding_horizon_rejected(self):
        for key in self.bars: self.bars[key]=np.delete(self.bars[key],30)
        with self.assertRaises(ValueError): self.run_order()

    def test_holding_deadline_starts_at_new_fill(self):
        self.bars['low'][7]=99.
        row=self.run_order()
        self.assertEqual(row['outcome'],'TIME_EXIT')
        self.assertEqual(np.datetime64(row['exit_time']),np.datetime64('2026-07-01T13:30'))

    def test_no_preentry_extreme_reuse(self):
        self.bars['high'][1]=150.
        self.bars['low'][3]=99.
        self.assertEqual(self.run_order()['outcome'],'TIME_EXIT')

    def test_future_changes_do_not_change_fill(self):
        self.bars['low'][3]=99.
        row=self.run_order()
        self.bars['high'][4:]=150.
        later=self.run_order()
        self.assertEqual(later['outcome'],'TP')
        for key in ('fill_idx','entry','risk','confirmation_close'):
            self.assertEqual(row[key],later[key])


if __name__=='__main__': unittest.main()
