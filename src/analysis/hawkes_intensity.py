"""Scale-invariant Hawkes-style excitation for the Aftershock kill-screen.

Registered contract: docs/research/2026-08-01-wave2-gate-triage.md.
Pure functions over OHLC frames — no strategy class, no live-path code,
no MLE fitting (the screen's banding is percentile-based and therefore
invariant to intensity scale; only the decay half-life matters).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """TR_t = max(high, prev_close) - min(low, prev_close); TR_0 = high - low."""
    prev_close = df["close"].shift(1)
    hi = pd.concat([df["high"], prev_close], axis=1).max(axis=1)
    lo = pd.concat([df["low"], prev_close], axis=1).min(axis=1)
    tr = hi - lo
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def flag_events(df: pd.DataFrame, q: float = 2.5, window: int = 200) -> pd.DataFrame:
    """Event flags per the registered protocol (trailing median excludes bar t)."""
    tr = true_range(df)
    tr_med = tr.shift(1).rolling(window).median()
    is_event = (tr > q * tr_med) & tr_med.notna()
    direction = np.sign(df["close"] - df["open"]).astype("int8")
    mid = (df["high"] + df["low"]) / 2.0
    beyond = ((direction == 1) & (df["close"] > mid)) | (
        (direction == -1) & (df["close"] < mid)
    )
    return pd.DataFrame(
        {
            "tr": tr,
            "tr_med": tr_med,
            "is_event": is_event.fillna(False),
            "event_dir": direction,
            "closes_beyond_mid": beyond,
        },
        index=df.index,
    )


def excitation(is_event: pd.Series, half_life: int = 24) -> pd.Series:
    """S-minus: excitation just BEFORE each bar (never includes the bar's own event).

    S_0 = 0; S_t = (S_{t-1} + 1{event at t-1}) * decay, decay = exp(-ln2/half_life).
    """
    decay = math.exp(-math.log(2.0) / half_life)
    ev = is_event.to_numpy(dtype=np.float64)
    out = np.zeros(len(ev))
    for t in range(1, len(ev)):
        out[t] = (out[t - 1] + ev[t - 1]) * decay
    return pd.Series(out, index=is_event.index)


def s_lo_threshold(s_minus: pd.Series, warmup: int = 200, pctile: float = 20.0) -> float:
    """Registered banding: percentile of S-minus over all bars with index >= warmup."""
    pop = s_minus.iloc[warmup:]
    return float(np.percentile(pop.to_numpy(), pctile))


def eligible_signals(
    df: pd.DataFrame,
    q: float = 2.5,
    window: int = 200,
    half_life: int = 24,
    s_lo_pctile: float = 20.0,
) -> pd.DataFrame:
    """Continuation-eligible events per the registered protocol.

    Eligible at t: event & dir != 0 & closes_beyond_mid & S-minus < s_lo
    & confirm at t+1 (close_{t+1} stays beyond the event bar's midpoint
    in the event direction). Signal time is t+1.
    """
    flags = flag_events(df, q=q, window=window)
    s_minus = excitation(flags["is_event"], half_life=half_life)
    s_lo = s_lo_threshold(s_minus, warmup=window, pctile=s_lo_pctile)

    mid = (df["high"] + df["low"]) / 2.0
    next_close = df["close"].shift(-1)
    confirm = ((flags["event_dir"] == 1) & (next_close > mid)) | (
        (flags["event_dir"] == -1) & (next_close < mid)
    )
    ok = (
        flags["is_event"]
        & (flags["event_dir"] != 0)
        & flags["closes_beyond_mid"]
        & (s_minus < s_lo)
        & confirm.fillna(False)
    )
    idx = np.flatnonzero(ok.to_numpy())
    hours = (
        pd.to_datetime(df["time"]).dt.hour.to_numpy()[idx]
        if "time" in df.columns
        else np.full(len(idx), -1)
    )
    return pd.DataFrame(
        {
            "event_idx": idx,
            "signal_idx": idx + 1,
            "direction": flags["event_dir"].to_numpy()[idx],
            "event_range": (df["high"] - df["low"]).to_numpy()[idx],
            "s_minus": s_minus.to_numpy()[idx],
            "hour": hours,
        }
    )
