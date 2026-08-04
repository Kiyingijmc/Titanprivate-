"""The frozen candidate panel (spec §3.2) — 8 features plus 2 placebos.

Strict causality: build_features() receives the FULL H1 arrays and slices to
sig['bar_idx'] itself. Never pass pre-truncated arrays — that makes the
look-ahead test vacuous, which is the whole point of it.

Features 4, 7 and 8 are sign-oriented to the signal direction so that
"higher = more favourable to this trade" holds uniformly.
"""
import hashlib

import numpy as np

from scripts.confidence_screen import NY_SHIFT, SEED

FEATURE_SPECS = {
    "f1_atr_pct": "continuous",
    "f2_atr_ratio": "continuous",
    "f3_efficiency": "continuous",
    "f4_prev_day_dist": "continuous",
    "f5_session": "categorical",
    "f6_h4_agree": "binary",
    "f7_range_pos": "continuous",
    "f8_ret_vol": "continuous",
}
PLACEBO_NAMES = ("placebo_a", "placebo_b")

_SESSIONS = (("LONDON", 2, 7), ("NY_AM", 7, 12), ("NY_PM", 12, 17))


def _session(broker_hour):
    ny = (int(broker_hour) + NY_SHIFT) % 24
    for name, lo, hi in _SESSIONS:
        if lo <= ny < hi:
            return name
    return "ASIA"


def _placebo(sig, salt, seed):
    key = f"{seed}:{salt}:{sig['symbol']}:{sig['bar_idx']}:{sig['time']}"
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def build_features(sig, h1, seed=SEED, h4_bias=None):
    i = int(sig["bar_idx"])
    hi = h1["high"][:i + 1]
    lo = h1["low"][:i + 1]
    close = h1["close"][:i + 1]
    open_ = h1["open"][:i + 1]
    atr = h1["atr"][:i + 1]
    risk = float(sig["risk"])
    is_long = sig["dir"] == "BUY"

    # f1: ATR percentile within the trailing 250 closed bars
    win = atr[-250:]
    f1 = float((win <= atr[-1]).sum()) / float(len(win))

    # f2: ATR(10)/ATR(50)
    f2 = float(atr[-10:].mean() / atr[-50:].mean())

    # f3: Kaufman efficiency ratio over 20 bars
    seg = close[-21:]
    path = float(np.abs(np.diff(seg)).sum())
    f3 = float(abs(seg[-1] - seg[0]) / path) if path > 0 else 0.0

    # f4: signed distance to the nearer previous-completed-day extreme, in R
    day_len = 24
    prev_day = slice(max(0, len(close) - 2 * day_len), max(0, len(close) - day_len))
    if len(close[prev_day]) == 0:
        f4 = 0.0
    else:
        pdh, pdl = float(hi[prev_day].max()), float(lo[prev_day].min())
        entry = float(sig["entry"])
        raw = min(abs(entry - pdh), abs(entry - pdl)) / risk
        f4 = raw if is_long else -raw

    f5 = _session(sig["hour"])

    # f6: H1 vs last-closed-H4 bias agreement (injectable for tests)
    f6 = 0 if h4_bias is None else int(h4_bias == sig["bias"])

    # f7: position in the trailing 20-bar range, oriented
    r_hi, r_lo = float(hi[-20:].max()), float(lo[-20:].min())
    raw = (float(sig["entry"]) - r_lo) / (r_hi - r_lo) if r_hi > r_lo else 0.5
    f7 = (1.0 - raw) if is_long else raw

    # f8: signal-bar return over trailing realized vol, oriented
    rets = np.diff(close[-21:])
    sd = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    bar_ret = float(close[-1] - open_[-1])
    raw = (bar_ret / sd) if sd > 0 else 0.0
    f8 = raw if is_long else -raw

    out = {"f1_atr_pct": f1, "f2_atr_ratio": f2, "f3_efficiency": f3,
           "f4_prev_day_dist": f4, "f5_session": f5, "f6_h4_agree": f6,
           "f7_range_pos": f7, "f8_ret_vol": f8}
    for salt, name in zip(("a", "b"), PLACEBO_NAMES):
        out[name] = _placebo(sig, salt, seed)
    return out
