"""Chronological IS/OOS split with purge + embargo (spec §2.1, §4.3).

The cut is a CALENDAR DATE, not a row index: splitting on row count lets a
symbol with denser signals dominate the training period.
"""
import numpy as np
import pandas as pd

from scripts.confidence_screen import EMBARGO_BUFFER_BARS, H_BARS, SPLIT_FRAC


def split_masks(times, symbols, frac=SPLIT_FRAC, horizon_bars=H_BARS,
                buffer_bars=EMBARGO_BUFFER_BARS, bar_minutes=60):
    times = np.asarray(times, dtype="datetime64[ns]")
    cut = np.quantile(times.astype("int64"), frac).astype("int64")
    cut_time = np.array(cut).astype("datetime64[ns]")

    band = np.timedelta64(int((horizon_bars + buffer_bars) * bar_minutes), "m")
    purged = (times > cut_time - band) & (times <= cut_time)
    is_mask = (times <= cut_time) & ~purged
    oos_mask = times > cut_time
    return {"cut_time": cut_time, "is_mask": is_mask,
            "oos_mask": oos_mask, "purged_mask": purged}


def week_clusters(times):
    """ISO year-week label per signal — the bootstrap block, shared by all
    symbols so cross-sectional dependence is preserved."""
    idx = pd.DatetimeIndex(pd.to_datetime(times))
    iso = idx.isocalendar()
    return np.array([f"{y}-W{w:02d}" for y, w in zip(iso.year, iso.week)])
