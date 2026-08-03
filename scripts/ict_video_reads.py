# scripts/ict_video_reads.py
# A1 (session buckets) + A2 (bias agreement) conditioning reads.
# Spec: docs/superpowers/specs/2026-08-03-ict-video-rules-design.md
#
# Exploratory reads on FROZEN tables. Both are REPORTED, NOT GATED.
# data/history/ is a read-only symlink into the live tree - never write there.
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.poc_sb_stops import cost_r, wilson              # noqa: E402
from src.analysis.session_time import (                       # noqa: E402
    infer_ny_shift, ny_bucket, KILLZONES, OUTSIDE,
)

TABLE = "data/history/sb_stops_trades_H1.csv"
OUTDIR = "data/results/ict_video_reads"
MODEL = "ATR10"          # NOT "LIVE" - those rows are the deprecated 0.2xATR stop
YEARS = [2023, 2024, 2025, 2026]


def load_atr10():
    """ATR10 trades with per-symbol net R attached."""
    with open("data/specs.json") as f:
        specs = json.load(f)
    df = pd.read_csv(TABLE)
    df = df[df["model"] == MODEL].copy()
    df["time"] = pd.to_datetime(df["time"])
    rows = df.to_dict("records")
    for t in rows:
        t["_net_r"] = t["r"] - cost_r(t, t["sym"], specs)
    return rows


def _stat(rows):
    n = len(rows)
    if n == 0:
        return None
    tot = sum(t["_net_r"] for t in rows)
    wins = sum(1 for t in rows if t["_net_r"] > 0)
    p, lo, hi = wilson(wins, n)
    return {"n": n, "exp": tot / n, "win": p * 100, "lo": lo * 100, "hi": hi * 100}


def a1_session_buckets(rows, shift, out):
    p = out.append
    p("=" * 78)
    p("A1 -- SESSION BUCKETS (Rule 2).  PRE-SPECIFIED, REPORTED NOT GATED.")
    p("=" * 78)
    p(f"broker->NY shift inferred from the weekend seam: +{shift} hours")
    p("(the FX week opens Sunday 17:00 New York; this data has no daily")
    p(" rollover gap to anchor on, so the weekly seam is used instead)")
    p(f"the rig's own NY_SHIFT = -7 is congruent to +{-7 % 24}: "
      f"{'CONFIRMED' if shift == -7 % 24 else 'MISMATCH - investigate'}")
    p("buckets are NY-time, snapped to H1 bar opens:")
    for name, (s, e) in KILLZONES.items():
        p(f"    {name:12} {s:02d}:00-{e:02d}:00 NY")
    p(f"    {OUTSIDE:12} everything else")
    p("canonical ICT quotes 08:30-11:00 / 13:30-16:00; H1 bars cannot")
    p("represent half-hour boundaries, so buckets snap outward.")
    p("")

    for t in rows:
        t["_bucket"] = ny_bucket(t["time"].hour, shift)

    pooled = _stat(rows)
    p(f"  {'POOLED':12} n={pooled['n']:5d}  exp={pooled['exp']:+.3f}R  "
      f"win={pooled['win']:4.1f}% CI[{pooled['lo']:.0f}-{pooled['hi']:.0f}]")
    p("")

    verdicts = []
    for name in list(KILLZONES) + [OUTSIDE]:
        sub = [t for t in rows if t["_bucket"] == name]
        s = _stat(sub)
        if s is None:
            p(f"  {name:12} n=0")
            continue
        sep = s["exp"] - pooled["exp"]
        per_year = []
        for y in YEARS:
            ys = _stat([t for t in sub if t["year"] == y])
            per_year.append((y, ys))
        signs = {(ys["exp"] > 0) for _, ys in per_year if ys and ys["n"] >= 30}
        stable = len(signs) == 1
        interesting = abs(sep) >= 0.10 and stable
        verdicts.append((name, interesting))
        p(f"  {name:12} n={s['n']:5d}  exp={s['exp']:+.3f}R  "
          f"win={s['win']:4.1f}% CI[{s['lo']:.0f}-{s['hi']:.0f}]  "
          f"sep={sep:+.3f}R  {'INTERESTING' if interesting else 'null'}")
        for y, ys in per_year:
            if ys is None:
                p(f"      {y}  n=0")
            else:
                p(f"      {y}  n={ys['n']:4d}  exp={ys['exp']:+.3f}R"
                  f"{'   [n<30, sign ignored]' if ys['n'] < 30 else ''}")
        p("")

    p("VERDICT RULE (declared before the run): a bucket is INTERESTING only if")
    p("  |exp - pooled exp| >= 0.10R AND its own exp holds sign across all")
    p("  years with n>=30. Anything weaker is recorded as null.")
    p(f"RESULT: {[n for n, v in verdicts if v] or 'no bucket separates - null'}")
    p("")


ANCHOR_SYM = "EURUSD"        # FX: metals and indices open an hour later
WEEKEND_GAP = pd.Timedelta(hours=6)


def _week_open_hours(times):
    """Broker-local hour of the first bar after each weekend gap."""
    return list(times[times.diff() > WEEKEND_GAP].dt.hour)


def infer_shift_verified():
    """Derive the broker->NY shift, and VERIFY the anchor assumption.

    Inferred from the underlying BAR series, not the trade series: trades are
    sparse and would not show the seams cleanly. Derived separately per year;
    if the answer moves, the broker does not track NY DST, the anchor is
    invalid, and the run aborts rather than bucketing on a wrong mapping.

    Expected: +17 in every year (measured 2023-2026 during planning).
    """
    bars = pd.read_csv(f"data/history/{ANCHOR_SYM}_M5.csv",
                       usecols=["datetime"])
    bars["datetime"] = pd.to_datetime(bars["datetime"])
    t = bars["datetime"]

    per_year = {}
    for y in sorted(t.dt.year.unique()):
        sub = t[t.dt.year == y]
        hrs = _week_open_hours(sub)
        if len(hrs) < 10:
            continue                      # partial year, too few seams
        per_year[int(y)] = infer_ny_shift(hrs)

    if len(set(per_year.values())) != 1:
        raise ValueError(
            f"broker->NY shift is not stable across years: {per_year}. "
            "The broker does not track NY DST, so the weekend anchor is "
            "invalid. Aborting rather than bucketing on a wrong mapping."
        )
    return infer_ny_shift(_week_open_hours(t)), per_year


def _bias_levels_by_symbol(syms):
    """Per-symbol H1 bias at two lookbacks from ONE algorithm.

    fractal  = structure_bias(lk=5)
    internal = structure_bias(lk=2)

    Returns {sym: (h1_times, fractal_list, internal_list)}. The rig's existing
    `bias` column is BiasEngine's 5-bar fractal - a DIFFERENT algorithm - so it
    is never mixed into the comparison.
    """
    from src.analysis.ict_structure import structure_bias
    out = {}
    for sym in syms:
        path = f"data/history/{sym}_M5.csv"
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df["datetime"] = pd.to_datetime(df["datetime"])
        h1 = (df.set_index("datetime")
                .resample("1h").agg({"open": "first", "high": "max",
                                     "low": "min", "close": "last"})
                .dropna().reset_index())
        highs = list(h1["high"].values)
        lows = list(h1["low"].values)
        out[sym] = (h1["datetime"].values,
                    structure_bias(highs, lows, lk=5),
                    structure_bias(highs, lows, lk=2))
    return out


def a2_bias_agreement(rows, out):
    import numpy as np
    p = out.append
    p("=" * 78)
    p("A2 -- FRACTAL vs INTERNAL BIAS AGREEMENT (Rule 1).")
    p("REPORTED ONLY -- THIS READ CANNOT CARRY A VERDICT.")
    p("=" * 78)
    p("Both levels come from ict_structure.structure_bias: fractal lk=5,")
    p("internal lk=2. The rig's own `bias` column is BiasEngine (a different")
    p("algorithm) and is shown as context only, never mixed in.")
    p("")

    syms = sorted({t["sym"] for t in rows})
    levels = _bias_levels_by_symbol(syms)

    for t in rows:
        t["_fractal"] = t["_internal"] = "NEUTRAL"
        lv = levels.get(t["sym"])
        if lv is None:
            continue
        h1_times, frac, intr = lv
        k = int(np.searchsorted(h1_times, t["time"].to_datetime64())) - 1
        if 0 <= k < len(frac):
            t["_fractal"], t["_internal"] = frac[k], intr[k]

    pooled = _stat(rows)
    agree = [t for t in rows
             if t["_fractal"] == t["_internal"] and t["_fractal"] != "NEUTRAL"]
    disagree = [t for t in rows if t["_fractal"] != t["_internal"]]
    aligned = [t for t in agree
               if (t["dir"] == "BUY" and t["_fractal"] == "BULLISH")
               or (t["dir"] == "SELL" and t["_fractal"] == "BEARISH")]

    for label, sub in [("POOLED", rows), ("AGREE (non-neutral)", agree),
                       ("DISAGREE", disagree), ("AGREE + trade aligned", aligned)]:
        s = _stat(sub)
        if s is None:
            p(f"  {label:24} n=0")
            continue
        p(f"  {label:24} n={s['n']:5d}  exp={s['exp']:+.3f}R  "
          f"win={s['win']:4.1f}% CI[{s['lo']:.0f}-{s['hi']:.0f}]")

    p("")
    p("POWER STATEMENT (declared before the run):")
    p(f"  pooled n={pooled['n']}, agreement subset n={len(agree)}, "
      f"aligned subset n={len(aligned)}.")
    p("  Against a +0.109R base these subsets cannot resolve an increment of")
    p("  the size the grading layer earns (+0.028R). This read is recorded as")
    p("  an OBSERVATION that may motivate a later powered test. It is NOT a")
    p("  gate and no GO/NO-GO may be drawn from it.")
    p("")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    rows = load_atr10()
    shift, per_year = infer_shift_verified()
    print(f"broker->NY shift +{shift}h; per-year check {per_year}")

    out = []
    a1_session_buckets(rows, shift, out)
    text = "\n".join(out)
    print(text)
    with open(f"{OUTDIR}/a1_session_buckets.txt", "w") as f:
        f.write(text + "\n")

    out2 = []
    a2_bias_agreement(rows, out2)
    text2 = "\n".join(out2)
    print(text2)
    with open(f"{OUTDIR}/a2_bias_agreement.txt", "w") as f:
        f.write(text2 + "\n")


if __name__ == "__main__":
    main()
