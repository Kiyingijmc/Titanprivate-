# ICT Video Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether SilverBullet's fixed 2.0R target should become a liquidity-anchored variable target, against a flat-RR control, plus two cheap conditioning reads on session and bias.

**Architecture:** Three exploratory reads on frozen data (session buckets, bias agreement, flat-RR sweep) establish a control value `RR*`. A new pure-stdlib module `src/analysis/liquidity_pools.py` adds equal-highs/lows and prior-day-level detection. A pre-registration is committed, then one single-variable experiment swaps the target only and compares LIQ against CONTROL.

**Tech Stack:** Python 3.12, stdlib `unittest` (there is no pytest), pandas/numpy for the research rig only. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-ict-video-rules-design.md`

## Global Constraints

- **Worktree:** all work happens in this worktree on branch `research/ict-video-rules`. The repo root is a *different* checkout on `main` running the live demo bot — never `git checkout` there.
- **`data/history/` is a SYMLINK into the live tree. It is READ-ONLY.** Never write to it. `poc_sb_stops.py main()` defaults `--out` to `data/history/sb_stops_trades_{tf}.csv` — if you ever invoke it, you MUST pass `--out data/results/...`. Clobbering those frozen tables destroys the study's baseline.
- `data/specs.json` is also a symlink into the live tree. Read-only.
- **All reads pin `model == "ATR10"`.** The `LIVE` rows are the deprecated 0.2×ATR stop. Config runs `stop_atr: 1.0` = `ATR10`.
- **Research universe is the rig's 11 symbols** (`poc_sb_stops.SYMS`), not config's 12.
- Years are 2023, 2024, 2025, 2026.
- Costs always use per-symbol `poc_sb_stops.cost_r`, never the flat 0.11 from `reach_screen.py`.
- Arms are **unpaired** — `resolve()` sets `busy_until = exit_k`, so changing the target changes which later signals are eligible. Always report per-arm `n`. Never use a paired test.
- No new dependencies. No live-path changes: no manifest entry, no `smc_pack` registration, no `config.yaml` edit.
- Run tests as: `.venv/bin/python -m unittest tests.unit.<module> -v`

## File Structure

| File | Responsibility |
|---|---|
| `scripts/poc_sb_stops.py` | **modify** — lift `RR` from module constant to a `resolve()` parameter. Nothing else changes. |
| `src/analysis/session_time.py` | **new** — derive the broker→UTC offset empirically, map to NY killzone buckets. Pure, no pandas. |
| `src/analysis/liquidity_pools.py` | **new** — equal-level pools, prior-day levels, target selection. Pure stdlib, no pandas, no I/O. |
| `tests/unit/test_session_time.py` | **new** |
| `tests/unit/test_liquidity_pools.py` | **new** |
| `tests/unit/test_sb_rig_rr_param.py` | **new** — pins the `resolve()` RR parameterisation. |
| `scripts/ict_video_reads.py` | **new** — A1 session buckets + A2 bias agreement. Writes to `data/results/ict_video_reads/`. |
| `scripts/exp2_liquidity_target.py` | **new** — A3 flat-RR sweep + B2 experiment. Writes to `data/results/exp2_liquidity_target/`. |
| `docs/research/2026-08-03-exp2-liquidity-target-preregistration.md` | **new** — committed BEFORE the B2 run. |
| `docs/research/2026-08-03-ict-video-rules-results.md` | **new** — final results. |

---

### Task 1: Parameterise RR in the SB rig

Unblocks the A3 sweep. Default must stay 2.0 so every existing caller
(`reach_screen.py`, `reach_sweep.py`, `poc_sb_stops.main`) is untouched.

**Files:**
- Modify: `scripts/poc_sb_stops.py:169-211` (`resolve`)
- Test: `tests/unit/test_sb_rig_rr_param.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `resolve(signals, bars, model, rr=RR)` — added trailing keyword-only-by-convention param `rr: float`. Return shape unchanged: list of dicts with keys `model, sl, tp, risk, outcome, r, fill_idx, exit_idx` merged over the signal dict.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sb_rig_rr_param.py
import unittest

import numpy as np

from scripts.poc_sb_stops import resolve


def _bars(highs, lows):
    n = len(highs)
    return {"high": np.array(highs, dtype=float),
            "low": np.array(lows, dtype=float),
            "atr": np.full(n, 1.0),
            "times": np.arange(n),
            "disp_bull": np.zeros(n, dtype=bool),
            "disp_bear": np.zeros(n, dtype=bool)}


# One BUY signal at bar 0. ATR10 stop => sl = entry - 1.0*atr = 99.0, risk = 1.0.
# Bar 1 touches entry (fill). Price then rises to 101.6 without ever hitting 99.
SIG = [{"bar_idx": 0, "dir": "BUY", "entry": 100.0, "atr": 1.0,
        "far_extreme": 99.5, "sig_high": 100.0, "sig_low": 100.0}]
HIGHS = [100.0, 100.2, 101.6, 101.6]
LOWS = [100.0, 99.9, 100.1, 100.5]


class TestResolveRRParam(unittest.TestCase):
    def test_default_rr_is_two(self):
        # tp = 100 + 2.0*1.0 = 102.0, never reached -> no closed trade
        out = resolve(SIG, _bars(HIGHS, LOWS), "ATR10")
        self.assertEqual(out, [])

    def test_rr_one_point_five_fills_and_wins(self):
        # tp = 100 + 1.5*1.0 = 101.5, reached on bar 2
        out = resolve(SIG, _bars(HIGHS, LOWS), "ATR10", rr=1.5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outcome"], "TP")
        self.assertAlmostEqual(out[0]["tp"], 101.5)
        self.assertAlmostEqual(out[0]["r"], 1.5)

    def test_rr_affects_r_on_tp_not_on_sl(self):
        # a losing path: bar 1 fills, bar 2 takes out the stop at 99.0
        lows = [100.0, 99.9, 98.5, 98.5]
        out = resolve(SIG, _bars([100.0, 100.2, 100.3, 100.3], lows),
                      "ATR10", rr=3.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["outcome"], "SL")
        self.assertAlmostEqual(out[0]["r"], -1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_rig_rr_param -v`
Expected: FAIL — `TypeError: resolve() got an unexpected keyword argument 'rr'` on the `rr=1.5` cases.

- [ ] **Step 3: Write minimal implementation**

In `scripts/poc_sb_stops.py`, change the signature and the two `RR` uses inside:

```python
def resolve(signals, bars, model, rr=RR):
    """Fixed-TP resolution, one open per symbol, limit fill within TTL.

    `rr` is the reward multiple for the take-profit. Defaults to the module
    constant so existing callers are unaffected; the A3 sweep varies it.
    """
```

Then inside the loop replace:

```python
        tp = entry + RR * risk if is_long else entry - RR * risk
```
with
```python
        tp = entry + rr * risk if is_long else entry - rr * risk
```

and replace:

```python
                outcome, r, exit_k = "TP", RR, k
```
with
```python
                outcome, r, exit_k = "TP", rr, k
```

Change nothing else in the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_rig_rr_param -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Verify no existing caller broke**

Run: `.venv/bin/python -c "import scripts.reach_screen, scripts.reach_sweep; print('imports ok')"`
Expected: `imports ok`

- [ ] **Step 6: Commit**

```bash
git add scripts/poc_sb_stops.py tests/unit/test_sb_rig_rr_param.py
git commit -m "refactor(rig): lift RR to a resolve() parameter for the A3 sweep"
```

---

### Task 2: Empirical broker→NY session mapping

Replaces blind trust in `NY_SHIFT = -7` ("+/-1h DST wobble accepted"). Pure
functions taking plain values so they are testable without data files.

**Files:**
- Create: `src/analysis/session_time.py`
- Test: `tests/unit/test_session_time.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `infer_ny_shift(week_open_hours) -> int` — takes the broker-local hours at which trading weeks opened, returns the whole-hour shift to ADD to a broker hour to get the NY hour. Raises `ValueError` when empty or when the modal hour covers under 80% of weeks.
  - `KILLZONES` — dict of bucket name → `(start_hour, end_hour)` in NY time, end exclusive.
  - `OUTSIDE` — the fourth bucket's name.
  - `ny_bucket(broker_hour, ny_shift) -> str` — one of `"London KZ"`, `"NY AM"`, `"NY PM"`, `"Outside"`.

**Why an anchor and not a UTC offset.** FBS server time follows US DST, so the
broker's *UTC* offset changes twice a year (GMT+2 winter, GMT+3 summer) while
its offset to New York stays constant. Converting via UTC therefore needs the
offset known per-date and gets it wrong at the boundaries. Anchoring instead on
the **weekend seam** — the FX week opens Sunday 17:00 New York — is exact and
needs no timezone database.

**Why the weekend seam and not the daily rollover.** The obvious anchor is the
daily maintenance gap, but *this data has none*: EURUSD M5 hourly bar counts run
8577–9324 across all 24 hours, with no hour anywhere near empty. A daily-gap
detector aborts on every symbol and every year. The weekly seam is unambiguous
by contrast — 159 of 160 weekends open at the same broker hour.

**Verified values (measured during planning, expect these):** the shift is
**+17**, identical in 2023/2024/2025/2026 (26/53/53/25 seams). Note `17 ≡ -7
(mod 24)`, so this *confirms* the rig's `NY_SHIFT = -7` rather than correcting
it — its "+/-1h DST wobble accepted" caveat turns out to be unnecessary, because
the broker tracks NY DST and the shift is genuinely constant. Report that.

**Use an FX symbol for the detection.** XAUUSD and US30 open an hour later than
FX (broker hour 1, not 0). EURUSD is the reference.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_session_time.py
import unittest

from src.analysis.session_time import (
    infer_ny_shift, ny_bucket, KILLZONES, OUTSIDE,
)


class TestShiftInference(unittest.TestCase):
    def test_week_opening_at_broker_midnight_gives_shift_17(self):
        # the FX week opens Sunday 17:00 NY; if that lands on broker hour 0
        # then broker 00:00 IS 17:00 NY -> shift = +17.
        # This is the real measured value for FBS.
        self.assertEqual(infer_ny_shift([0] * 50), 17)

    def test_shift_tracks_the_open_hour(self):
        # a feed whose week opens at broker 01:00 (metals behave this way)
        self.assertEqual(infer_ny_shift([1] * 50), 16)

    def test_tolerates_a_minority_of_odd_weeks(self):
        # 49 of 50 at hour 0 - holidays and short weeks must not derail it
        self.assertEqual(infer_ny_shift([0] * 49 + [23]), 17)

    def test_rejects_an_unstable_open_hour(self):
        # a 50/50 split means the anchor is not identifiable
        with self.assertRaises(ValueError):
            infer_ny_shift([0] * 25 + [1] * 25)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            infer_ny_shift([])


class TestBuckets(unittest.TestCase):
    def test_three_killzones_plus_outside(self):
        self.assertEqual(set(KILLZONES), {"London KZ", "NY AM", "NY PM"})
        self.assertEqual(OUTSIDE, "Outside")

    def test_london_killzone(self):
        # broker 09:00 with shift 17 -> (9+17)%24 = 02:00 NY -> London KZ
        self.assertEqual(ny_bucket(9, 17), "London KZ")

    def test_ny_am(self):
        # broker 15:00 -> 08:00 NY
        self.assertEqual(ny_bucket(15, 17), "NY AM")

    def test_ny_pm(self):
        # broker 20:00 -> 13:00 NY
        self.assertEqual(ny_bucket(20, 17), "NY PM")

    def test_outside(self):
        # broker 05:00 -> 22:00 NY
        self.assertEqual(ny_bucket(5, 17), "Outside")

    def test_boundaries_are_end_exclusive(self):
        # every window's END hour falls OUTSIDE it.
        # (broker + 17) % 24 = NY hour
        self.assertEqual(ny_bucket(17, 17), "NY AM")    # 34%24 = 10, inside (8,11)
        self.assertEqual(ny_bucket(18, 17), "Outside")  # 35%24 = 11, end-exclusive
        self.assertEqual(ny_bucket(11, 17), "London KZ")  # 28%24 =  4, inside (2,5)
        self.assertEqual(ny_bucket(12, 17), "Outside")  # 29%24 =  5, end-exclusive
        self.assertEqual(ny_bucket(22, 17), "NY PM")    # 39%24 = 15, inside (13,16)
        self.assertEqual(ny_bucket(23, 17), "Outside")  # 40%24 = 16, end-exclusive
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_session_time -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.session_time'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/analysis/session_time.py
# Broker-time -> New York session mapping for the ICT video-rules study.
# Spec: docs/superpowers/specs/2026-08-03-ict-video-rules-design.md (A1).
#
# The SB rig carries NY_SHIFT = -7 with the comment "broker(GMT+3ish) -> NY
# approx; +/-1h DST wobble accepted". This module replaces that approximation
# with a shift derived from the data itself. Pure functions, no pandas, no I/O.
#
# WHY AN ANCHOR RATHER THAN A UTC OFFSET: FBS server time follows US DST, so
# the broker's UTC offset moves twice a year (GMT+2 winter, GMT+3 summer) while
# its offset to New York does not. Routing through UTC therefore needs a
# per-date offset and is wrong at the DST boundaries.
#
# WHY THE WEEKEND SEAM AND NOT THE DAILY ROLLOVER: the obvious anchor is the
# daily maintenance gap, but this data has none - EURUSD M5 hourly bar counts
# run 8577-9324 across all 24 hours. The weekly seam is unambiguous instead:
# the FX week opens Sunday 17:00 New York, and 159 of 160 weekends in this data
# open at the same broker hour.
#
# Measured: shift = +17, identical across 2023-2026. Note 17 == -7 (mod 24),
# so this CONFIRMS the rig's NY_SHIFT = -7 rather than correcting it.

# NY-time killzone buckets, end-exclusive, snapped to H1 bar opens.
# Canonical ICT quotes 08:30-11:00 and 13:30-16:00; H1 bars cannot represent
# half-hour boundaries, so these snap outward to the bar open. Stated in the
# results doc as an approximation, not hidden.
KILLZONES = {
    "London KZ": (2, 5),
    "NY AM": (8, 11),
    "NY PM": (13, 16),
}
OUTSIDE = "Outside"

_WEEK_OPEN_NY_HOUR = 17    # the FX week opens Sunday 17:00 New York
_MIN_MODAL_SHARE = 0.80    # the modal open hour must cover this many weeks


def infer_ny_shift(week_open_hours):
    """Whole hours to ADD to a broker-local hour to get the New York hour.

    `week_open_hours` is the broker-local hour of the first bar after each
    weekend gap. The modal value pins the week open, which is 17:00 New York.

    Raises ValueError when there are no seams, or when the modal hour covers
    under _MIN_MODAL_SHARE of weeks - an unstable anchor aborts the run instead
    of silently bucketing on a wrong mapping.
    """
    if not week_open_hours:
        raise ValueError("no weekend seams found - cannot anchor the shift")
    counts = {}
    for h in week_open_hours:
        counts[h] = counts.get(h, 0) + 1
    modal_hour = max(counts, key=lambda h: (counts[h], -h))
    share = counts[modal_hour] / len(week_open_hours)
    if share < _MIN_MODAL_SHARE:
        raise ValueError(
            f"week-open hour is not stable: {sorted(counts.items())} "
            f"(modal share {share:.0%} < {_MIN_MODAL_SHARE:.0%}) - aborting")
    return (_WEEK_OPEN_NY_HOUR - modal_hour) % 24


def ny_bucket(broker_hour, ny_shift):
    """Map a broker-local hour to its NY killzone bucket."""
    ny_hour = (broker_hour + ny_shift) % 24
    for name, (start, end) in KILLZONES.items():
        if start <= ny_hour < end:
            return name
    return OUTSIDE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_session_time -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/session_time.py tests/unit/test_session_time.py
git commit -m "feat(analysis): empirical broker->NY session mapping with DST"
```

---

### Task 3: A1 — session bucket read

**Files:**
- Create: `scripts/ict_video_reads.py`
- Reads: `data/history/sb_stops_trades_H1.csv` (read-only symlink), `data/specs.json`
- Writes: `data/results/ict_video_reads/a1_session_buckets.txt`

**Interfaces:**
- Consumes: `session_time.infer_ny_shift`, `session_time.ny_bucket`, `poc_sb_stops.cost_r`, `poc_sb_stops.wilson`.
- Produces: `load_atr10()` returning a list of trade dicts with `_net_r` populated — Task 4 reuses it.

- [ ] **Step 1: Write the script**

```python
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


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python scripts/ict_video_reads.py`
Expected: prints the inferred shift, the per-year stability check, and four bucket blocks with per-year rows.

If it raises either `ValueError` — *"week-open hour is not stable"* or *"not stable across years"* — **stop and report the error**. Do not hardcode a shift to get past it and do not lower `_MIN_MODAL_SHARE` to force a result. Those aborts are the design working: they mean the mapping cannot be trusted, and a wrong mapping makes every A1 number meaningless while still looking plausible.

- [ ] **Step 3: Sanity-check the output**

These values were measured during planning. Confirm all four before continuing:
- `shift == 17`, and the per-year check reads `{2023: 17, 2024: 17, 2025: 17, 2026: 17}`
- the bucket map puts **London KZ at broker hours 9–11, NY AM at 15–17, NY PM at 20–22**. If buckets land elsewhere, the anchor is wrong — stop.
- pooled `n` is ~2217 (matches `reach_screen.py`'s ATR10 count)
- bucket `n` values sum to pooled `n`

Report in the results doc that `17 ≡ -7 (mod 24)`, so the derivation **confirms** the rig's `NY_SHIFT = -7`; its "+/-1h DST wobble accepted" caveat proved unnecessary.

- [ ] **Step 4: Commit**

```bash
git add scripts/ict_video_reads.py
git commit -m "research(A1): session-bucket read on frozen ATR10 trades"
```

---

### Task 4: A2 — bias agreement read

Both bias levels come from **one** algorithm (`ict_structure.structure_bias`) at
two lookbacks. The rig's existing `bias` column comes from `BiasEngine` (a
different algorithm) and is reported alongside as context only — mixing them
would compare unlike things.

**Files:**
- Modify: `scripts/ict_video_reads.py`
- Writes: `data/results/ict_video_reads/a2_bias_agreement.txt`

**Interfaces:**
- Consumes: `load_atr10()` from Task 3, `ict_structure.structure_bias`.
- Produces: nothing downstream.

- [ ] **Step 1: Add the A2 function**

Insert into `scripts/ict_video_reads.py` above `main()`:

```python
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
```

- [ ] **Step 2: Wire it into `main()`**

Replace the tail of `main()` (from `out = []` onward) with:

```python
    out = []
    a1_session_buckets(rows, offset, out)
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
```

- [ ] **Step 3: Run it**

Run: `.venv/bin/python scripts/ict_video_reads.py`
Expected: both blocks print. The A2 block ends with the power statement. Runtime is a few minutes — it resamples 11 M5 files to H1 and runs `structure_bias` twice per symbol.

- [ ] **Step 4: Sanity-check**

- AGREE + DISAGREE + (both-NEUTRAL) sums to pooled `n`
- the agreement subset is roughly 500–1000 trades (if it is near pooled `n`, the two lookbacks are not actually differing — investigate before continuing)

- [ ] **Step 5: Commit**

```bash
git add scripts/ict_video_reads.py
git commit -m "research(A2): fractal-vs-internal bias agreement read (underpowered, reported)"
```

---

### Task 5: `equal_level_pools`

**Files:**
- Create: `src/analysis/liquidity_pools.py`
- Test: `tests/unit/test_liquidity_pools.py`

**Interfaces:**
- Consumes: `ict_structure.confirmed_swings`.
- Produces: `equal_level_pools(highs, lows, atr, lk=3, tol_atr=0.10, min_members=2) -> list[tuple[float, str, int]]` — `(level, side, usable_from_idx)`, sorted by `usable_from_idx`. `side` is `"buy"` (above equal highs) or `"sell"` (below equal lows).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_liquidity_pools.py
import unittest

from src.analysis.liquidity_pools import equal_level_pools

# lk=1. Swing highs at j=2 (10.00) and j=6 (10.02) - within 0.10*ATR(=0.10)
# of each other, so they form ONE buy-side pool. Swing lows at j=4 and j=8 are
# 9.00 and 9.50 - 0.50 apart, far beyond tolerance, so NO sell-side pool.
HIGHS = [9.6, 9.8, 10.00, 9.7, 9.3, 9.9, 10.02, 9.8, 9.9, 10.4]
LOWS = [9.2, 9.4, 9.60, 9.3, 9.00, 9.5, 9.70, 9.6, 9.50, 9.9]
ATR = [1.0] * 10


class TestEqualLevelPools(unittest.TestCase):
    def test_near_equal_highs_form_one_buy_pool(self):
        pools = equal_level_pools(HIGHS, LOWS, ATR, lk=1, tol_atr=0.10)
        buys = [p for p in pools if p[1] == "buy"]
        self.assertEqual(len(buys), 1)
        level, side, usable = buys[0]
        # level is the HIGHEST member - stops rest above the highest equal high
        self.assertAlmostEqual(level, 10.02)

    def test_far_apart_lows_form_no_pool(self):
        pools = equal_level_pools(HIGHS, LOWS, ATR, lk=1, tol_atr=0.10)
        self.assertEqual([p for p in pools if p[1] == "sell"], [])

    def test_tolerance_is_scaled_by_atr(self):
        # widen ATR 10x -> tolerance 1.0 -> the two lows (0.50 apart) now cluster
        pools = equal_level_pools(HIGHS, LOWS, [10.0] * 10, lk=1, tol_atr=0.10)
        sells = [p for p in pools if p[1] == "sell"]
        self.assertEqual(len(sells), 1)
        # level is the LOWEST member for a sell-side pool
        self.assertAlmostEqual(sells[0][0], 9.00)

    def test_min_members_rejects_a_lone_swing(self):
        # min_members=3 -> the 2-member high cluster no longer qualifies
        pools = equal_level_pools(HIGHS, LOWS, ATR, lk=1, tol_atr=0.10,
                                  min_members=3)
        self.assertEqual(pools, [])

    def test_no_lookahead_usable_from_last_member_confirmation(self):
        pools = equal_level_pools(HIGHS, LOWS, ATR, lk=1, tol_atr=0.10)
        level, side, usable = [p for p in pools if p[1] == "buy"][0]
        # last member is the swing high at j=6; confirmed from j+lk = 7
        self.assertEqual(usable, 7)

    def test_sorted_by_usable_from(self):
        pools = equal_level_pools(HIGHS, LOWS, [10.0] * 10, lk=1, tol_atr=0.10)
        self.assertEqual([p[2] for p in pools], sorted(p[2] for p in pools))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_liquidity_pools -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.liquidity_pools'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/analysis/liquidity_pools.py
# Liquidity-pool primitives for the ICT video-rules study (Rule 3).
# Spec: docs/superpowers/specs/2026-08-03-ict-video-rules-design.md (B1).
#
# Deliberately NOT in ict_zones.py, which is scoped to a frozen Unicorn rule
# set. Deliberately distinct from src/analysis/liquidity.py, which is the
# pandas-based live-path premium/discount engine. Pure stdlib: no pandas,
# no numpy, no I/O - same split as ict_structure.py / ict_zones.py.
#
# THE LOAD-BEARING INVARIANT IS NO LOOK-AHEAD. Every pool carries the bar index
# from which it first becomes usable, and callers MUST filter on it.
from src.analysis.ict_structure import confirmed_swings

BUY = "buy"      # pool resting ABOVE equal highs - a long's draw
SELL = "sell"    # pool resting BELOW equal lows  - a short's draw


def _cluster(swings, prices, atr, lk, tol_atr, min_members, side):
    """Greedy consecutive clustering of swing extremes at near-equal price."""
    pools = []
    group = []
    for j in swings:
        tol = tol_atr * atr[j]
        if group and abs(prices[j] - prices[group[0]]) <= tol:
            group.append(j)
            continue
        if len(group) >= min_members:
            pools.append(_emit(group, prices, lk, side))
        group = [j]
    if len(group) >= min_members:
        pools.append(_emit(group, prices, lk, side))
    return pools


def _emit(group, prices, lk, side):
    """A pool sits at the extreme of its members - stops rest beyond the
    furthest equal level, not at their mean. Usable only once the LAST member
    is confirmed (index + lk)."""
    level = (max(prices[j] for j in group) if side == BUY
             else min(prices[j] for j in group))
    return (level, side, group[-1] + lk)


def equal_level_pools(highs, lows, atr, lk=3, tol_atr=0.10, min_members=2):
    """Clusters of confirmed swing extremes at near-equal price.

    Two extremes are "equal" when within tol_atr * atr[j] of each other,
    evaluated at the later swing's bar j. Returns [(level, side, usable_from),
    ...] sorted by usable_from.
    """
    swh, swl = confirmed_swings(highs, lows, lk)
    pools = _cluster(swh, highs, atr, lk, tol_atr, min_members, BUY)
    pools += _cluster(swl, lows, atr, lk, tol_atr, min_members, SELL)
    pools.sort(key=lambda p: p[2])
    return pools
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_liquidity_pools -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/liquidity_pools.py tests/unit/test_liquidity_pools.py
git commit -m "feat(analysis): equal-level liquidity pool detection"
```

---

### Task 6: `prior_day_levels`

Takes pre-computed day keys rather than timestamps, so the function stays pure
stdlib and the datetime handling lives in the caller.

**Files:**
- Modify: `src/analysis/liquidity_pools.py`
- Modify: `tests/unit/test_liquidity_pools.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `prior_day_levels(day_keys, highs, lows) -> tuple[list, list]` — per-bar `(pdh, pdl)`, `None` at bars with no completed prior day. `day_keys` is any per-bar hashable, non-decreasing day identifier.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_liquidity_pools.py`:

```python
from src.analysis.liquidity_pools import prior_day_levels


class TestPriorDayLevels(unittest.TestCase):
    # three days, 2 bars each
    DAYS = ["d1", "d1", "d2", "d2", "d3", "d3"]
    H = [10.0, 11.0, 12.0, 12.5, 9.0, 9.5]
    L = [8.0, 8.5, 9.5, 9.9, 7.0, 7.5]

    def test_first_day_has_no_prior(self):
        pdh, pdl = prior_day_levels(self.DAYS, self.H, self.L)
        self.assertIsNone(pdh[0])
        self.assertIsNone(pdh[1])
        self.assertIsNone(pdl[0])

    def test_second_day_sees_first_day_extremes(self):
        pdh, pdl = prior_day_levels(self.DAYS, self.H, self.L)
        self.assertEqual(pdh[2], 11.0)   # max of day1 highs
        self.assertEqual(pdl[2], 8.0)    # min of day1 lows
        self.assertEqual(pdh[3], 11.0)   # constant across the day

    def test_never_leaks_the_current_day(self):
        pdh, pdl = prior_day_levels(self.DAYS, self.H, self.L)
        # day3 must see day2 (12.5 / 9.5), NOT day3's own 9.5 / 7.0
        self.assertEqual(pdh[4], 12.5)
        self.assertEqual(pdl[4], 9.5)
        self.assertEqual(pdh[5], 12.5)

    def test_rolls_exactly_at_the_boundary(self):
        pdh, _ = prior_day_levels(self.DAYS, self.H, self.L)
        # last bar of day2 still sees day1; first bar of day3 sees day2
        self.assertEqual(pdh[3], 11.0)
        self.assertEqual(pdh[4], 12.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_liquidity_pools -v`
Expected: FAIL — `ImportError: cannot import name 'prior_day_levels'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/analysis/liquidity_pools.py`:

```python
def prior_day_levels(day_keys, highs, lows):
    """Per-bar (pdh, pdl) from the previous COMPLETED day.

    day_keys is any per-bar hashable, non-decreasing day identifier (the caller
    owns the timezone decision). Entries are None until a full prior day
    exists. No look-ahead by construction: a day's extremes are only published
    from the first bar of the FOLLOWING day.
    """
    n = len(highs)
    pdh = [None] * n
    pdl = [None] * n
    prev_h = prev_l = None
    cur_key = None
    cur_h = cur_l = None
    for i in range(n):
        if day_keys[i] != cur_key:
            if cur_key is not None:
                prev_h, prev_l = cur_h, cur_l
            cur_key = day_keys[i]
            cur_h, cur_l = highs[i], lows[i]
        else:
            cur_h = max(cur_h, highs[i])
            cur_l = min(cur_l, lows[i])
        pdh[i] = prev_h
        pdl[i] = prev_l
    return pdh, pdl
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_liquidity_pools -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/liquidity_pools.py tests/unit/test_liquidity_pools.py
git commit -m "feat(analysis): prior-day high/low levels with no current-day leak"
```

---

### Task 7: `nearest_pool_beyond`

The function that turns pools into a target, and the one that produces both
degeneracy diagnostics.

**Files:**
- Modify: `src/analysis/liquidity_pools.py`
- Modify: `tests/unit/test_liquidity_pools.py`

**Interfaces:**
- Consumes: pool tuples from Tasks 5–6.
- Produces: `nearest_pool_beyond(pools, entry, risk, is_long, i, floor_r=1.0, cap_r=5.0) -> tuple[float, str] | None` — `(target_price, bound)` where `bound` is `"pool"` (target sits at the pool) or `"floor"` (pool was nearer than `floor_r`, target clamped out). `None` means no eligible pool → caller falls back to `RR*`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_liquidity_pools.py`:

```python
from src.analysis.liquidity_pools import nearest_pool_beyond

# entry 100.0, risk 1.0 -> 1R = 1.0 price unit
POOLS = [
    (102.5, "buy", 5),     # +2.5R, usable from bar 5
    (104.0, "buy", 5),     # +4.0R
    (100.3, "buy", 9),     # +0.3R, only usable from bar 9
    (97.0, "sell", 5),     # -3.0R
    (112.0, "buy", 5),     # +12.0R, beyond cap
]


class TestNearestPoolBeyond(unittest.TestCase):
    def test_picks_nearest_eligible_buy_pool_for_a_long(self):
        got = nearest_pool_beyond(POOLS, 100.0, 1.0, True, i=5)
        self.assertEqual(got, (102.5, "pool"))

    def test_picks_sell_side_for_a_short(self):
        got = nearest_pool_beyond(POOLS, 100.0, 1.0, False, i=5)
        self.assertEqual(got, (97.0, "pool"))

    def test_respects_usable_from(self):
        # at i=9 the 100.3 pool becomes visible; it is nearer than 102.5
        # but sits at 0.3R, so the target clamps out to the 1.0R floor
        got = nearest_pool_beyond(POOLS, 100.0, 1.0, True, i=9)
        self.assertEqual(got, (101.0, "floor"))

    def test_pool_beyond_cap_is_not_eligible(self):
        # only the 112.0 pool is in range -> +12R > cap -> no eligible pool
        got = nearest_pool_beyond([(112.0, "buy", 5)], 100.0, 1.0, True, i=5)
        self.assertIsNone(got)

    def test_no_pool_returns_none_for_fallback(self):
        self.assertIsNone(nearest_pool_beyond([], 100.0, 1.0, True, i=5))

    def test_pool_behind_entry_is_ignored(self):
        # a buy pool BELOW a long's entry is not a draw
        self.assertIsNone(
            nearest_pool_beyond([(99.0, "buy", 5)], 100.0, 1.0, True, i=5))

    def test_zero_risk_is_rejected(self):
        with self.assertRaises(ValueError):
            nearest_pool_beyond(POOLS, 100.0, 0.0, True, i=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_liquidity_pools -v`
Expected: FAIL — `ImportError: cannot import name 'nearest_pool_beyond'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/analysis/liquidity_pools.py`:

```python
def nearest_pool_beyond(pools, entry, risk, is_long, i,
                        floor_r=1.0, cap_r=5.0):
    """Target from the nearest usable opposing-side pool beyond entry.

    Returns (target_price, bound) where bound is "pool" when the target sits at
    the pool and "floor" when the pool was nearer than floor_r and the target
    was clamped out. Returns None when no pool qualifies - the caller then
    falls back to the flat RR* control target.

    A pool farther than cap_r is NOT eligible: placing an unreachable target is
    worse than falling back. Only pools with usable_from <= i are visible, which
    is what enforces no look-ahead.
    """
    if risk <= 0:
        raise ValueError(f"risk must be positive, got {risk}")
    want = BUY if is_long else SELL
    best = None
    for level, side, usable_from in pools:
        if side != want or usable_from > i:
            continue
        dist_r = (level - entry) / risk if is_long else (entry - level) / risk
        if dist_r <= 0 or dist_r > cap_r:
            continue
        if best is None or dist_r < best:
            best = dist_r
    if best is None:
        return None
    bound = "pool"
    if best < floor_r:
        best, bound = floor_r, "floor"
    target = entry + best * risk if is_long else entry - best * risk
    return (target, bound)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_liquidity_pools -v`
Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/liquidity_pools.py tests/unit/test_liquidity_pools.py
git commit -m "feat(analysis): liquidity-anchored target selection with floor and cap"
```

---

### Task 8: A3 — flat-RR sweep, fixing `RR*`

**Files:**
- Create: `scripts/exp2_liquidity_target.py`
- Writes: `data/results/exp2_liquidity_target/a3_rr_sweep.txt`

**Interfaces:**
- Consumes: `poc_sb_stops.collect_signals`, `resolve(..., rr=)`, `cost_r`, `SYMS`.
- Produces: `build(sym)` returning `(signals, bars)` cached per symbol; `arm_stats(trades, specs, spread_mult=1.0)` returning the per-arm dict used again in Task 10.

- [ ] **Step 1: Write the script**

```python
# scripts/exp2_liquidity_target.py
# A3 flat-RR sweep (the CONTROL) + B2 liquidity-target experiment.
# Spec: docs/superpowers/specs/2026-08-03-ict-video-rules-design.md
#
# data/history/ is a READ-ONLY symlink into the live tree. All output goes to
# data/results/exp2_liquidity_target/.
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.poc_sb_stops import (                            # noqa: E402
    SYMS, collect_signals, resolve, cost_r,
)

OUTDIR = "data/results/exp2_liquidity_target"
MODEL = "ATR10"
YEARS = [2023, 2024, 2025, 2026]
RR_GRID = [1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 3.00]

_CACHE = {}


def build(sym):
    """H1 signals + bars for one symbol, cached (collection is the slow part)."""
    if sym not in _CACHE:
        _CACHE[sym] = collect_signals(sym, tf="H1")
    return _CACHE[sym]


def load_specs():
    with open("data/specs.json") as f:
        return json.load(f)


def arm_stats(trades, specs, spread_mult=1.0):
    """Net-R summary for one arm. Arms are UNPAIRED (busy_until = exit_k), so
    every arm reports its own n and no paired test is ever used."""
    nets = [t["r"] - cost_r(t, t["sym"], specs, spread_mult) for t in trades]
    n = len(nets)
    if n == 0:
        return {"n": 0, "exp": 0.0, "win": 0.0, "nets": []}
    wins = sum(1 for x in nets if x > 0)
    return {"n": n, "exp": sum(nets) / n, "win": 100.0 * wins / n, "nets": nets}


def by_year(trades, specs):
    out = {}
    for y in YEARS:
        out[y] = arm_stats([t for t in trades if t["year"] == y], specs)
    return out


def by_symbol(trades, specs):
    return {s: arm_stats([t for t in trades if t["sym"] == s], specs)
            for s in sorted({t["sym"] for t in trades})}


def run_flat(rr, specs):
    """All symbols at one flat RR."""
    trades = []
    for sym in SYMS:
        sigs, bars = build(sym)
        if sigs is None:
            continue
        for t in resolve(sigs, bars, MODEL, rr=rr):
            t["sym"] = sym
            trades.append(t)
    return trades


def a3_sweep(specs, out):
    p = out.append
    p("=" * 78)
    p("A3 -- FLAT-RR SWEEP (the CONTROL arm for B2)")
    p("=" * 78)
    p("Arms are UNPAIRED: resolve() sets busy_until = exit_k, so changing the")
    p("target changes which later signals are eligible. n shifts per arm.")
    p("")
    p(f"  {'RR':>5} {'n':>6} {'exp':>8} {'win%':>6}   per-year exp")

    results = {}
    for rr in RR_GRID:
        tr = run_flat(rr, specs)
        s = arm_stats(tr, specs)
        ys = by_year(tr, specs)
        results[rr] = {"all": s, "year": ys, "sym": by_symbol(tr, specs)}
        yr = "  ".join(f"{y}:{ys[y]['exp']:+.3f}" for y in YEARS)
        p(f"  {rr:5.2f} {s['n']:6d} {s['exp']:+8.3f} {s['win']:6.1f}   {yr}")

    p("")
    base = results[2.00]
    p("RR* SELECTION RULE (declared before the run):")
    p("  2.00 stands as RR* unless a challenger beats it on net exp in EVERY")
    p("  year AND in >=6 of 11 symbols. If two challengers qualify, RR* is the")
    p("  one nearer 2.00. Raw argmax over 7 arms is a selection artifact and is")
    p("  NOT used.")
    p("")

    qualified = []
    for rr in RR_GRID:
        if rr == 2.00:
            continue
        r = results[rr]
        years_ok = all(r["year"][y]["exp"] > base["year"][y]["exp"] for y in YEARS)
        syms_ok = sum(1 for s in r["sym"]
                      if s in base["sym"]
                      and r["sym"][s]["exp"] > base["sym"][s]["exp"])
        p(f"  challenger RR={rr:.2f}: all-years-better={years_ok}  "
          f"symbols-better={syms_ok}/11  "
          f"{'QUALIFIES' if years_ok and syms_ok >= 6 else 'no'}")
        if years_ok and syms_ok >= 6:
            qualified.append(rr)

    rr_star = min(qualified, key=lambda r: abs(r - 2.00)) if qualified else 2.00
    p("")
    p(f"  RR* = {rr_star:.2f}")
    p("")
    return rr_star


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    specs = load_specs()
    out = []
    rr_star = a3_sweep(specs, out)
    text = "\n".join(out)
    print(text)
    with open(f"{OUTDIR}/a3_rr_sweep.txt", "w") as f:
        f.write(text + "\n")
    with open(f"{OUTDIR}/rr_star.json", "w") as f:
        json.dump({"rr_star": rr_star}, f)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it in the background**

Run: `.venv/bin/python scripts/exp2_liquidity_target.py > /tmp/a3.log 2>&1 &`
This collects signals for 11 symbols across 7 arms. Signal collection is cached
per symbol, so the cost is one collection pass plus 7 cheap resolve passes.
Expect roughly 10–25 minutes.

- [ ] **Step 3: Sanity-check the output**

- the `RR=2.00` row's `n` should be ~2217 and `exp` ~+0.109R — this reproduces
  the known baseline and is the proof the harness is wired correctly. **If it
  does not reproduce, stop and diagnose before going further.**
- `n` should fall as RR rises (farther targets → longer holds → fewer eligible
  signals under the occupancy rule)

- [ ] **Step 4: Commit**

```bash
git add scripts/exp2_liquidity_target.py
git commit -m "research(A3): flat-RR sweep establishing the RR* control"
```

---

### Task 9: Pre-registration — HARD GATE

Nothing from Task 10 may be written or run until this is committed. `RR*` is
now a known number, so the pre-registration states it concretely.

**Files:**
- Create: `docs/research/2026-08-03-exp2-liquidity-target-preregistration.md`

**Interfaces:**
- Consumes: `rr_star` from Task 8's `rr_star.json`.
- Produces: the frozen criteria Task 10 reports against.

- [ ] **Step 1: Write the pre-registration**

Substitute the real `RR*` from `data/results/exp2_liquidity_target/rr_star.json`
wherever `<RR*>` appears.

```markdown
# EXP-2 pre-registration — liquidity-anchored variable target

**Date:** 2026-08-03
**Status:** pre-registered, not yet run
**Spec:** docs/superpowers/specs/2026-08-03-ict-video-rules-design.md

## Question

Does anchoring SilverBullet's take-profit to the nearest opposing liquidity
pool beat the best flat reward multiple?

## Design

Single variable. **Frozen:** entry (SB FVG + `BODY_MIN_ATR` gate), `ATR10`
stop, the rig's 11-symbol universe, per-symbol `cost_r`, `TTL_BARS = 12`, and
the one-open-per-symbol occupancy rule.

**Varied:** the target only.

| Arm | Target |
|---|---|
| CONTROL | flat <RR*>R (established by the A3 sweep) |
| LIQ | nearest opposing pool beyond entry, floored 1.0R, capped 5.0R, falling back to <RR*>R when no pool is in range |

Pool parameters, fixed in advance: `lk=3`, `tol_atr=0.10`, `min_members=2`.
Pool sources: equal highs/lows clusters, plus prior-day high/low.
A `lk=5` sensitivity run is reported, not gated.

## Degeneracy diagnostics — can void the arm regardless of its mean

- **fallback share** — trades taking the <RR*>R fallback. If > 50%, LIQ is
  mostly CONTROL under another name.
- **floor-bind share** — trades clamped to the 1.0R floor. If > 50%, LIQ is
  flat 1.0R, which A3 already tested.
- combined fallback + floor-bind > 65% → **INCONCLUSIVE**, no verdict drawn.

## GO criteria — all four required

1. LIQ − CONTROL ≥ **+0.05R**/trade net of costs.
2. Unpaired bootstrap 95% CI on the difference of means excludes 0
   (10,000 resamples, seed 20260803).
3. The LIQ − CONTROL difference is positive in all four years and in ≥6 of 11
   symbols (sign of the *difference*, not of either arm's absolute return).
4. Survives 1.5× spread stress.

Anything short of all four is NO-GO. `n` is reported per arm; arms are
unpaired, so no paired test is used.

## Declared in advance

- Statistics are computed once, on the full sample. No arm is added, no
  parameter is retuned, and no criterion is renegotiated after seeing results.
- A NO-GO is a publishable result and is recorded as such.
- A GO promotes to the research → demo → live ladder as a separate cycle. It
  does **not** authorise a config or live-path change in this cycle.
- The 11-symbol research universe is not the 12-symbol live universe; a GO does
  not transfer to US100/ETHUSD/XTIUSD without a re-run.
```

- [ ] **Step 2: Commit — this is the gate**

```bash
git add docs/research/2026-08-03-exp2-liquidity-target-preregistration.md
git commit -m "research(EXP-2): pre-register the liquidity-target experiment"
```

- [ ] **Step 3: Verify the gate closed**

Run: `git log --oneline -1 -- docs/research/2026-08-03-exp2-liquidity-target-preregistration.md`
Expected: a commit hash. Only now may Task 10 be written.

---

### Task 10: B2 — run the experiment and write results

**Files:**
- Modify: `scripts/exp2_liquidity_target.py`
- Create: `docs/research/2026-08-03-ict-video-rules-results.md`
- Writes: `data/results/exp2_liquidity_target/b2_experiment.txt`

**Interfaces:**
- Consumes: `equal_level_pools`, `prior_day_levels`, `nearest_pool_beyond`, `build`, `arm_stats`, `run_flat`.
- Produces: the results doc.

- [ ] **Step 1: Add the LIQ resolver**

Insert into `scripts/exp2_liquidity_target.py` above `main()`:

```python
from src.analysis.liquidity_pools import (                    # noqa: E402
    equal_level_pools, prior_day_levels, nearest_pool_beyond, BUY, SELL,
)

BOOTSTRAP_N = 10000
BOOTSTRAP_SEED = 20260803


def _pools_for(bars, lk=3):
    """Equal-level pools + prior-day levels for one symbol's H1 bars."""
    highs = list(bars["high"])
    lows = list(bars["low"])
    atr = list(bars["atr"])
    pools = equal_level_pools(highs, lows, atr, lk=lk,
                              tol_atr=0.10, min_members=2)

    # prior-day levels -> pools usable from the first bar of the next day.
    # day key is broker-local calendar day; the caller owns that choice.
    import numpy as np
    days = np.asarray(bars["times"]).astype("datetime64[D]")
    pdh, pdl = prior_day_levels(list(days), highs, lows)
    seen_h = seen_l = None
    for i in range(len(highs)):
        if pdh[i] is not None and pdh[i] != seen_h:
            pools.append((pdh[i], BUY, i))
            seen_h = pdh[i]
        if pdl[i] is not None and pdl[i] != seen_l:
            pools.append((pdl[i], SELL, i))
            seen_l = pdl[i]
    pools.sort(key=lambda p: p[2])
    return pools


def resolve_liq(signals, bars, model, rr_star, pools):
    """Same as resolve(), but the target comes from the nearest opposing pool.

    Deliberately mirrors poc_sb_stops.resolve line for line - same stop, same
    fill rule, same occupancy rule, same pessimistic same-bar SL - so the ONLY
    difference between arms is the target.
    """
    from scripts.poc_sb_stops import stop_price, TTL_BARS
    highs, lows = bars["high"], bars["low"]
    n = len(highs)
    trades = []
    busy_until = -1
    for sig in signals:
        i = sig["bar_idx"]
        if i <= busy_until:
            continue
        entry = sig["entry"]
        sl = stop_price(sig, model)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        is_long = sig["dir"] == "BUY"

        picked = nearest_pool_beyond(pools, entry, risk, is_long, i,
                                     floor_r=1.0, cap_r=5.0)
        if picked is None:
            tp = entry + rr_star * risk if is_long else entry - rr_star * risk
            bound = "fallback"
        else:
            tp, bound = picked

        fill = None
        for k in range(i + 1, min(i + 1 + TTL_BARS, n)):
            if lows[k] <= entry <= highs[k]:
                fill = k
                break
        if fill is None:
            busy_until = min(i + TTL_BARS, n - 1)
            continue

        outcome, r, exit_k = "OPEN", 0.0, n - 1
        tp_r = abs(tp - entry) / risk
        for k in range(fill, n):
            sl_hit = (lows[k] <= sl) if is_long else (highs[k] >= sl)
            tp_hit = (highs[k] >= tp) if is_long else (lows[k] <= tp)
            if sl_hit:
                outcome, r, exit_k = "SL", -1.0, k
                break
            if tp_hit:
                outcome, r, exit_k = "TP", tp_r, k
                break
        busy_until = exit_k
        if outcome in ("SL", "TP"):
            trades.append({**sig, "model": model, "sl": sl, "tp": tp,
                           "risk": risk, "outcome": outcome, "r": r,
                           "fill_idx": fill, "exit_idx": exit_k,
                           "_bound": bound, "_tp_r": tp_r})
    return trades


def run_liq(rr_star, specs, lk=3):
    trades = []
    for sym in SYMS:
        sigs, bars = build(sym)
        if sigs is None:
            continue
        pools = _pools_for(bars, lk=lk)
        for t in resolve_liq(sigs, bars, MODEL, rr_star, pools):
            t["sym"] = sym
            trades.append(t)
    return trades


def bootstrap_diff_ci(a_nets, b_nets):
    """Unpaired bootstrap CI on mean(a) - mean(b). Arms have different n and
    different trade populations, so a paired test is invalid here."""
    import random
    rng = random.Random(BOOTSTRAP_SEED)
    diffs = []
    na, nb = len(a_nets), len(b_nets)
    for _ in range(BOOTSTRAP_N):
        sa = sum(a_nets[rng.randrange(na)] for _ in range(na)) / na
        sb = sum(b_nets[rng.randrange(nb)] for _ in range(nb)) / nb
        diffs.append(sa - sb)
    diffs.sort()
    return diffs[int(0.025 * BOOTSTRAP_N)], diffs[int(0.975 * BOOTSTRAP_N)]
```

- [ ] **Step 2: Add the B2 report function**

Insert above `main()`:

```python
def b2_experiment(rr_star, specs, out):
    p = out.append
    p("=" * 78)
    p("B2 -- LIQUIDITY-ANCHORED TARGET vs FLAT RR* CONTROL")
    p("=" * 78)
    p(f"CONTROL = flat {rr_star:.2f}R.  LIQ = nearest opposing pool,")
    p("floor 1.0R, cap 5.0R, fallback to CONTROL when no pool is in range.")
    p("Criteria were pre-registered before this run:")
    p("  docs/research/2026-08-03-exp2-liquidity-target-preregistration.md")
    p("")

    ctrl = run_flat(rr_star, specs)
    liq = run_liq(rr_star, specs)
    cs, ls = arm_stats(ctrl, specs), arm_stats(liq, specs)

    p(f"  {'CONTROL':10} n={cs['n']:5d}  exp={cs['exp']:+.3f}R  win={cs['win']:4.1f}%")
    p(f"  {'LIQ':10} n={ls['n']:5d}  exp={ls['exp']:+.3f}R  win={ls['win']:4.1f}%")
    diff = ls["exp"] - cs["exp"]
    p(f"  {'DIFF':10} {diff:+.3f}R")
    p("")

    # --- degeneracy diagnostics, declared in advance -----------------------
    nb = len(liq)
    fb = 100.0 * sum(1 for t in liq if t["_bound"] == "fallback") / nb
    fl = 100.0 * sum(1 for t in liq if t["_bound"] == "floor") / nb
    p("DEGENERACY DIAGNOSTICS (can void the arm regardless of its mean)")
    p(f"  fallback share  {fb:5.1f}%   (>50% => LIQ is mostly CONTROL)")
    p(f"  floor-bind share {fl:5.1f}%   (>50% => LIQ is flat 1.0R)")
    p(f"  combined        {fb + fl:5.1f}%   (>65% => INCONCLUSIVE)")
    degenerate = fb > 50 or fl > 50 or (fb + fl) > 65
    p(f"  -> {'DEGENERATE: INCONCLUSIVE' if degenerate else 'readable'}")
    p("")

    lo, hi = bootstrap_diff_ci(ls["nets"], cs["nets"])
    p(f"  bootstrap 95% CI on DIFF: [{lo:+.3f}, {hi:+.3f}]  "
      f"(n={BOOTSTRAP_N}, seed={BOOTSTRAP_SEED})")

    cy, ly = by_year(ctrl, specs), by_year(liq, specs)
    years_pos = [y for y in YEARS if ly[y]["exp"] - cy[y]["exp"] > 0]
    p("  per-year DIFF: " + "  ".join(
        f"{y}:{ly[y]['exp'] - cy[y]['exp']:+.3f}" for y in YEARS))

    csym, lsym = by_symbol(ctrl, specs), by_symbol(liq, specs)
    syms_pos = sum(1 for s in lsym
                   if s in csym and lsym[s]["exp"] - csym[s]["exp"] > 0)
    p(f"  symbols with positive DIFF: {syms_pos}/11")

    st_c = arm_stats(ctrl, specs, 1.5)
    st_l = arm_stats(liq, specs, 1.5)
    stress = st_l["exp"] - st_c["exp"]
    p(f"  1.5x spread stress DIFF: {stress:+.3f}R")
    p("")

    c1 = diff >= 0.05
    c2 = lo > 0
    c3 = len(years_pos) == 4 and syms_pos >= 6
    c4 = stress > 0
    p("GO CRITERIA (all four required)")
    p(f"  1. DIFF >= +0.05R                  {diff:+.3f}   {'PASS' if c1 else 'FAIL'}")
    p(f"  2. bootstrap CI excludes 0         [{lo:+.3f},{hi:+.3f}]  {'PASS' if c2 else 'FAIL'}")
    p(f"  3. all 4 years + >=6/11 symbols    {len(years_pos)}/4, {syms_pos}/11  {'PASS' if c3 else 'FAIL'}")
    p(f"  4. survives 1.5x spread stress     {stress:+.3f}   {'PASS' if c4 else 'FAIL'}")
    p("")
    if degenerate:
        verdict = "INCONCLUSIVE (degenerate arm)"
    else:
        verdict = "GO" if (c1 and c2 and c3 and c4) else "NO-GO"
    p(f"VERDICT: {verdict}")
    p("")

    # lk=5 sensitivity, reported not gated
    liq5 = run_liq(rr_star, specs, lk=5)
    l5 = arm_stats(liq5, specs)
    p(f"SENSITIVITY lk=5 (reported, not gated): n={l5['n']}  "
      f"exp={l5['exp']:+.3f}R  DIFF={l5['exp'] - cs['exp']:+.3f}R")
    p("")
    return verdict
```

- [ ] **Step 3: Wire into `main()`**

Replace `main()`'s body after the A3 block with:

```python
    b2 = []
    verdict = b2_experiment(rr_star, specs, b2)
    text2 = "\n".join(b2)
    print(text2)
    with open(f"{OUTDIR}/b2_experiment.txt", "w") as f:
        f.write(text2 + "\n")
    print(f"\nVERDICT: {verdict}")
```

- [ ] **Step 4: Run it**

Run: `.venv/bin/python scripts/exp2_liquidity_target.py > /tmp/b2.log 2>&1 &`
Expected: A3 block, then B2 with diagnostics, criteria table, and a verdict.

- [ ] **Step 5: Check the diagnostics FIRST**

Read the degeneracy block before reading the verdict. If combined
fallback+floor-bind exceeds 65%, the verdict is INCONCLUSIVE and **the mean is
not to be interpreted or reported as evidence either way** — that is the whole
point of declaring the diagnostic in advance.

- [ ] **Step 6: Write the results doc**

Create `docs/research/2026-08-03-ict-video-rules-results.md` covering, in order:

1. **What was tested and what was dropped** — Rule 4 dropped on EXP-1 evidence (ITT −0.451 to −0.757, n=1889); Rule 5 iFVG deferred as unmotivated.
2. **A1 session buckets** — the inferred broker offset, the four bucket rows, and whether any bucket met the declared 0.10R + sign-stability rule. Note the H1 snapping approximation.
3. **A2 bias agreement** — the numbers *and* the power statement, verbatim. State that no verdict is drawn.
4. **A3 sweep** — the full grid, which challengers qualified, and `RR*`. State explicitly that raw argmax was not used.
5. **B2** — diagnostics first, then criteria table, then verdict.
6. **Known gaps** — copy the spec's "Known gaps" section verbatim, plus anything discovered during the run.

Paste the real numbers from `data/results/exp2_liquidity_target/` and
`data/results/ict_video_reads/`. Do not paraphrase them.

- [ ] **Step 7: Commit**

```bash
git add scripts/exp2_liquidity_target.py \
        docs/research/2026-08-03-ict-video-rules-results.md
git commit -m "research(EXP-2): liquidity-target experiment results"
```

- [ ] **Step 8: Final regression check**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -5`
Expected: `OK`. Check `uptime` load and `ps aux | grep 'unittest discover'` first — a
concurrent suite from another session corrupts both the timing and the result.

---

## Verification Checklist

Before calling this plan done:

- [ ] `data/history/` was never written to (`git status` in the repo root shows no new files under it)
- [ ] Every read pinned `model == "ATR10"`, never `"LIVE"`
- [ ] The `RR=2.00` sweep row reproduced the known ~+0.109R / n≈2217 baseline
- [ ] The pre-registration commit predates the B2 run commit (`git log --oneline`)
- [ ] Degeneracy diagnostics were read before the verdict
- [ ] Full unit suite passes
- [ ] No live-path file changed: `git diff main --stat -- src/core src/execution config/` is empty
