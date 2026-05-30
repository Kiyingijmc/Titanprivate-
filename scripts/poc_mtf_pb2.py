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


def impulse_leg(highs, lows, upto, lk, bias):
    """Most recent leg in bias dir that BROKE the prior swing, using bars [0..upto].
    BULL: a confirmed swing high exceeding the previous confirmed swing high (BOS up);
    origin = most recent confirmed swing low before it. Returns
    (leg_low, leg_high, lo_idx, hi_idx) or None."""
    if bias not in ("BULLISH", "BEARISH"):
        return None
    h = highs[:upto + 1]
    l = lows[:upto + 1]
    his, los = confirmed_swing_seq(h, l, lk)
    if bias == "BULLISH":
        for k in range(len(his) - 1, 0, -1):
            if highs[his[k]] > highs[his[k - 1]]:                 # BOS up
                hi = his[k]
                befs = [j for j in los if j < hi]
                if befs:
                    lo = befs[-1]
                    return (lows[lo], highs[hi], lo, hi)
        return None
    for k in range(len(los) - 1, 0, -1):
        if lows[los[k]] < lows[los[k - 1]]:                       # BOS down
            lo = los[k]
            befs = [j for j in his if j < lo]
            if befs:
                hi = befs[-1]
                return (lows[lo], highs[hi], lo, hi)
    return None


def ote_zone(leg_low, leg_high, bias, lo=0.62, hi=0.79):
    """Golden-zone price band (z_lo, z_hi). BULL: measured down from the high."""
    rng = leg_high - leg_low
    if bias == "BULLISH":
        return (leg_high - hi * rng, leg_high - lo * rng)
    return (leg_low + lo * rng, leg_low + hi * rng)


def find_fvg(bars, j, bias):
    """3-candle imbalance ending at index j. BULL gap = (c1.high, c3.low) when c1.high <
    c3.low; BEAR gap = (c3.high, c1.low) when c1.low > c3.high. Returns (lo, hi) or None."""
    if j < 2:
        return None
    c1, c3 = bars[j - 2], bars[j]
    if bias == "BULLISH" and c1["high"] < c3["low"]:
        return (c1["high"], c3["low"])
    if bias == "BEARISH" and c1["low"] > c3["high"]:
        return (c3["high"], c1["low"])
    return None


def _overlap(a_lo, a_hi, b_lo, b_hi):
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def qualifying_fvg(leg_bars, zone, bias, min_frac=0.30):
    """First FVG within the leg whose body is >=min_frac inside the golden zone, or lies
    entirely within it. zone=(z_lo,z_hi). Returns (lo,hi) or None."""
    z_lo, z_hi = zone
    for j in range(2, len(leg_bars)):
        g = find_fvg(leg_bars, j, bias)
        if not g:
            continue
        g_lo, g_hi = g
        size = g_hi - g_lo
        if size <= 0:
            continue
        entirely = g_lo >= z_lo and g_hi <= z_hi
        if entirely or _overlap(g_lo, g_hi, z_lo, z_hi) / size >= min_frac:
            return g
    return None


def swept_liquidity(lows, highs, start, end, bias, lk=2):
    """Did the pullback (bars start..end) take out a prior confirmed minor swing?
    BULL: a later bar's low breaches an earlier confirmed swing low. Returns
    (swept_bool, sweep_extreme) where sweep_extreme is the breach low (bull)/high (bear)."""
    sub_h = highs[start:end + 1]
    sub_l = lows[start:end + 1]
    his, los = confirmed_swing_seq(sub_h, sub_l, lk)
    if bias == "BULLISH":
        for li in los:
            after = sub_l[li + lk + 1:]
            if after and min(after) < sub_l[li]:
                return (True, min(after))
        return (False, None)
    for hi in his:
        after = sub_h[hi + lk + 1:]
        if after and max(after) > sub_h[hi]:
            return (True, max(after))
    return (False, None)


def mss_confirm(highs, lows, closes, i, bias, lk=2):
    """M5 CHoCH at bar i in the trend direction. BULL: close[i] > the most recent confirmed
    swing high before i. Returns (confirmed, mss_level) where mss_level is the swing low
    (bull) / swing high (bear) the shift breaks away from -- used by the no-FVG stop."""
    his, los = confirmed_swing_seq(highs[:i], lows[:i], lk)
    if bias == "BULLISH":
        cand = [j for j in his if j + lk < i]
        if not cand:
            return (False, None)
        sh = cand[-1]
        if closes[i] > highs[sh]:
            after = [j for j in los if j > sh and j + lk < i]
            return (True, lows[after[-1]] if after else lows[sh])
        return (False, None)
    cand = [j for j in los if j + lk < i]
    if not cand:
        return (False, None)
    sl = cand[-1]
    if closes[i] < lows[sl]:
        after = [j for j in his if j > sl and j + lk < i]
        return (True, highs[after[-1]] if after else highs[sl])
    return (False, None)
