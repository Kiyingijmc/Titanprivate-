"""Almanac turn-of-month canary -- strategy contract tests.

The strategy is H1-routed with an internal calendar gate: it emits one BUY
MARKET decision per symbol per month, on the first H1 close at/after
`entry_hour` (broker time) of the month's last trading day. Stop is
stop_atr_d1 x ATR(atr_period_d1, D1) resampled from the H1 window; TP is a
far anchor (tp_risk_mult x risk) that keeps the ratchet dormant in practice
while avoiding a tp=0 registration.
"""
import asyncio
import unittest
from datetime import datetime, timedelta

import pandas as pd

from src.strategies.models.almanac import Almanac


class _Logger:
    def log_event(self, *a, **k):
        pass


def make_h1_df(end, bars=420, price=40000.0, step=25.0):
    """Synthetic H1 frame ending exactly at `end` (a datetime, bar open time).
    Gives every daily resample a ~600-point range so ATR is stable and known.
    """
    times = [end - timedelta(hours=i) for i in range(bars - 1, -1, -1)]
    rows = []
    for t in times:
        base = price + (t.hour - 12) * step
        rows.append({
            "time": t.strftime("%Y-%m-%d %H:%M:%S"),
            "open": base, "high": base + 10.0, "low": base - 10.0,
            "close": base + 5.0, "tick_volume": 100,
        })
    return pd.DataFrame(rows)


def cfg(**over):
    base = {
        "enabled": True, "timeframe": "H1", "entry_hour": 16,
        "stop_atr_d1": 2.0, "atr_period_d1": 14, "tp_risk_mult": 10.0,
    }
    base.update(over)
    return base


def run(coro):
    return asyncio.run(coro)


class TestAlmanacEntry(unittest.TestCase):
    # 2026-07-31 (Friday) is the last trading day of July 2026.
    LAST_TD_16H = datetime(2026, 7, 31, 16, 0, 0)

    def test_fires_buy_on_last_trading_day_at_entry_hour(self):
        s = Almanac(cfg(), _Logger())
        df = make_h1_df(self.LAST_TD_16H)
        d = run(s.on_new_candle(df, {"symbol": "US30"}))
        self.assertIsNotNone(d)
        self.assertEqual(d["signal"], "BUY")
        self.assertEqual(d["type"], "MARKET")
        price, sl, tp = d["price"], d["sl"], d["tp"]
        self.assertLess(sl, price)
        self.assertGreater(tp, price)
        # tp anchored at tp_risk_mult x risk
        self.assertAlmostEqual(tp - price, 10.0 * (price - sl), places=6)

    def test_no_signal_mid_month(self):
        s = Almanac(cfg(), _Logger())
        df = make_h1_df(datetime(2026, 7, 15, 16, 0, 0))
        self.assertIsNone(run(s.on_new_candle(df, {"symbol": "US30"})))

    def test_no_signal_before_entry_hour(self):
        s = Almanac(cfg(), _Logger())
        df = make_h1_df(datetime(2026, 7, 31, 9, 0, 0))
        self.assertIsNone(run(s.on_new_candle(df, {"symbol": "US30"})))

    def test_one_entry_per_symbol_per_month(self):
        s = Almanac(cfg(), _Logger())
        first = run(s.on_new_candle(make_h1_df(self.LAST_TD_16H), {"symbol": "US30"}))
        self.assertIsNotNone(first)
        again = run(s.on_new_candle(
            make_h1_df(self.LAST_TD_16H + timedelta(hours=1)), {"symbol": "US30"}))
        self.assertIsNone(again)

    def test_dedup_is_per_symbol(self):
        s = Almanac(cfg(), _Logger())
        self.assertIsNotNone(
            run(s.on_new_candle(make_h1_df(self.LAST_TD_16H), {"symbol": "US30"})))
        self.assertIsNotNone(
            run(s.on_new_candle(make_h1_df(self.LAST_TD_16H), {"symbol": "US100"})))

    def test_insufficient_history_no_signal(self):
        s = Almanac(cfg(), _Logger())
        df = make_h1_df(self.LAST_TD_16H, bars=48)  # two days of H1
        self.assertIsNone(run(s.on_new_candle(df, {"symbol": "US30"})))

    def test_next_month_window_fires_again(self):
        s = Almanac(cfg(), _Logger())
        self.assertIsNotNone(
            run(s.on_new_candle(make_h1_df(self.LAST_TD_16H), {"symbol": "US30"})))
        # 2026-08-31 (Monday) is the last trading day of August 2026.
        aug = datetime(2026, 8, 31, 16, 0, 0)
        self.assertIsNotNone(
            run(s.on_new_candle(make_h1_df(aug), {"symbol": "US30"})))

    def test_stop_uses_daily_atr(self):
        s = Almanac(cfg(), _Logger())
        df = make_h1_df(self.LAST_TD_16H)
        d = run(s.on_new_candle(df, {"symbol": "US30"}))
        risk = d["price"] - d["sl"]
        # Synthetic daily range: hours 0..23 -> base spans 12*25*2 = 600 plus
        # the 20-point wick band; completed-day TR is ~620. Stop = 2 x ATR.
        self.assertGreater(risk, 1000.0)
        self.assertLess(risk, 1400.0)


if __name__ == "__main__":
    unittest.main()
