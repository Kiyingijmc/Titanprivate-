import unittest
import numpy as np

from scripts.confidence_screen.inference import (
    benjamini_hochberg, cluster_bootstrap, icc, rank_within_symbol, spearman_rho,
)


class TestRankWithinSymbol(unittest.TestCase):
    def test_ranks_are_computed_per_symbol_not_pooled(self):
        values = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
        symbols = np.array(["A", "A", "A", "B", "B", "B"])
        out = rank_within_symbol(values, symbols)
        np.testing.assert_allclose(out[:3], out[3:], atol=1e-12)

    def test_invariant_to_symbol_level_rescaling(self):
        """Directly tests the confound this exists to remove: BTCUSD and
        EURUSD have structurally different R distributions."""
        values = np.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0])
        symbols = np.array(["A", "A", "A", "B", "B", "B"])
        scaled = values.copy()
        scaled[3:] *= 1000.0
        np.testing.assert_allclose(
            rank_within_symbol(values, symbols), rank_within_symbol(scaled, symbols))

    def test_ties_get_midranks(self):
        out = rank_within_symbol(np.array([5.0, 5.0]), np.array(["A", "A"]))
        self.assertAlmostEqual(out[0], out[1], places=12)


class TestBenjaminiHochberg(unittest.TestCase):
    def test_known_answer_rejects_all_five(self):
        """Classic BH worked example: with m=5 and q=0.05, p_(5)=0.042 <= 0.05
        so k=5 and every hypothesis is rejected, including p=0.041 which fails
        its own individual threshold. A naive per-test comparison gets this
        wrong, which is exactly the bug this test catches."""
        p = np.array([0.001, 0.008, 0.039, 0.041, 0.042])
        np.testing.assert_array_equal(
            benjamini_hochberg(p, q=0.05), np.array([True] * 5))

    def test_known_answer_rejects_only_the_first(self):
        p = np.array([0.01, 0.5, 0.6])
        np.testing.assert_array_equal(
            benjamini_hochberg(p, q=0.10), np.array([True, False, False]))

    def test_result_order_matches_input_order_not_sorted_order(self):
        p = np.array([0.6, 0.01, 0.5])
        np.testing.assert_array_equal(
            benjamini_hochberg(p, q=0.10), np.array([False, True, False]))

    def test_no_rejections_when_everything_is_null(self):
        p = np.array([0.4, 0.5, 0.6, 0.7])
        self.assertFalse(benjamini_hochberg(p, q=0.10).any())


class TestSpearman(unittest.TestCase):
    def test_perfect_monotone_is_one(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(spearman_rho(x, x ** 3), 1.0, places=9)

    def test_perfect_inverse_is_minus_one(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(spearman_rho(x, -x), -1.0, places=9)


class TestClusterBootstrap(unittest.TestCase):
    def _data(self, n=400, seed=3):
        rng = np.random.default_rng(seed)
        x = rng.normal(size=n)
        y = 0.6 * x + rng.normal(size=n)
        clusters = np.repeat(np.arange(n // 10), 10)
        return x, y, clusters

    def test_is_deterministic_for_a_fixed_seed(self):
        x, y, c = self._data()
        a = cluster_bootstrap(x, y, c, n_draws=200, seed=11)
        b = cluster_bootstrap(x, y, c, n_draws=200, seed=11)
        self.assertEqual(a["pvalue"], b["pvalue"])
        self.assertEqual(a["ci_lo"], b["ci_lo"])

    def test_detects_a_strong_real_relationship(self):
        x, y, c = self._data()
        out = cluster_bootstrap(x, y, c, n_draws=500, seed=5)
        self.assertGreater(out["rho"], 0.3)
        self.assertLess(out["pvalue"], 0.05)

    def test_pure_noise_is_not_significant(self):
        rng = np.random.default_rng(9)
        n = 400
        x, y = rng.normal(size=n), rng.normal(size=n)
        c = np.repeat(np.arange(n // 10), 10)
        self.assertGreater(cluster_bootstrap(x, y, c, n_draws=500, seed=5)["pvalue"], 0.05)


class TestICC(unittest.TestCase):
    def test_identical_within_clusters_is_near_one(self):
        values = np.repeat(np.arange(20, dtype=float), 10)
        clusters = np.repeat(np.arange(20), 10)
        self.assertGreater(icc(values, clusters), 0.9)

    def test_pure_noise_is_near_zero(self):
        rng = np.random.default_rng(1)
        values = rng.normal(size=400)
        clusters = np.repeat(np.arange(40), 10)
        self.assertLess(abs(icc(values, clusters)), 0.2)


if __name__ == "__main__":
    unittest.main()
