# OTE Canonical MTF Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared OTE detection module + a 3-year cost-aware backtest rig for the canonical OTE model (H4+H1 BOS bias → H1 impulse leg → 0.62–0.79 zone → M5 MSS confirm → MARKET entry, H1-anchored stops), run the pre-registered validation gate, and produce a GO/NO-GO results doc.

**Architecture:** Pure detection functions live in `src/analysis/ote_structure.py` (no pandas, no I/O) so the rig and any future live strategy import the *same* code. The rig `scripts/poc_ote_canonical.py` sweeps M5 data, drives an explicit setup state machine, resolves entries with fixed-2.5R (for trade sequencing) and replays the v14.4 ratchet/runner via the **unmodified** `replay_managed`/`cost_r` imported from `scripts/poc_sb_stops.py`.

**Tech Stack:** Python 3.10+, pandas/numpy (rig only), stdlib `unittest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md`

## Global Constraints

- **Frozen parameters (spec §1 — no tuning, ever, in this plan):** zone `0.62–0.79`; leg displacement `≥ 2.0×ATR(H1)`; stop floor `0.5×ATR(H1)`; zone-invalidation buffer `0.1×ATR(H1)`; setup TTL `12` H1 bars; fixed target `2.5R`; swing lookback `lk=3` on H1/H4, `lk=2` on M5; MARKET entry at next M5 open after the confirm close.
- **Pessimistic replay conventions (spec §2):** bias/legs only on closed H4/H1 bars; same-bar-SL-first; partials fill at the fib level; one open trade per symbol; chronological portfolio ordering for DD.
- **Reuse unmodified (spec §5):** `replay_managed`, `cost_r`, `metrics`, `wilson`, `SPREADS`, `COMMISSION_USD_PER_LOT` from `scripts/poc_sb_stops.py`. Do NOT edit `scripts/poc_sb_stops.py` or `scripts/poc_mtf_pb2.py`.
- **One-pass rule (spec §3):** if the run fails the gate, do not iterate parameters in place. Document and stop.
- Tests: stdlib `unittest`, run with `.venv/bin/python -m unittest …`. No pytest.
- Data: existing `data/history/<SYM>_M5.csv` (columns `datetime,open,high,low,close`) and `data/specs.json`. No new exports.
- **Live port (spec §4) is OUT OF SCOPE** — it gets its own plan only on a GO verdict. No EA/MQL5 changes.
- Work on branch `feat/trade-mgmt-pipeline` (current). Commit after every task.

---

### Task 1: Swing primitives + structural BOS bias (`ote_structure.py`)

**Files:**
- Create: `src/analysis/ote_structure.py`
- Create: `tests/unit/test_ote_structure.py`

**Interfaces:**
- Produces (consumed by Tasks 2–6):
  - `is_swing_high(highs: list[float], j: int, lk: int) -> bool`
  - `is_swing_low(lows: list[float], j: int, lk: int) -> bool`
  - `confirmed_swings(highs, lows, lk) -> tuple[list[int], list[int]]` — `(his, los)` index lists
  - `structure_bias(highs, lows, lk=3) -> list[str]` — per-bar `"BULLISH"|"BEARISH"|"NEUTRAL"`

These are clean-room ports of the definitions in `scripts/poc_mtf_pb.py` (`_is_swing_high`/`_is_swing_low`) and `scripts/poc_mtf_pb2.py` (`confirmed_swing_seq`, `structure_bias`) — same semantics, re-homed in `src/` because live code must never import from `scripts/`. The scripts keep their own copies (they are frozen historical studies).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ote_structure.py
import unittest

from src.analysis.ote_structure import (
    is_swing_high, is_swing_low, confirmed_swings, structure_bias,
)

# Shared fixture: lk=1 uptrend with confirmed HH+HL.
# Swing highs at j=2 (10) and j=6 (12); swing lows at j=4 (8) and j=8 (9).
HIGHS = [9.0, 9.5, 10.0, 9.2, 8.5, 9.5, 12.0, 10.0, 9.5, 10.5, 11.0]
LOWS  = [8.5, 9.0,  9.5, 8.8, 8.0, 9.0, 11.0,  9.2, 9.0,  9.8, 10.2]


class TestSwings(unittest.TestCase):
    def test_swing_high_strict(self):
        self.assertTrue(is_swing_high(HIGHS, 2, 1))
        self.assertFalse(is_swing_high(HIGHS, 3, 1))
        # ties are NOT swings (strict inequality)
        self.assertFalse(is_swing_high([1.0, 2.0, 2.0], 1, 1))

    def test_swing_low_strict(self):
        self.assertTrue(is_swing_low(LOWS, 4, 1))
        self.assertFalse(is_swing_low(LOWS, 5, 1))

    def test_confirmed_swings_indices(self):
        his, los = confirmed_swings(HIGHS, LOWS, 1)
        self.assertEqual(his, [2, 6])
        self.assertEqual(los, [4, 8])


class TestStructureBias(unittest.TestCase):
    def test_uptrend_turns_bullish_only_after_confirmation(self):
        bias = structure_bias(HIGHS, LOWS, lk=1)
        # SL@8 confirms at bar 9 (j+lk); before that, <2 confirmed lows -> NEUTRAL
        self.assertEqual(bias[8], "NEUTRAL")
        self.assertEqual(bias[9], "BULLISH")   # HH (12>10) and HL (9>8)
        self.assertEqual(bias[10], "BULLISH")

    def test_downtrend_mirror(self):
        h = [x for x in reversed(HIGHS)]
        l = [x for x in reversed(LOWS)]
        # reversed series trends down; find at least one BEARISH bar at the end
        bias = structure_bias(h, l, lk=1)
        self.assertIn("BEARISH", bias)
        self.assertEqual(bias[-1], "BEARISH")

    def test_short_series_all_neutral(self):
        self.assertEqual(structure_bias([1.0, 2.0], [0.5, 1.5], lk=3),
                         ["NEUTRAL", "NEUTRAL"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.ote_structure'`

- [ ] **Step 3: Write the implementation**

```python
# src/analysis/ote_structure.py
# ==============================================================================
# Canonical OTE detection primitives — SHARED by the backtest rig
# (scripts/poc_ote_canonical.py) and the future live strategy (on GO).
# Pure functions only: no pandas, no I/O, no logging. Spec:
# docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md
# Definitions ported from scripts/poc_mtf_pb.py / poc_mtf_pb2.py (frozen studies).
# ==============================================================================
import bisect


def is_swing_high(highs, j, lk):
    """True when highs[j] is strictly greater than all lk neighbours each side."""
    window = list(highs[j - lk:j + lk + 1])
    return highs[j] > max(window[:lk] + window[lk + 1:])


def is_swing_low(lows, j, lk):
    """True when lows[j] is strictly less than all lk neighbours each side."""
    window = list(lows[j - lk:j + lk + 1])
    return lows[j] < min(window[:lk] + window[lk + 1:])


def confirmed_swings(highs, lows, lk):
    """Index lists (his, los) of confirmed swing highs / lows (lk bars each side)."""
    n = len(highs)
    his = [j for j in range(lk, n - lk) if is_swing_high(highs, j, lk)]
    los = [j for j in range(lk, n - lk) if is_swing_low(lows, j, lk)]
    return his, los


def structure_bias(highs, lows, lk=3):
    """Per-bar BOS bias. BULLISH when the last two confirmed swing highs are
    higher-high AND the last two confirmed swing lows are higher-low; BEARISH on
    the mirror; else NEUTRAL. A swing at j is 'confirmed' from bar j+lk on
    (no look-ahead); bias[i] is usable at the close of bar i."""
    n = len(highs)
    his, los = confirmed_swings(highs, lows, lk)
    cl_h = [j + lk for j in his]
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
            out.append("BULLISH" if (hh and hl) else
                       "BEARISH" if (lh and ll) else "NEUTRAL")
        else:
            out.append("NEUTRAL")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: PASS (6 tests OK)

- [ ] **Step 5: Run the full unit suite (no regressions)**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK (existing 258 tests + 6 new)

- [ ] **Step 6: Commit**

```bash
git add src/analysis/ote_structure.py tests/unit/test_ote_structure.py
git commit -m "feat(ote): swing primitives + structural BOS bias (shared rig/live module)"
```

---

### Task 2: Impulse leg, OTE zone, zone invalidation

**Files:**
- Modify: `src/analysis/ote_structure.py` (append)
- Modify: `tests/unit/test_ote_structure.py` (append)

**Interfaces:**
- Consumes: `confirmed_swings` (Task 1)
- Produces (consumed by Tasks 4, 6):
  - `impulse_leg(highs, lows, upto, lk, bias, swh=None, swl=None) -> tuple[float, float, int, int] | None` — `(leg_low, leg_high, lo_idx, hi_idx)`; `swh/swl` are the full-series `confirmed_swings` lists for the O(log n) fast path
  - `ote_zone(leg_low, leg_high, bias, lo=0.62, hi=0.79) -> tuple[float, float]` — `(z_lo, z_hi)` price band
  - `zone_invalidation(z_lo, z_hi, atr, is_long, buffer_mult=0.1) -> float` — stop must be at/beyond this level

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_ote_structure.py`)

```python
from src.analysis.ote_structure import impulse_leg, ote_zone, zone_invalidation


class TestImpulseLeg(unittest.TestCase):
    def test_bullish_leg_found(self):
        # HIGHS/LOWS fixture: SWH 6 (12) broke SWH 2 (10) -> BOS up;
        # origin = most recent confirmed swing low before it = idx 4 (8.0)
        leg = impulse_leg(HIGHS, LOWS, upto=10, lk=1, bias="BULLISH")
        self.assertEqual(leg, (8.0, 12.0, 4, 6))

    def test_fast_path_matches_slow_path(self):
        swh, swl = confirmed_swings(HIGHS, LOWS, 1)
        slow = impulse_leg(HIGHS, LOWS, 10, 1, "BULLISH")
        fast = impulse_leg(HIGHS, LOWS, 10, 1, "BULLISH", swh, swl)
        self.assertEqual(slow, fast)

    def test_no_leg_when_neutral_or_no_bos(self):
        self.assertIsNone(impulse_leg(HIGHS, LOWS, 10, 1, "NEUTRAL"))
        flat_h = [10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0]
        flat_l = [9.0, 10.0, 9.0, 10.0, 9.0, 10.0, 9.0]
        self.assertIsNone(impulse_leg(flat_h, flat_l, 6, 1, "BULLISH"))

    def test_bearish_mirror(self):
        h = [x for x in reversed(HIGHS)]
        l = [x for x in reversed(LOWS)]
        leg = impulse_leg(h, l, upto=10, lk=1, bias="BEARISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high, lo_idx, hi_idx = leg
        self.assertLess(leg_low, leg_high)
        self.assertGreater(lo_idx, hi_idx)   # bear leg: high first, low after


class TestOteZone(unittest.TestCase):
    def test_bull_zone_measured_down_from_high(self):
        z_lo, z_hi = ote_zone(8.0, 12.0, "BULLISH")
        self.assertAlmostEqual(z_lo, 12.0 - 0.79 * 4.0)   # 8.84
        self.assertAlmostEqual(z_hi, 12.0 - 0.62 * 4.0)   # 9.52

    def test_bear_zone_measured_up_from_low(self):
        z_lo, z_hi = ote_zone(8.0, 12.0, "BEARISH")
        self.assertAlmostEqual(z_lo, 8.0 + 0.62 * 4.0)    # 10.48
        self.assertAlmostEqual(z_hi, 8.0 + 0.79 * 4.0)    # 11.16


class TestZoneInvalidation(unittest.TestCase):
    def test_long_below_zone_bottom(self):
        self.assertAlmostEqual(zone_invalidation(8.84, 9.52, 1.0, True), 8.74)

    def test_short_above_zone_top(self):
        self.assertAlmostEqual(zone_invalidation(10.48, 11.16, 1.0, False), 11.26)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: FAIL — `ImportError: cannot import name 'impulse_leg'`

- [ ] **Step 3: Write the implementation** (append to `src/analysis/ote_structure.py`)

```python
def impulse_leg(highs, lows, upto, lk, bias, swh=None, swl=None):
    """Most recent leg in the bias direction that BROKE the prior swing, using
    bars [0..upto]. BULL: a confirmed swing high exceeding the previous confirmed
    swing high (BOS up); origin = most recent confirmed swing low before it.
    Returns (leg_low, leg_high, lo_idx, hi_idx) or None.
    Pass precomputed full-series swh/swl (confirmed_swings on the whole array)
    for the O(log n) fast path; both paths are behavior-equivalent."""
    if bias not in ("BULLISH", "BEARISH"):
        return None
    if swh is None or swl is None:
        swh, swl = confirmed_swings(highs[:upto + 1], lows[:upto + 1], lk)
        nh, nl = len(swh), len(swl)
    else:
        cutoff = upto - lk
        nh = bisect.bisect_right(swh, cutoff)
        nl = bisect.bisect_right(swl, cutoff)
    if bias == "BULLISH":
        for k in range(nh - 1, 0, -1):
            if highs[swh[k]] > highs[swh[k - 1]]:            # BOS up
                hi = swh[k]
                p = bisect.bisect_left(swl, hi, 0, nl) - 1   # last low before hi
                if p >= 0:
                    lo = swl[p]
                    return (lows[lo], highs[hi], lo, hi)
        return None
    for k in range(nl - 1, 0, -1):
        if lows[swl[k]] < lows[swl[k - 1]]:                  # BOS down
            lo = swl[k]
            p = bisect.bisect_left(swh, lo, 0, nh) - 1       # last high before lo
            if p >= 0:
                hi = swh[p]
                return (lows[lo], highs[hi], lo, hi)
    return None


def ote_zone(leg_low, leg_high, bias, lo=0.62, hi=0.79):
    """Golden-zone price band (z_lo, z_hi). BULL: measured down from the high."""
    rng = leg_high - leg_low
    if bias == "BULLISH":
        return (leg_high - hi * rng, leg_high - lo * rng)
    return (leg_low + lo * rng, leg_low + hi * rng)


def zone_invalidation(z_lo, z_hi, atr, is_long, buffer_mult=0.1):
    """Level the stop must sit at/beyond: past the 0.79 edge + 0.1*ATR buffer."""
    return (z_lo - buffer_mult * atr) if is_long else (z_hi + buffer_mult * atr)
```

Note the unified slow/fast path (`nh`/`nl` bounds) — in the slow path the swing
lists are already prefix-limited so the bounds are their full lengths.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis/ote_structure.py tests/unit/test_ote_structure.py
git commit -m "feat(ote): impulse leg detection + OTE zone + invalidation level"
```

---

### Task 3: M5 MSS confirmation (precomputed swings)

**Files:**
- Modify: `src/analysis/ote_structure.py` (append)
- Modify: `tests/unit/test_ote_structure.py` (append)

**Interfaces:**
- Consumes: `confirmed_swings` (Task 1)
- Produces (consumed by Tasks 4, 6):
  - `precompute_last_swings(highs, lows, lk) -> tuple[list[int], list[int]]` — per-bar index of the most recent *confirmed* swing high/low usable at that bar (`-1` if none)
  - `mss_confirm(highs, lows, closes, i, bias, last_swh, last_swl) -> bool` — True when bar i's close breaks the last confirmed opposing minor swing in the trend direction (bull: close > last confirmed swing high). Note: unlike v2, no `mss_level` is returned — the stop is H1-anchored by spec and must never come from M5 structure.

- [ ] **Step 1: Write the failing tests** (append)

```python
from src.analysis.ote_structure import precompute_last_swings, mss_confirm

# lk=2 fixture: confirmed swing high at j=2 (7.0), usable from i>=5 (j+lk<i)
M5H = [5.0, 6.0, 7.0, 6.0, 5.0, 6.0, 7.5]
M5L = [4.0, 5.0, 6.0, 5.0, 4.0, 5.0, 6.5]
M5C = [4.5, 5.5, 6.5, 5.5, 4.5, 5.8, 7.2]


class TestMssConfirm(unittest.TestCase):
    def test_precompute_last_swings(self):
        swh, swl = precompute_last_swings(M5H, M5L, 2)
        self.assertEqual(swh, [-1, -1, -1, -1, -1, 2, 2])
        self.assertEqual(swl, [-1, -1, -1, -1, -1, -1, -1])

    def test_bull_mss_fires_only_on_break(self):
        swh, swl = precompute_last_swings(M5H, M5L, 2)
        self.assertFalse(mss_confirm(M5H, M5L, M5C, 5, "BULLISH", swh, swl))
        self.assertTrue(mss_confirm(M5H, M5L, M5C, 6, "BULLISH", swh, swl))

    def test_no_swing_yet_no_mss(self):
        swh, swl = precompute_last_swings(M5H, M5L, 2)
        self.assertFalse(mss_confirm(M5H, M5L, M5C, 4, "BULLISH", swh, swl))

    def test_bear_mirror(self):
        h = [-x for x in M5L]   # mirror the geometry
        l = [-x for x in M5H]
        c = [-x for x in M5C]
        swh, swl = precompute_last_swings(h, l, 2)
        self.assertTrue(mss_confirm(h, l, c, 6, "BEARISH", swh, swl))
        self.assertFalse(mss_confirm(h, l, c, 5, "BEARISH", swh, swl))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: FAIL — `ImportError: cannot import name 'precompute_last_swings'`

- [ ] **Step 3: Write the implementation** (append)

```python
def precompute_last_swings(highs, lows, lk):
    """For each bar i, the index of the most recent CONFIRMED swing high / low
    usable at i (a swing at j is confirmed once j+lk < i). O(n). -1 where none."""
    n = len(highs)
    swh, swl = confirmed_swings(highs, lows, lk)
    last_swh = [-1] * n
    last_swl = [-1] * n
    p, cur = 0, -1
    for i in range(n):
        while p < len(swh) and swh[p] + lk < i:
            cur = swh[p]; p += 1
        last_swh[i] = cur
    p, cur = 0, -1
    for i in range(n):
        while p < len(swl) and swl[p] + lk < i:
            cur = swl[p]; p += 1
        last_swl[i] = cur
    return last_swh, last_swl


def mss_confirm(highs, lows, closes, i, bias, last_swh, last_swl):
    """M5 market-structure shift at bar i in the trend direction: the close
    breaks the last confirmed opposing minor swing. Pure timing signal — the
    stop is H1-anchored by spec and never derives from M5 structure."""
    if bias == "BULLISH":
        sh = last_swh[i]
        return sh >= 0 and closes[i] > highs[sh]
    sl = last_swl[i]
    return sl >= 0 and closes[i] < lows[sl]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis/ote_structure.py tests/unit/test_ote_structure.py
git commit -m "feat(ote): M5 MSS confirmation with O(n) precomputed swings"
```

---

### Task 4: Stop anchor + setup state machine

**Files:**
- Modify: `src/analysis/ote_structure.py` (append)
- Modify: `tests/unit/test_ote_structure.py` (append)

**Interfaces:**
- Produces (consumed by Task 6 and the future live port):
  - State constants `AWAIT_ZONE = "AWAIT_ZONE"`, `IN_ZONE = "IN_ZONE"`, `CONFIRMED = "CONFIRMED"`, `DEAD = "DEAD"`
  - `stop_anchor(entry, pullback_ext, inval_level, atr, is_long, floor_mult=0.5) -> float` — the most protective of: beyond pullback extreme, beyond zone invalidation, ≥ floor_mult×ATR from entry
  - `advance_setup(state, is_long, z_lo, z_hi, leg_origin, bar_high, bar_low, bar_close, mss_ok) -> str` — one M5-bar transition; `CONFIRMED` means "enter MARKET at next bar open"

- [ ] **Step 1: Write the failing tests** (append)

```python
from src.analysis.ote_structure import (
    stop_anchor, advance_setup, AWAIT_ZONE, IN_ZONE, CONFIRMED, DEAD,
)


class TestStopAnchor(unittest.TestCase):
    def test_long_takes_most_protective(self):
        # floor: 100 - 0.5*2 = 99; pullback 99.5; inval 99.2 -> min = 99.0
        self.assertAlmostEqual(stop_anchor(100.0, 99.5, 99.2, 2.0, True), 99.0)
        # deep pullback dominates
        self.assertAlmostEqual(stop_anchor(100.0, 98.5, 99.2, 2.0, True), 98.5)

    def test_short_mirror(self):
        self.assertAlmostEqual(stop_anchor(100.0, 100.5, 100.8, 2.0, False), 101.0)
        self.assertAlmostEqual(stop_anchor(100.0, 101.5, 100.8, 2.0, False), 101.5)

    def test_distance_never_below_floor(self):
        sl = stop_anchor(100.0, 99.9, 99.95, 2.0, True)
        self.assertGreaterEqual(100.0 - sl, 0.5 * 2.0)


class TestAdvanceSetup(unittest.TestCase):
    # long setup: zone (8.84, 9.52), leg origin 8.0
    Z = dict(is_long=True, z_lo=8.84, z_hi=9.52, leg_origin=8.0)

    def _adv(self, state, hi, lo, close, mss=False):
        return advance_setup(state, self.Z["is_long"], self.Z["z_lo"],
                             self.Z["z_hi"], self.Z["leg_origin"],
                             hi, lo, close, mss)

    def test_waits_above_zone(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.6, 9.8), AWAIT_ZONE)

    def test_touch_enters_zone(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.4, 9.6), IN_ZONE)

    def test_mss_only_counts_in_zone(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.6, 9.8, mss=True), AWAIT_ZONE)
        self.assertEqual(self._adv(IN_ZONE, 10.0, 9.6, 9.8, mss=True), CONFIRMED)

    def test_same_bar_touch_and_mss_confirms(self):
        # documented accepted edge: touch + MSS on one bar -> CONFIRMED
        self.assertEqual(self._adv(AWAIT_ZONE, 10.0, 9.4, 9.9, mss=True), CONFIRMED)

    def test_leg_origin_breach_kills(self):
        self.assertEqual(self._adv(AWAIT_ZONE, 9.0, 7.9, 8.2), DEAD)
        self.assertEqual(self._adv(IN_ZONE, 9.0, 7.9, 8.2), DEAD)

    def test_terminal_states_stick(self):
        self.assertEqual(self._adv(DEAD, 10.0, 9.4, 9.6, mss=True), DEAD)
        self.assertEqual(self._adv(CONFIRMED, 10.0, 9.4, 9.6), CONFIRMED)

    def test_short_mirror_touch_and_kill(self):
        # short: zone (10.48, 11.16), origin 12.0
        self.assertEqual(advance_setup(AWAIT_ZONE, False, 10.48, 11.16, 12.0,
                                       10.6, 10.0, 10.3, False), IN_ZONE)
        self.assertEqual(advance_setup(IN_ZONE, False, 10.48, 11.16, 12.0,
                                       12.1, 11.0, 11.5, False), DEAD)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: FAIL — `ImportError: cannot import name 'stop_anchor'`

- [ ] **Step 3: Write the implementation** (append)

```python
# --- setup lifecycle states -------------------------------------------------
AWAIT_ZONE = "AWAIT_ZONE"   # leg + zone exist; price hasn't traded into the zone
IN_ZONE = "IN_ZONE"         # price has touched the zone; watching for M5 MSS
CONFIRMED = "CONFIRMED"     # MSS printed -> enter MARKET at next bar open
DEAD = "DEAD"               # leg origin breached; setup invalid


def stop_anchor(entry, pullback_ext, inval_level, atr, is_long, floor_mult=0.5):
    """H1-anchored stop: the most protective of (a) beyond the pullback extreme,
    (b) beyond zone invalidation, (c) >= floor_mult*ATR(H1) from entry. The M5
    confirmation NEVER tightens the stop (spec section 1)."""
    if is_long:
        return min(pullback_ext, inval_level, entry - floor_mult * atr)
    return max(pullback_ext, inval_level, entry + floor_mult * atr)


def advance_setup(state, is_long, z_lo, z_hi, leg_origin,
                  bar_high, bar_low, bar_close, mss_ok):
    """One closed-M5-bar transition of the setup state machine.
    AWAIT_ZONE -> IN_ZONE on zone touch; IN_ZONE -> CONFIRMED on MSS; any live
    state -> DEAD when the bar trades beyond the leg origin. A single bar that
    both touches the zone and prints MSS confirms immediately (accepted edge)."""
    if state in (CONFIRMED, DEAD):
        return state
    if (is_long and bar_low <= leg_origin) or \
       (not is_long and bar_high >= leg_origin):
        return DEAD
    if state == AWAIT_ZONE:
        touched = (bar_low <= z_hi) if is_long else (bar_high >= z_lo)
        if not touched:
            return AWAIT_ZONE
        state = IN_ZONE
    if state == IN_ZONE and mss_ok:
        return CONFIRMED
    return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_structure -v`
Expected: PASS

- [ ] **Step 5: Run the full unit suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/analysis/ote_structure.py tests/unit/test_ote_structure.py
git commit -m "feat(ote): H1-anchored stop rule + setup state machine"
```

---

### Task 5: Regression anchors for the reused SB replay/cost components

**Files:**
- Create: `tests/unit/test_ote_rig.py`

**Interfaces:**
- Consumes: `replay_managed(tr, bars, runner=False)`, `cost_r(tr, sym, specs, spread_mult=1.0)` from `scripts/poc_sb_stops.py` (unmodified)
- Produces: golden-value tests that pin the exact behavior the rig depends on (spec §5 reconciliation, unit tier). `tr` dict contract: keys `entry, sl, tp, risk, dir, fill_idx`; `bars` dict contract: keys `high, low` (index-aligned arrays).

- [ ] **Step 1: Write the tests** (these pass immediately — they pin existing behavior; the value is failing LOUDLY if anyone ever edits `poc_sb_stops.py`)

```python
# tests/unit/test_ote_rig.py
# Golden regression anchors: the OTE rig imports replay_managed/cost_r from the
# SB stop study UNMODIFIED (spec section 5 reconciliation rule). These tests pin
# their exact arithmetic so any drift breaks the build, not the study.
import unittest

from scripts.poc_sb_stops import replay_managed, cost_r


def _trade():
    # long, entry 100, sl 99 (risk 1.0), tp 102.5 (2.5R); range = 2.5
    return {"entry": 100.0, "sl": 99.0, "tp": 102.5, "risk": 1.0,
            "dir": "BUY", "fill_idx": 1}


BARS = {
    # bar0 = signal bar (unused), bar1 sweeps to L3 without stopping,
    # bar2 pulls back to the tightened trail.
    "high": [100.0, 102.6, 102.0],
    "low":  [99.5, 100.2, 101.5],
}


class TestReplayManagedGolden(unittest.TestCase):
    def test_ratchet_runner_golden_value(self):
        # bar1: BE@0.382 -> bank 30% @101.545 (0.4635R) -> bank 50% of 0.70
        # @102.215 (0.77525R) -> runner drops TP, trail=0.268*2.5=0.67,
        # sl -> 102.6-0.67=101.93; bar2 low 101.5 <= 101.93 -> exit
        # 0.35*1.93 = 0.6755R. Total 1.91425R.
        r = replay_managed(_trade(), BARS, runner=True)
        self.assertAlmostEqual(r, 1.91425, places=6)

    def test_ratchet_fixed_tp_golden_value(self):
        # runner=False: after both banks, remaining 0.35 exits at TP 102.5
        # same bar: 1.23875 + 0.35*2.5 = 2.11375R.
        r = replay_managed(_trade(), BARS, runner=False)
        self.assertAlmostEqual(r, 2.11375, places=6)

    def test_stop_first_same_bar(self):
        bars = {"high": [100.0, 102.6], "low": [99.5, 98.9]}   # sweeps SL too
        r = replay_managed(_trade(), bars, runner=True)
        self.assertAlmostEqual(r, -1.0, places=6)              # pessimistic


class TestCostRGolden(unittest.TestCase):
    def test_eurusd_cost_arithmetic(self):
        specs = {"EURUSD": {"tick_size": 1e-05, "tick_value": 1.0}}
        tr = {"risk": 0.001}   # 10 pips
        # spread 8 ticks*1e-5 + (7/1.0)*1e-5 commission = 15e-5 / 1e-3 = 0.15R
        self.assertAlmostEqual(cost_r(tr, "EURUSD", specs), 0.15, places=9)

    def test_spread_stress_multiplier(self):
        specs = {"EURUSD": {"tick_size": 1e-05, "tick_value": 1.0}}
        tr = {"risk": 0.001}
        # 1.5x: (12e-5 + 7e-5)/1e-3 = 0.19R
        self.assertAlmostEqual(cost_r(tr, "EURUSD", specs, 1.5), 0.19, places=9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — verify they pass against the untouched study code**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_rig -v`
Expected: PASS (5 tests). If any fails, STOP — either the hand-computed goldens are wrong (recompute, fix the test) or `poc_sb_stops.py` changed since the study (investigate before proceeding; do not edit the study).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_ote_rig.py
git commit -m "test(ote): golden regression anchors for reused SB replay/cost components"
```

---

### Task 6: Rig core — `scan_symbol` end-to-end on synthetic data

**Files:**
- Create: `scripts/poc_ote_canonical.py`
- Modify: `tests/unit/test_ote_rig.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–4; `SMCAnalyzer` (H1 ATR — the exact live ATR source, avoiding rig/live ATR drift)
- Produces (consumed by Task 7):
  - `scan_symbol(m5df, quick=False, verbose=False) -> (trades: list[dict], bars: dict, funnel: dict)`
  - Trade dict keys: `dir, time, year, entry, sl, tp, risk, fill_idx, exit_idx, outcome ("SL"|"TP"), r (fixed gross), leg_low, leg_high, atr_h1, z_lo, z_hi, pullback_ext, bias` (plus `sym` added by the caller). `bars = {"high": np.array, "low": np.array}` at M5 resolution — directly consumable by `replay_managed`.
  - `funnel` keys: `legs, setups, zone_touch, mss, entries`
  - Module constants: `ZONE_LO=0.62, ZONE_HI=0.79, MIN_SWING_ATR=2.0, STOP_FLOOR_ATR=0.5, TTL_H1_BARS=12, RR=2.5, LK_HTF=3, LK_M5=2`

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_ote_rig.py`)

```python
import pandas as pd

from scripts.poc_ote_canonical import scan_symbol, RR, STOP_FLOOR_ATR
from src.analysis.ote_structure import zone_invalidation


def _mk_m5(segments, start=100.0, t0="2024-01-02"):
    """Deterministic M5 candles from linear (n_bars, delta) segments.
    open=prev close, close=linear step, high/low = body +/- 0.01."""
    rows = []
    px = start
    t = pd.Timestamp(t0)
    for n, delta in segments:
        step = delta / n
        for _ in range(n):
            o, c = px, px + step
            rows.append({"time": t, "open": o, "close": c,
                         "high": max(o, c) + 0.01, "low": min(o, c) - 0.01})
            px = c
            t += pd.Timedelta(minutes=5)
    return pd.DataFrame(rows)


# Synthetic bullish market (~3,111 M5 bars ~ 259 H1 ~ 65 H4):
# 5 trend cycles (24 H1 up +3.0 / 16 H1 down -1.2: HH+HL on H1 AND H4, pullback
# depth 0.4 -> never reaches the 0.62-0.79 zone, so no early entries), then an
# impulse leg +4.0 (24 H1), a pullback -2.9 into the zone (depth 0.725), an M5
# chop that prints a confirmed lk=2 swing high and breaks it (MSS), then +2.8
# continuation that reaches the 2.5R target.
SEGMENTS = (5 * [(288, +3.0), (192, -1.2)]
            + [(288, +4.0), (120, -2.9),
               (6, +0.15), (6, -0.10), (3, +0.20),
               (288, +2.8)])


class TestScanSymbolSynthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trades, cls.bars, cls.funnel = scan_symbol(_mk_m5(SEGMENTS))

    def test_exactly_one_buy_entry(self):
        self.assertEqual(self.funnel["entries"], 1, msg=f"funnel={self.funnel}")
        self.assertEqual(len(self.trades), 1)
        self.assertEqual(self.trades[0]["dir"], "BUY")

    def test_funnel_progression(self):
        f = self.funnel
        self.assertGreater(f["legs"], 0)
        self.assertGreater(f["setups"], 0)
        self.assertGreaterEqual(f["setups"], f["zone_touch"])
        self.assertGreaterEqual(f["zone_touch"], f["mss"])

    def test_stop_is_h1_anchored(self):
        t = self.trades[0]
        inval = zone_invalidation(t["z_lo"], t["z_hi"], t["atr_h1"], True)
        self.assertLessEqual(t["sl"], inval + 1e-9)             # beyond invalidation
        self.assertLessEqual(t["sl"], t["pullback_ext"] + 1e-9)  # beyond pullback
        self.assertGreaterEqual(t["entry"] - t["sl"],
                                STOP_FLOOR_ATR * t["atr_h1"] - 1e-9)

    def test_tp_is_25R_and_hit(self):
        t = self.trades[0]
        self.assertAlmostEqual(t["tp"], t["entry"] + RR * t["risk"], places=9)
        self.assertEqual(t["outcome"], "TP")
        self.assertAlmostEqual(t["r"], RR, places=9)

    def test_entry_inside_or_above_zone(self):
        t = self.trades[0]
        self.assertGreaterEqual(t["entry"], t["z_lo"])
        self.assertLess(t["entry"], t["leg_high"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_rig -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.poc_ote_canonical'`

- [ ] **Step 3: Write the rig core**

```python
#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/poc_ote_canonical.py
# Canonical OTE MTF study (3-year, 11 instruments, net of costs).
# Spec + pre-registered gate: docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md
#
# Model (frozen a-priori, spec section 1): H4+H1 structural BOS bias agree ->
# most recent H1 impulse leg (>=2.0xATR(H1)) -> OTE zone 0.62-0.79 -> price
# trades into zone -> M5 MSS in trend direction -> MARKET at next M5 open.
# Stop: H1-anchored (pullback extreme / zone invalidation / 0.5xATR floor).
# Exits: fixed 2.5R AND v14.4 ratchet+runner (dual-model gate).
#
#   .venv/bin/python scripts/poc_ote_canonical.py                    # full run
#   .venv/bin/python scripts/poc_ote_canonical.py --sym EURUSD --quick
#   .venv/bin/python scripts/poc_ote_canonical.py --sym EURUSD --golden \
#       --start 2026-03-02 --end 2026-03-20      # event log for manual check
# ==============================================================================
import argparse
import json
import os
import random as _random
import sys
import time as _t

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.analysis.smc_analyzer import SMCAnalyzer                  # noqa: E402
from src.analysis.signal_grader import SignalGrader                # noqa: E402
from src.analysis.ote_structure import (                           # noqa: E402
    structure_bias, confirmed_swings, precompute_last_swings, impulse_leg,
    ote_zone, zone_invalidation, mss_confirm, stop_anchor, advance_setup,
    AWAIT_ZONE, IN_ZONE, CONFIRMED, DEAD,
)
from scripts.poc_sb_stops import (                                 # noqa: E402
    replay_managed, cost_r, metrics, wilson, SPREADS,
)

# Frozen parameters (spec section 1) — the one-pass rule forbids tuning these.
ZONE_LO, ZONE_HI = 0.62, 0.79
MIN_SWING_ATR = 2.0
STOP_FLOOR_ATR = 0.5
TTL_H1_BARS = 12
RR = 2.5
LK_HTF = 3
LK_M5 = 2
COST_SCREEN_R = 0.25        # a-priori economic viability screen (spec section 2)
NY_SHIFT = -7               # broker->NY approx, as in poc_sb_stops

# Copied from scripts/poc_mtf_pb2.py (import avoided: that module drags in the
# whole backtest-engine chain at import time; these 8 lines are stable).
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


def bootstrap_expectancy_ci(rs, n_boot=2000, alpha=0.05, seed=0):
    """Percentile bootstrap CI for mean R (copied from poc_mtf_pb2, same reason)."""
    if not rs:
        return (0.0, 0.0)
    rng = _random.Random(seed)
    n = len(rs)
    means = sorted(sum(rs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(n_boot))
    return (means[int((alpha / 2) * n_boot)],
            means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))])


def _resample(df, rule):
    return (df.set_index("time")
              .resample(rule).agg({"open": "first", "high": "max",
                                   "low": "min", "close": "last"})
              .dropna().reset_index())


def scan_symbol(m5df, quick=False, verbose=False):
    """One pass over an M5 frame -> (trades, bars, funnel). Trades carry the
    FIXED-2.5R outcome (which also fixes the one-open-per-symbol sequencing);
    the managed exit is replayed by the caller on the same entries."""
    df = m5df.copy()
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    m5_t = pd.to_datetime(df["time"]).values
    m5_o = df["open"].values.astype(float)
    m5_h = df["high"].values.astype(float)
    m5_l = df["low"].values.astype(float)
    m5_c = df["close"].values.astype(float)
    n = len(df)

    h1 = _resample(df, "1h")
    h4 = _resample(df, "4h")
    h1_t = pd.to_datetime(h1["time"]).values
    h4_t = pd.to_datetime(h4["time"]).values
    h1_h = list(h1["high"].values.astype(float))
    h1_l = list(h1["low"].values.astype(float))
    h1_bias = structure_bias(h1_h, h1_l, LK_HTF)
    h4_bias = structure_bias(list(h4["high"].values.astype(float)),
                             list(h4["low"].values.astype(float)), LK_HTF)
    atr_h1 = SMCAnalyzer(h1.copy()).process()["ATR"].values   # live ATR source
    swh_h1, swl_h1 = confirmed_swings(h1_h, h1_l, LK_HTF)
    last_swh, last_swl = precompute_last_swings(list(m5_h), list(m5_l), LK_M5)

    # containing H1/H4 index per M5 bar; H1 bar (cont-1) is closed once we are
    # inside bar `cont` (bias/legs use only CLOSED HTF bars — no look-ahead)
    cont_h1 = np.searchsorted(h1_t, m5_t, side="right") - 1

    trades = []
    funnel = {"legs": 0, "setups": 0, "zone_touch": 0, "mss": 0, "entries": 0}
    setup = None
    busy_until = -1
    prev_cont = int(cont_h1[0])

    def _say(msg, i):
        if verbose:
            print(f"  [{pd.Timestamp(m5_t[i])}] {msg}")

    for i in range(n):
        cont = int(cont_h1[i])
        if cont != prev_cont:                       # a new H1 bar started ->
            upto = cont - 1                         # bar `upto` just closed
            prev_cont = cont
            if upto >= 1:
                h4c = int(np.searchsorted(h4_t, m5_t[i], side="right")) - 2
                b1 = h1_bias[upto]
                b4 = h4_bias[h4c] if h4c >= 0 else "NEUTRAL"
                bias = b1 if (b1 == b4 and b1 != "NEUTRAL") else None
                if bias is None:
                    if setup is not None:
                        _say("SETUP dropped: bias lost", i)
                    setup = None
                else:
                    leg = impulse_leg(h1_h, h1_l, upto, LK_HTF, bias,
                                      swh_h1, swl_h1)
                    a = float(atr_h1[upto]) if not np.isnan(atr_h1[upto]) else 0.0
                    if leg is not None and a > 0 and \
                            (leg[1] - leg[0]) >= MIN_SWING_ATR * a:
                        funnel["legs"] += 1
                        key = (leg[2], leg[3])
                        is_long = bias == "BULLISH"
                        if setup is None or setup["key"] != key \
                                or setup["is_long"] != is_long:
                            z_lo, z_hi = ote_zone(leg[0], leg[1], bias,
                                                  ZONE_LO, ZONE_HI)
                            ext = leg[3] if is_long else leg[2]
                            pb_start = (int(np.searchsorted(m5_t, h1_t[ext + 1]))
                                        if ext + 1 < len(h1_t) else i)
                            setup = {"key": key, "is_long": is_long,
                                     "bias": bias, "leg_lo": leg[0],
                                     "leg_hi": leg[1], "z_lo": z_lo,
                                     "z_hi": z_hi, "atr": a, "created": upto,
                                     "state": AWAIT_ZONE, "pb_start": pb_start}
                            funnel["setups"] += 1
                            _say(f"SETUP {bias} leg=({leg[0]:.5f},{leg[1]:.5f}) "
                                 f"zone=({z_lo:.5f},{z_hi:.5f}) atr={a:.5f}", i)
                # TTL expiry (checked on every H1 close)
                if setup is not None and upto - setup["created"] >= TTL_H1_BARS:
                    _say("SETUP expired: TTL", i)
                    setup = None

        if i <= busy_until or setup is None:
            continue

        s = setup
        mss_ok = mss_confirm(m5_h, m5_l, m5_c, i, s["bias"], last_swh, last_swl)
        leg_origin = s["leg_lo"] if s["is_long"] else s["leg_hi"]
        prev_state = s["state"]
        st = advance_setup(prev_state, s["is_long"], s["z_lo"], s["z_hi"],
                           leg_origin, m5_h[i], m5_l[i], m5_c[i], mss_ok)
        if st == IN_ZONE and prev_state == AWAIT_ZONE:
            funnel["zone_touch"] += 1
            _say("ZONE touched", i)
        s["state"] = st
        if st == DEAD:
            _say("SETUP dead: leg origin breached", i)
            setup = None
            continue
        if st != CONFIRMED:
            continue

        funnel["mss"] += 1
        _say("MSS confirmed", i)
        setup = None                                # one shot per setup
        if i + 1 >= n:
            continue
        is_long = s["is_long"]
        entry = float(m5_o[i + 1])
        pb_ext = (float(np.min(m5_l[s["pb_start"]:i + 1])) if is_long
                  else float(np.max(m5_h[s["pb_start"]:i + 1])))
        inval = zone_invalidation(s["z_lo"], s["z_hi"], s["atr"], is_long)
        sl = stop_anchor(entry, pb_ext, inval, s["atr"], is_long, STOP_FLOOR_ATR)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = entry + RR * risk if is_long else entry - RR * risk

        # fixed-RR resolution, same-bar SL first (pessimistic); fixes sequencing
        outcome, r, exit_k = "OPEN", 0.0, n - 1
        for k in range(i + 1, n):
            sl_hit = (m5_l[k] <= sl) if is_long else (m5_h[k] >= sl)
            tp_hit = (m5_h[k] >= tp) if is_long else (m5_l[k] <= tp)
            if sl_hit:
                outcome, r, exit_k = "SL", -1.0, k
                break
            if tp_hit:
                outcome, r, exit_k = "TP", RR, k
                break
        busy_until = exit_k
        if outcome == "OPEN":
            continue
        funnel["entries"] += 1
        ts = pd.Timestamp(m5_t[i + 1])
        _say(f"ENTRY {'BUY' if is_long else 'SELL'} @{entry:.5f} sl={sl:.5f} "
             f"tp={tp:.5f} -> {outcome}", i)
        trades.append({"dir": "BUY" if is_long else "SELL", "time": ts,
                       "year": int(ts.year), "entry": entry, "sl": sl,
                       "tp": tp, "risk": risk, "fill_idx": i + 1,
                       "exit_idx": exit_k, "outcome": outcome, "r": float(r),
                       "leg_low": s["leg_lo"], "leg_high": s["leg_hi"],
                       "atr_h1": s["atr"], "z_lo": s["z_lo"],
                       "z_hi": s["z_hi"], "pullback_ext": pb_ext,
                       "bias": s["bias"]})

    bars = {"high": m5_h, "low": m5_l}
    return trades, bars, funnel
```

(`main()` comes in Task 7 — for now end the file with:)

```python
if __name__ == "__main__":
    print("main() arrives in Task 7; use scan_symbol() via tests until then.")
```

- [ ] **Step 4: Run the synthetic e2e test**

Run: `.venv/bin/python -m unittest tests.unit.test_ote_rig -v`
Expected: PASS (all tests including the 5 Task-5 goldens).

If `test_exactly_one_buy_entry` fails, debug with the funnel counts in the failure message before touching anything: `legs=0` → the H1 zigzag isn't producing confirmed BOS swings (check `structure_bias` wiring); `setups>0, zone_touch=0` → zone math or the pullback depth; `zone_touch>0, mss=0` → the M5 chop isn't printing a confirmed lk=2 swing or the break bar's close isn't above it. Fix the *rig wiring* — the fixture geometry is hand-verified in the plan; the detection functions are pinned by Tasks 1–4. Do NOT weaken the fixture or the frozen parameters to make it pass.

- [ ] **Step 5: Run the full unit suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK, no regressions

- [ ] **Step 6: Commit**

```bash
git add scripts/poc_ote_canonical.py tests/unit/test_ote_rig.py
git commit -m "feat(ote): rig core scan_symbol - synthetic end-to-end validated"
```

---

### Task 7: Rig `main()` — cost screen, gate sections, outputs, real-data smoke

**Files:**
- Modify: `scripts/poc_ote_canonical.py` (replace the placeholder `__main__` block with `main()`)

**Interfaces:**
- Consumes: `scan_symbol` (Task 6); `replay_managed`, `cost_r`, `metrics`, `wilson` (SB study); `bootstrap_expectancy_ci`, `ASSET_CLASSES`, `asset_class_of` (module-local)
- Produces: CLI `--sym --quick --golden --start --end --out`; CSV `data/history/ote_canonical_trades.csv`; stdout report with Sections 0–5 and a final verdict block (log captured via shell redirect in Task 8)

- [ ] **Step 1: Implement `main()`** (replace the placeholder block)

```python
def _grade_mirror(t, grader):
    """Offline SignalGrader mirror (reported, not gated — spec section 3).
    candle=None: the displacement factor is unavailable offline; noted in output."""
    decision = {"signal": t["dir"], "price": t["entry"], "sl": t["sl"],
                "tp": t["tp"]}
    ny_hour = (int(t["time"].hour) + NY_SHIFT) % 24
    ctx = {"bias": t["bias"], "liquidity": {}, "ny_time": f"{ny_hour:02d}:00"}
    return grader.grade(decision, ctx, candle=None)["grade"]


def _gate_class(rows, key_net, label):
    """70/30 chronological OOS gate for one asset class + one exit model.
    Returns (train_exp, test_exp, n_test, ci_lo, ci_hi, passed)."""
    rows = sorted(rows, key=lambda t: t["time"])
    cut = int(len(rows) * 0.7)
    tr_rs = [t[key_net] for t in rows[:cut]]
    te_rs = [t[key_net] for t in rows[cut:]]
    tr_exp = sum(tr_rs) / len(tr_rs) if tr_rs else 0.0
    te_exp = sum(te_rs) / len(te_rs) if te_rs else 0.0
    lo, hi = bootstrap_expectancy_ci(te_rs)
    wins = sum(1 for r in te_rs if r > 0)
    _, w_lo, w_hi = wilson(wins, len(te_rs))     # win-rate CI (reported, spec s3)
    passed = (tr_exp > 0 and te_exp > 0 and len(te_rs) >= 30
              and (lo > 0 or lo > -0.02))
    print(f"    {label:10} train={tr_exp:+.3f} test={te_exp:+.3f} "
          f"(n_te={len(te_rs)}) bootCI[{lo:+.3f},{hi:+.3f}] "
          f"winCI[{w_lo*100:.0f}-{w_hi*100:.0f}%] "
          f"{'PASS' if passed else 'fail'}")
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--golden", action="store_true",
                    help="verbose per-event log for manual verification")
    ap.add_argument("--start", default=None, help="date filter (golden mode)")
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default="data/history/ote_canonical_trades.csv")
    a = ap.parse_args()
    syms = [a.sym] if a.sym else SYMS

    with open("data/specs.json") as f:
        specs = json.load(f)

    print("### Canonical OTE MTF study — H4+H1 BOS -> H1 leg -> 0.62-0.79 zone "
          "-> M5 MSS (spec 2026-07-11) ###\n", flush=True)

    all_trades = []
    funnels = {}
    for sym in syms:
        path = f"data/history/{sym}_M5.csv"
        if not os.path.exists(path):
            print(f"[SKIP] {sym}: no data file")
            continue
        t0 = _t.time()
        df = pd.read_csv(path).rename(columns={"datetime": "time"})
        df["time"] = pd.to_datetime(df["time"])
        if a.start:
            df = df[df["time"] >= pd.Timestamp(a.start)].reset_index(drop=True)
        if a.end:
            df = df[df["time"] <= pd.Timestamp(a.end)].reset_index(drop=True)
        trades, bars, funnel = scan_symbol(df, quick=a.quick, verbose=a.golden)
        funnels[sym] = funnel
        for t in trades:
            t["sym"] = sym
            t["r_mgd"] = replay_managed(t, bars, runner=True)   # v14.4 engine
            for mult, key in ((1.0, "c1"), (1.5, "c15"), (2.0, "c2")):
                t[key] = cost_r(t, sym, specs, mult)
        all_trades += trades
        print(f"[{sym}] funnel={funnel}  ({_t.time()-t0:.0f}s)", flush=True)

    if not all_trades:
        print("No trades.")
        return
    pd.DataFrame(all_trades).to_csv(a.out, index=False)
    print(f"\n[CSV] {len(all_trades)} trades -> {a.out}\n")

    # net columns: gross r minus cost, per exit model / spread stress
    for t in all_trades:
        t["net_fix_1"] = t["r"] - t["c1"]
        t["net_fix_15"] = t["r"] - t["c15"]
        t["net_mgd_1"] = t["r_mgd"] - t["c1"]
        t["net_mgd_15"] = t["r_mgd"] - t["c15"]

    # ---- Section 1: a-priori cost screen (median RT cost at realized stops)
    print("=" * 88)
    print(f"1. COST SCREEN — median round-trip cost at realized stops "
          f"(exclude > {COST_SCREEN_R}R)")
    print("=" * 88)
    included = []
    for sym in sorted({t["sym"] for t in all_trades}):
        cs = [t["c1"] for t in all_trades if t["sym"] == sym]
        med = float(np.median(cs))
        ok = med <= COST_SCREEN_R
        if ok:
            included.append(sym)
        print(f"  {sym:8} median={med:.3f}R n={len(cs):5d} "
              f"{'INCLUDED' if ok else 'EXCLUDED (economic screen)'}")
    inc_trades = [t for t in all_trades if t["sym"] in included]

    # ---- Section 2: per-symbol table (net 1x)
    print("\n" + "=" * 88)
    print("2. PER-SYMBOL (net 1x costs)")
    print("=" * 88)
    for sym in sorted({t["sym"] for t in all_trades}):
        rows = [t for t in all_trades if t["sym"] == sym]
        mf = metrics([t["net_fix_1"] for t in rows])
        mm = metrics([t["net_mgd_1"] for t in rows])
        print(f"  {sym:8} n={mf['n']:5d} FIXED exp={mf['exp']:+.3f}R "
              f"PF={mf['pf']:4.2f} | MANAGED exp={mm['exp']:+.3f}R "
              f"PF={mm['pf']:4.2f}")

    # ---- Section 3: pre-registered gate per asset class
    print("\n" + "=" * 88)
    print("3. GATE — per asset class: net>0 train AND test, BOTH exit models, "
          "n_te>=30, 1.5x sign holds, bootCI (spec section 3)")
    print("=" * 88)
    verdicts = {}
    for cls, cls_syms in ASSET_CLASSES.items():
        rows = [t for t in inc_trades if t["sym"] in cls_syms]
        if not rows:
            print(f"\n  [{cls}] no trades (or all symbols cost-excluded)")
            verdicts[cls] = False
            continue
        print(f"\n  [{cls}] n={len(rows)}")
        p_fix = _gate_class(rows, "net_fix_1", "FIXED")
        p_mgd = _gate_class(rows, "net_mgd_1", "MANAGED")
        s15_f = sum(t["net_fix_15"] for t in rows)
        s15_m = sum(t["net_mgd_15"] for t in rows)
        stress = s15_f > 0 and s15_m > 0
        print(f"    1.5x spread pooled: FIXED {s15_f:+.1f}R "
              f"MANAGED {s15_m:+.1f}R {'holds' if stress else 'SIGN FLIP'}")
        verdicts[cls] = p_fix and p_mgd and stress
        print(f"    VERDICT: {'GO' if verdicts[cls] else 'NO-GO'}")

    # ---- Section 4: pooled portfolio, chronological (correct equity-curve DD)
    print("\n" + "=" * 88)
    print("4. POOLED PORTFOLIO — included symbols, chronological")
    print("=" * 88)
    pooled = sorted(inc_trades, key=lambda t: t["time"])
    for key, label in (("net_fix_1", "FIXED net1x"),
                       ("net_mgd_1", "MANAGED net1x"),
                       ("net_mgd_15", "MANAGED net1.5x")):
        m = metrics([t[key] for t in pooled])
        print(f"  {label:16} n={m['n']:5d} exp={m['exp']:+.3f}R "
              f"totR={m['totR']:+7.1f} PF={m['pf']:4.2f} DD={m['dd']:.0f}R "
              f"win={m['winpct']:.1f}%")
    print("  per-year (MANAGED net1x):")
    for yr in sorted({t["year"] for t in pooled}):
        rs = [t["net_mgd_1"] for t in pooled if t["year"] == yr]
        print(f"    {yr}: n={len(rs):4d} exp={sum(rs)/len(rs):+.3f}R")

    # ---- Section 5: grader mirror (reported, not gated)
    print("\n" + "=" * 88)
    print("5. SIGNAL-GRADER MIRROR (candle=None: displacement factor absent — "
          "approximation, reported only)")
    print("=" * 88)
    grader = SignalGrader({"signal_grading": {"enabled": True, "min_grade": "B"}})
    for t in pooled:
        t["grade"] = _grade_mirror(t, grader)
    for g in ("A++", "A+", "A", "B", "C"):
        rs = [t["net_mgd_1"] for t in pooled if t["grade"] == g]
        if rs:
            print(f"  grade {g:3} n={len(rs):5d} exp={sum(rs)/len(rs):+.3f}R")
    gated = [t["net_mgd_1"] for t in pooled if grader.passes(t["grade"])]
    if gated:
        print(f"  >=B floor: n={len(gated)} exp={sum(gated)/len(gated):+.3f}R "
              f"(vs ungated {sum(t['net_mgd_1'] for t in pooled)/len(pooled):+.3f}R)")

    # ---- Final verdict
    print("\n" + "=" * 88)
    gos = [c for c, v in verdicts.items() if v]
    print(f"FINAL: {'GO for ' + ', '.join(gos) if gos else 'NO-GO everywhere'}"
          f"  (one-pass rule: no in-place re-tuning — spec section 3)")
    print("=" * 88)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Re-run the rig unit tests** (imports moved around — make sure nothing broke)

Run: `.venv/bin/python -m unittest tests.unit.test_ote_rig -v`
Expected: PASS

- [ ] **Step 3: Real-data smoke test (single symbol, quick)**

Run: `.venv/bin/python scripts/poc_ote_canonical.py --sym EURUSD --quick`
Expected: completes in under ~3 minutes; prints a funnel line with `legs>0`; Sections 1–5 render without exceptions (small n is fine; `[n<30]`-style thin samples expected on 30k bars). If `entries == 0` on quick data that is a *finding*, not necessarily a bug — check the funnel: a canonical multi-condition model can legitimately be sparse. Verify the funnel decays plausibly (legs ≫ setups ≥ zone_touch ≥ mss ≥ entries) rather than cliff-dropping to zero at one stage.

- [ ] **Step 4: Commit**

```bash
git add scripts/poc_ote_canonical.py
git commit -m "feat(ote): rig main() - cost screen, pre-registered gate, grader mirror"
```

---

### Task 8: Golden-slice verification, full 3-year run, results doc, verdict

**Files:**
- Create: `docs/research/2026-07-XX-ote-canonical-results.md` (XX = actual run date)
- Output: `data/history/ote_canonical_trades.csv`, `data/history/ote_canonical_3yr.log`

**Interfaces:**
- Consumes: the complete rig (Task 7)
- Produces: the GO/NO-GO verdict that decides whether a live-port plan (spec §4) gets written

- [ ] **Step 1: Golden-slice manual verification (spec §5 — before trusting the 3yr run)**

Run: `.venv/bin/python scripts/poc_ote_canonical.py --sym XAUUSD --golden --start 2026-03-02 --end 2026-03-27`
(3 weeks of gold; adjust the window if it prints no SETUP events — pick any window that does.)

Then hand-verify against the raw CSV (`data/history/XAUUSD_M5.csv`) for 2–3 printed setups:
- the SETUP leg endpoints correspond to real H1 swing extremes with an intervening BOS;
- the zone prices are 0.62/0.79 of that leg;
- ZONE touched / MSS confirmed / ENTRY lines occur at bars where the M5 data actually does what the log claims;
- any ENTRY's `sl` is at/most-protective-of the three anchors.

Document what was checked (symbols, dates, events) — it goes in the results doc's "Verification" section. If a discrepancy is found: STOP, fix the rig, re-run Tasks 6–7 tests, redo this step.

- [ ] **Step 2: SB-control reconciliation (belt-and-braces, background)**

The unit goldens (Task 5) already pin `replay_managed`/`cost_r`. As the integration-tier check from spec §5, rerun the SB study once and confirm it still reproduces its published headline:

Run (background, ~30–60 min): `.venv/bin/python scripts/poc_sb_stops.py --tf H1 > /tmp/sb_recon_h1.log 2>&1` (or the session scratchpad dir — anywhere outside the repo; this log is a throwaway check, not an artifact)
Expected: the `RATCHET+RUNNER` / `ATR10` pooled row shows `exp=+0.109R PF=1.26` (±0.001), matching `docs/research/2026-07-11-silverbullet-h1-stop-study.md`. If it doesn't, STOP — the shared components or data changed; investigate before running the OTE study.

- [ ] **Step 3: Calibration pre-pass (spec §2 — read the cost screen before the verdict)**

The full run prints Section 1 first; there is no separate pre-pass script. Sanity-expectations before launching: realized stops should be ≥0.5×ATR(H1) by construction, so median costs should land near the SB study's ATR05–ATR10 range (all 11 symbols passed ≤0.25R except GBPCAD 0.26R and XBRUSD 1.00R there). If Section 1 excludes materially more than those two, treat it as a red flag on stop plumbing (check a few trades' `risk` vs `atr_h1` in the CSV) before accepting the numbers.

- [ ] **Step 4: Full 3-year run**

Run (background; expect roughly 30–90 min for 11 symbols):
```bash
.venv/bin/python scripts/poc_ote_canonical.py > data/history/ote_canonical_3yr.log 2>&1
```
Expected: log ends with the `FINAL:` verdict block; `data/history/ote_canonical_trades.csv` written.

- [ ] **Step 5: Write the results doc**

Create `docs/research/2026-07-XX-ote-canonical-results.md` (use the actual date) with this structure, filling every number from the log:

```markdown
# Canonical OTE MTF — 3-Year Gate Results

**Date:** 2026-07-XX · **Rig:** `scripts/poc_ote_canonical.py`
**Data:** 3 years M5 (2023-06 → 2026-06), 11 instruments, FBS specs, costs in R
(spread ×1/×1.5 + $7/lot). **Raw:** `data/history/ote_canonical_3yr.log`,
`data/history/ote_canonical_trades.csv`
**Spec + pre-registered gate:** `docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md`

## Verdict
**[GO for <classes> / NO-GO everywhere].** [2-3 sentences: which gate legs
failed/passed, and whether the three deltas vs MTF-PB v2 (H1 legs, H1-anchored
stops, v14.4 engine) changed the sign as hypothesized.]

## Verification performed
[Golden-slice: symbols/dates/events hand-checked. SB reconciliation result.]

## Cost screen
[Section 1 table. Symbols excluded and why.]

## Gate table
[Section 3 per class: train/test exp both models, n_te, bootCI, 1.5x, verdict.]

## Portfolio + context
[Section 4 pooled rows + per-year. Comparison row: MTF-PB v2 pooled −0.28R and
SB-H1 control +0.109R for scale.]

## Grader mirror
[Section 5, with the candle=None caveat.]

## What happens next
[On GO: live-port plan per spec section 4. On NO-GO: OTE stays disabled;
carry the rig to the Unicorn cycle. One-pass rule: any rule change requires a
new mini-spec + fresh pre-registered run.]
```

- [ ] **Step 6: Run the full unit suite one final time**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK

- [ ] **Step 7: Commit the study**

```bash
git add docs/research/2026-07-*-ote-canonical-results.md data/history/ote_canonical_3yr.log
git commit -m "docs(research): canonical OTE 3yr gate results - [GO/NO-GO verdict]"
```
(Adjust the message to the actual verdict. The trades CSV is large — commit the log + doc only, matching how prior studies were archived.)

- [ ] **Step 8: Report back to the user**

Present: the verdict per asset class, the headline numbers vs the two anchors (MTF-PB v2 −0.28R pooled; SB-H1 +0.109R), and the decision point — on GO, the live port (spec §4) needs its own plan; on NO-GO, the sequence advances to the Unicorn cycle. **Do not start the live port or any parameter iteration without explicit user direction.**

---

## Verification (whole plan)

1. `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` — everything green.
2. `data/history/ote_canonical_3yr.log` exists and ends with a `FINAL:` block.
3. The results doc's every number traces to the log; the verdict follows mechanically from the pre-registered gate — no judgment calls, no post-hoc filters.
