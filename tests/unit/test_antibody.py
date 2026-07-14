# tests/unit/test_antibody.py
# Antibody v1 / Task 1: pure OHLC anomaly scorer. Deterministic synthetic
# data only (no market data, no randomness beyond a seeded Random).
import os
import random
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.antibody import (
    AntibodyScorer,
    compute_features,
    MIN_FIT_SAMPLES,
)


def _bars(rows):
    """rows: list of (open, high, low, close) -> DataFrame with a time column."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(
        {
            "time": idx,
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
        }
    )


def _benign(n, seed=7):
    """Small-range noise bars around 1.0000, ~5-pip ranges."""
    rng = random.Random(seed)
    rows, price = [], 1.0000
    for _ in range(n):
        drift = rng.uniform(-0.0002, 0.0002)
        o = price
        c = price + drift
        hi = max(o, c) + rng.uniform(0.0, 0.0003)
        lo = min(o, c) - rng.uniform(0.0, 0.0003)
        rows.append((o, hi, lo, c))
        price = c
    return _bars(rows)


class TestComputeFeatures(unittest.TestCase):
    def test_length_and_warmup(self):
        df = _benign(30)
        feats = compute_features(df)
        self.assertEqual(len(feats), len(df))
        self.assertIsNone(feats[0])  # first bar has no previous bar

    def test_feature_values_hand_computed(self):
        # 16 flat 20-pip bars, then a wide bar; check the wide bar's features.
        rows = [(1.0, 1.0010, 0.9990, 1.0) for _ in range(16)]
        rows.append((1.0, 1.0100, 0.9950, 1.0080))  # wide bar with a body
        df = _bars(rows)
        feats = compute_features(df)
        f1, f2, f3, f4 = feats[16]
        # prior ATR ~ mean TR of the flat 20-pip bars (~0.0020); range 150 pips.
        self.assertGreater(f1, 5.0)
        self.assertAlmostEqual(f2, abs(1.0080 - 1.0) / (1.0100 - 0.9950), places=9)
        self.assertGreaterEqual(f3, 0.0)
        self.assertGreaterEqual(f4, 0.0)

    def test_zero_range_body_ratio_is_zero(self):
        rows = [(1.0, 1.0010, 0.9990, 1.0) for _ in range(16)]
        rows.append((1.0, 1.0, 1.0, 1.0))  # zero-range bar
        df = _bars(rows)
        feats = compute_features(df)
        self.assertEqual(feats[16][1], 0.0)  # body/range -> 0 when range 0


class TestScorerStateMachine(unittest.TestCase):
    def _fit_scorer(self, n=400):
        df = _benign(n)
        feats = [f for f in compute_features(df) if f is not None]
        return AntibodyScorer(feats), df

    def test_single_anomaly_bar_does_not_alert(self):
        scorer, _ = self._fit_scorer()
        r1 = scorer.score((50.0, 0.9, 40.0, 0.0))
        self.assertTrue(r1.score > r1.threshold)
        self.assertEqual(r1.state, "PATROL")   # 1 high bar is not enough
        r2 = scorer.score((0.5, 0.2, 0.0, 0.9))  # benign-ish
        self.assertEqual(r2.state, "PATROL")

    def test_two_consecutive_anomalies_raise_alert(self):
        scorer, _ = self._fit_scorer()
        scorer.score((50.0, 0.9, 40.0, 0.0))
        r2 = scorer.score((60.0, 0.95, 45.0, 0.0))
        self.assertEqual(r2.state, "ALERT")
        self.assertTrue(r2.alert)

    def test_all_clear_after_three_calm_bars(self):
        scorer, _ = self._fit_scorer()
        scorer.score((50.0, 0.9, 40.0, 0.0))
        scorer.score((60.0, 0.95, 45.0, 0.0))  # -> ALERT
        calm = (0.5, 0.2, 0.0, 0.9)
        self.assertEqual(scorer.score(calm).state, "ALERT")  # 1 calm
        self.assertEqual(scorer.score(calm).state, "ALERT")  # 2 calm
        self.assertEqual(scorer.score(calm).state, "PATROL")  # 3 calm -> ALL-CLEAR

    def test_alert_rate_on_fresh_benign_is_near_one_percent(self):
        # q99 threshold => ~1% of same-distribution bars exceed it.
        df_fit = _benign(2000, seed=1)
        feats_fit = [f for f in compute_features(df_fit) if f is not None]
        scorer = AntibodyScorer(feats_fit)
        df_test = _benign(2000, seed=99)
        feats_test = [f for f in compute_features(df_test) if f is not None]
        exceed = sum(1 for f in feats_test if scorer.score(f).score > scorer.threshold)
        rate = exceed / len(feats_test)
        self.assertLess(rate, 0.05)  # generously bounded around the 1% design point


class TestDeterminismAndFailure(unittest.TestCase):
    def test_determinism(self):
        df = _benign(500, seed=3)
        feats = [f for f in compute_features(df) if f is not None]
        a = AntibodyScorer(feats)
        b = AntibodyScorer(feats)
        self.assertEqual(a.threshold, b.threshold)
        probe = [(0.3, 0.4, 0.2, 0.8), (5.0, 0.9, 4.0, 0.1), (0.3, 0.4, 0.2, 0.8)]
        self.assertEqual(
            [a.score(p).score for p in probe],
            [b.score(p).score for p in probe],
        )

    def test_too_few_fit_samples_fails_loud(self):
        with self.assertRaises(ValueError):
            AntibodyScorer([(1.0, 0.5, 0.1, 0.2)] * (MIN_FIT_SAMPLES - 1))

    def test_refit_preserves_state(self):
        df = _benign(600)
        feats = [f for f in compute_features(df) if f is not None]
        scorer = AntibodyScorer(feats[:300])
        scorer.score((50.0, 0.9, 40.0, 0.0))
        scorer.score((60.0, 0.95, 45.0, 0.0))  # -> ALERT
        self.assertEqual(scorer.state, "ALERT")
        scorer.refit(feats[300:])  # roll the model
        self.assertEqual(scorer.state, "ALERT")  # state carried across refit
        calm = (0.5, 0.2, 0.0, 0.9)
        scorer.score(calm)
        scorer.score(calm)
        self.assertEqual(scorer.score(calm).state, "PATROL")  # ALL-CLEAR still counts


if __name__ == "__main__":
    unittest.main()
