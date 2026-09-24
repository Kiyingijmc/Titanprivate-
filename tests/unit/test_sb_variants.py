import unittest

import numpy as np
import pandas as pd

from src.research.sb_variants import collect, resample_complete
from tests.unit.test_sb_execution import bars, run, sig


def sample():
    n = 60
    x = pd.DataFrame({'time': pd.date_range('2024-01-02', periods=n, freq='5min'),
                      'open': 100., 'high': 101., 'low': 99., 'close': 100.})
    x.loc[50, ['open', 'high', 'low', 'close']] = [100., 100.5, 98., 100.]
    x.loc[51, ['open', 'high', 'low', 'close']] = [100., 104.5, 99.8, 104.]
    x.loc[52, ['open', 'high', 'low', 'close']] = [104., 104.4, 103.5, 104.2]
    return x


class VariantTests(unittest.TestCase):
    def signals(self, x, variant='middle_retest', window='all_hours', **kwargs):
        return collect(resample_complete(x, 5), 5, variant, window,
                       spread=kwargs.get('spread', .01), commission=.01)[0]

    def test_middle_displacement_and_structural_stop(self):
        out = self.signals(sample())
        signal = next(s for s in out if s['time'].startswith('2024-01-02T04:20'))
        self.assertEqual(signal['entry'], 102.)
        self.assertAlmostEqual(signal['risk'], 4. + .1*signal['atr'])
        self.assertFalse(self.signals(sample(), 'edge_control'))

    def test_sweep_requires_reclaim_and_preexisting_range(self):
        self.assertTrue(self.signals(sample(), 'sweep_reclaim'))
        x = sample()
        x.loc[50, 'close'] = 98.5
        self.assertFalse(self.signals(x, 'sweep_reclaim'))

    def test_cost_filter_rejects_instead_of_widening_stop(self):
        self.assertTrue(self.signals(sample()))
        self.assertFalse(self.signals(sample(), spread=10.))

    def test_buy_sell_detector_symmetry(self):
        x = sample()
        mirror = x.copy()
        mirror['open'], mirror['close'] = 200-x.open, 200-x.close
        mirror['high'], mirror['low'] = 200-x.low, 200-x.high
        for variant in ('middle_retest', 'sweep_reclaim'):
            a, b = self.signals(x, variant), self.signals(mirror, variant)
            self.assertEqual(len(a), len(b))
            self.assertTrue(a)
            for long, short in zip(a, b):
                self.assertEqual((long['dir'], short['dir']), ('BUY', 'SELL'))
                self.assertAlmostEqual(long['entry']+short['entry'], 200.)
                self.assertAlmostEqual(long['risk'], short['risk'])

    def test_only_first_cost_eligible_ny_candidate_per_date(self):
        x = sample()
        x.loc[56:58, ['open','high','low','close']] = x.loc[50:52, ['open','high','low','close']].to_numpy()
        x['time'] += pd.Timestamp('2024-01-02 16:55')-x.time.iloc[52]
        signals, counts = collect(resample_complete(x, 5), 5, 'middle_retest', 'ny_am',
                                  spread=.01, commission=.01)
        self.assertEqual(len(signals), 1)
        self.assertGreaterEqual(counts['duplicate_session'], 1)

    def test_prefix_invariance(self):
        x = sample()
        prefix = self.signals(x.iloc[:53])
        full = self.signals(x)
        self.assertEqual(prefix, [s for s in full if np.datetime64(s['time']) <= x.time.iloc[52]])

    def test_missing_setup_bar_cannot_manufacture_gap(self):
        self.assertFalse(self.signals(sample().drop(index=51)))

    def test_resampling_discards_partial_buckets(self):
        x = sample().iloc[:8]
        out = resample_complete(x, 15)
        self.assertEqual(len(out), 2)
        self.assertEqual(out.time.iloc[1], pd.Timestamp('2024-01-02 00:15'))
        self.assertEqual(len(resample_complete(x.drop(index=1), 15)), 1)

    def test_duplicate_and_misaligned_source_rejected(self):
        x = sample()
        x.loc[1, 'time'] = x.time.iloc[0]
        with self.assertRaises(ValueError):
            resample_complete(x, 15)
        x = sample()
        x['time'] += pd.Timedelta(minutes=1)
        with self.assertRaises(ValueError):
            resample_complete(x, 15)

    def test_ny_window_uses_signal_close_and_dst(self):
        for date, broker_open in [('2024-01-02', '16:55'), ('2024-07-02', '15:55')]:
            x = sample()
            target = pd.Timestamp(f'{date} {broker_open}')
            x['time'] += target-x.time.iloc[52]
            self.assertTrue(self.signals(x, window='ny_am'))  # closes at NY 10
            x['time'] -= pd.Timedelta(minutes=5)
            self.assertFalse(self.signals(x, window='ny_am'))


class MultiTimeframeExecutionTests(unittest.TestCase):
    def test_m5_signal_enters_after_five_minutes(self):
        data = bars([(100., 100.2, 99.8, 100.1)], ['2024-01-01T00:05'])
        result = run(data, signal_minutes=5, ttl_minutes=15)
        self.assertEqual(result['fill_idx'], 0)

    def test_m30_signal_cannot_enter_before_close(self):
        data = bars([(100., 103., 98., 100.), (101., 102., 100.5, 101.)],
                    ['2024-01-01T00:25', '2024-01-01T00:30'])
        self.assertIsNone(run(data, signal_minutes=30)['fill_idx'])

    def test_explicit_structural_risk_overrides_atr(self):
        result = run(bars([(100., 100.5, 98.5, 99.)]), sig(risk=2.))
        self.assertAlmostEqual(result['gross_r'], -.5)

    def test_time_exit_uses_open_not_later_extrema(self):
        data = bars([(100., 100.2, 99.8, 100.1), (100.5, 103., 98., 101.)])
        result = run(data, max_hold_minutes=5)
        self.assertEqual(result['outcome'], 'TIME_EXIT')
        self.assertEqual(result['gross_r'], .5)

    def test_time_exit_gap_stop_has_priority(self):
        data = bars([(100., 100.2, 99.8, 100.1), (98., 99., 97., 98.)])
        result = run(data, max_hold_minutes=5)
        self.assertEqual(result['outcome'], 'STOP')
        self.assertEqual(result['gross_r'], -2.)

    def test_pending_m5_ttl_boundary_excluded(self):
        data = bars([(101., 102., 100.5, 101.), (100., 102., 99., 100.)],
                    ['2024-01-01T00:05', '2024-01-01T00:20'])
        self.assertEqual(run(data, signal_minutes=5, ttl_minutes=15)['outcome'], 'EXPIRED')

    def test_holding_limit_starts_at_fill_bar_not_signal(self):
        data = bars([(101., 101.5, 100.5, 101.), (100., 100.2, 99.8, 100.1),
                     (100.4, 100.6, 100.2, 100.5)])
        result = run(data, max_hold_minutes=5)
        self.assertEqual(result['fill_idx'], 1)
        self.assertEqual(result['exit_idx'], 2)
        self.assertEqual(result['outcome'], 'TIME_EXIT')
        self.assertAlmostEqual(result['gross_r'], .4)

    def test_invalid_durations_fail(self):
        data = bars([(100., 100.2, 99.8, 100.1)])
        for field in ('signal_minutes', 'ttl_minutes', 'max_hold_minutes'):
            for value in (0, -5, 1, float('nan'), float('inf')):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    run(data, **{field:value})


if __name__ == '__main__':
    unittest.main()
