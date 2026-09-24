import unittest
import numpy as np
import pandas as pd
from src.research.sb_session_range import collect_session_range


class SessionRangeTests(unittest.TestCase):
    def setUp(self):
        self.frame=pd.DataFrame(dict(time=pd.date_range('2026-07-01',periods=80,freq='15min'),
            open=100.,high=110.,low=90.,close=100.,atr=5.))
        self.frame.loc[66,['open','high','low','close']]=[100.,101.,89.,95.]
        self.frame.loc[67,['open','high','low','close']]=[95.,109.,94.,108.]
        self.frame.loc[68,['open','high','low','close']]=[108.,111.,105.,109.]

    def collect(self,frame=None,spread=1.,commission=.5):
        return collect_session_range(self.frame if frame is None else frame,spread=spread,commission=commission)

    def test_buy_completed_range_geometry(self):
        signals,days=self.collect()
        self.assertEqual(len(signals),1)
        s=signals[0]
        self.assertEqual(s['entry'],103.)
        self.assertEqual(s['risk'],14.5)
        self.assertEqual(s['range_low'],90.)
        self.assertEqual(s['range_high'],110.)
        self.assertEqual(s['event_time'],str(self.frame.time.iloc[66].to_datetime64().astype('datetime64[ns]')))

    def test_sell_symmetry(self):
        f=self.frame
        f['open'],f['close']=200-f.open,200-f.close
        f['high'],f['low']=200-f.low,200-f.high
        s=self.collect()[0][0]
        self.assertEqual(s['dir'],'SELL')
        self.assertEqual(s['entry'],97.)
        self.assertEqual(s['risk'],14.5)

    def test_incomplete_range_rejected(self):
        signals,days=self.collect(self.frame.drop(index=50).reset_index(drop=True))
        self.assertEqual(signals,[])
        self.assertEqual(days[-1]['complete_range'],0)

    def test_ambiguous_sweep_abandons_day(self):
        self.frame.loc[66,'high']=111.
        self.assertEqual(self.collect()[0],[])
        self.assertEqual(self.collect()[1][-1]['ambiguous'],1)

    def test_close_back_below_boundary_invalidates(self):
        self.frame.loc[67,['low','close']]=[88.,89.]
        self.assertEqual(self.collect()[0],[])
        self.assertEqual(self.collect()[1][-1]['invalidated'],1)

    def test_reference_boundary_touch_is_not_sweep(self):
        self.frame.loc[66,'low']=90.
        self.assertEqual(self.collect()[0],[])

    def test_event_need_not_be_exactly_two_bars_earlier(self):
        self.frame.loc[67,['open','high','low','close']]=[95.,100.,94.,96.]
        self.frame.loc[68,['open','high','low','close']]=[96.,109.,95.,108.]
        self.frame.loc[69,['open','high','low','close']]=[108.,111.,105.,109.]
        s=self.collect()[0][0]
        self.assertEqual(pd.Timestamp(s['time'])-pd.Timestamp(s['event_time']),pd.Timedelta(minutes=45))

    def test_gap_after_event_not_bridged(self):
        self.assertEqual(self.collect(self.frame.drop(index=67).reset_index(drop=True))[0],[])

    def test_prefix_and_future_extremes_cannot_change_signal(self):
        expected=self.collect(self.frame.iloc[:69])[0]
        self.frame.loc[70:,'high']=500.
        self.frame.loc[70:,'low']=1.
        self.assertEqual(self.collect()[0],expected)

    def test_only_one_parent_per_day(self):
        self.assertEqual(len(self.collect()[0]),1)

    def test_cost_gate(self):
        signals,days=self.collect(spread=4.,commission=1.)
        self.assertEqual(signals,[])
        self.assertGreater(days[-1]['cost_rejected'],0)

    def test_later_sweep_does_not_reset_event(self):
        self.frame.loc[67,'low']=88.
        s=self.collect()[0][0]
        self.assertEqual(pd.Timestamp(s['event_time']),self.frame.time.iloc[66])
        self.assertEqual(s['risk'],15.5)

    def test_signal_more_than_hour_after_event_rejected(self):
        self.frame.loc[67:70,['open','high','low','close']]=[95.,100.,94.,96.]
        self.frame.loc[70,['open','high','low','close']]=[96.,109.,95.,108.]
        self.frame.loc[71,['open','high','low','close']]=[108.,111.,105.,109.]
        self.assertEqual(self.collect()[0],[])

    def test_event_after_scan_window_rejected(self):
        self.frame.loc[66:69,['open','high','low','close']]=[100.,110.,90.,100.]
        self.frame.loc[70,['open','high','low','close']]=[100.,101.,89.,95.]
        self.assertEqual(self.collect()[0],[])

    def test_invalid_costs_rejected(self):
        with self.assertRaises(ValueError): self.collect(spread=float('nan'))


if __name__=='__main__': unittest.main()
