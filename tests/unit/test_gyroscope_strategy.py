# tests/unit/test_gyroscope_strategy.py
# Plan 07 / Task 4: decision-dict contract, idempotency, cooldown, gating.
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from src.strategies.models.gyroscope import GyroscopeStrategy
from src.analysis.atr_simple import last_atr

CFG = {
    "enabled": True, "timeframe": "H1",
    "warmup_bars": 60, "q_atr_frac": 0.05, "r_frac": 1.0,
    "sprt": {"alpha": 0.05, "beta": 0.20, "delta": 0.40},
    "nis_window": 50, "k_sl": 3.0, "sl_atr_floor": 0.8,
    "rr_target": 2.0, "max_bars_in_trade": 48,
    "reentry_lockout": 5, "max_spread_atr_frac": 0.10,
}


class _NullLogger:
    def log_event(self, *a, **k):
        pass


def _bars(closes, start="2026-01-01 00:00:00"):
    t0 = pd.Timestamp(start)
    rows = []
    for k, c in enumerate(closes):
        rows.append({"time": str(t0 + pd.Timedelta(hours=k)),
                     "open": c, "high": c + 0.0008, "low": c - 0.0008, "close": c})
    return pd.DataFrame(rows)


def _drift_series(n_flat=300, n_drift=80, step=0.0015, seed=3):
    import random
    rng = random.Random(seed)
    closes, level = [], 0.0
    for i in range(n_flat + n_drift):
        if i >= n_flat:
            level += step
        closes.append(1.0 + level + rng.gauss(0.0, 0.0005))
    return closes


def _run(strat, df, ctx=None):
    return asyncio.run(strat.on_new_candle(df, context=ctx or {"symbol": "EURUSD"}))


class TestAtrSimple(unittest.TestCase):
    def test_last_atr_is_mean_true_range(self):
        df = _bars([1.0, 1.0, 1.0])
        # TR per bar = max(high-low, |high-prev_close|, |low-prev_close|) = 0.0016
        self.assertAlmostEqual(last_atr(df, period=14), 0.0016, places=6)

    def test_too_short_returns_zero(self):
        self.assertEqual(last_atr(_bars([1.0])), 0.0)


class TestGyroscopeContract(unittest.TestCase):
    def test_below_warmup_returns_none(self):
        strat = GyroscopeStrategy(CFG, _NullLogger())
        self.assertIsNone(_run(strat, _bars([1.0] * 30)))

    def test_no_time_column_returns_none(self):
        strat = GyroscopeStrategy(CFG, _NullLogger())
        df = _bars([1.0] * 80).drop(columns=["time"])
        self.assertIsNone(_run(strat, df))

    def test_drift_onset_emits_market_buy_with_coherent_levels(self):
        closes = _drift_series()
        strat = GyroscopeStrategy(CFG, _NullLogger())
        decision = None
        # Feed growing windows one bar at a time, like replay does.
        for end in range(60, len(closes) + 1):
            d = _run(strat, _bars(closes[:end]))
            if d is not None:
                decision = d
                break
        self.assertIsNotNone(decision, "drift onset never produced a signal")
        self.assertEqual(decision["signal"], "BUY")
        self.assertEqual(decision["type"], "MARKET")
        self.assertLess(decision["sl"], decision["price"])
        self.assertGreater(decision["tp"], decision["price"])
        # rr_target geometry
        risk = decision["price"] - decision["sl"]
        self.assertAlmostEqual(decision["tp"] - decision["price"], 2.0 * risk, places=9)
        # sl_atr_floor: risk never tighter than 0.8 * ATR
        # (ATR of the synthetic bars is ~0.0016-0.003)
        self.assertGreater(risk, 0.8 * 0.0010)

    def test_duplicate_window_is_noop(self):
        closes = _drift_series()
        strat = GyroscopeStrategy(CFG, _NullLogger())
        first = None
        for end in range(60, len(closes) + 1):
            df = _bars(closes[:end])
            d = _run(strat, df)
            if d is not None:
                first = (df, d)
                break
        self.assertIsNotNone(first)
        df, _ = first
        self.assertIsNone(_run(strat, df), "same window re-fed must be a no-op")

    def test_older_window_leaves_state_untouched(self):
        # T4-review Important: a strictly-OLDER window (newest ts < last fed)
        # must not overwrite _last_ts — otherwise the next legitimate window
        # would re-feed already-seen bars into the filter (state corruption).
        closes = _drift_series(n_flat=100, n_drift=0)
        strat = GyroscopeStrategy(CFG, _NullLogger())
        full = _bars(closes)                       # bootstrap: bars 0..99
        self.assertIsNone(_run(strat, full))       # flat noise -> no signal
        newest = str(full["time"].iloc[-1])
        self.assertEqual(strat._last_ts["EURUSD"], newest)

        stale = _bars(closes[:95])                 # strictly older window
        self.assertIsNone(_run(strat, stale))
        self.assertEqual(strat._last_ts["EURUSD"], newest,
                         "stale window must not rewind _last_ts")

    def test_cooldown_blocks_reentry_for_lockout_bars(self):
        closes = _drift_series(n_drift=200)  # long drift: crossings keep coming
        strat = GyroscopeStrategy(CFG, _NullLogger())
        signal_ends = []
        for end in range(60, len(closes) + 1):
            if _run(strat, _bars(closes[:end])) is not None:
                signal_ends.append(end)
        self.assertGreaterEqual(len(signal_ends), 1)
        for a, b in zip(signal_ends, signal_ends[1:]):
            self.assertGreater(b - a, 5, "re-entry inside reentry_lockout")

    def test_wide_spread_blocks_entry(self):
        closes = _drift_series()
        strat = GyroscopeStrategy(CFG, _NullLogger())
        got_none_on_spread = False
        for end in range(60, len(closes) + 1):
            ctx = {"symbol": "EURUSD", "spread": 1.0}  # absurd spread >> 0.10*ATR
            if _run(strat, _bars(closes[:end]), ctx) is not None:
                self.fail("signal emitted despite spread screen")
            got_none_on_spread = True
        self.assertTrue(got_none_on_spread)


if __name__ == "__main__":
    unittest.main()
