# tests/unit/test_export_history_http.py
import os, sys, unittest
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import export_history as eh
from src.execution.broker import types as T


class FakeBroker:
    """Returns candles for the most-recent window only; older windows are empty (history floor)."""
    def __init__(self, newest_from):
        self.newest_from = newest_from
        self.calls = []
    async def get_candles_range(self, symbol, tf, from_dt, to_dt):
        self.calls.append((from_dt, to_dt))
        if from_dt >= self.newest_from:
            t = from_dt
            out = []
            while t < to_dt:
                out.append(T.Candle(time=t, open=1, high=2, low=0.5, close=1.5,
                                    tick_volume=1, spread_points=1))
                t += timedelta(minutes=5)
            return out
        return []   # no more history


class Export(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_pull_stops_at_empty_window(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        fb = FakeBroker(newest_from=now - timedelta(days=30))
        bars = await eh.pull_history(fb, "XAUUSD", T.Timeframe.M5, now=now,
                                     max_lookback=timedelta(days=90), chunk=timedelta(days=30))
        self.assertGreater(len(bars), 0)
        times = [b.time for b in bars]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

    def test_csv_text_format_matches_legacy(self):
        c = T.Candle(time=datetime(2026,1,1,0,5,tzinfo=timezone.utc), open=1.1, high=1.2,
                     low=1.0, close=1.15, tick_volume=1, spread_points=1)
        txt = eh.candles_to_csv([c])
        self.assertEqual(txt.splitlines()[0], "datetime,open,high,low,close")
        self.assertEqual(txt.splitlines()[1], "2026-01-01 00:05:00,1.1,1.2,1.0,1.15")


if __name__ == "__main__":
    unittest.main()
