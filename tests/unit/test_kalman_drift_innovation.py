# tests/unit/test_kalman_drift_innovation.py
# Gyroscope v2 (docs/research/2026-08-01-gyroscope2-gate.md): SPRT on
# standardized one-step innovations u = eps/sqrt(S) instead of the
# autocorrelated velocity statistic (audit F1/F2), with a velocity-sign
# confirmation at the crossing and a reachable NIS persistence (F7).
# Deterministic synthetic series only; the velocity mode must stay
# bit-identical to v1.
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.kalman_drift import KalmanDrift

ATR = 0.002


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


class TestVelocityModeUnchanged(unittest.TestCase):
    def test_default_mode_is_velocity_and_bit_identical(self):
        ys = _flat_then_drift(300, 200, 0.0015, seed=3)
        default = _feed(KalmanDrift(warmup_bars=60, nis_window=50), ys)
        explicit = _feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                     sprt_on="velocity"), ys)
        for a, b in zip(default, explicit):
            self.assertEqual(a, b)
        self.assertTrue(any(r.crossed for r in default))

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            KalmanDrift(sprt_on="magic")


class TestInnovationSprt(unittest.TestCase):
    def _fires(self, readings):
        return [i for i, r in enumerate(readings) if r.crossed]

    def test_pure_noise_fires_less_than_velocity_mode(self):
        ys = _noise(3000, 0.0005, seed=7)
        vel = self._fires(_feed(KalmanDrift(warmup_bars=60, nis_window=50), ys))
        inn = self._fires(_feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                            sprt_on="innovation",
                                            z_confirm=1.0), ys))
        self.assertLess(len(inn), max(1, len(vel) // 2))
        self.assertLessEqual(len(inn), 45)  # ~<15/1000 post-warmup bars

    def test_sustained_drift_does_not_systematically_refire(self):
        # v1's whipsaw pathology (audit F3): one long trend => serial fires.
        # In innovation mode the filter absorbs the drift and self-quiets, so
        # in-trend fires stay near the background noise rate.
        ys = _flat_then_drift(300, 1500, 0.0010, seed=8)
        vel = _feed(KalmanDrift(warmup_bars=60, nis_window=50), ys)
        inn = _feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                sprt_on="innovation", z_confirm=1.0), ys)
        vel_in_trend = [i for i, r in enumerate(vel) if r.crossed and i >= 300]
        inn_in_trend = [i for i, r in enumerate(inn) if r.crossed and i >= 300]
        self.assertGreater(len(vel_in_trend), 3 * max(1, len(inn_in_trend)))

    def test_drift_onset_still_detected_long(self):
        ys = _flat_then_drift(300, 200, 0.0015, seed=3)
        inn = _feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                sprt_on="innovation", z_confirm=1.0), ys)
        onset = [i for i, r in enumerate(inn) if r.crossed == "LONG"]
        self.assertTrue(any(300 <= i <= 380 for i in onset),
                        f"no LONG within 80 bars of onset: {onset}")

    def test_short_mirror(self):
        ys = _flat_then_drift(300, 200, -0.0015, seed=5)
        inn = _feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                sprt_on="innovation", z_confirm=1.0), ys)
        self.assertIn("SHORT", [r.crossed for r in inn if r.crossed])

    def test_reading_exposes_signed_innovation(self):
        f = KalmanDrift(warmup_bars=10, sprt_on="innovation")
        rs = _feed(f, _flat_then_drift(50, 50, 0.0015, seed=3))
        self.assertTrue(any(r.u != 0.0 for r in rs[1:]))
        # during the up-drift the innovations skew positive
        self.assertGreater(sum(r.u for r in rs[55:70]), 0.0)


class TestZConfirm(unittest.TestCase):
    def test_unreachable_z_confirm_blocks_all_crossings(self):
        ys = _flat_then_drift(300, 200, 0.0015, seed=3)
        inn = _feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                sprt_on="innovation", z_confirm=1000.0), ys)
        self.assertEqual([r.crossed for r in inn if r.crossed], [])

    def test_failed_confirmation_resets_lambdas(self):
        ys = _flat_then_drift(300, 200, 0.0015, seed=3)
        f = KalmanDrift(warmup_bars=60, nis_window=50,
                        sprt_on="innovation", z_confirm=1000.0)
        for r in _feed(f, ys):
            pass
        # evidence must have been spent at every would-be crossing, never
        # allowed to sit at/above the boundary
        self.assertLess(f.lam_long, f.A)
        self.assertLess(f.lam_short, f.A)

    def test_zero_z_confirm_allows_crossings(self):
        ys = _flat_then_drift(300, 200, 0.0015, seed=3)
        inn = _feed(KalmanDrift(warmup_bars=60, nis_window=50,
                                sprt_on="innovation", z_confirm=0.0), ys)
        self.assertTrue(any(r.crossed for r in inn))


class TestNisPersistDecoupled(unittest.TestCase):
    def _vol_jump(self):
        return _noise(300, 0.0005, seed=11) + _noise(200, 0.005, seed=12)

    def test_default_persist_still_equals_window(self):
        f = KalmanDrift(nis_window=50)
        self.assertEqual(f.nis_persist, 50)

    def test_short_persist_suspends_earlier(self):
        slow = KalmanDrift(warmup_bars=60, nis_window=50)
        fast = KalmanDrift(warmup_bars=60, nis_window=50, nis_persist=10)
        ys = self._vol_jump()
        first_slow = next((i for i, r in enumerate(_feed(slow, ys))
                           if r.state == "SUSPENDED"), None)
        first_fast = next((i for i, r in enumerate(_feed(fast, ys))
                           if r.state == "SUSPENDED"), None)
        self.assertIsNotNone(first_fast)
        self.assertTrue(first_slow is None or first_fast < first_slow)


if __name__ == "__main__":
    unittest.main()
