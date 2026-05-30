# MTF Trend-Pullback PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cost-validated proof-of-concept for an MTF trend-pullback strategy (4H+1H 50-EMA bias → 5m fib pullback + confirmation-close entry → 1.0×ATR(1H) structural stop → two exit models), and screen it for a net-of-cost, out-of-sample edge across asset classes.

**Architecture:** One new script `scripts/poc_mtf_pb.py` of small pure functions (TDD-first), reusing the offline harness (`tests/backtest/backtest_engine.py`: `simulate_signals`, `aggregate_metrics`, `split_trades`, `win_rate_ci`) and `scripts/poc_trend_h4.py` (`atr_series`, `net_r_after_costs`, `SPREAD`, `_net`, specs loading). Unit tests in `tests/unit/test_mtf_pb.py`. No look-ahead: all HTF reads use only **closed** bars (a `last_closed_indexer` maps each 5m bar to the last closed 4H/1H bar); fib pivots use only confirmed past swings; entry is at the **next** bar open.

**Tech Stack:** Python 3.10+, pandas, stdlib `unittest` (no pytest), run via `.venv/bin/python`.

**Spec:** `docs/superpowers/specs/2026-05-30-mtf-trend-pullback-poc-design.md`

**A-priori parameters (committed; never swept):** 50-EMA (4H & 1H), 5-bar pivot lookback, fib band [0.5, 0.705], stop k=1.0×ATR(1H), trail k=2.0×ATR(1H), fixed target 2.5R, ATR period 14, train/test split 0.7.

---

## File Structure

- **Create** `scripts/poc_mtf_pb.py` — the whole PoC (indicators, bias alignment, entry logic, two exit sims, costs, asset-class report, `main()`).
- **Create** `tests/unit/test_mtf_pb.py` — unit tests for every pure function.
- **Reuse, do not modify** `tests/backtest/backtest_engine.py` and `scripts/poc_trend_h4.py`.
- **Read-only data** `data/history/<SYM>_M5.csv` (header `datetime,open,high,low,close`), `data/specs.json`.

Import convention (matches `scripts/poc_trend_h4.py`): the script inserts repo-root and `tests/backtest` on `sys.path`, then `from scripts import poc_trend_h4 as tp` and `import backtest_engine as bt`. Tests do `from scripts import poc_mtf_pb as mp` after inserting repo root (mirrors `tests/unit/test_trend_poc.py`).

---

## Task 1: Scaffold script + `resample_tf`

**Files:**
- Create: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mtf_pb.py
import os, sys, unittest
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_mtf_pb as mp


class Resample(unittest.TestCase):
    def test_resample_tf_4h_ohlc(self):
        rows = []
        for h in range(8):
            rows.append({"datetime": f"2026-01-01 {h:02d}:00:00", "open": h, "high": h + 2,
                         "low": h - 1, "close": h + 1})
        h4 = mp.resample_tf(pd.DataFrame(rows), "4h")
        self.assertEqual(len(h4), 2)
        self.assertEqual(list(h4.columns)[0], "time")
        self.assertEqual(h4.iloc[0]["open"], 0)
        self.assertEqual(h4.iloc[0]["high"], 5)   # max high of bars 0..3 = 3+2
        self.assertEqual(h4.iloc[0]["low"], -1)
        self.assertEqual(h4.iloc[0]["close"], 4)  # close of bar 3 = 3+1


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.poc_mtf_pb'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/poc_mtf_pb.py
#!/usr/bin/env python3
# MTF trend-pullback proof-of-concept. 4H+1H 50-EMA bias -> 5m fib(0.5-0.705) pullback
# + confirmation-close entry -> 1.0xATR(1H) structural stop -> two exit models
# (fixed-2.5R, partial-at-1R+ATR-trail). Screens net-of-cost, OOS edge across asset
# classes. NOT a live strategy. See docs/superpowers/specs/2026-05-30-mtf-trend-pullback-poc-design.md
import bisect
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
                                "tests", "backtest"))
import backtest_engine as bt          # noqa: E402
from scripts import poc_trend_h4 as tp # noqa: E402


def resample_tf(m5_df, rule):
    """Resample M5 OHLC to a higher timeframe ('4h','1h','15min'). Returns a df with a
    'time' column (bar-open timestamp) + open/high/low/close. Bars are label='left'
    (pandas default): a 4h bar stamped 00:00 spans 00:00-03:59 and CLOSES at 04:00."""
    df = m5_df.copy()
    tcol = "time" if "time" in df.columns else "datetime"
    df["time"] = pd.to_datetime(df[tcol])
    df = df.set_index("time")
    r = df.resample(rule).agg({"open": "first", "high": "max",
                               "low": "min", "close": "last"}).dropna()
    return r.reset_index()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB scaffold + resample_tf (TDD)"
```

---

## Task 2: `ma_bias` (50-EMA trend per closed HTF bar)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class MaBias(unittest.TestCase):
    def test_ma_bias_bull_bear_and_warmup(self):
        # 60 rising closes -> bullish once past warmup; flip to falling -> bearish.
        closes = list(range(1, 61)) + list(range(60, 30, -1))
        df = pd.DataFrame({"close": closes})
        bias = mp.ma_bias(df, ma_len=50)
        self.assertEqual(len(bias), len(closes))
        self.assertEqual(bias[10], "NEUTRAL")        # within warmup (< ma_len)
        self.assertEqual(bias[59], "BULLISH")        # rising, past warmup
        self.assertEqual(bias[-1], "BEARISH")        # falling tail, price below EMA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.MaBias -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'ma_bias'`.

- [ ] **Step 3: Write minimal implementation** (append to `scripts/poc_mtf_pb.py`)

```python
def ma_bias(htf_df, ma_len=50):
    """Per-closed-bar trend by price vs a single EMA. BULLISH if close>EMA, BEARISH if
    close<EMA, NEUTRAL within the warmup (< ma_len bars) or on an exact touch."""
    closes = htf_df["close"].reset_index(drop=True)
    e = closes.ewm(span=ma_len, adjust=False).mean()
    out = []
    for i in range(len(closes)):
        if i < ma_len:
            out.append("NEUTRAL")
        elif closes[i] > e[i]:
            out.append("BULLISH")
        elif closes[i] < e[i]:
            out.append("BEARISH")
        else:
            out.append("NEUTRAL")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.MaBias -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB ma_bias 50-EMA trend filter (TDD)"
```

---

## Task 3: `last_closed_indexer` (the no-look-ahead core)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test** — the critical look-ahead guard.

```python
class ClosedIndexer(unittest.TestCase):
    def test_htf_bar_unused_until_closed(self):
        ts = pd.to_datetime
        htf_times = [ts("2026-01-01 00:00:00"), ts("2026-01-01 04:00:00")]  # 4h bars
        m5_times = [ts("2026-01-01 03:55:00"),   # before 1st bar closes (04:00) -> -1
                    ts("2026-01-01 04:00:00"),   # 1st bar just closed -> idx 0
                    ts("2026-01-01 04:05:00"),   # still only 1st closed -> idx 0
                    ts("2026-01-01 08:00:00")]   # 2nd bar (04:00) closed at 08:00 -> idx 1
        idx = mp.last_closed_indexer(m5_times, htf_times, 4)
        self.assertEqual(idx, [-1, 0, 0, 1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.ClosedIndexer -v`
Expected: FAIL — no attribute `last_closed_indexer`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def last_closed_indexer(m5_times, htf_times, tf_hours):
    """For each m5 timestamp, the index of the most recently CLOSED htf bar (or -1).
    An htf bar stamped T closes at T + tf_hours; it may only be used from then on.
    No look-ahead: a bar in progress is never visible to an earlier m5 bar."""
    close_times = [t + pd.Timedelta(hours=tf_hours) for t in htf_times]  # ascending
    out = []
    for t in m5_times:
        out.append(bisect.bisect_right(close_times, t) - 1)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.ClosedIndexer -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB last_closed_indexer (no look-ahead) (TDD)"
```

---

## Task 4: `combined_bias` (4H AND 1H agreement, per 5m bar)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class CombinedBias(unittest.TestCase):
    def test_agreement_required(self):
        ts = pd.to_datetime
        # one closed 4h bar (BULLISH) and one closed 1h bar (BEARISH) -> NEUTRAL (disagree)
        h4 = pd.DataFrame({"time": [ts("2026-01-01 00:00:00")], "close": [10.0]})
        h1 = pd.DataFrame({"time": [ts("2026-01-01 00:00:00")], "close": [10.0]})
        m5 = pd.DataFrame({"time": [ts("2026-01-01 09:00:00")], "open": [1], "high": [1],
                           "low": [1], "close": [1]})
        # Force biases via monkeypatch-free injection: stub ma_bias outputs by length.
        out = mp.combine_bias_lists(["BULLISH"], ["BEARISH"],
                                    mp.last_closed_indexer(list(m5["time"]), list(h4["time"]), 4),
                                    mp.last_closed_indexer(list(m5["time"]), list(h1["time"]), 1))
        self.assertEqual(out, ["NEUTRAL"])

    def test_both_bullish(self):
        out = mp.combine_bias_lists(["BULLISH"], ["BULLISH"], [0], [0])
        self.assertEqual(out, ["BULLISH"])

    def test_warmup_neutral_when_no_closed_bar(self):
        out = mp.combine_bias_lists(["BULLISH"], ["BULLISH"], [-1], [0])
        self.assertEqual(out, ["NEUTRAL"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.CombinedBias -v`
Expected: FAIL — no attribute `combine_bias_lists`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def combine_bias_lists(bias4, bias1, idx4, idx1):
    """Combine per-bar 4H/1H bias for each 5m bar given the closed-bar indices.
    BULLISH only if both agree bullish, BEARISH only if both agree bearish, else NEUTRAL.
    A negative index (no closed HTF bar yet) -> NEUTRAL."""
    out = []
    for k in range(len(idx4)):
        a = bias4[idx4[k]] if idx4[k] >= 0 else "NEUTRAL"
        b = bias1[idx1[k]] if idx1[k] >= 0 else "NEUTRAL"
        if a == "BULLISH" and b == "BULLISH":
            out.append("BULLISH")
        elif a == "BEARISH" and b == "BEARISH":
            out.append("BEARISH")
        else:
            out.append("NEUTRAL")
    return out


def combined_bias(m5_df, h4, h1, ma_len=50):
    """Per-5m-bar combined 4H+1H bias, using only closed HTF bars (no look-ahead)."""
    m5t = list(pd.to_datetime(m5_df["time" if "time" in m5_df.columns else "datetime"]))
    idx4 = last_closed_indexer(m5t, list(pd.to_datetime(h4["time"])), 4)
    idx1 = last_closed_indexer(m5t, list(pd.to_datetime(h1["time"])), 1)
    return combine_bias_lists(ma_bias(h4, ma_len), ma_bias(h1, ma_len), idx4, idx1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.CombinedBias -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB combined 4H+1H bias agreement (TDD)"
```

---

## Task 5: `attach_atr1h` (1H ATR aligned to each 5m bar, closed-bar)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class AttachAtr(unittest.TestCase):
    def test_atr_uses_last_closed_h1(self):
        ts = pd.to_datetime
        # 20 H1 bars, constant 1.0 range -> ATR ~1.0 after warmup.
        h1 = pd.DataFrame({
            "time": [ts("2026-01-01 00:00:00") + pd.Timedelta(hours=i) for i in range(20)],
            "open": [10.0]*20, "high": [10.5]*20, "low": [9.5]*20, "close": [10.0]*20,
        })
        m5 = pd.DataFrame({"time": [ts("2026-01-02 00:00:00")],  # well after all H1 closed
                           "open": [10], "high": [10], "low": [10], "close": [10]})
        atr = mp.attach_atr1h(m5, h1, period=14)
        self.assertEqual(len(atr), 1)
        self.assertAlmostEqual(atr[0], 1.0, places=6)

    def test_atr_zero_before_any_closed_bar(self):
        ts = pd.to_datetime
        h1 = pd.DataFrame({"time": [ts("2026-01-01 05:00:00")], "open": [1.0],
                           "high": [2.0], "low": [0.0], "close": [1.0]})
        m5 = pd.DataFrame({"time": [ts("2026-01-01 04:00:00")],  # before H1 bar closes
                           "open": [1], "high": [1], "low": [1], "close": [1]})
        self.assertEqual(mp.attach_atr1h(m5, h1), [0.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.AttachAtr -v`
Expected: FAIL — no attribute `attach_atr1h`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def attach_atr1h(m5_df, h1, period=14):
    """ATR(1H) value of the last CLOSED H1 bar, aligned to each 5m bar (0.0 if none yet).
    Reuses poc_trend_h4.atr_series for the ATR computation."""
    atr = tp.atr_series(h1, period).fillna(0.0).values
    m5t = list(pd.to_datetime(m5_df["time" if "time" in m5_df.columns else "datetime"]))
    idx = last_closed_indexer(m5t, list(pd.to_datetime(h1["time"])), 1)
    return [float(atr[j]) if j >= 0 else 0.0 for j in idx]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.AttachAtr -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB attach_atr1h closed-bar ATR alignment (TDD)"
```

---

## Task 6: `impulse_leg` (most recent confirmed 5m swing leg)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class ImpulseLeg(unittest.TestCase):
    def test_bullish_up_leg(self):
        # V-shape: swing low at idx 5, swing high at idx 11; decision at idx 18.
        highs = [10,10,10,10,10, 9,  10,11,12,13,14,15,  14,14,14,14,14,14,14]
        lows  = [ 9, 9, 9, 9, 9, 8,  9,10,11,12,13,14,   13,13,13,13,13,13,13]
        leg = mp.impulse_leg(highs, lows, 18, lk=2, bias="BULLISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high = leg
        self.assertEqual(leg_low, 8)    # lows[5]
        self.assertEqual(leg_high, 15)  # highs[11]

    def test_none_when_leg_wrong_direction_for_bias(self):
        highs = [10,10,10,10,10, 9, 10,11,12,13,14,15, 14,14,14,14,14,14,14]
        lows  = [ 9, 9, 9, 9, 9, 8,  9,10,11,12,13,14, 13,13,13,13,13,13,13]
        # up-leg present (low before high) but bias bearish -> reject
        self.assertIsNone(mp.impulse_leg(highs, lows, 18, lk=2, bias="BEARISH"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.ImpulseLeg -v`
Expected: FAIL — no attribute `impulse_leg`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def _is_swing_high(highs, j, lk):
    return highs[j] == max(highs[j - lk:j + lk + 1])


def _is_swing_low(lows, j, lk):
    return lows[j] == min(lows[j - lk:j + lk + 1])


def recent_swing(highs, lows, i, lk):
    """Indices of the most recent CONFIRMED swing high and swing low strictly before bar i.
    A swing at j needs lk bars either side; confirmation requires j+lk < i (no look-ahead).
    Returns (lo_idx, hi_idx), either may be None."""
    hi_idx = lo_idx = None
    j = i - lk - 1
    while j >= lk:
        if hi_idx is None and _is_swing_high(highs, j, lk):
            hi_idx = j
        if lo_idx is None and _is_swing_low(lows, j, lk):
            lo_idx = j
        if hi_idx is not None and lo_idx is not None:
            break
        j -= 1
    return lo_idx, hi_idx


def impulse_leg(highs, lows, i, lk, bias):
    """The most recent impulse leg matching the bias: an up-leg (swing low BEFORE swing
    high) for BULLISH, a down-leg (swing high before swing low) for BEARISH. Returns
    (leg_low, leg_high) prices, or None if no leg in the trend direction is found."""
    lo_idx, hi_idx = recent_swing(highs, lows, i, lk)
    if lo_idx is None or hi_idx is None:
        return None
    if bias == "BULLISH" and hi_idx > lo_idx:
        return (lows[lo_idx], highs[hi_idx])
    if bias == "BEARISH" and lo_idx > hi_idx:
        return (lows[lo_idx], highs[hi_idx])
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.ImpulseLeg -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB impulse_leg confirmed-swing detection (TDD)"
```

---

## Task 7: `confirmed_entry` (fib-zone tag + resumption close)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class ConfirmedEntry(unittest.TestCase):
    # leg_low=0, leg_high=10 -> bullish discount zone = [10-0.705*10, 10-0.5*10] = [2.95, 5.0]
    def test_bullish_confirmation(self):
        leg = (0.0, 10.0)
        bar = {"open": 3.0, "high": 4.5, "low": 3.0, "close": 4.0}  # dips into zone, closes up
        self.assertTrue(mp.confirmed_entry(bar, leg, "BULLISH"))

    def test_no_entry_when_not_tagged(self):
        leg = (0.0, 10.0)
        bar = {"open": 6.0, "high": 7.0, "low": 5.5, "close": 6.5}  # low 5.5 never reaches 5.0
        self.assertFalse(mp.confirmed_entry(bar, leg, "BULLISH"))

    def test_no_entry_when_close_not_resuming(self):
        leg = (0.0, 10.0)
        bar = {"open": 4.5, "high": 4.6, "low": 3.0, "close": 3.2}  # tagged but bearish close
        self.assertFalse(mp.confirmed_entry(bar, leg, "BULLISH"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.ConfirmedEntry -v`
Expected: FAIL — no attribute `confirmed_entry`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
FIB_LO, FIB_HI = 0.5, 0.705  # a-priori discount/premium band (NOT swept)


def confirmed_entry(bar, leg, bias, lo=FIB_LO, hi=FIB_HI):
    """A just-closed 5m bar triggers entry if it tagged the fib zone AND closed back in the
    trend direction (a resumption candle). Never a passive limit at the level (limits get
    wicked / expire -- the OTE failure mode)."""
    leg_low, leg_high = leg
    rng = leg_high - leg_low
    if rng <= 0:
        return False
    if bias == "BULLISH":
        z_hi = leg_high - lo * rng    # shallow (0.5) retrace
        z_lo = leg_high - hi * rng    # deep (0.705) retrace
        tagged = bar["low"] <= z_hi
        held = bar["close"] >= z_lo
        resume = bar["close"] > bar["open"]
        return tagged and held and resume
    if bias == "BEARISH":
        z_lo = leg_low + lo * rng
        z_hi = leg_low + hi * rng
        tagged = bar["high"] >= z_lo
        held = bar["close"] <= z_hi
        resume = bar["close"] < bar["open"]
        return tagged and held and resume
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.ConfirmedEntry -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB confirmed_entry fib-zone + resumption (TDD)"
```

---

## Task 8: `build_signals` (assemble entries, structural stops, both signal forms)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class BuildSignals(unittest.TestCase):
    def test_signal_fields_and_structural_stop(self):
        # Construct one clean bullish setup; verify entry=next open, stop=1.0xATR(1H), tp=2.5R.
        n = 25
        highs = [10]*5 + [9] + [10,11,12,13,14,15] + [14]*13
        lows  = [ 9]*5 + [8] + [ 9,10,11,12,13,14] + [13]*13
        opens = [10]*25
        closes= [10]*25
        # decision bar i=18: make it tag zone [2.95.. ] of leg(8,15)? leg_low=8,leg_high=15,
        # rng=7 -> zone=[15-0.705*7, 15-0.5*7]=[10.065,11.5]; craft bar 18 to tag+close up.
        highs[18], lows[18], opens[18], closes[18] = 11.4, 10.0, 10.2, 11.2
        m5 = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})
        bias = ["NEUTRAL"]*25
        for k in range(12, 25):
            bias[k] = "BULLISH"
        atr1h = [0.0]*25
        for k in range(25):
            atr1h[k] = 0.5
        # entry bar = 19, open[19]=10
        m5.loc[19, "open"] = 100.0  # make next-open distinctive to assert entry picks it
        sigs = mp.build_signals(m5, bias, atr1h, lk=2, rr=2.5)
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s["bar_idx"], 19)
        self.assertEqual(s["dir"], "BUY")
        self.assertEqual(s["entry"], 100.0)
        self.assertAlmostEqual(s["risk"], 0.5)            # 1.0 x ATR(1H)
        self.assertAlmostEqual(s["sl"], 99.5)             # entry - risk
        self.assertAlmostEqual(s["tp"], 100.0 + 2.5*0.5)  # entry + rr*risk
        self.assertEqual(s["cmd"], "MARKET")

    def test_skips_neutral_and_zero_atr(self):
        m5 = pd.DataFrame({"open": [1]*10, "high": [1]*10, "low": [1]*10, "close": [1]*10})
        self.assertEqual(mp.build_signals(m5, ["NEUTRAL"]*10, [1.0]*10, lk=2), [])
        self.assertEqual(mp.build_signals(m5, ["BULLISH"]*10, [0.0]*10, lk=2), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.BuildSignals -v`
Expected: FAIL — no attribute `build_signals`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def build_signals(m5_df, bias_list, atr1h, lk=5, rr=2.5):
    """Scan 5m bars; on a confirmed pullback entry in the trend direction, emit a signal:
    entry at the NEXT bar open, structural stop = 1.0xATR(1H), fixed target = rr*risk.
    Carries 'risk' and 'atr' for the partial/trail exit. One signal per qualifying bar;
    concurrency (one-open-per-symbol) is enforced by the exit simulators."""
    highs = list(m5_df["high"].values)
    lows = list(m5_df["low"].values)
    recs = m5_df[["open", "high", "low", "close"]].to_dict("records")
    n = len(recs)
    sigs = []
    for i in range(lk + 1, n - 1):
        bias = bias_list[i]
        if bias == "NEUTRAL":
            continue
        a = atr1h[i]
        if not (a > 0):
            continue
        leg = impulse_leg(highs, lows, i, lk, bias)
        if leg is None:
            continue
        if not confirmed_entry(recs[i], leg, bias):
            continue
        entry = recs[i + 1]["open"]
        risk = 1.0 * a
        if bias == "BULLISH":
            sl, tp, d = entry - risk, entry + rr * risk, "BUY"
        else:
            sl, tp, d = entry + risk, entry - rr * risk, "SELL"
        sigs.append({"bar_idx": i + 1, "dir": d, "cmd": "MARKET", "entry": entry,
                     "sl": sl, "tp": tp, "risk": risk, "atr": a, "ttl_bars": 1})
    return sigs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.BuildSignals -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB build_signals entries + structural ATR stop (TDD)"
```

---

## Task 9: `simulate_partial_trail` (half at 1R → BE → ATR-trail)

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test**

```python
class PartialTrail(unittest.TestCase):
    def _bars(self, seq):
        return [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in seq]

    def test_full_stop_before_1r(self):
        # entry 10, risk 1 (sl 9), price drops straight to 9 -> full -1R.
        sig = {"bar_idx": 0, "dir": "BUY", "entry": 10.0, "sl": 9.0, "risk": 1.0, "atr": 1.0}
        bars = self._bars([(10, 10, 8.9, 9)])
        trades = mp.simulate_partial_trail([sig], bars, trail_mult=2.0)
        self.assertAlmostEqual(trades[0]["r"], -1.0)
        self.assertEqual(trades[0]["outcome"], "SL")

    def test_partial_then_breakeven_gives_half_r(self):
        # reaches +1R (11) -> book half (+0.5R), stop to BE(10); then dips to 10 -> remainder 0.
        sig = {"bar_idx": 0, "dir": "BUY", "entry": 10.0, "sl": 9.0, "risk": 1.0, "atr": 0.1}
        bars = self._bars([(10, 11.0, 10.0, 10.8),   # hits 1R, partial+BE; trail=11-0.2=10.8
                           (10.8, 10.8, 10.0, 10.4)])  # low 10.0 <= trailed/BE stop -> exit
        trades = mp.simulate_partial_trail([sig], bars, trail_mult=2.0)
        # half at +1.0R*0.5=0.5 ; remainder exits at ~BE/just above -> total close to +0.5R..+0.9R
        self.assertGreaterEqual(trades[0]["r"], 0.5)
        self.assertEqual(trades[0]["outcome"], "TP")

    def test_one_open_per_symbol(self):
        # two signals, second inside the first's lifetime -> skipped.
        s1 = {"bar_idx": 0, "dir": "BUY", "entry": 10.0, "sl": 9.0, "risk": 1.0, "atr": 1.0}
        s2 = {"bar_idx": 1, "dir": "BUY", "entry": 10.0, "sl": 9.0, "risk": 1.0, "atr": 1.0}
        bars = self._bars([(10, 10, 10, 10), (10, 10, 8.9, 9), (9, 9, 9, 9)])
        trades = mp.simulate_partial_trail([s1, s2], bars, trail_mult=2.0)
        self.assertEqual(len(trades), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.PartialTrail -v`
Expected: FAIL — no attribute `simulate_partial_trail`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def simulate_partial_trail(sigs, bars, trail_mult=2.0):
    """Exit model (b): book HALF at +1R and move the stop to break-even, then TRAIL the
    remaining half by trail_mult*ATR(1H) off the running extreme; exit when the stop is hit.
    One open position per symbol (later signals during a live trade are skipped). Same-bar
    stop+target -> stop wins (conservative). Returns trade dicts with blended R + outcome."""
    trades = []
    busy_until = -1
    n = len(bars)
    for sig in sigs:
        b0 = sig["bar_idx"]
        if b0 <= busy_until or b0 >= n:
            continue
        is_long = sig["dir"] == "BUY"
        E, S, risk = sig["entry"], sig["sl"], sig["risk"]
        trail_dist = trail_mult * sig["atr"]
        one_r = E + risk if is_long else E - risk
        partialed = False
        stop = S
        extreme = bars[b0]["high"] if is_long else bars[b0]["low"]
        r_total, exit_idx = None, b0
        for j in range(b0, n):
            bar = bars[j]
            extreme = max(extreme, bar["high"]) if is_long else min(extreme, bar["low"])
            hit = (bar["low"] <= stop) if is_long else (bar["high"] >= stop)
            if hit:
                exit_r = (stop - E) / risk if is_long else (E - stop) / risk
                r_total = (0.5 * 1.0 + 0.5 * exit_r) if partialed else exit_r
                exit_idx = j
                break
            if not partialed:
                reached = (bar["high"] >= one_r) if is_long else (bar["low"] <= one_r)
                if reached:
                    partialed = True
                    stop = E  # break-even on the remainder
            if partialed:
                t_stop = (extreme - trail_dist) if is_long else (extreme + trail_dist)
                stop = max(stop, t_stop) if is_long else min(stop, t_stop)
        if r_total is None:  # never resolved -> mark out at last close
            px = bars[n - 1]["close"]
            exit_r = (px - E) / risk if is_long else (E - px) / risk
            r_total = (0.5 * 1.0 + 0.5 * exit_r) if partialed else exit_r
            exit_idx = n - 1
        trades.append({**sig, "r": r_total, "entry_idx": b0, "exit_idx": exit_idx,
                       "outcome": "TP" if r_total > 0 else "SL"})
        busy_until = exit_idx
    return trades
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.PartialTrail -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB partial-at-1R + BE + ATR-trail exit sim (TDD)"
```

---

## Task 10: Per-symbol pipeline + asset-class report + `main()`

**Files:**
- Modify: `scripts/poc_mtf_pb.py`
- Test: `tests/unit/test_mtf_pb.py`

- [ ] **Step 1: Write the failing test** (the pure pieces: asset-class map + a one-symbol runner returning both trade lists)

```python
class Pipeline(unittest.TestCase):
    def test_asset_class_of(self):
        self.assertEqual(mp.asset_class_of("EURUSD"), "FX-majors")
        self.assertEqual(mp.asset_class_of("GBPJPY"), "FX-crosses")
        self.assertEqual(mp.asset_class_of("XAUUSD"), "metals")
        self.assertEqual(mp.asset_class_of("US30"), "index")
        self.assertEqual(mp.asset_class_of("BTCUSD"), "crypto")
        self.assertEqual(mp.asset_class_of("XBRUSD"), "energy")

    def test_run_symbol_returns_two_models(self):
        # Tiny synthetic M5 df with a clear uptrend then pullback; just assert it runs and
        # returns dict with 'fixed' and 'partial' lists of trade dicts (may be empty).
        import numpy as np
        ts = pd.date_range("2026-01-01", periods=4000, freq="5min")
        # gentle uptrend so 4H/1H bias can turn bullish, with noise for pullbacks
        base = pd.Series(range(4000)).astype(float) * 0.01 + 100.0
        noise = pd.Series([(-1)**i for i in range(4000)]).astype(float) * 0.05
        close = base + noise
        m5 = pd.DataFrame({"datetime": ts, "open": close.shift(1).fillna(close[0]),
                           "high": close + 0.1, "low": close - 0.1, "close": close})
        out = mp.run_symbol(m5)
        self.assertIn("fixed", out)
        self.assertIn("partial", out)
        self.assertIsInstance(out["fixed"], list)
        self.assertIsInstance(out["partial"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.Pipeline -v`
Expected: FAIL — no attribute `asset_class_of` / `run_symbol`.

- [ ] **Step 3: Write minimal implementation** (append)

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


def run_symbol(m5_df, ma_len=50, lk=5, rr=2.5, trail_mult=2.0):
    """Run the full MTF-PB pipeline on one symbol's M5 frame. Returns
    {'fixed': [...], 'partial': [...]} of resolved (pre-cost) trade dicts."""
    h4 = resample_tf(m5_df, "4h")
    h1 = resample_tf(m5_df, "1h")
    bias = combined_bias(m5_df, h4, h1, ma_len)
    atr1h = attach_atr1h(m5_df, h1)
    sigs = build_signals(m5_df, bias, atr1h, lk=lk, rr=rr)
    bars = m5_df[["open", "high", "low", "close"]].to_dict("records")
    fixed = bt.simulate_signals(sigs, bars)
    partial = simulate_partial_trail(sigs, bars, trail_mult=trail_mult)
    return {"fixed": fixed, "partial": partial}


def _report(model_name, by_class):
    """Print pooled net-of-cost metrics per asset class + overall, with Wilson CI, an
    out-of-sample (70/30) expectancy, and an n<30 significance flag."""
    print(f"\n===== {model_name} (NET OF COSTS) =====")
    pooled = []
    for cls in list(ASSET_CLASSES) + ["POOLED-ALL"]:
        trades = pooled if cls == "POOLED-ALL" else by_class.get(cls, [])
        if cls != "POOLED-ALL":
            pooled += trades
        m = bt.aggregate_metrics(trades)
        p, lo, hi = bt.win_rate_ci(m["wins"], m["trades"])
        norm = [{**t, "bar_idx": t.get("bar_idx", t.get("entry_idx", 0))} for t in trades]
        _, test = bt.split_trades(norm, 0.7)
        mt = bt.aggregate_metrics(test)
        flag = "  [INSUFFICIENT n<30]" if m["trades"] < 30 else ""
        print(f"  {cls:12} n={m['trades']:4d} win={p*100:4.1f}% CI[{lo*100:.0f}-{hi*100:.0f}] "
              f"netExpR={m['expectancy']:+.3f} totR={m['total_r']:+.1f} PF={m['profit_factor']:.2f} "
              f"DD={m['max_drawdown_r']:.0f}R | TEST n={mt['trades']} exp={mt['expectancy']:+.3f}{flag}")


def main():
    fixed_by_class, partial_by_class = {}, {}
    for sym in SYMS:
        path = f"data/history/{sym}_M5.csv"
        if not os.path.exists(path):
            continue
        m5 = pd.read_csv(path)
        res = run_symbol(m5)
        cls = asset_class_of(sym)
        fixed_by_class.setdefault(cls, []).extend(tp._net(res["fixed"], sym))
        partial_by_class.setdefault(cls, []).extend(tp._net(res["partial"], sym))
    print("MTF-PB PoC -- 4H+1H 50-EMA bias, 5m fib(0.5-0.705) pullback, 1.0xATR(1H) stop")
    _report("FIXED-2.5R", fixed_by_class)
    _report("PARTIAL-1R+ATR-TRAIL", partial_by_class)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_mtf_pb.Pipeline -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_mtf_pb.py tests/unit/test_mtf_pb.py
git commit -m "feat(poc): MTF-PB per-symbol pipeline + asset-class report + main (TDD)"
```

---

## Task 11: Full suite green + run the PoC on real data + record results

**Files:**
- Create: `docs/research/2026-05-30-mtf-pb-poc-results.md`

- [ ] **Step 1: Run the full unit suite (no regressions)**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK — all tests pass (existing + the new `test_mtf_pb` classes).

- [ ] **Step 2: Run the PoC on the real M5 data**

Run: `.venv/bin/python scripts/poc_mtf_pb.py | tee data/history/mtf_pb_poc.txt`
Expected: a FIXED-2.5R block and a PARTIAL-1R+ATR-TRAIL block, each with per-asset-class
pooled rows (FX-majors, FX-crosses, metals, index, crypto, energy) + POOLED-ALL, showing
n / win% / CI / net expectancy R / total R / PF / DD / out-of-sample test expectancy, with
`[INSUFFICIENT n<30]` flags where samples are thin.

- [ ] **Step 3: Record results + apply the GO/NO-GO gate** (write `docs/research/2026-05-30-mtf-pb-poc-results.md`)

Paste the PoC output, then evaluate against the spec's gate and write the verdict explicitly:

```markdown
# MTF-PB PoC results — 2026-05-30

Parameters (a-priori, not swept): 50-EMA (4H&1H), 5-bar pivot, fib [0.5,0.705],
stop 1.0xATR(1H), trail 2.0xATR(1H), fixed target 2.5R, ATR(14), split 0.7.

## Output
<paste the FIXED-2.5R and PARTIAL blocks here>

## GO/NO-GO verdict (per spec gate)
- Net-of-cost expectancy positive in BOTH train and test? <yes/no, per class>
- Sample n>=30 (per class, pooling within class)? <list classes that clear it>
- Positive in the synthesis-predicted classes (index/commodity/crypto)? <yes/no>
- Edge present under BOTH exit models (not just one)? <yes/no>

**Decision:** GO -> proceed to management layers (order -> risk -> ... ML last) |
NO-GO -> iterate the few a-priori rules / shelve | INCONCLUSIVE -> "need more history"
(state plainly; do NOT dress a thin or one-sided result as a win).
```

- [ ] **Step 4: Commit**

```bash
git add docs/research/2026-05-30-mtf-pb-poc-results.md
git commit -m "docs(poc): MTF-PB PoC results + GO/NO-GO verdict"
```

Note: `data/history/mtf_pb_poc.txt` is git-ignored (per repo convention) — do not commit it.

---

## Self-Review notes

- **Spec coverage:** 4H+1H 50-EMA bias (T2,T4), closed-bar/no-look-ahead (T3, used in T4/T5), 5m fib pullback (T6,T7), confirmation-close not limit (T7), 1.0×ATR(1H) structural stop (T8), fixed-2.5R via harness (T8+T10), partial/trail (T9), net-of-cost via `tp._net` (T10), OOS split + Wilson CI + n<30 flag (T10 `_report`), all asset classes (T10), GO/NO-GO gate (T11). All spec sections map to a task.
- **No M1 / 1-2m entry:** intentionally absent (deferred per spec); entry granularity is M5.
- **Type consistency:** signal dicts carry `bar_idx, dir, cmd, entry, sl, tp, risk, atr, ttl_bars` from `build_signals` (T8) and are consumed unchanged by `bt.simulate_signals` (needs entry/sl/tp/cmd/ttl_bars/bar_idx) and `simulate_partial_trail` (needs entry/sl/risk/atr/dir/bar_idx). `tp._net` overwrites `r`+`outcome` by sign for both lists. `_report` reads `bar_idx` for `split_trades`. Consistent across tasks.
- **Cost approximation:** `tp._net` applies cost on the full stop distance for both models (documented in spec); acceptable for a screening PoC.
