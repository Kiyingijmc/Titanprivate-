import unittest
import numpy as np
from src.research.sb_confirmation import confirm_order


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.signal = dict(time='2026-07-01T09:45', dir='BUY', entry=100., risk=10.)
        self.bars = dict(time=np.arange(np.datetime64('2026-07-01T09:55'),
                                       np.datetime64('2026-07-01T14:05'), np.timedelta64(5,'m')).astype('datetime64[ns]'))
        for key, value in [('open',101.),('high',103.),('low',100.),('close',102.)]:
            self.bars[key] = np.full(len(self.bars['time']),value)
        self.bars['low'][1] = 98.
        self.bars['high'][1] = 106.
        self.bars['close'][1] = 105.

    def run_order(self, **kwargs):
        return confirm_order(self.signal,self.bars,path='OHLC',spread=1.,commission=.5,**kwargs)

    def test_buy_next_open_ask_original_stop(self):
        row=self.run_order()
        self.assertEqual(row['fill_idx'],2)
        self.assertEqual(row['entry'],102.)
        self.assertEqual(row['risk'],12.)
        self.assertEqual(row['entry']-row['risk'],90.)
        self.assertEqual(row['outcome'],'TIME_EXIT')
        self.assertAlmostEqual(row['net_r'],(101.-102.-.5)/12.)

    def test_sell_symmetry_ask_exit(self):
        self.signal['dir']='SELL'
        b=self.bars
        b['open'],b['close']=200-b['open'],200-b['close']
        b['high'],b['low']=200-b['low'],200-b['high']
        row=self.run_order()
        self.assertEqual(row['entry'],99.)
        self.assertEqual(row['risk'],11.)
        self.assertEqual(row['entry']+row['risk'],110.)
        self.assertAlmostEqual(row['net_r'],(99.-100.-.5)/11.)

    def test_confirmation_extreme_not_reused(self):
        self.bars['high'][1]=150.
        row=self.run_order()
        self.assertEqual(row['outcome'],'TIME_EXIT')

    def test_stop_on_confirmation_bar_invalidates(self):
        self.bars['low'][1]=89.
        self.assertEqual(self.run_order()['outcome'],'INVALIDATED')

    def test_bid_touch_without_ask_touch_does_not_confirm(self):
        self.bars['low'][1]=99.5
        self.assertEqual(self.run_order()['outcome'],'NO_CONFIRMATION')

    def test_touch_can_precede_break(self):
        self.bars['close'][1]=102.
        self.bars['close'][2]=107.
        self.bars['high'][2]=108.
        self.assertEqual(self.run_order()['fill_idx'],3)

    def test_expiry_excludes_boundary_open(self):
        self.bars['close'][1]=102.
        self.bars['close'][9]=107.
        self.bars['high'][9]=108.
        self.assertEqual(self.run_order()['outcome'],'NO_CONFIRMATION')

    def test_gap_through_stop_rejected(self):
        self.bars['open'][2]=89.
        self.assertEqual(self.run_order()['outcome'],'ENTRY_INVALID')

    def test_cost_ceiling_at_actual_entry(self):
        self.bars['open'][2]=91.
        self.assertEqual(self.run_order()['outcome'],'ENTRY_COST')

    def test_missing_entry_bar_rejected(self):
        for key in self.bars:
            self.bars[key]=np.delete(self.bars[key],2)
        with self.assertRaises(ValueError): self.run_order()

    def test_future_changes_cannot_change_entry(self):
        before=self.run_order()
        self.bars['high'][3:]=200.
        after=self.run_order()
        for key in ['entry','risk','fill_idx','confirmation_close']:
            self.assertEqual(before[key],after[key])
        self.assertEqual(after['outcome'],'TP')

    def test_commission_charged_once(self):
        row=self.run_order()
        self.assertAlmostEqual(row['gross_r']-row['net_r'],.5/row['risk'])


if __name__=='__main__': unittest.main()
