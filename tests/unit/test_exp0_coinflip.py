import os
import sys
import shutil
import tempfile
import unittest
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import numpy as np
import pandas as pd

from scripts import poc_sb_stops as sb
from scripts import exp0_coinflip as exp0


def _synthetic_bars(n=600, seed=7):
    """H1-like bars dict in the collect_signals 'bars' schema (+atr/times)."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.5, n).cumsum()
    close = 100.0 + steps
    spread = np.abs(rng.normal(0.4, 0.15, n)) + 0.05
    high = close + spread
    low = close - spread
    atr = np.full(n, 0.8)
    times = pd.date_range("2024-01-01", periods=n, freq="1h").values
    return {"high": high, "low": low, "atr": atr, "times": times,
            "disp_bull": np.zeros(n, dtype=bool),
            "disp_bear": np.zeros(n, dtype=bool)}


def _synthetic_signals(bars, n_sig=40, seed=3):
    """Real-signal stand-ins carrying every field gen_placebo_signals consumes."""
    rng = np.random.default_rng(seed)
    n = len(bars["high"])
    idxs = np.sort(rng.choice(np.arange(60, n - 20), size=n_sig, replace=False))
    signals = []
    for k, i in enumerate(idxs):
        hi, lo = bars["high"][i], bars["low"][i]
        d = "BUY" if k % 5 < 3 else "SELL"          # 60/40 direction mix
        frac = float(rng.uniform(0.1, 0.9))
        t = pd.Timestamp(bars["times"][i])
        signals.append({
            "bar_idx": int(i), "time": t, "dir": d,
            "entry": float(lo + frac * (hi - lo)),
            "far_extreme": float(bars["high"][i - 2] if d == "SELL" else bars["low"][i - 2]),
            "sig_high": float(hi), "sig_low": float(lo),
            "atr": float(bars["atr"][i]), "body_atr": 1.0,
            "bias": "NEUTRAL", "liq_status": "",
            "hour": int(t.hour), "year": int(t.year),
        })
    return signals


class TestPlaceboGenerator(unittest.TestCase):
    def setUp(self):
        self.bars = _synthetic_bars()
        self.signals = _synthetic_signals(self.bars)

    def test_matches_marginals(self):
        placebo = exp0.gen_placebo_signals(self.signals, self.bars, seed=11)
        self.assertEqual(len(placebo), len(self.signals))
        # direction balance preserved exactly (shuffled real directions)
        self.assertEqual(Counter(p["dir"] for p in placebo),
                         Counter(s["dir"] for s in self.signals))
        # hour-of-day marginal preserved exactly (hour-conditioned sampling)
        self.assertEqual(Counter(p["hour"] for p in placebo),
                         Counter(s["hour"] for s in self.signals))
        n = len(self.bars["high"])
        for p in placebo:
            self.assertGreaterEqual(p["bar_idx"], exp0.MIN_BAR)
            self.assertLess(p["bar_idx"], n - 1)
            j = p["bar_idx"]
            self.assertGreaterEqual(p["entry"], self.bars["low"][j] - 1e-9)
            self.assertLessEqual(p["entry"], self.bars["high"][j] + 1e-9)
            self.assertGreater(p["atr"], 0)
        # resolve() consumes signals in bar order
        self.assertEqual([p["bar_idx"] for p in placebo],
                         sorted(p["bar_idx"] for p in placebo))

    def test_deterministic_and_seed_sensitive(self):
        a = exp0.gen_placebo_signals(self.signals, self.bars, seed=11)
        b = exp0.gen_placebo_signals(self.signals, self.bars, seed=11)
        self.assertEqual([(p["bar_idx"], p["dir"], p["entry"]) for p in a],
                         [(p["bar_idx"], p["dir"], p["entry"]) for p in b])
        c = exp0.gen_placebo_signals(self.signals, self.bars, seed=12)
        self.assertNotEqual([p["bar_idx"] for p in a], [p["bar_idx"] for p in c])

    def test_stop_models_apply_to_placebo(self):
        placebo = exp0.gen_placebo_signals(self.signals, self.bars, seed=11)
        for model in sb.STOP_MODELS:
            for p in placebo:
                stop = sb.stop_price(p, model)
                self.assertTrue(np.isfinite(stop))
                if p["dir"] == "BUY":
                    self.assertLess(stop, p["entry"])
                else:
                    self.assertGreater(stop, p["entry"])

    def test_pipeline_end_to_end(self):
        placebo = exp0.gen_placebo_signals(self.signals, self.bars, seed=11)
        trades = sb.resolve(placebo, self.bars, "ATR10")
        self.assertGreater(len(trades), 0)
        for t in trades:
            r1 = sb.replay_managed(t, self.bars)
            r2 = sb.replay_managed(t, self.bars, runner=True)
            self.assertTrue(np.isfinite(r1))
            self.assertTrue(np.isfinite(r2))


class TestCollectSignalsBarsSchema(unittest.TestCase):
    """collect_signals must expose atr/times in bars for the placebo generator."""

    def test_bars_carry_atr_and_times(self):
        tmp = tempfile.mkdtemp(prefix="exp0_")
        cwd = os.getcwd()
        try:
            os.makedirs(os.path.join(tmp, "data", "history"))
            rng = np.random.default_rng(5)
            n = 4000                                     # ~2 weeks of M5
            close = 100.0 + rng.normal(0, 0.3, n).cumsum()
            spread = np.abs(rng.normal(0.2, 0.1, n)) + 0.02
            df = pd.DataFrame({
                "datetime": pd.date_range("2024-01-01", periods=n, freq="5min"),
                "open": np.r_[close[0], close[:-1]],
                "high": close + spread, "low": close - spread, "close": close,
            })
            df.to_csv(os.path.join(tmp, "data", "history", "EXP0T_M5.csv"),
                      index=False)
            os.chdir(tmp)
            signals, bars = sb.collect_signals("EXP0T", tf="H1")
            self.assertIsNotNone(bars)
            self.assertIn("atr", bars)
            self.assertIn("times", bars)
            self.assertEqual(len(bars["atr"]), len(bars["high"]))
            self.assertEqual(len(bars["times"]), len(bars["high"]))
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
