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


def _ragged_clusters(rng, n_clusters, lo=3, hi=41):
    """Deliberately UNEQUAL cluster sizes (spec §4.1 Amendment).

    Equal 10-per-cluster fixtures are exactly what hid the original defect:
    the deleted permutation null fragmented a cluster across neighbours only
    when block boundaries didn't line up, which never happens when every
    block is the same size. Sizes are drawn uniformly from [lo, hi) so real
    calendar-week-sized ragged blocks (weeks vary from a few signals to
    dozens) are represented.
    """
    sizes = rng.integers(lo, hi, size=n_clusters)
    clusters = np.repeat(np.arange(n_clusters), sizes)
    return clusters, int(sizes.sum())


class TestClusterBootstrap(unittest.TestCase):
    def _data(self, seed=3, n_clusters=20):
        rng = np.random.default_rng(seed)
        clusters, n = _ragged_clusters(rng, n_clusters)
        x = rng.normal(size=n)
        y = 0.6 * x + rng.normal(size=n)
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
        c, n = _ragged_clusters(rng, 20)
        x, y = rng.normal(size=n), rng.normal(size=n)
        self.assertGreater(cluster_bootstrap(x, y, c, n_draws=500, seed=5)["pvalue"], 0.05)


class TestClusterBootstrapCalibration(unittest.TestCase):
    """Binding requirement from spec §4.1 Amendment: a calibration check on
    DELIBERATELY UNEQUAL cluster sizes, because the deleted permutation null
    was invisible to 14 passing tests purely because every bootstrap fixture
    used equal 10-per-cluster blocks. That null measured a 15% false-positive
    rate against a nominal 5%; this pins the replacement — inverting the
    same-index resampling distribution — at nominal.
    """

    N_TRIALS = 250
    N_CLUSTERS = 15
    # Production default (BOOTSTRAP_DRAWS) is 10,000 draws; that is far more
    # than a calibration loop needs per trial (this test already runs 250
    # independent trials) and would blow the module's runtime budget, so a
    # deliberately modest per-trial draw count is used instead.
    N_DRAWS = 300
    ALPHA = 0.05

    def test_false_positive_rate_is_near_nominal_with_ragged_clusters(self):
        """H0 is mechanically true here (x, y independent) so any rejection
        at alpha=0.05 is by construction a false positive.

        Trial count / band reasoning: with N_TRIALS=250 independent trials,
        the binomial standard error of the measured FPR under a truly
        nominal 5% rate is sqrt(0.05*0.95/250) ~= 0.0138. A 3-SE band
        ([0.0086, 0.0914]) keeps the test from flaking on ordinary Monte
        Carlo noise while still being far tighter than the 15% the deleted
        permutation null actually measured (>7 SE outside this band, so a
        regression back to that defect fails loudly, not marginally).
        250 trials x 300 draws keeps this test in the tens-of-seconds range
        rather than the minutes a production-scale 10,000-draw bootstrap
        would take per trial.
        """
        rng = np.random.default_rng(2026)
        rejects = 0
        for _ in range(self.N_TRIALS):
            clusters, n = _ragged_clusters(rng, self.N_CLUSTERS)
            x = rng.normal(size=n)
            y = rng.normal(size=n)  # independent of x: H0 is true
            draw_seed = int(rng.integers(0, 2**31 - 1))
            out = cluster_bootstrap(x, y, clusters, n_draws=self.N_DRAWS, seed=draw_seed)
            if out["pvalue"] < self.ALPHA:
                rejects += 1
        fpr = rejects / self.N_TRIALS
        se = (self.ALPHA * (1 - self.ALPHA) / self.N_TRIALS) ** 0.5
        self.assertGreater(fpr, self.ALPHA - 3 * se, msg=f"measured FPR={fpr}")
        self.assertLess(fpr, self.ALPHA + 3 * se, msg=f"measured FPR={fpr}")

    def test_still_detects_genuine_association_with_ragged_clusters(self):
        """Companion to the calibration test above: a method that always
        returns pvalue=1.0 would also "pass" a calibration-only check, so
        this proves the same ragged-cluster setup still finds a real signal.
        """
        rng = np.random.default_rng(4242)
        clusters, n = _ragged_clusters(rng, self.N_CLUSTERS)
        x = rng.normal(size=n)
        y = 0.6 * x + rng.normal(size=n)
        out = cluster_bootstrap(x, y, clusters, n_draws=1000, seed=7)
        self.assertGreater(out["rho"], 0.3)
        self.assertLess(out["pvalue"], self.ALPHA)


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
