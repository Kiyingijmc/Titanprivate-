import unittest
import numpy as np
import pandas as pd
from scripts.sb_parent_audit import week_interval, period_of, without_top_gains


class ParentAuditTests(unittest.TestCase):
    def test_gain_removal_preserves_losses_and_zero(self):
        returns=pd.Series([-1.,2.,0.,-2.,1.])
        self.assertEqual(without_top_gains(returns).tolist(),[-1.,0.,-2.])

    def test_week_clusters_keep_offsetting_symbols_together(self):
        group=pd.DataFrame(dict(created=['2026-07-06 17:00','2026-07-06 17:00','2026-07-20 17:00','2026-07-20 17:00'],net_r=[2.,-2.,4.,-4.]))
        result=week_interval(group)
        self.assertEqual(result['weeks'],3)
        self.assertEqual(result['ci_low'],0.)
        self.assertEqual(result['ci_high'],0.)
        self.assertLess(result['bootstrap_valid'],2000)

    def test_unfilled_orders_do_not_dilute_per_fill_mean(self):
        group=pd.DataFrame(dict(created=['2026-07-06 17:00','2026-07-07 17:00'],net_r=[2.,np.nan]))
        result=week_interval(group)
        self.assertEqual(result['mean_net_r'],2.)
        self.assertEqual(result['ci_low'],2.)
        self.assertEqual(result['ci_high'],2.)

    def test_empty_fill_distribution_is_not_zero_edge(self):
        group=pd.DataFrame(dict(created=['2026-07-06 17:00'],net_r=[np.nan]))
        result=week_interval(group)
        self.assertEqual(result['bootstrap_valid'],0)
        self.assertTrue(np.isnan(result['ci_low']))

    def test_frozen_partition_boundaries(self):
        self.assertEqual(period_of(pd.Timestamp('2024-12-31'),'history'),'early')
        self.assertIsNone(period_of(pd.Timestamp('2025-01-01'),'history'))
        self.assertEqual(period_of(pd.Timestamp('2025-01-08'),'history'),'late')
        self.assertIsNone(period_of(pd.Timestamp('2026-06-24'),'extension'))
        self.assertEqual(period_of(pd.Timestamp('2026-06-25'),'extension'),'extension')
        self.assertIsNone(period_of(pd.Timestamp('2026-09-17'),'extension'))


if __name__=='__main__': unittest.main()
