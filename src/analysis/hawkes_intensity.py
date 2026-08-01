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
