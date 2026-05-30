#!/usr/bin/env python3
# scripts/poc_mtf_pb2.py
# MTF trend-pullback v2 PoC. H4+H1 BOS bias -> M15 OTE(0.62-0.79) pullback -> liquidity
# sweep -> M5 MSS -> entry-TF pressure -> OTE n HTF-POI confluence -> two entry models,
# two exit models. Screens net-of-cost + slippage, OOS edge, per asset class. NOT a live
# strategy. Spec: docs/superpowers/specs/2026-05-30-mtf-trend-pullback-v2-design.md
import bisect
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
                                "tests", "backtest"))
import backtest_engine as bt                       # noqa: E402
from scripts import poc_trend_h4 as tp             # noqa: E402
from scripts.poc_mtf_pb import (                   # noqa: E402  (reuse generic helpers)
    resample_tf, last_closed_indexer, combine_bias_lists, _is_swing_high, _is_swing_low,
)


def confirmed_swing_seq(highs, lows, lk):
    """Positions of confirmed swing highs / swing lows (each needs lk bars either side)."""
    n = len(highs)
    his = [j for j in range(lk, n - lk) if _is_swing_high(highs, j, lk)]
    los = [j for j in range(lk, n - lk) if _is_swing_low(lows, j, lk)]
    return his, los


def structure_bias(df, lk=3):
    """Per-bar BOS bias. BULLISH when the last two confirmed swing highs are higher-high
    AND the last two confirmed swing lows are higher-low; BEARISH on the mirror; else
    NEUTRAL. A swing at j is only 'confirmed' from bar j+lk on (no look-ahead)."""
    highs = list(df["high"].values)
    lows = list(df["low"].values)
    n = len(highs)
    his, los = confirmed_swing_seq(highs, lows, lk)
    cl_h = [j + lk for j in his]   # confirmation bar of each swing high
    cl_l = [j + lk for j in los]
    out = []
    hp = lp = 0
    for i in range(n):
        while hp < len(cl_h) and cl_h[hp] <= i:
            hp += 1
        while lp < len(cl_l) and cl_l[lp] <= i:
            lp += 1
        if hp >= 2 and lp >= 2:
            hh = highs[his[hp - 1]] > highs[his[hp - 2]]
            hl = lows[los[lp - 1]] > lows[los[lp - 2]]
            lh = highs[his[hp - 1]] < highs[his[hp - 2]]
            ll = lows[los[lp - 1]] < lows[los[lp - 2]]
            out.append("BULLISH" if (hh and hl) else "BEARISH" if (lh and ll) else "NEUTRAL")
        else:
            out.append("NEUTRAL")
    return out


def combined_structure_bias(m5_df, h4, h1, lk=3):
    """Per-5m-bar combined H4+H1 BOS bias, using only closed HTF bars (no look-ahead).
    Reuses v1's last_closed_indexer + combine_bias_lists."""
    tcol = "time" if "time" in m5_df.columns else "datetime"
    m5t = list(pd.to_datetime(m5_df[tcol]))
    idx4 = last_closed_indexer(m5t, list(pd.to_datetime(h4["time"])), 4)
    idx1 = last_closed_indexer(m5t, list(pd.to_datetime(h1["time"])), 1)
    return combine_bias_lists(structure_bias(h4, lk), structure_bias(h1, lk), idx4, idx1)
