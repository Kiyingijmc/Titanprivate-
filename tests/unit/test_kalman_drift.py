# tests/unit/test_kalman_drift.py
# Plan 07 / Task 3: KalmanDrift filter + velocity-SPRT + NIS on synthetic
# series. Deterministic: seeded random.Random for noise; no market data.
# Decision layer runs on the standardized velocity z = v_hat/sqrt(P_vel)
# (see the module docstring for why, vs whitened innovations).
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.kalman_drift import KalmanDrift, Reading

ATR = 0.002  # constant synthetic ATR (price units around price ~ e^0 = 1.0)


def _noise(n, sigma, seed=42):
    rng = random.Random(seed)
    return [rng.gauss(0.0, sigma) for _ in range(n)]


def _feed(filt, log_prices):
    return [filt.update(y, ATR) for y in log_prices]


def _flat_then_drift(n_flat, n_drift, step, seed):
    noise = _noise(n_flat + n_drift, 0.0005, seed=seed)
    ys, level = [], 0.0
    for i in range(n_flat + n_drift):
        if i >= n_flat:
            level += step
        ys.append(level + noise[i])
    return ys


class TestKalmanFilterCore(unittest.TestCase):
    def test_boundaries_match_wald_formulas(self):
        f = KalmanDrift(alpha=0.05, beta=0.20)
        # A = ln((1-beta)/alpha) = ln(0.80/0.05); B = ln(beta/(1-alpha)).
        self.assertAlmostEqual(f.A, math.log(0.80 / 0.05), places=9)
        self.assertAlmostEqual(f.B, math.log(0.20 / 0.95), places=9)

    def test_velocity_recovers_known_drift_after_onset(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        ys = _flat_then_drift(250, 300, 0.0015, seed=1)
        readings = _feed(f, ys)
        self.assertAlmostEqual(readings[-1].velocity, 0.0015, delta=0.0008)

    def test_first_reading_initializes_warmup(self):
        f = KalmanDrift(warmup_bars=10)
        r = f.update(0.0, ATR)
        self.assertIsInstance(r, Reading)
        self.assertEqual(r.state, "WARMUP")
        self.assertEqual(r.crossed, "")
        self.assertEqual(r.velocity, 0.0)

    def test_nis_is_calibrated_on_clean_noise(self):
        # The R correction (0.5 * return variance) puts NIS near 1 on clean
        # noise so the chi-square band is meaningful (~0.44 without it).
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        readings = _feed(f, _noise(1500, 0.0005, seed=3))
        tail = [r.nis_mean for r in readings[300:]]
        mean_nis = sum(tail) / len(tail)
        self.assertGreater(mean_nis, 0.6)
        self.assertLess(mean_nis, 1.4)


class TestSprtLayer(unittest.TestCase):
    def test_pure_noise_rarely_crosses(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        crossings = sum(1 for r in _feed(f, _noise(2000, 0.0005, seed=7)) if r.crossed)
        self.assertLessEqual(crossings, 8)

    def test_drift_onset_crosses_long_within_window(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        readings = _feed(f, _flat_then_drift(300, 100, 0.0015, seed=3))
        onset = [i for i, r in enumerate(readings) if r.crossed == "LONG"]
        self.assertTrue(any(300 <= i <= 360 for i in onset),
                        f"no LONG crossing within 60 bars of onset: {onset}")

    def test_crossing_resets_both_lambdas(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        for r in _feed(f, _flat_then_drift(300, 100, 0.0015, seed=3)):
            if r.crossed:
                self.assertEqual(r.lam_long, 0.0)
                self.assertEqual(r.lam_short, 0.0)
                break
        else:
            self.fail("no crossing observed")

    def test_short_mirror_crosses_on_negative_drift(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        crossings = [r.crossed for r in _feed(f, _flat_then_drift(300, 100, -0.0015, seed=5)) if r.crossed]
        self.assertIn("SHORT", crossings)


class TestNisIntegrityMonitor(unittest.TestCase):
    def _vol_jump(self):
        return _noise(300, 0.0005, seed=11) + _noise(200, 0.005, seed=12)

    def test_sustained_vol_regime_jump_suspends(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        states = [r.state for r in _feed(f, self._vol_jump())]
        self.assertIn("SUSPENDED", states[300:])

    def test_no_crossings_while_suspended(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        for r in _feed(f, self._vol_jump()):
            if r.state == "SUSPENDED":
                self.assertEqual(r.crossed, "")

    def test_drift_onset_never_suspends(self):
        # A brief drift-onset spike must NOT trip the sustained-break failsafe.
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        states = [r.state for r in _feed(f, _flat_then_drift(300, 100, 0.0015, seed=3))]
        self.assertNotIn("SUSPENDED", states)


if __name__ == "__main__":
    unittest.main()
