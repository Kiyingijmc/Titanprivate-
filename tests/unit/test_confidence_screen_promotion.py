import unittest
import numpy as np

from scripts.confidence_screen.promotion import (
    economic_spread, select_winner, sign_consistency,
)


class TestEconomicSpread(unittest.TestCase):
    def test_continuous_uses_top_minus_bottom_quintile(self):
        # n=200 so each quintile holds 40 >= MIN_CELL_N(30). With n=100 the
        # quintiles hold 20 and economic_spread correctly returns 0.0.
        values = np.arange(200, dtype=float)
        skew = np.arange(200, dtype=float) / 200.0
        self.assertAlmostEqual(economic_spread(values, skew, "continuous"), 0.8, delta=0.05)

    def test_quintiles_below_the_minimum_cell_size_return_zero(self):
        values = np.arange(100, dtype=float)
        skew = np.arange(100, dtype=float) / 100.0
        self.assertEqual(economic_spread(values, skew, "continuous"), 0.0)

    def test_binary_uses_the_group_mean_difference(self):
        values = np.array([0, 0, 1, 1] * 25)
        skew = np.array([0.0, 0.0, 0.5, 0.5] * 25)
        self.assertAlmostEqual(economic_spread(values, skew, "binary"), 0.5, places=9)

    def test_categorical_uses_max_minus_min_group_mean(self):
        values = np.array(["A", "B", "C"] * 40)
        skew = np.array([0.0, 1.0, 2.0] * 40)
        self.assertAlmostEqual(economic_spread(values, skew, "categorical"), 2.0, places=9)

    def test_thin_cells_are_excluded_so_they_cannot_manufacture_a_spread(self):
        """MIN_CELL_N = 30. A 5-signal group with a wild mean must not create
        the illusion of a 10R spread."""
        values = np.array(["BIG"] * 100 + ["TINY"] * 5)
        skew = np.concatenate([np.zeros(100), np.full(5, 10.0)])
        self.assertAlmostEqual(economic_spread(values, skew, "categorical"), 0.0, places=9)


class TestSignConsistency(unittest.TestCase):
    def test_counts_groups_agreeing_with_the_pooled_sign(self):
        values = np.tile(np.array([0.0, 1.0]), 30)
        skew = np.tile(np.array([0.0, 1.0]), 30)
        groups = np.repeat(np.array(["s1", "s2", "s3"]), 20)
        out = sign_consistency(values, skew, groups, "continuous")
        self.assertEqual(out["agree"], 3)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["sign"], 1)

    def test_a_group_with_the_opposite_sign_is_counted_as_disagreeing(self):
        values = np.concatenate([np.tile([0.0, 1.0], 20), np.tile([0.0, 1.0], 10)])
        skew = np.concatenate([np.tile([0.0, 1.0], 20), np.tile([1.0, 0.0], 10)])
        groups = np.array(["s1"] * 40 + ["s2"] * 20)
        out = sign_consistency(values, skew, groups, "continuous")
        self.assertEqual(out["agree"], 1)
        self.assertEqual(out["total"], 2)


class TestSelectWinner(unittest.TestCase):
    def _r(self, name, spread, pvalue):
        return {"feature": name, "spread": spread, "pvalue": pvalue, "promoted": True}

    def test_ranks_on_economic_spread_not_on_pvalue(self):
        """p-values under clustered inference are the noisier quantity;
        ranking on them selects on sampling error."""
        winner = select_winner([self._r("a", 0.30, 0.001), self._r("b", 0.90, 0.04)])
        self.assertEqual(winner["feature"], "b")

    def test_ignores_features_that_did_not_pass(self):
        losing = {"feature": "c", "spread": 5.0, "pvalue": 0.9, "promoted": False}
        winner = select_winner([losing, self._r("a", 0.30, 0.001)])
        self.assertEqual(winner["feature"], "a")

    def test_returns_none_when_nothing_passed(self):
        self.assertIsNone(select_winner([
            {"feature": "c", "spread": 5.0, "pvalue": 0.9, "promoted": False}]))


if __name__ == "__main__":
    unittest.main()
