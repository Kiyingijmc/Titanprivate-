# tests/unit/test_ma_slope_baseline.py
# Plan 07 / Task 5: the naive competitor Gyroscope must beat (gate criterion 6).
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from src.strategies.models.ma_slope_baseline import MaSlopeBaseline

CFG = {"enabled": True, "timeframe": "H1", "ma_window": 4,
       "stop_atr": 1.0, "rr_target": 2.0}


class _NullLogger:
    def log_event(self, *a, **k):
        pass


def _bars(closes):
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    return pd.DataFrame([
        {"time": str(t0 + pd.Timedelta(hours=k)), "open": c,
         "high": c + 0.001, "low": c - 0.001, "close": c}
        for k, c in enumerate(closes)
    ])


def _run(strat, df):
    return asyncio.run(strat.on_new_candle(df, context={"symbol": "EURUSD"}))


class TestMaSlopeBaseline(unittest.TestCase):
    def test_uptrend_flip_emits_market_buy_once(self):
        strat = MaSlopeBaseline(CFG, _NullLogger())
        closes = [1.0] * 8 + [1.0 + 0.002 * k for k in range(1, 8)]
        decisions = []
        for end in range(6, len(closes) + 1):
            d = _run(strat, _bars(closes[:end]))
            if d:
                decisions.append(d)
        self.assertEqual(len(decisions), 1, "slope sign flip must fire exactly once")
        d = decisions[0]
        self.assertEqual(d["signal"], "BUY")
        self.assertEqual(d["type"], "MARKET")
        risk = d["price"] - d["sl"]
        self.assertGreater(risk, 0)
        self.assertAlmostEqual(d["tp"] - d["price"], 2.0 * risk, places=9)

    def test_downtrend_flip_emits_sell(self):
        strat = MaSlopeBaseline(CFG, _NullLogger())
        closes = [1.0] * 8 + [1.0 - 0.002 * k for k in range(1, 8)]
        decisions = [d for end in range(6, len(closes) + 1)
                     if (d := _run(strat, _bars(closes[:end])))]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["signal"], "SELL")
        self.assertGreater(decisions[0]["sl"], decisions[0]["price"])

    def test_short_window_returns_none(self):
        strat = MaSlopeBaseline(CFG, _NullLogger())
        self.assertIsNone(_run(strat, _bars([1.0, 1.0, 1.0])))


if __name__ == "__main__":
    unittest.main()
