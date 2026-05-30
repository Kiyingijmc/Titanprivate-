# scripts/poc_mtf_pb.py
#!/usr/bin/env python3
# MTF trend-pullback proof-of-concept. 4H+1H 50-EMA bias -> 5m fib(0.5-0.705) pullback
# + confirmation-close entry -> 1.0xATR(1H) structural stop -> two exit models
# (fixed-2.5R, partial-at-1R+ATR-trail). Screens net-of-cost, OOS edge across asset
# classes. NOT a live strategy. See docs/superpowers/specs/2026-05-30-mtf-trend-pullback-poc-design.md
import bisect
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
                                "tests", "backtest"))
import backtest_engine as bt          # noqa: E402
from scripts import poc_trend_h4 as tp # noqa: E402


def resample_tf(m5_df, rule):
    """Resample M5 OHLC to a higher timeframe ('4h','1h','15min'). Returns a df with a
    'time' column (bar-open timestamp) + open/high/low/close. Bars are label='left'
    (pandas default): a 4h bar stamped 00:00 spans 00:00-03:59 and CLOSES at 04:00."""
    df = m5_df.copy()
    tcol = "time" if "time" in df.columns else "datetime"
    df["time"] = pd.to_datetime(df[tcol])
    df = df.set_index("time")
    r = df.resample(rule).agg({"open": "first", "high": "max",
                               "low": "min", "close": "last"}).dropna()
    return r.reset_index()
