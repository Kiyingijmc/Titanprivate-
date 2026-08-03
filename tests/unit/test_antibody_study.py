# tests/unit/test_antibody_study.py
# Antibody v1 / Task 2: walk-forward study helpers. Small synthetic fixtures;
# no heavy data, no market files.
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scripts.antibody_study import (
    window_bounds,
    alert_windows,
    classify_trades,
    bucket_metrics,
    fit_diagnostics,
    walk_forward_states,
)


class TestWindowBounds(unittest.TestCase):
    def test_tiles_without_overlap_or_gap(self):
        wins = window_bounds(n_bars=25, fit_bars=10, step_bars=5)
        self.assertEqual(wins[0], (0, 10, 10, 15))
        self.assertEqual(wins[1], (5, 15, 15, 20))
        self.assertEqual(wins[2], (10, 20, 20, 25))
        self.assertEqual([w[2] for w in wins], [10, 15, 20])
        self.assertEqual([w[3] for w in wins], [15, 20, 25])

    def test_partial_last_window(self):
        # A short tail stays a short final region (NOT back-pinned to a full
        # step) so score regions never overlap and no bar is scored twice.
        wins = window_bounds(n_bars=23, fit_bars=10, step_bars=5)
        self.assertEqual(wins[-1], (10, 20, 20, 23))  # short 3-bar tail region
        # score regions tile [10, 23) exactly, contiguous, no overlap
        self.assertEqual([w[2] for w in wins], [10, 15, 20])
        self.assertEqual([w[3] for w in wins], [15, 20, 23])

    def test_no_windows_when_too_short(self):
        self.assertEqual(window_bounds(n_bars=10, fit_bars=10, step_bars=5), [])
        self.assertEqual(window_bounds(n_bars=8, fit_bars=10, step_bars=5), [])

    def test_partial_tail_never_double_scores(self):
        # Regression guard: non-divisible tail must not overlap the prior window.
        wins = window_bounds(n_bars=23, fit_bars=10, step_bars=5)
        scored = [k for _flo, _fhi, lo, hi in wins for k in range(lo, hi)]
        self.assertEqual(scored, sorted(set(scored)))          # no bar scored twice
        self.assertEqual(scored, list(range(10, 23)))          # covers [fit_bars, n_bars)


class TestAlertWindows(unittest.TestCase):
    def _states(self, seq):
        idx = pd.date_range("2024-01-01", periods=len(seq), freq="h")
        return [
            {"i": k, "time": idx[k], "score": sc, "threshold": 1.0,
             "state": st, "alert": st == "ALERT"}
            for k, (st, sc) in enumerate(seq)
        ]

    def test_contiguous_runs(self):
        seq = [("PATROL", 0.1), ("ALERT", 5.0), ("ALERT", 9.0), ("PATROL", 0.2),
               ("ALERT", 4.0), ("PATROL", 0.1)]
        wins = alert_windows(self._states(seq))
        self.assertEqual(len(wins), 2)
        self.assertEqual(wins[0]["duration"], 2)
        self.assertEqual(wins[0]["peak_score"], 9.0)
        self.assertEqual(wins[1]["duration"], 1)
        self.assertEqual(wins[1]["peak_score"], 4.0)

    def test_no_alerts(self):
        seq = [("PATROL", 0.1)] * 4
        self.assertEqual(alert_windows(self._states(seq)), [])


class TestClassifyTrades(unittest.TestCase):
    def test_inside_and_boundary(self):
        win = {"start_time": pd.Timestamp("2024-01-01 05:00"),
               "end_time": pd.Timestamp("2024-01-01 08:00"),
               "start_i": 5, "end_i": 8, "duration": 4, "peak_score": 9.0}
        windows_by_symbol = {"EURUSD": [win]}
        trades = [
            {"symbol": "EURUSD", "time": "2024-01-01 06:00"},   # inside
            {"symbol": "EURUSD", "time": "2024-01-01 05:00"},   # boundary start -> inside
            {"symbol": "EURUSD", "time": "2024-01-01 08:00"},   # boundary end -> inside
            {"symbol": "EURUSD", "time": "2024-01-01 09:00"},   # outside
            {"symbol": "GBPUSD", "time": "2024-01-01 06:00"},   # other symbol -> outside
        ]
        out = classify_trades(trades, windows_by_symbol)
        self.assertEqual([t["inside_alert"] for t in out], [True, True, True, False, False])


class TestBucketMetrics(unittest.TestCase):
    def test_expectancy_and_pf(self):
        trades = [
            {"outcome": "TP", "r": 2.0}, {"outcome": "SL", "r": -1.0},
            {"outcome": "TP", "r": 1.0}, {"outcome": "EXPIRED", "r": 0.0},  # ignored
        ]
        m = bucket_metrics(trades)
        self.assertEqual(m["n"], 3)
        self.assertAlmostEqual(m["expectancy"], (2.0 - 1.0 + 1.0) / 3, places=9)
        self.assertAlmostEqual(m["profit_factor"], 3.0 / 1.0, places=9)

    def test_empty_bucket(self):
        m = bucket_metrics([{"outcome": "EXPIRED", "r": 0.0}])
        self.assertEqual(m["n"], 0)
        self.assertEqual(m["expectancy"], 0.0)


class TestFitDiagnostics(unittest.TestCase):
    def test_well_conditioned_window(self):
        import random
        rng = random.Random(4)
        feats = [(rng.gauss(1.0, 0.3), rng.gauss(0.5, 0.2),
                  rng.gauss(0.4, 0.15), rng.gauss(0.6, 0.2)) for _ in range(200)]
        d = fit_diagnostics(feats)
        self.assertGreater(d["min_variance"], 0.0)
        self.assertLess(d["cov_condition"], 1e6)  # all dims have real variance

    def test_degenerate_dimension_flagged(self):
        # a constant 3rd feature -> near-zero variance -> huge condition number
        import random
        rng = random.Random(4)
        feats = [(rng.gauss(1.0, 0.3), rng.gauss(0.5, 0.2), 0.0, rng.gauss(0.6, 0.2))
                 for _ in range(200)]
        d = fit_diagnostics(feats)
        self.assertLess(d["min_variance"], 1e-12)
        self.assertGreater(d["cov_condition"], 1e6)  # ridge lets it dominate

    def test_too_few_samples_fails_loud(self):
        with self.assertRaises(ValueError):
            fit_diagnostics([(1.0, 0.5, 0.4, 0.6)] * 4)


class TestWalkForwardLookahead(unittest.TestCase):
    def test_scored_region_and_refit_continuity(self):
        import random
        rng = random.Random(5)
        rows, price = [], 1.0
        # 63 bars with fit_bars=20/step_bars=10 leaves a non-divisible 3-bar
        # tail -- the case a back-pinned final window would double-score.
        for _ in range(63):
            d = rng.uniform(-0.0002, 0.0002)
            o, c = price, price + d
            rows.append((o, max(o, c) + 0.0002, min(o, c) - 0.0002, c))
            price = c
        df = pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=63, freq="h"),
            "open": [r[0] for r in rows], "high": [r[1] for r in rows],
            "low": [r[2] for r in rows], "close": [r[3] for r in rows],
        })
        states = walk_forward_states(df, fit_bars=20, step_bars=10)
        self.assertTrue(all(s["i"] >= 20 for s in states))
        self.assertTrue(all(s["state"] in ("PATROL", "ALERT") for s in states))
        idxs = [s["i"] for s in states]
        self.assertEqual(idxs, sorted(set(idxs)))     # monotone, no duplicates
        self.assertEqual(idxs, list(range(20, 63)))   # every tail bar scored once


if __name__ == "__main__":
    unittest.main()
