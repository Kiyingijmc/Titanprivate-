# MTF Trend-Pullback v2 — Tier 1 + Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reworked MTF trend-pullback screening PoC (`scripts/poc_mtf_pb2.py`) that decides, net-of-cost and out-of-sample, whether the v2 structural edge exists — at M5 fidelity, per asset-class.

**Architecture:** A new pure-function pipeline mirroring `scripts/poc_mtf_pb.py`, reusing the existing backtest harness (`tests/backtest/backtest_engine.py`) and cost model (`scripts/poc_trend_h4.py`). H4+H1 BOS bias → M15 OTE 0.62–0.79 pullback → liquidity sweep → M5 MSS → entry-TF pressure → OTE∩HTF-POI confluence → entry (two models) → exits (managed + fixed-2.5R comparator) → costs+slippage → per-class gate + funnel + bootstrap CIs. Every step is TDD'd in `tests/unit/test_mtf_pb2.py`.

**Tech Stack:** Python 3.10+, pandas, stdlib `unittest` (no pytest), stdlib `random`/`statistics`. Reuses repo harness functions.

**Spec:** `docs/superpowers/specs/2026-05-30-mtf-trend-pullback-v2-design.md`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `scripts/poc_mtf_pb2.py` | The v2 pipeline: structural primitives, signal builder, managed exit, reporting, `main()` | Create |
| `tests/unit/test_mtf_pb2.py` | Unit tests for every pure function + an end-to-end mini scenario | Create |
| `scripts/poc_mtf_pb.py` | v1 baseline | **Leave untouched** (import generic helpers from it) |
| `tests/backtest/backtest_engine.py` | `simulate_signals`, `aggregate_metrics`, `split_trades`, `win_rate_ci` | Reuse, no change |
| `scripts/poc_trend_h4.py` | `atr_series`, `net_r_after_costs`, `_net`, `SPREAD`, specs loading | Reuse, no change |

**Reuse (DRY) from `scripts/poc_mtf_pb.py`:** `resample_tf`, `last_closed_indexer`, `combine_bias_lists`, `_is_swing_high`, `_is_swing_low`. These are strategy-agnostic and already tested in `tests/unit/test_mtf_pb.py`.

---

## Prerequisite (operational, NOT code — run when ready, does not block the build)

The headline verdict needs more than the current ~3 months of M5. When the live MT5 + Gateway EA is up and `main.py` is **stopped** (shared ZMQ ports), pull the maximum M5 FBS returns, per symbol:

```bash
for S in EURUSD GBPUSD USDJPY AUDUSD USDCAD GBPCAD GBPJPY XAUUSD US30 BTCUSD XBRUSD; do
  .venv/bin/python scripts/export_history.py --symbol "$S" --tf M5 --count 200000 \
    --out "data/history/${S}_M5.csv"
done
```

Record the actual span returned (it will be < 200k if the broker caps it). **All tasks below run on whatever M5 is on disk** — build now on the existing data; re-run `main()` after the bigger pull for the real verdict.

---

## Task 1: Scaffold the module + structure-based bias

**Files:**
- Create: `scripts/poc_mtf_pb2.py`
- Create: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mtf_pb2.py
import os, sys, unittest
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_mtf_pb2 as m2


def _zigzag(up=True):
    # lk=1 zigzag: ascending (HH+HL) when up=True, descending (LH+LL) when up=False
    h = [5, 7, 4, 9, 6, 11, 8, 13, 10]
    l = [3, 5, 2, 6, 4, 8, 6, 10, 8]
    if not up:
        h = [-x for x in reversed(h)]
        l = [-x for x in reversed(l)]
        h, l = [-x for x in l], [-x for x in h]  # keep high>=low after mirroring
    return pd.DataFrame({"open": h, "high": h, "low": l, "close": h})


class StructureBias(unittest.TestCase):
    def test_bullish_when_hh_and_hl(self):
        df = _zigzag(up=True)
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(len(bias), len(df))
        self.assertEqual(bias[-1], "BULLISH")

    def test_neutral_during_warmup(self):
        df = _zigzag(up=True)
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(bias[0], "NEUTRAL")  # no confirmed swings yet


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.poc_mtf_pb2'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2 -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): mtf-pb v2 scaffold + structure-based BOS bias (TDD)"
```

---

## Task 2: Combined H4+H1 bias (no look-ahead)

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class CombinedBias(unittest.TestCase):
    def test_requires_both_htf_agree(self):
        # 5m bars hourly-spaced; H4 & H1 both built from the same rising frame -> BULLISH tail.
        rows = []
        price = 1.0
        for k in range(600):
            price += 0.01
            ts = pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * k)
            rows.append({"datetime": str(ts), "open": price, "high": price + 0.02,
                         "low": price - 0.02, "close": price})
        m5 = pd.DataFrame(rows)
        h4 = m2.resample_tf(m5, "4h")
        h1 = m2.resample_tf(m5, "1h")
        bias = m2.combined_structure_bias(m5, h4, h1, lk=2)
        self.assertEqual(len(bias), len(m5))
        self.assertIn(bias[-1], ("BULLISH", "NEUTRAL"))  # never BEARISH on a pure uptrend
        self.assertNotEqual(bias[-1], "BEARISH")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.CombinedBias -v`
Expected: FAIL — `AttributeError: module 'scripts.poc_mtf_pb2' has no attribute 'combined_structure_bias'`

- [ ] **Step 3: Write minimal implementation**

```python
def combined_structure_bias(m5_df, h4, h1, lk=3):
    """Per-5m-bar combined H4+H1 BOS bias, using only closed HTF bars (no look-ahead).
    Reuses v1's last_closed_indexer + combine_bias_lists."""
    tcol = "time" if "time" in m5_df.columns else "datetime"
    m5t = list(pd.to_datetime(m5_df[tcol]))
    idx4 = last_closed_indexer(m5t, list(pd.to_datetime(h4["time"])), 4)
    idx1 = last_closed_indexer(m5t, list(pd.to_datetime(h1["time"])), 1)
    return combine_bias_lists(structure_bias(h4, lk), structure_bias(h1, lk), idx4, idx1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.CombinedBias -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): combined H4+H1 BOS bias with closed-bar indexing (TDD)"
```

---

## Task 3: M15 impulse leg + OTE zone

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class ImpulseLegAndOTE(unittest.TestCase):
    def setUp(self):
        self.highs = [5, 7, 4, 9, 6, 11, 8, 13, 10]
        self.lows = [3, 5, 2, 6, 4, 8, 6, 10, 8]

    def test_bull_leg_is_most_recent_bos_up(self):
        leg = m2.impulse_leg(self.highs, self.lows, upto=8, lk=1, bias="BULLISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high, lo_idx, hi_idx = leg
        self.assertEqual(leg_high, 13)   # BOS up high
        self.assertEqual(leg_low, 6)     # most recent confirmed swing low before it (idx 6)
        self.assertEqual((lo_idx, hi_idx), (6, 7))

    def test_no_leg_when_bias_neutral(self):
        self.assertIsNone(m2.impulse_leg(self.highs, self.lows, 8, 1, "NEUTRAL"))

    def test_ote_zone_bull(self):
        z_lo, z_hi = m2.ote_zone(6, 13, "BULLISH")  # rng=7
        self.assertAlmostEqual(z_hi, 13 - 0.62 * 7, places=6)
        self.assertAlmostEqual(z_lo, 13 - 0.79 * 7, places=6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.ImpulseLegAndOTE -v`
Expected: FAIL — `AttributeError: ... has no attribute 'impulse_leg'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.ImpulseLegAndOTE -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): M15 impulse-leg (BOS) detector + OTE 0.62-0.79 zone (TDD)"
```

---

## Task 4: FVG detection + qualifying OTE-leg FVG

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class FVG(unittest.TestCase):
    def test_find_bullish_fvg(self):
        bars = [{"open": 1, "high": 2, "low": 1, "close": 2},   # c1 high=2
                {"open": 2, "high": 5, "low": 2, "close": 5},   # displacement
                {"open": 4, "high": 6, "low": 3, "close": 5}]   # c3 low=3 > c1 high=2 -> gap
        self.assertEqual(m2.find_fvg(bars, 2, "BULLISH"), (2, 3))

    def test_no_fvg_when_no_gap(self):
        bars = [{"open": 1, "high": 4, "low": 1, "close": 3},
                {"open": 3, "high": 5, "low": 2, "close": 4},
                {"open": 4, "high": 6, "low": 3, "close": 5}]   # c3 low=3 < c1 high=4
        self.assertIsNone(m2.find_fvg(bars, 2, "BULLISH"))

    def test_qualifying_fvg_needs_30pct_in_zone(self):
        # leg bars containing one bullish FVG gap (10, 14); zone (12, 20) -> overlap (12,14)=2
        # of size 4 -> 50% >= 30% -> qualifies.
        leg = [{"open": 8, "high": 10, "low": 8, "close": 10},
               {"open": 10, "high": 16, "low": 10, "close": 16},
               {"open": 15, "high": 18, "low": 14, "close": 17}]
        self.assertEqual(m2.qualifying_fvg(leg, (12, 20), "BULLISH"), (10, 14))

    def test_qualifying_fvg_rejected_when_below_threshold(self):
        leg = [{"open": 8, "high": 10, "low": 8, "close": 10},
               {"open": 10, "high": 16, "low": 10, "close": 16},
               {"open": 15, "high": 18, "low": 14, "close": 17}]
        # zone (13.5, 20): overlap (13.5,14)=0.5 of size 4 = 12.5% < 30% -> None
        self.assertIsNone(m2.qualifying_fvg(leg, (13.5, 20), "BULLISH"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.FVG -v`
Expected: FAIL — `AttributeError: ... has no attribute 'find_fvg'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.FVG -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): FVG detection + qualifying OTE-leg FVG (>=30% in zone) (TDD)"
```

---

## Task 5: Liquidity sweep + M5 MSS

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class SweepAndMSS(unittest.TestCase):
    def test_sweep_detects_breached_swing_low(self):
        # lows form a minor swing low at idx 2 (val 4), later bar dips to 3 -> swept.
        highs = [10, 9, 8, 9, 10, 11]
        lows = [7, 6, 4, 6, 3, 5]
        swept, extreme = m2.swept_liquidity(lows, highs, 0, 5, "BULLISH", lk=1)
        self.assertTrue(swept)
        self.assertEqual(extreme, 3)

    def test_no_sweep_when_holds_above(self):
        highs = [10, 9, 8, 9, 10, 11]
        lows = [7, 6, 4, 6, 5, 6]   # never below the 4 swing low
        swept, _ = m2.swept_liquidity(lows, highs, 0, 5, "BULLISH", lk=1)
        self.assertFalse(swept)

    def test_mss_confirms_when_close_breaks_swing_high(self):
        # swing high at idx 2 (val 8); bar 5 closes 9 > 8 -> MSS up.
        highs = [5, 6, 8, 6, 5, 9]
        lows = [3, 4, 6, 4, 3, 7]
        closes = [4, 5, 7, 5, 4, 9]
        confirmed, lvl = m2.mss_confirm(highs, lows, closes, i=5, bias="BULLISH", lk=1)
        self.assertTrue(confirmed)
        self.assertIsInstance(lvl, (int, float))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.SweepAndMSS -v`
Expected: FAIL — `AttributeError: ... has no attribute 'swept_liquidity'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.SweepAndMSS -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): liquidity-sweep detector + M5 MSS/CHoCH confirm (TDD)"
```

---

## Task 6: Displacement, micro-BOS & pressure test

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class Pressure(unittest.TestCase):
    def test_displacement_candle(self):
        med = 1.0
        strong = {"open": 10, "high": 12, "low": 9.8, "close": 11.9}  # body 1.9 of range 2.2
        weak = {"open": 10, "high": 12, "low": 9.8, "close": 10.2}    # tiny body
        self.assertTrue(m2.is_displacement(strong, med, "BULLISH"))
        self.assertFalse(m2.is_displacement(weak, med, "BULLISH"))

    def test_pressure_true_on_displacement_fvg(self):
        # bar i leaves a bullish FVG (c1.high < c3.low) -> pressure ok regardless of body.
        bars = [{"open": 1, "high": 2, "low": 1, "close": 2},
                {"open": 2, "high": 5, "low": 2, "close": 5},
                {"open": 4, "high": 6, "low": 3, "close": 5}]
        highs = [b["high"] for b in bars]; lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        self.assertTrue(m2.pressure_ok(bars, highs, lows, closes, 2, "BULLISH", lk=1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.Pressure -v`
Expected: FAIL — `AttributeError: ... has no attribute 'is_displacement'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.Pressure -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): displacement candle, micro-BOS, entry-TF pressure test (TDD)"
```

---

## Task 7: HTF-POI confluence

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class Confluence(unittest.TestCase):
    def _htf(self, fvg=True):
        # 3 H1 bars leaving a bullish FVG gap (high0=2 < low2=3) when fvg=True.
        low2 = 3 if fvg else 1
        rows = [{"time": "2026-01-01 00:00:00", "open": 1, "high": 2, "low": 1, "close": 2},
                {"time": "2026-01-01 01:00:00", "open": 2, "high": 5, "low": 2, "close": 5},
                {"time": "2026-01-01 02:00:00", "open": 4, "high": 6, "low": low2, "close": 5}]
        return pd.DataFrame(rows)

    def test_overlap_true_when_zone_hits_h1_fvg(self):
        h1 = self._htf(fvg=True)
        h4 = self._htf(fvg=True)
        t = pd.Timestamp("2026-01-01 05:00:00")     # after the H1 bars closed
        self.assertTrue(m2.htf_poi_overlap((2.4, 2.9), h1, h4, t, "BULLISH", lk=1))

    def test_overlap_false_when_zone_misses(self):
        h1 = self._htf(fvg=True)
        h4 = self._htf(fvg=True)
        t = pd.Timestamp("2026-01-01 05:00:00")
        self.assertFalse(m2.htf_poi_overlap((100.0, 101.0), h1, h4, t, "BULLISH", lk=1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.Confluence -v`
Expected: FAIL — `AttributeError: ... has no attribute 'htf_poi_overlap'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.Confluence -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): OTE n H1/H4 POI confluence (FVG + swing levels) (TDD)"
```

---

## Task 8: Conditional stop-loss

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class ConditionalStop(unittest.TestCase):
    def test_fvg_present_not_swept_uses_leg_origin(self):
        s = m2.conditional_stop("BULLISH", leg_low=6.0, leg_high=13.0, qfvg=(7.0, 8.0),
                                fully_swept=False, sweep_extreme=None, mss_level=9.0)
        self.assertEqual(s, 6.0)

    def test_fvg_present_swept_uses_sweep_extreme(self):
        s = m2.conditional_stop("BULLISH", 6.0, 13.0, qfvg=(7.0, 8.0),
                                fully_swept=True, sweep_extreme=6.7, mss_level=9.0)
        self.assertEqual(s, 6.7)

    def test_no_fvg_uses_mss_level(self):
        s = m2.conditional_stop("BULLISH", 6.0, 13.0, qfvg=None,
                                fully_swept=False, sweep_extreme=None, mss_level=9.0)
        self.assertEqual(s, 9.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.ConditionalStop -v`
Expected: FAIL — `AttributeError: ... has no attribute 'conditional_stop'`

- [ ] **Step 3: Write minimal implementation**

```python
def conditional_stop(bias, leg_low, leg_high, qfvg, fully_swept, sweep_extreme, mss_level):
    """The M5-structure stop level per the spec's decision table:
      - qualifying FVG present, NOT fully swept -> OTE leg origin
      - qualifying FVG present, fully swept     -> swept extreme
      - no qualifying FVG                       -> M5 MSS swing level"""
    if qfvg is not None and not fully_swept:
        return leg_low if bias == "BULLISH" else leg_high
    if qfvg is not None and fully_swept:
        return sweep_extreme
    return mss_level
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.ConditionalStop -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): conditional M5-structure stop-loss decision table (TDD)"
```

---

## Task 9: Managed exit simulator (TP1 → 33% + BE → trail → TP2)

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

The managed model books 33% at TP1 and moves to breakeven, then trails the 67% runner by the
most recent M5 higher-low (bull) / lower-high (bear) — activated **after** TP1 — with TP2 as the
final target. Same-bar stop+target → stop wins (conservative). Blended R is volume-weighted:
`0.33 * R(TP1) + 0.67 * R(runner exit)`.

- [ ] **Step 1: Write the failing test**

```python
class ManagedExit(unittest.TestCase):
    def test_tp1_then_runner_hits_tp2(self):
        # long: entry 100, stop 95 (risk 5), TP1 105 (=+1R internal), TP2 115 (+3R external).
        sig = {"bar_idx": 0, "dir": "BUY", "entry": 100.0, "sl": 95.0, "risk": 5.0,
               "tp1": 105.0, "tp2": 115.0}
        bars = [{"open": 100, "high": 100, "low": 100, "close": 100},
                {"open": 101, "high": 106, "low": 100, "close": 105},   # TP1 hit
                {"open": 106, "high": 112, "low": 104, "close": 111},   # higher-low forms
                {"open": 112, "high": 116, "low": 110, "close": 115}]   # TP2 hit
        trades = m2.simulate_managed([sig], bars)
        self.assertEqual(len(trades), 1)
        # 0.33*(1.0) + 0.67*((115-100)/5 = 3.0) = 0.33 + 2.01 = 2.34
        self.assertAlmostEqual(trades[0]["r"], 0.33 * 1.0 + 0.67 * 3.0, places=6)
        self.assertEqual(trades[0]["outcome"], "TP")

    def test_full_stop_before_tp1(self):
        sig = {"bar_idx": 0, "dir": "BUY", "entry": 100.0, "sl": 95.0, "risk": 5.0,
               "tp1": 105.0, "tp2": 115.0}
        bars = [{"open": 100, "high": 100, "low": 100, "close": 100},
                {"open": 99, "high": 100, "low": 94, "close": 95}]      # stop hit, no partial
        trades = m2.simulate_managed([sig], bars)
        self.assertAlmostEqual(trades[0]["r"], -1.0, places=6)
        self.assertEqual(trades[0]["outcome"], "SL")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.ManagedExit -v`
Expected: FAIL — `AttributeError: ... has no attribute 'simulate_managed'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.ManagedExit -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): managed exit sim (TP1->33%+BE->M5 trail->TP2) (TDD)"
```

---

## Task 10: MAE/MFE + bootstrap CIs + slippage cost wrapper

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class Diagnostics(unittest.TestCase):
    def test_mae_mfe_long(self):
        sig = {"dir": "BUY", "entry": 100.0, "risk": 5.0, "entry_idx": 0, "exit_idx": 2}
        bars = [{"open": 100, "high": 101, "low": 98, "close": 100},   # MAE -2 -> -0.4R
                {"open": 100, "high": 110, "low": 99, "close": 108},   # MFE +10 -> +2.0R
                {"open": 108, "high": 109, "low": 107, "close": 108}]
        mae, mfe = m2.mae_mfe(sig, bars)
        self.assertAlmostEqual(mae, -0.4, places=6)
        self.assertAlmostEqual(mfe, 2.0, places=6)

    def test_bootstrap_ci_is_ordered_and_brackets_mean(self):
        rs = [1.0, -1.0, 1.0, -1.0, 2.0, -1.0, 1.0, -1.0, 1.0, -1.0]
        lo, hi = m2.bootstrap_expectancy_ci(rs, n_boot=500, seed=1)
        self.assertLess(lo, hi)
        mean = sum(rs) / len(rs)
        self.assertTrue(lo <= mean <= hi)

    def test_net_with_slippage_charges_more_than_zero(self):
        t = {"r": 2.0, "entry": 100.0, "sl": 95.0, "outcome": "TP"}
        out = m2.net_with_slippage([dict(t)], "XAUUSD", slip_frac=0.05)
        self.assertLess(out[0]["r"], 2.0)        # cost + slippage reduce R
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.Diagnostics -v`
Expected: FAIL — `AttributeError: ... has no attribute 'mae_mfe'`

- [ ] **Step 3: Write minimal implementation**

```python
import random as _random  # add to the import block at the top of the module


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
    top of the 2x spread + commission. slip_frac models entering into displacement."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.Diagnostics -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): MAE/MFE, bootstrap CI, slippage cost wrapper (TDD)"
```

---

## Task 11: Signal builder (compose pipeline, both entry models, funnel, baseline)

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

`build_signals` walks M5 bars and, per bar, maps to the current M15 leg, checks arming/sweep/
MSS/pressure/confluence, and on a full pass emits **two** signal dicts (`entry_model` =
`"market"` at next-bar open; `"limit"` resting at the displacement-FVG midpoint with a TTL). It
returns `(signals, funnel)`. Flags `require_sweep` / `require_confluence` let the same code
produce the **unfiltered baseline** (both False). The test drives a hand-built scenario and only
asserts the funnel mechanics + that a market signal carries the required fields — the heavy
correctness comes from the per-primitive tests above and the end-to-end smoke run in Task 13.

- [ ] **Step 1: Write the failing test**

```python
class BuildSignals(unittest.TestCase):
    def test_returns_signals_and_funnel_keys(self):
        # Minimal monotonic uptrend frame; we assert structure of outputs, not trade count.
        rows = []
        price = 100.0
        for k in range(800):
            price += 0.05 if (k % 20) < 15 else -0.03   # drifts up with pullbacks
            ts = pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * k)
            rows.append({"datetime": str(ts), "open": price, "high": price + 0.1,
                         "low": price - 0.1, "close": price})
        m5 = pd.DataFrame(rows)
        sigs, funnel = m2.build_signals(m5, require_sweep=False, require_confluence=False)
        self.assertIsInstance(sigs, list)
        for key in ("bias", "leg", "armed", "sweep", "mss", "pressure", "confluence", "emitted"):
            self.assertIn(key, funnel)
        for s in sigs:
            self.assertIn(s["entry_model"], ("market", "limit"))
            for f in ("bar_idx", "dir", "cmd", "entry", "sl", "tp1", "tp2", "risk"):
                self.assertIn(f, s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.BuildSignals -v`
Expected: FAIL — `AttributeError: ... has no attribute 'build_signals'`

- [ ] **Step 3: Write minimal implementation**

```python
def _nearest_internal(highs, lows, entry_bar, bias, leg_high, leg_low, lk=2):
    """TP1 = nearest opposing minor swing beyond entry (bull: nearest confirmed swing high
    above entry, below leg_high). Falls back to the leg extreme if none."""
    his, los = confirmed_swing_seq(highs[:entry_bar], lows[:entry_bar], lk)
    if bias == "BULLISH":
        cands = sorted(highs[j] for j in his if highs[j] > highs[entry_bar - 1])
        return next((p for p in cands if p < leg_high), leg_high)
    cands = sorted((lows[j] for j in los if lows[j] < lows[entry_bar - 1]), reverse=True)
    return next((p for p in cands if p > leg_low), leg_low)


def build_signals(m5_df, lk_htf=3, lk_m15=2, lk_m5=2, require_sweep=True,
                  require_confluence=True):
    """Compose the full v2 pipeline over M5 bars. Returns (signals, funnel_counts).
    Emits two signals per qualifying bar (entry_model 'market' and 'limit'). Set
    require_sweep / require_confluence False for the unfiltered core-thesis baseline."""
    tcol = "time" if "time" in m5_df.columns else "datetime"
    m5t = list(pd.to_datetime(m5_df[tcol]))
    h4 = resample_tf(m5_df, "4h")
    h1 = resample_tf(m5_df, "1h")
    m15 = resample_tf(m5_df, "15min")
    bias_list = combined_structure_bias(m5_df, h4, h1, lk_htf)

    bars = m5_df[["open", "high", "low", "close"]].to_dict("records")
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    n = len(bars)

    # Map each M5 bar to the most recent CLOSED M15 bar.
    idx15 = last_closed_indexer(m5t, list(pd.to_datetime(m15["time"])), 0.25)
    m15h = list(m15["high"].values)
    m15l = list(m15["low"].values)
    m15_recs = m15[["open", "high", "low", "close"]].to_dict("records")
    m15_close_times = [t + pd.Timedelta(minutes=15) for t in pd.to_datetime(m15["time"])]

    funnel = dict(bias=0, leg=0, armed=0, sweep=0, mss=0, pressure=0, confluence=0, emitted=0)
    sigs = []
    cur_leg_key = None
    armed = False
    pullback_low = pullback_high = None
    pb_start = 0

    for i in range(lk_m5 + 2, n - 1):
        bias = bias_list[i]
        if bias == "NEUTRAL":
            continue
        funnel["bias"] += 1
        j15 = idx15[i]
        if j15 < lk_m15 + 1:
            continue
        leg = impulse_leg(m15h, m15l, j15, lk_m15, bias)
        if leg is None:
            continue
        funnel["leg"] += 1
        leg_low, leg_high, lo15, hi15 = leg
        zone = ote_zone(leg_low, leg_high, bias)
        z_lo, z_hi = zone

        key = (bias, hi15, lo15)
        if key != cur_leg_key:                       # new leg -> reset arming state
            cur_leg_key = key
            armed = False
            pullback_low, pullback_high = lows[i], highs[i]
            # pullback window starts at the M5 bar nearest the M15 leg extreme close
            ext_t = m15_close_times[hi15] if bias == "BULLISH" else m15_close_times[lo15]
            pb_start = max(0, bisect.bisect_left(m5t, ext_t))
        pullback_low = min(pullback_low, lows[i])
        pullback_high = max(pullback_high, highs[i])

        # invalidation: close beyond the leg origin
        if (bias == "BULLISH" and closes[i] < leg_low) or \
           (bias == "BEARISH" and closes[i] > leg_high):
            armed = False
            continue
        tagged = (lows[i] <= z_hi) if bias == "BULLISH" else (highs[i] >= z_lo)
        if tagged:
            armed = True
        if not armed:
            continue
        funnel["armed"] += 1

        swept, sweep_ext = swept_liquidity(lows, highs, pb_start, i, bias, lk_m5)
        if require_sweep and not swept:
            continue
        funnel["sweep"] += 1

        mss, mss_level = mss_confirm(highs, lows, closes, i, bias, lk_m5)
        if not mss:
            continue
        funnel["mss"] += 1

        if not pressure_ok(bars, highs, lows, closes, i, bias, lk_m5):
            continue
        funnel["pressure"] += 1

        if require_confluence and not htf_poi_overlap(zone, h1, h4, m5t[i], bias, lk_htf):
            continue
        funnel["confluence"] += 1

        # qualifying OTE-leg FVG (stop logic) on the M15 leg bars [lo15..hi15] inclusive
        leg_bars = m15_recs[min(lo15, hi15):max(lo15, hi15) + 1]
        qfvg = qualifying_fvg(leg_bars, zone, bias)
        fully_swept = False
        if qfvg is not None:
            fully_swept = (pullback_low < qfvg[0]) if bias == "BULLISH" else (pullback_high > qfvg[1])
        stop = conditional_stop(bias, leg_low, leg_high, qfvg, fully_swept, sweep_ext, mss_level)

        entry = bars[i + 1]["open"]
        risk = abs(entry - stop)
        if not (risk > 0):
            continue
        tp2 = leg_high if bias == "BULLISH" else leg_low          # external liquidity
        tp1 = _nearest_internal(highs, lows, i + 1, bias, leg_high, leg_low, lk_m5)
        d = "BUY" if bias == "BULLISH" else "SELL"
        funnel["emitted"] += 1

        # entry model A: market at next-bar open
        sigs.append({"bar_idx": i + 1, "entry_model": "market", "dir": d, "cmd": "MARKET",
                     "entry": entry, "sl": stop, "tp1": tp1, "tp2": tp2, "risk": risk,
                     "tp": tp2, "ttl_bars": 1})
        # entry model B: limit at the displacement-FVG midpoint (fallback: the 0.705 level)
        dfvg = find_fvg(bars, i, bias) or find_fvg(bars, i - 1, bias)
        limit_px = ((dfvg[0] + dfvg[1]) / 2.0) if dfvg else (z_lo + z_hi) / 2.0
        lrisk = abs(limit_px - stop)
        if lrisk > 0:
            sigs.append({"bar_idx": i + 1, "entry_model": "limit", "dir": d, "cmd": "LIMIT",
                         "entry": limit_px, "sl": stop, "tp1": tp1, "tp2": tp2, "risk": lrisk,
                         "tp": tp2, "ttl_bars": 6})
    return sigs, funnel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.BuildSignals -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): v2 signal builder — compose pipeline, 2 entry models, funnel (TDD)"
```

---

## Task 12: Per-symbol run + per-class report + funnel + baseline + main()

**Files:**
- Modify: `scripts/poc_mtf_pb2.py`
- Test: `tests/unit/test_mtf_pb2.py`

- [ ] **Step 1: Write the failing test**

```python
class RunSymbol(unittest.TestCase):
    def test_run_symbol_returns_both_models_and_funnel(self):
        rows = []
        price = 100.0
        for k in range(900):
            price += 0.05 if (k % 20) < 15 else -0.03
            ts = pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * k)
            rows.append({"datetime": str(ts), "open": price, "high": price + 0.1,
                         "low": price - 0.1, "close": price})
        out = m2.run_symbol(pd.DataFrame(rows))
        for key in ("market_fixed", "market_managed", "limit_fixed", "limit_managed",
                    "funnel", "baseline_funnel"):
            self.assertIn(key, out)
        self.assertIsInstance(out["market_fixed"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.RunSymbol -v`
Expected: FAIL — `AttributeError: ... has no attribute 'run_symbol'`

- [ ] **Step 3: Write minimal implementation**

```python
ASSET_CLASSES = {
    "FX-majors": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
    "FX-crosses": ["GBPCAD", "GBPJPY"],
    "metals": ["XAUUSD"],
    "index": ["US30"],
    "crypto": ["BTCUSD"],
    "energy": ["XBRUSD"],
}
SYMS = [s for syms in ASSET_CLASSES.values() for s in syms]


def asset_class_of(sym):
    for cls, syms in ASSET_CLASSES.items():
        if sym in syms:
            return cls
    return "other"


def _split_by_model(sigs):
    return ([s for s in sigs if s["entry_model"] == "market"],
            [s for s in sigs if s["entry_model"] == "limit"])


def run_symbol(m5_df):
    """Full v2 pipeline for one symbol's M5 frame. Returns resolved (pre-cost) trades for
    the 2x2 entry/exit matrix, plus the filtered + baseline funnels."""
    bars = m5_df[["open", "high", "low", "close"]].to_dict("records")
    sigs, funnel = build_signals(m5_df, require_sweep=True, require_confluence=True)
    _, base_funnel = build_signals(m5_df, require_sweep=False, require_confluence=False)
    mkt, lim = _split_by_model(sigs)
    return {
        "market_fixed": bt.simulate_signals(mkt, bars),
        "market_managed": simulate_managed(mkt, bars),
        "limit_fixed": bt.simulate_signals(lim, bars),
        "limit_managed": simulate_managed(lim, bars),
        "funnel": funnel,
        "baseline_funnel": base_funnel,
    }


def _report(title, by_class):
    """Per-class + pooled net-of-cost metrics, Wilson CI, bootstrap CI, OOS expectancy."""
    print(f"\n===== {title} (NET OF COSTS + SLIPPAGE) =====")
    pooled = []
    for cls in list(ASSET_CLASSES) + ["POOLED-ALL"]:
        trades = pooled if cls == "POOLED-ALL" else by_class.get(cls, [])
        if cls != "POOLED-ALL":
            pooled += trades
        m = bt.aggregate_metrics(trades)
        p, lo, hi = bt.win_rate_ci(m["wins"], m["trades"])
        norm = [{**t, "bar_idx": t.get("bar_idx", t.get("entry_idx", 0))} for t in trades]
        train, test = bt.split_trades(norm, 0.7)
        mtr, mte = bt.aggregate_metrics(train), bt.aggregate_metrics(test)
        rs = [t["r"] for t in trades if t["outcome"] in ("TP", "SL")]
        blo, bhi = bootstrap_expectancy_ci(rs, seed=1)
        flag = "  [INSUFFICIENT n<30]" if m["trades"] < 30 else ""
        print(f"  {cls:12} n={m['trades']:4d} win={p*100:4.1f}% CI[{lo*100:.0f}-{hi*100:.0f}] "
              f"netExpR={m['expectancy']:+.3f} bootCI[{blo:+.2f},{bhi:+.2f}] PF={m['profit_factor']:.2f} "
              f"DD={m['max_drawdown_r']:.0f}R | TRAIN exp={mtr['expectancy']:+.3f} "
              f"TEST n={mte['trades']} exp={mte['expectancy']:+.3f}{flag}")


def _funnel_report(title, funnels):
    print(f"\n----- {title} (setup funnel, summed) -----")
    keys = ["bias", "leg", "armed", "sweep", "mss", "pressure", "confluence", "emitted"]
    agg = {k: sum(f.get(k, 0) for f in funnels) for k in keys}
    print("  " + "  ".join(f"{k}={agg[k]}" for k in keys))


def main():
    classes = {k: {} for k in ("market_fixed", "market_managed", "limit_fixed", "limit_managed")}
    funnels, base_funnels = [], []
    for sym in SYMS:
        path = f"data/history/{sym}_M5.csv"
        if not os.path.exists(path):
            continue
        res = run_symbol(pd.read_csv(path))
        cls = asset_class_of(sym)
        for model in classes:
            costed = net_with_slippage(res[model], sym)
            classes[model].setdefault(cls, []).extend(costed)
        funnels.append(res["funnel"])
        base_funnels.append(res["baseline_funnel"])
    print("MTF-PB v2 -- H4+H1 BOS bias, M15 OTE pullback, sweep, M5 MSS, pressure, HTF-POI")
    _funnel_report("FILTERED", funnels)
    _funnel_report("UNFILTERED BASELINE", base_funnels)
    _report("MARKET entry / FIXED-2.5R", classes["market_fixed"])
    _report("MARKET entry / MANAGED", classes["market_managed"])
    _report("LIMIT entry / FIXED-2.5R (uplift, not gated)", classes["limit_fixed"])
    _report("LIMIT entry / MANAGED (uplift, not gated)", classes["limit_managed"])


if __name__ == "__main__":
    main()
```

Note: `simulate_signals` resolves the fixed model via each signal's `tp` (= `tp2`). The managed
model uses `tp1`/`tp2` directly. The gate reads the **MARKET** blocks; LIMIT blocks are uplift.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb2.RunSymbol -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb2.py tests/unit/test_mtf_pb2.py
git commit -m "feat(poc): per-symbol run, per-class + funnel + bootstrap report, main (TDD)"
```

---

## Task 13: Full suite + end-to-end smoke run on existing data

**Files:**
- Test: `tests/unit/test_mtf_pb2.py` (add a smoke test)

- [ ] **Step 1: Add an end-to-end smoke test (skips if data absent)**

```python
class EndToEndSmoke(unittest.TestCase):
    def test_runs_on_real_csv_if_present(self):
        path = "data/history/XAUUSD_M5.csv"
        if not os.path.exists(path):
            self.skipTest("no history on disk")
        out = m2.run_symbol(pd.read_csv(path))
        # pipeline must complete and produce list outputs + a populated funnel
        self.assertIsInstance(out["market_managed"], list)
        self.assertGreaterEqual(out["funnel"]["bias"], 0)
```

- [ ] **Step 2: Run the full unit suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: PASS (all v1 + v2 tests; v2 smoke runs or skips)

- [ ] **Step 3: Run the pipeline end-to-end on whatever M5 is on disk**

Run: `.venv/bin/python scripts/poc_mtf_pb2.py | tee data/history/mtf_pb2_poc.txt`
Expected: prints FILTERED + UNFILTERED funnels and the four entry/exit report blocks without error. (On the thin ~3-month data, expect small `n` and `[INSUFFICIENT n<30]` flags — that is informative, not a failure.)

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_mtf_pb2.py data/history/mtf_pb2_poc.txt
git commit -m "test(poc): v2 end-to-end smoke + capture first run output"
```

---

## Task 14: Results write-up + GO/NO-GO verdict

**Files:**
- Create: `docs/research/2026-05-30-mtf-pb-v2-results.md`

- [ ] **Step 1: After the max-M5 export (prerequisite) + a fresh `main()` run, record results**

Capture, per asset class, under **both exit models on the MARKET entry**: `n`, win% + Wilson CI, net expectancy + bootstrap CI, PF, max-DD, and TRAIN vs TEST expectancy. Include the FILTERED vs UNFILTERED funnel counts and the LIMIT-entry uplift blocks.

- [ ] **Step 2: State the verdict against the spec gate**

GO (per class) iff net expectancy positive in BOTH train and test, `n≥30`, under BOTH exit models, on the MARKET entry. Otherwise NO-GO / inconclusive. Note any class killed purely by filter starvation (compare FILTERED vs UNFILTERED funnel + baseline expectancy) and the LIMIT-entry uplift. Be explicit about multiple-comparisons caution: a single surviving class is a lead, not proof.

- [ ] **Step 3: Commit**

```bash
git add docs/research/2026-05-30-mtf-pb-v2-results.md
git commit -m "docs(research): MTF-PB v2 Tier-1 results + GO/NO-GO verdict"
```

---

## Tier 2 (DEFERRED — its own plan)

Do **not** build Tier 2 here. Write `docs/superpowers/plans/<date>-mtf-trend-pullback-v2-tier2.md` **only when both** are true: (1) Tier 1 returns GO (or a defensible lead) for at least one class, **and** (2) M1 history has been exported (requires extending `export_history.py` `--tf` to accept `M1` and verifying the EA passes `PERIOD_M1`). Tier 2 measures the M1/M2 entry-refinement (better entry vs the **same** M5 stop): R-uplift minus added cost-in-R, strictly subordinate to the Tier-1 verdict, thin-sample caveated. Building it now is speculative (YAGNI) — the M1 data shape and whether any class even passes Tier 1 are both unknown.

---

## Self-review notes (author)

- **Spec coverage:** bias (T1–2), M15 leg+OTE (T3), FVG/qualifying (T4), sweep+MSS (T5), pressure (T6), HTF-POI confluence (T7), conditional stop (T8), managed exit (T9), MAE/MFE+bootstrap+slippage (T10), two entry models + funnel + baseline (T11), per-class gate + report + main (T12), suite+smoke (T13), results+verdict (T14). Tier 2 deferred by design. Diagnostics "session/regime report-only" was NOT selected by the user and is intentionally omitted.
- **Type/name consistency:** signal dicts carry `bar_idx,dir,cmd,entry,sl,tp,tp1,tp2,risk,entry_model,ttl_bars`; `simulate_signals` (fixed) reads `tp`, `simulate_managed` reads `tp1/tp2`; cost wrapper mutates `r`+`outcome`; funnel keys fixed across builder/report.
- **Known approximations (intentional, documented):** internal-liquidity TP1 and HTF-POI/OB definitions are objective proxies; `structure_bias` uses a two-swing HH/HL test; the limit-entry fill uses `resolve_trade`'s LIMIT+TTL path. These are screening-grade by design and pinned by tests.
