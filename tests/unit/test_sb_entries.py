import unittest

import pandas as pd

from src.research.sb_entries import candidates,h1_alignment
from src.research.sb_variants import collect,resample_complete
from src.research.sb_sessions import select_ny
from tests.unit.test_sb_variants import sample


def frame(two=False,recent=False):
    x=sample()
    if two:
        x.loc[53:55,['open','high','low','close']]=x.loc[50:52,['open','high','low','close']].to_numpy()
        x.loc[53,'low']=96.
    if recent:
        x.loc[49,'low']=98.
        x.loc[50,'low']=99.2
    f=resample_complete(x,5)
    f['time']=pd.date_range(end='2026-07-01 18:30',periods=60,freq='15min')
    # Index 52 opens at 16:45 broker summer -> closes at NY 10:00.
    return f


class EntryTests(unittest.TestCase):
    def test_baseline_matches_existing_detector_and_session(self):
        f=frame()
        raw,_=collect(f,15,'sweep_reclaim','all_hours',spread=.01,commission=.01)
        expected=select_ny(raw,15,'seasonal_eet')
        actual,_=candidates(f,'baseline',spread=.01,commission=.01)
        self.assertTrue(actual)
        self.assertEqual(actual,expected)

    def test_shallow_entries_keep_absolute_stop_and_recompute_risk(self):
        f=frame()
        base=candidates(f,'baseline',spread=.01,commission=.01)[0][0]
        for arm,entry in [('quarter_retest',102.75),('edge_retest',103.5)]:
            s=candidates(f,arm,spread=.01,commission=.01)[0][0]
            self.assertAlmostEqual(s['entry'],entry)
            self.assertAlmostEqual(s['entry']-s['risk'],base['entry']-base['risk'])
            self.assertGreater(s['risk'],base['risk'])

    def test_two_distinct_setups_cap(self):
        f=frame(two=True)
        self.assertEqual(len(candidates(f,'baseline',spread=.01,commission=.01)[0]),1)
        self.assertEqual(len(candidates(f,'two_setups',spread=.01,commission=.01)[0]),2)

    def test_short_shallow_entry_keeps_absolute_stop(self):
        f=frame()
        mirrored=f.copy()
        mirrored['open'],mirrored['close']=200-f.open,200-f.close
        mirrored['high'],mirrored['low']=200-f.low,200-f.high
        base=candidates(mirrored,'baseline',spread=.01,commission=.01)[0][0]
        self.assertEqual(base['dir'],'SELL')
        for arm in ('quarter_retest','edge_retest'):
            s=candidates(mirrored,arm,spread=.01,commission=.01)[0][0]
            long=candidates(f,arm,spread=.01,commission=.01)[0][0]
            self.assertAlmostEqual(s['entry']+s['risk'],base['entry']+base['risk'])
            self.assertAlmostEqual(s['entry']+long['entry'],200.)
            self.assertAlmostEqual(s['risk'],long['risk'])

    def test_cost_rejection_does_not_consume_daily_allowance(self):
        result,counts=candidates(frame(two=True),'baseline',spread=1.2,commission=.01)
        self.assertEqual(len(result),1)
        self.assertEqual(pd.Timestamp(result[0]['time']),frame(two=True).time.iloc[55])
        self.assertEqual(counts['cost_rejected'],1)

    def test_open_window_includes_0930_close(self):
        f=frame()
        f['time']-=pd.Timedelta(minutes=30)
        self.assertFalse(candidates(f,'baseline',spread=.01,commission=.01)[0])
        self.assertTrue(candidates(f,'open_window',spread=.01,commission=.01)[0])

    def test_recent_sweep_can_precede_first_gap_candle(self):
        f=frame(recent=True)
        self.assertFalse(candidates(f,'baseline',spread=.01,commission=.01)[0])
        s=candidates(f,'recent_sweep',spread=.01,commission=.01)[0]
        self.assertEqual(len(s),1)
        self.assertAlmostEqual(s[0]['entry']-s[0]['risk'],98.-.1*s[0]['atr'])

    def test_recent_sweep_requires_contiguous_history(self):
        f=frame(recent=True).drop(index=48).reset_index(drop=True)
        self.assertFalse(candidates(f,'recent_sweep',spread=.01,commission=.01)[0])

    def test_prefix_invariance_for_entry_changes(self):
        f=frame(two=True)
        for arm in ('baseline','quarter_retest','edge_retest','recent_sweep','two_setups'):
            a=candidates(f.iloc[:53],arm,spread=.01,commission=.01)[0]
            b=candidates(f,arm,spread=.01,commission=.01)[0]
            self.assertEqual(a,[s for s in b if pd.Timestamp(s['time'])<=f.time.iloc[52]])


class H1ContextTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame({'time':pd.date_range('2026-01-01',periods=25,freq='h'),
                             'close':[100.+i for i in range(25)]})

    def test_only_completed_h1_is_visible(self):
        h=self.history()
        stamp='2026-01-01 23:00'  # available 23:15; H1 at 23:00 still open
        before=h1_alignment(h,[stamp],['BUY'])
        h.loc[23:,'close']=-10000.
        self.assertEqual(h1_alignment(h,[stamp],['BUY']),before)
        self.assertEqual(before,[True])

    def test_direction_neutral_warmup_and_stale_context(self):
        h=self.history()
        self.assertEqual(h1_alignment(h,['2026-01-01 23:00'],['SELL']),[False])
        self.assertEqual(h1_alignment(h,['2026-01-01 10:00'],['BUY']),[False])
        self.assertEqual(h1_alignment(h,['2026-01-02 03:00'],['BUY']),[False])
        h['close']=100.
        self.assertEqual(h1_alignment(h,['2026-01-01 23:00'],['BUY']),[False])


if __name__=='__main__':
    unittest.main()
