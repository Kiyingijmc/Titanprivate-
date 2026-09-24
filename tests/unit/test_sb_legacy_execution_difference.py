"""Concrete counterexamples to interpreting the legacy replay as executable.

These preserve the historical engine for reproducibility; they do not assign
the aggregate performance difference to any single modeling assumption.
"""
import unittest

from scripts.poc_sb_stops import replay_managed
from tests.unit.test_sb_execution import bars, run


class LegacyExecutionDifference(unittest.TestCase):
    def test_prefill_high_cannot_arm_ratchet(self):
        # Price visits 103 before falling to the BUY limit at 100. There is
        # no post-entry profit; the following bar hits the initial stop.
        rows = [(101., 103., 99.5, 100.), (100., 100.1, 98.5, 99.)]
        trade = {'entry': 100., 'sl': 99., 'tp': 102., 'risk': 1.,
                 'dir': 'BUY', 'fill_idx': 0}
        old = replay_managed(trade, bars(rows), runner=True)
        new = run(bars(rows), arm='runner', path='OHLC')
        self.assertGreater(old, 1.)
        self.assertEqual(new['gross_r'], -1.)

    def test_new_stop_must_apply_to_same_bar_reversal(self):
        # Fill at the open, touch L1, reverse through BE, then rally in the
        # next bar. Legacy only tests the old stop before arming the new one.
        rows = [(100., 100.9, 99.5, 100.5), (100.5, 102.1, 100.1, 102.)]
        trade = {'entry': 100., 'sl': 99., 'tp': 102., 'risk': 1.,
                 'dir': 'BUY', 'fill_idx': 0}
        old = replay_managed(trade, bars(rows))
        new = run(bars(rows), arm='ratchet', path='OHLC')
        self.assertGreater(old, 1.)
        self.assertEqual(new['gross_r'], 0.)


if __name__ == '__main__':
    unittest.main()
