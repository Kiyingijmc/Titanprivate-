import unittest
import numpy as np

from scripts.confidence_screen.controls import inject_synthetic, permute_within_symbol
from scripts.confidence_screen.inference import spearman_rho


class TestPermutation(unittest.TestCase):
    def test_permutes_only_inside_each_symbol(self):
        y = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
        symbols = np.array(["A", "A", "A", "B", "B", "B"])
        out = permute_within_symbol(y, symbols, seed=1)
        np.testing.assert_array_equal(np.sort(out[:3]), np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(np.sort(out[3:]), np.array([10.0, 20.0, 30.0]))

    def test_is_deterministic_for_a_fixed_seed(self):
        y = np.arange(50, dtype=float)
        symbols = np.array(["A"] * 50)
        np.testing.assert_array_equal(
            permute_within_symbol(y, symbols, seed=3),
            permute_within_symbol(y, symbols, seed=3))

    def test_actually_shuffles(self):
        y = np.arange(200, dtype=float)
        symbols = np.array(["A"] * 200)
        self.assertFalse(np.array_equal(permute_within_symbol(y, symbols, seed=3), y))


class TestInjection(unittest.TestCase):
    def test_recovers_close_to_the_target_correlation(self):
        rng = np.random.default_rng(2)
        y = rng.normal(size=4000)
        injected = inject_synthetic(y, target_rho=0.15, seed=7)
        self.assertAlmostEqual(spearman_rho(injected, y), 0.15, delta=0.04)

    def test_is_deterministic_for_a_fixed_seed(self):
        y = np.random.default_rng(4).normal(size=500)
        np.testing.assert_array_equal(
            inject_synthetic(y, seed=7), inject_synthetic(y, seed=7))

    def test_a_zero_target_produces_no_relationship(self):
        rng = np.random.default_rng(6)
        y = rng.normal(size=4000)
        self.assertLess(abs(spearman_rho(inject_synthetic(y, target_rho=0.0, seed=7), y)), 0.06)


if __name__ == "__main__":
    unittest.main()
