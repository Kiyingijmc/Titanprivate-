from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.research.sb_sessions import utc_from_broker, select_ny, assemble_snapshots


class ClockTests(unittest.TestCase):
    def test_seasonal_offsets_and_mismatched_dst_weeks(self):
        # Times are broker-local CLOSE times corresponding to NY 10:00.
        times = pd.to_datetime(['2024-01-02 17:00','2024-03-15 16:00',
                                '2024-04-02 17:00','2024-10-30 16:00'])
        result = utc_from_broker(times,'seasonal_eet').tz_convert('America/New_York')
        self.assertEqual(list(result.hour),[10,10,10,10])

    def test_ambiguous_and_nonexistent_clock_is_not_guessed(self):
        result = utc_from_broker(pd.to_datetime(['2024-03-31 03:15','2024-10-27 03:15']), 'seasonal_eet')
        self.assertTrue(result.isna().all())

    def test_fixed_offset_does_not_silently_become_seasonal(self):
        times = pd.to_datetime(['2024-07-02 17:00'])
        a = utc_from_broker(times,'fixed_2').tz_convert('America/New_York')
        b = utc_from_broker(times,'seasonal_eet').tz_convert('America/New_York')
        self.assertEqual((a.hour[0],b.hour[0]),(11,10))

    def test_first_signal_rule_spans_segments(self):
        seen = set()
        a = [{'time':'2024-07-02 16:45'}]
        b = [{'time':'2024-07-02 17:15'}]
        self.assertEqual(select_ny(a,15,'seasonal_eet',seen),a)
        self.assertEqual(select_ny(b,15,'seasonal_eet',seen),[])

    def test_session_uses_close_and_excludes_upper_boundary(self):
        signals = [{'time':'2024-07-02 16:40'}, {'time':'2024-07-02 16:45'},
                   {'time':'2024-07-03 17:45'}]
        self.assertEqual(select_ny(signals,15,'seasonal_eet'),signals[1:2])

    def test_aware_input_and_unknown_clock_rejected(self):
        with self.assertRaises(ValueError):
            utc_from_broker(pd.date_range('2024-01-01',periods=1,tz='UTC'),'fixed_2')
        with self.assertRaises(ValueError):
            utc_from_broker(pd.to_datetime(['2024-01-01']),'guess')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self,capture,times,closes=None):
        path = Path(self.tmp.name)/capture/'EURUSD_M5.csv'
        path.parent.mkdir(parents=True)
        x = pd.DataFrame({'time':times,'open':100.,'high':101.,'low':99.,
                          'close':closes if closes is not None else 100.})
        x.to_csv(path,index=False)
        return path

    def test_forming_bar_removed_and_data_sorted(self):
        file = self.write('20260701-120000',['2026-07-01 15:00','2026-07-01 14:55','2026-07-01 14:50'])
        segments,stats = assemble_snapshots([file],'2026-06-30')
        self.assertEqual(stats['forming_or_ambiguous'],1)
        self.assertEqual(len(segments),1)
        self.assertEqual(list(segments[0].time.dt.minute),[50,55])

    def test_conflicts_discarded_and_exact_duplicates_deduplicated(self):
        times=['2026-07-01 14:45','2026-07-01 14:50','2026-07-01 14:55']
        a=self.write('20260701-120000',times)
        b=self.write('20260701-120100',times,[100.,100.5,100.])
        segments,stats=assemble_snapshots([a,b],'2026-06-30')
        self.assertEqual(stats['conflicting_times'],1)
        self.assertEqual(stats['duplicate_rows'],2)
        self.assertEqual(stats['unique_bars'],2)
        self.assertEqual(len(segments),2)  # never bridge the discarded middle candle

    def test_old_bars_and_invalid_prices_removed(self):
        file=self.write('20260701-120000',['2026-06-01 14:45','2026-07-01 14:50','2026-07-01 14:55'],
                        [100.,float('nan'),100.])
        segments,stats=assemble_snapshots([file],'2026-06-30')
        self.assertEqual(stats['before_cutoff'],1)
        self.assertEqual(stats['invalid'],1)
        self.assertEqual(stats['unique_bars'],1)

    def test_no_files_is_an_empty_sample(self):
        segments,stats=assemble_snapshots([],'2026-06-30')
        self.assertEqual(segments,[])
        self.assertEqual(stats['unique_bars'],0)


if __name__ == '__main__':
    unittest.main()
