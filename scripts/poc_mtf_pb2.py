#!/usr/bin/env python3
# scripts/poc_mtf_pb2.py
# MTF trend-pullback v2 PoC. H4+H1 BOS bias -> M15 OTE(0.62-0.79) pullback -> liquidity
# sweep -> M5 MSS -> entry-TF pressure -> OTE n HTF-POI confluence -> two entry models,
# two exit models. Screens net-of-cost + slippage, OOS edge, per asset class. NOT a live
# strategy. Spec: docs/superpowers/specs/2026-05-30-mtf-trend-pullback-v2-design.md
import bisect
import os
import random as _random
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


def median_range(bars, end, window=20):
    """Median high-low range over the `window` bars before index `end`."""
    seg = bars[max(0, end - window):end]
    rngs = sorted(b["high"] - b["low"] for b in seg)
    if not rngs:
        return 0.0
    mid = len(rngs) // 2
    return rngs[mid] if len(rngs) % 2 else (rngs[mid - 1] + rngs[mid]) / 2.0


def is_displacement(bar, med_range, bias, body_frac=0.60, range_mult=1.0):
    """Strong momentum candle: body >= body_frac of range AND range >= range_mult*median,
    closing in the trend direction."""
    rng = bar["high"] - bar["low"]
    if rng <= 0 or abs(bar["close"] - bar["open"]) < body_frac * rng:
        return False
    if rng < range_mult * med_range:
        return False
    return bar["close"] > bar["open"] if bias == "BULLISH" else bar["close"] < bar["open"]


def pressure_ok(bars, highs, lows, closes, i, bias, lk=2, window=20):
    """(A) a displacement FVG left by the resumption impulse ending at/just before i, OR
    (B) a micro-BOS (M5 CHoCH) accompanied by a displacement candle at i."""
    if find_fvg(bars, i, bias) or (i >= 3 and find_fvg(bars, i - 1, bias)):
        return True
    bos, _ = mss_confirm(highs, lows, closes, i, bias, lk)
    return bool(bos) and is_displacement(bars[i], median_range(bars, i, window), bias)


def htf_pois(htf, upto_idx, bias, lk=3):
    """POI price bands visible by upto_idx: trend-dir FVG gaps + confirmed swing-candle
    ranges. Returns a list of (lo, hi)."""
    bars = htf[["open", "high", "low", "close"]].to_dict("records")[:upto_idx + 1]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    pois = []
    for j in range(2, len(bars)):
        g = find_fvg(bars, j, bias)
        if g:
            pois.append(g)
    his, los = confirmed_swing_seq(highs, lows, lk)
    for j in his + los:
        pois.append((bars[j]["low"], bars[j]["high"]))
    return pois


def htf_poi_overlap(zone, h1, h4, t, bias, lk=3):
    """True if the OTE zone intersects any H1/H4 POI band (closed bars only at time t)."""
    z_lo, z_hi = zone
    for htf, hours in ((h1, 1), (h4, 4)):
        times = list(pd.to_datetime(htf["time"]))
        close_times = [tt + pd.Timedelta(hours=hours) for tt in times]
        idx = bisect.bisect_right(close_times, t) - 1
        if idx < 0:
            continue
        for lo, hi in htf_pois(htf, idx, bias, lk):
            if _overlap(z_lo, z_hi, lo, hi) > 0:
                return True
    return False


def conditional_stop(bias, leg_low, leg_high, qfvg, fully_swept, sweep_extreme, mss_level):
    """The M5-structure stop level per the spec's decision table:
      - qualifying FVG present, NOT fully swept -> OTE leg origin
      - qualifying FVG present, fully swept     -> swept extreme
      - no qualifying FVG                       -> M5 MSS swing level"""
    if qfvg is not None and not fully_swept:
        return leg_low if bias == "BULLISH" else leg_high
    elif qfvg is not None:
        return sweep_extreme
    return mss_level


def simulate_managed(sigs, bars, partial_frac=0.33):
    """Exit model: TP1 -> book partial_frac + stop to break-even, then trail the runner to
    each new M5 higher-low (bull)/lower-high (bear) (active AFTER TP1), final target TP2.
    Runner closes at trail-stop or TP2, whichever first. One open position per symbol.
    Same-bar stop+target -> stop wins. Returns trade dicts with blended R + outcome."""
    trades = []
    busy_until = -1
    n = len(bars)
    for sig in sigs:
        b0 = sig["bar_idx"]
        if b0 <= busy_until or b0 >= n:
            continue
        is_long = sig["dir"] == "BUY"
        E, S, risk = sig["entry"], sig["sl"], sig["risk"]
        tp1, tp2 = sig["tp1"], sig["tp2"]
        partialed = False
        stop = S
        last_extreme_swing = None          # running higher-low (bull) / lower-high (bear)
        prev_low, prev_high = bars[b0]["low"], bars[b0]["high"]
        r_total, exit_idx = None, b0
        for j in range(b0, n):
            bar = bars[j]
            stop_hit = (bar["low"] <= stop) if is_long else (bar["high"] >= stop)
            if stop_hit:
                ex = (stop - E) / risk if is_long else (E - stop) / risk
                r_total = (partial_frac * 1.0 + (1 - partial_frac) * ex) if partialed else ex
                exit_idx = j
                break
            if not partialed:
                if (bar["high"] >= tp1) if is_long else (bar["low"] <= tp1):
                    partialed = True
                    stop = E                # break-even on the runner
            else:
                tp2_hit = (bar["high"] >= tp2) if is_long else (bar["low"] <= tp2)
                if tp2_hit:
                    ex = (tp2 - E) / risk if is_long else (E - tp2) / risk
                    r_total = partial_frac * 1.0 + (1 - partial_frac) * ex
                    exit_idx = j
                    break
                # structural trail: ratchet to the latest confirmed M5 swing extreme
                if is_long and bar["low"] > prev_low and last_extreme_swing is not None:
                    stop = max(stop, last_extreme_swing)
                if (not is_long) and bar["high"] < prev_high and last_extreme_swing is not None:
                    stop = min(stop, last_extreme_swing)
                last_extreme_swing = prev_low if is_long else prev_high
            prev_low, prev_high = bar["low"], bar["high"]
        if r_total is None:                 # open at end -> mark out at last close
            px = bars[n - 1]["close"]
            ex = (px - E) / risk if is_long else (E - px) / risk
            r_total = (partial_frac * 1.0 + (1 - partial_frac) * ex) if partialed else ex
            exit_idx = n - 1
        trades.append({**sig, "r": r_total, "entry_idx": b0, "exit_idx": exit_idx,
                       "outcome": "TP" if r_total > 0 else "SL"})
        busy_until = exit_idx
    return trades


def mae_mfe(sig, bars):
    """Max adverse / favorable excursion in R over the trade's life [entry_idx..exit_idx]."""
    is_long = sig["dir"] == "BUY"
    E, risk = sig["entry"], sig["risk"]
    seg = bars[sig["entry_idx"]:sig["exit_idx"] + 1]
    if not seg or risk <= 0:
        return (0.0, 0.0)
    if is_long:
        mae = (min(b["low"] for b in seg) - E) / risk
        mfe = (max(b["high"] for b in seg) - E) / risk
    else:
        mae = (E - max(b["high"] for b in seg)) / risk
        mfe = (E - min(b["low"] for b in seg)) / risk
    return (mae, mfe)


def bootstrap_expectancy_ci(rs, n_boot=2000, alpha=0.05, seed=0):
    """Percentile bootstrap CI for mean R. Deterministic given seed."""
    if not rs:
        return (0.0, 0.0)
    rng = _random.Random(seed)
    n = len(rs)
    means = []
    for _ in range(n_boot):
        s = sum(rs[rng.randrange(n)] for _ in range(n))
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return (lo, hi)


def net_with_slippage(trades, sym, slip_frac=0.05, comm_rt=14.0):
    """Like poc_trend_h4._net but adds a slippage charge (slip_frac of the stop, in R) on
    top of the 2x spread + commission. slip_frac already expressed as a fraction of 1R."""
    import json
    sp = tp.SPREAD.get(sym, 0.0002)
    specs = json.load(open("data/specs.json")) if os.path.exists("data/specs.json") else {}
    spec = specs.get(sym, {"tick_size": 1e-5, "tick_value": 1.0})
    for t in trades:
        base = tp.net_r_after_costs(t["r"], t["entry"], t["sl"], sp,
                                    spec["tick_size"], spec["tick_value"], comm_rt)
        t["r"] = base - slip_frac      # slippage already expressed as a fraction of 1R
        t["outcome"] = "TP" if t["r"] > 0 else "SL"
    return trades
