# Pullback Monetizer Overlay — Rig Validation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the offline SilverBullet study rig (`scripts/poc_sb_stops.py`) so it simulates the runner-phase Pullback Monetizer overlay and reports it against the spec's pre-registered gate — the decision point that determines whether any live code gets built.

**Architecture:** Add one pure replay function, `replay_overlay()`, that reproduces the validated `replay_managed(runner=True)` exactly when the overlay is off (the Control arm), and adds bank/re-add (arm A) or trail-tighten (arm C) in the runner phase (`level ≥ 3`). Add a `metrics()` helper and a new reporting section that sweeps the spec grid and prints a PASS/FAIL verdict per cell. All new logic is unit-tested with deterministic synthetic price paths, mirroring `tests/unit/test_mtf_pb2_perf.py`.

**Tech Stack:** Python 3.10+, numpy/pandas, stdlib `unittest` (no pytest). Existing rig conventions: R measured on initial risk, volume-weighted; same-bar SL-first (pessimistic); partials fill at the fib level.

## Global Constraints

- **Do not modify `replay_managed()`** — it defines the Control baseline (+0.109R/trade, PF 1.26, 24R DD). The overlay's arm="off" path must stay byte-identical to `replay_managed(tr, bars, runner=True)`, guarded by a parity test.
- **This plan builds NO live/production code.** Scope is the offline rig only. Live plumbing (StateManager fields, child tickets, Telegram, ExposureManager) is a separate plan, written only if the gate passes.
- **Tests:** stdlib `unittest`, files under `tests/unit/test_*.py`, run with `.venv/bin/python -m unittest tests.unit.<module> -v`. Import the rig as `from scripts import poc_sb_stops as sb`.
- **R/cost conventions (copy exactly):** realized R is volume-weighted on initial risk via `r_of(px) = (px-e)/risk` (long) / `(e-px)/risk` (short). Overlay round-trip cost is charged by the caller as `cost_r(t) * extra_rt_units` — `replay_overlay` never computes cost itself.
- **Pre-registered success criteria (in order):** (1) max DD meaningfully below 24R (target ≤ 18R); (2) PF ≥ 1.26; (3) total net R ≥ 90% of Control; (4) holds on the 70/30 OOS split and at ×1.5 spread. Verdict is printed, not decided by the implementer.
- **Overlay parameters:** bank fraction `f ∈ {0.5, 1.0}`; give-back `g ∈ {0.5, 0.75}` (give-back signal only); hard cap `max_cycles = 2`; trail-tighten constant `TIGHT_TRAIL = 0.10`. Runner tail after level 3 is `0.35` of initial volume; runner trail is `(0.886-0.618) = 0.268 × range`.

---

### Task 1: `replay_overlay()` scaffold with Control-arm parity

Add the overlay replay function whose `arm="off"` path is identical to `replay_managed(runner=True)`. This locks the Control baseline before any overlay behavior is added.

**Files:**
- Modify: `scripts/poc_sb_stops.py` (add `replay_overlay` after `replay_managed`, ~line 227)
- Create: `tests/unit/test_sb_overlay.py`

**Interfaces:**
- Consumes: `sb.replay_managed(tr, bars, runner=True) -> float`; trade dict keys `entry, sl, tp, risk, dir, fill_idx`; `bars = {"high": np.array, "low": np.array}`.
- Produces: `sb.replay_overlay(tr, bars, *, arm="off", signal="giveback", f=0.5, g=0.5, max_cycles=2, disp15=None, trace=None) -> (realized_r: float, extra_rt_units: float)`. `arm="off"` returns `(replay_managed(tr,bars,runner=True), 0.0)`. `trace`, if a list, receives `("bank", k, px)` / `("readd", k, px)` tuples.

- [ ] **Step 1: Write the failing parity test**

Create `tests/unit/test_sb_overlay.py`:

```python
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import numpy as np
from scripts import poc_sb_stops as sb


def _bars(path):
    """path: list of (high, low) -> bars dict with numpy arrays."""
    hi = np.array([p[0] for p in path], dtype=float)
    lo = np.array([p[1] for p in path], dtype=float)
    return {"high": hi, "low": lo}


def _long_trade(fill_idx=0):
    # e=100, sl=95 (risk 5), tp=110 (RR2) -> rng=10; L1=103.82 L2=106.18 L3=108.86
    return {"entry": 100.0, "sl": 95.0, "tp": 110.0, "risk": 5.0,
            "dir": "BUY", "fill_idx": fill_idx}


def _runner_then_pullback():
    # climb to L3, set a runner high, then pull back and finally stop out on trail
    return _bars([
        (100.5, 99.9),    # 0: reach 0.05
        (104.0, 103.0),   # 1: reach 0.40 -> BE
        (106.5, 105.5),   # 2: reach 0.65 -> bank30, sl->103.82
        (109.2, 108.0),   # 3: reach 0.92 -> bank50, runner on, hwm=109.2, trail sl->106.52
        (108.5, 107.4),   # 4: pullback (give 1.8 from hwm)
        (110.5, 109.5),   # 5: new hwm 110.5 -> resumption; trail sl->107.82
        (108.0, 107.0),   # 6: lo 107.0 < sl 107.82 -> stop
    ])


class OverlayControlParity(unittest.TestCase):
    def test_arm_off_equals_managed_runner(self):
        bars = _runner_then_pullback()
        tr = _long_trade()
        managed = sb.replay_managed(tr, bars, runner=True)
        r, extra = sb.replay_overlay(tr, bars, arm="off")
        self.assertAlmostEqual(r, managed, places=9)
        self.assertEqual(extra, 0.0)

    def test_arm_off_parity_across_several_paths(self):
        cases = [_bars([(100.2, 99.5), (100.5, 94.9)]),          # immediate stop
                 _bars([(100.1, 99.9), (111.0, 110.0)]),         # straight to TP
                 _runner_then_pullback()]                        # runner + pullback
        for bars in cases:
            tr = _long_trade()
            managed = sb.replay_managed(tr, bars, runner=True)
            r, extra = sb.replay_overlay(tr, bars, arm="off")
            self.assertAlmostEqual(r, managed, places=9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay -v`
Expected: FAIL — `AttributeError: module 'scripts.poc_sb_stops' has no attribute 'replay_overlay'`.

- [ ] **Step 3: Implement `replay_overlay` (overlay hooks present but inert for arm="off")**

Add module constant near the other constants (after `STOP_MODELS`, ~line 49):

```python
TIGHT_TRAIL = 0.10          # arm C: trail distance as fraction of range after signal
```

Add after `replay_managed` (after line 226):

```python
def replay_overlay(tr, bars, *, arm="off", signal="giveback",
                   f=0.5, g=0.5, max_cycles=2, disp15=None, trace=None):
    """Runner-phase Pullback Monetizer overlay on top of the v14.4 ratchet.

    arm="off" -> byte-identical to replay_managed(tr, bars, runner=True) (Control).
    arm="A"   -> bank fraction f of the runner tail on a pullback signal, re-add
                 the banked volume on the next new high-water mark (resumption);
                 at most max_cycles bank/re-add cycles.
    arm="C"   -> same bank signal, but tighten the trail to TIGHT_TRAIL*range once
                 (no extra trades) instead of banking.

    Returns (realized_r, extra_rt_units). realized_r is volume-weighted R on
    initial risk (same convention as replay_managed). extra_rt_units is the total
    tail volume that did an extra bank+re-add round trip; the caller charges it as
    cost_r(t)*extra_rt_units. Bank signal selects only WHEN to bank; re-add is
    always the next-new-HWM event (spec: resumption proven).
    """
    highs, lows = bars["high"], bars["low"]
    e, sl0, tp, risk = tr["entry"], tr["sl"], tr["tp"], tr["risk"]
    is_long = tr["dir"] == "BUY"
    rng = abs(tp - e)
    L1, L2, L3 = 0.382, 0.618, 0.886
    lvl_price = lambda fr: e + fr * rng if is_long else e - fr * rng
    r_of = lambda px: ((px - e) / risk) if is_long else ((e - px) / risk)

    sl, level, vol, realized = sl0, 0, 1.0, 0.0
    trail = (L3 - L2) * rng
    hwm = None
    ov_state = "ARMED"          # ARMED -> BANKED -> (re-add) ARMED ... / DONE
    banked_vol = 0.0
    cycles = 0
    extra_rt_units = 0.0
    n = len(highs)
    for k in range(tr["fill_idx"], n):
        hi, lo = highs[k], lows[k]
        if (is_long and lo <= sl) or (not is_long and hi >= sl):
            return realized + vol * r_of(sl), extra_rt_units
        reach = (hi - e) / rng if is_long else (e - lo) / rng
        if level < 1 and reach >= L1:
            sl, level = e, 1
        if level < 2 and reach >= L2:
            realized += 0.30 * vol * r_of(lvl_price(L2))
            vol *= 0.70
            sl, level = lvl_price(L1), 2
        if level < 3 and reach >= L3:
            realized += 0.50 * vol * r_of(lvl_price(L3))
            vol *= 0.50
            sl, level = lvl_price(L2), 3
            tp = None                       # runner: drop TP
            hwm = hi if is_long else lo
        if level >= 3:
            cur_ext = hi if is_long else lo
            pull_ext = lo if is_long else hi
            if arm != "off" and cycles < max_cycles and ov_state == "ARMED":
                if _overlay_bank_signal(signal, is_long, hwm, pull_ext, g,
                                        trail, disp15, k):
                    if arm == "A":
                        bank_px = (hwm - g * trail) if is_long else (hwm + g * trail)
                        realized += f * vol * r_of(bank_px)
                        banked_vol = f * vol
                        vol *= (1 - f)
                        ov_state = "BANKED"
                        if trace is not None:
                            trace.append(("bank", k, bank_px))
                    elif arm == "C":
                        trail = TIGHT_TRAIL * rng
                        ov_state = "DONE"
            if arm == "A" and ov_state == "BANKED":
                new_hwm = (cur_ext > hwm) if is_long else (cur_ext < hwm)
                if new_hwm:
                    realized -= banked_vol * r_of(cur_ext)   # re-add basis = cur_ext
                    vol += banked_vol
                    extra_rt_units += banked_vol
                    banked_vol = 0.0
                    cycles += 1
                    ov_state = "ARMED"
                    if trace is not None:
                        trace.append(("readd", k, cur_ext))
            hwm = max(hwm, hi) if is_long else min(hwm, lo)
        if tp is not None and ((is_long and hi >= tp) or (not is_long and lo <= tp)):
            return realized + vol * r_of(tp), extra_rt_units
        if level >= 3:
            cand = (hi - trail) if is_long else (lo + trail)
            if (is_long and cand > sl) or (not is_long and cand < sl):
                sl = cand
    return realized + vol * 0.0, extra_rt_units


def _overlay_bank_signal(signal, is_long, hwm, pull_ext, g, trail, disp15, k):
    """Return True if a bank should fire on bar k. giveback: retrace >= g*trail
    from HWM. m15disp: an opposing (counter-core) M15 displacement in bar k."""
    if signal == "giveback":
        give = (hwm - pull_ext) if is_long else (pull_ext - hwm)
        return give >= g * trail
    if signal == "m15disp":
        if disp15 is None:
            return False
        return bool(disp15["bear"][k] if is_long else disp15["bull"][k])
    return False
```

- [ ] **Step 4: Run the parity tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay -v`
Expected: PASS (both parity tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_sb_stops.py tests/unit/test_sb_overlay.py
git commit -m "feat(rig): replay_overlay scaffold with Control-arm parity to replay_managed

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Give-back bank + re-add (arm A)

Verify the arm A behavior end-to-end on deterministic paths: bank fires at the `g×trail` retrace, re-add fires on the next new HWM, the `max_cycles` cap holds, and `extra_rt_units` accounts the re-added volume. (The code was written in Task 1; this task proves and pins it with behavior tests.)

**Files:**
- Modify: `tests/unit/test_sb_overlay.py`

**Interfaces:**
- Consumes: `sb.replay_overlay(..., arm="A", signal="giveback", f, g, max_cycles, trace=[])`.
- Produces: nothing new — validates existing behavior.

- [ ] **Step 1: Write the failing behavior tests**

Append to `tests/unit/test_sb_overlay.py`:

```python
class GiveBackArmA(unittest.TestCase):
    def test_bank_then_readd_once(self):
        bars = _runner_then_pullback()
        tr = _long_trade()
        trace = []
        r, extra = sb.replay_overlay(tr, bars, arm="A", signal="giveback",
                                     f=0.5, g=0.5, trace=trace)
        banks = [t for t in trace if t[0] == "bank"]
        readds = [t for t in trace if t[0] == "readd"]
        self.assertEqual(len(banks), 1, trace)
        self.assertEqual(len(readds), 1, trace)
        self.assertAlmostEqual(extra, 0.5 * 0.35, places=6)  # f * runner tail
        # bank price is HWM(109.2) - g*trail(1.34) = 107.86
        self.assertAlmostEqual(banks[0][2], 107.86, places=2)

    def test_no_readd_when_trailed_out_during_pullback(self):
        # bank fires, then price falls straight into the trail: no new HWM -> no re-add
        bars = _bars([
            (100.5, 99.9), (104.0, 103.0), (106.5, 105.5),
            (109.2, 108.0),   # runner on, hwm 109.2, sl->106.52
            (108.5, 105.0),   # pullback banks; lo 105.0 < sl 106.52 -> stop same bar
        ])
        tr = _long_trade()
        trace = []
        r, extra = sb.replay_overlay(tr, bars, arm="A", signal="giveback",
                                     f=0.5, g=0.5, trace=trace)
        self.assertEqual(extra, 0.0, trace)      # nothing re-added
        self.assertFalse([t for t in trace if t[0] == "readd"])

    def test_max_cycles_cap(self):
        # three separate pullback/resume swings, cap at 2 -> only 2 re-adds
        bars = _bars([
            (100.5, 99.9), (104.0, 103.0), (106.5, 105.5),
            (109.2, 108.0),                        # runner on, hwm 109.2
            (108.6, 107.3),                        # pullback -> bank (cycle 1)
            (110.0, 109.4),                        # new hwm -> re-add 1
            (109.3, 108.0),                        # pullback -> bank (cycle 2)
            (111.0, 110.2),                        # new hwm -> re-add 2
            (110.3, 109.0),                        # pullback -> would bank (blocked by cap)
            (112.5, 111.5),                        # new hwm -> would re-add (blocked)
            (108.0, 100.0),                        # stop out
        ])
        tr = _long_trade()
        trace = []
        r, extra = sb.replay_overlay(tr, bars, arm="A", signal="giveback",
                                     f=1.0, g=0.5, max_cycles=2, trace=trace)
        self.assertEqual(len([t for t in trace if t[0] == "readd"]), 2, trace)
        self.assertEqual(len([t for t in trace if t[0] == "bank"]), 2, trace)
```

- [ ] **Step 2: Run to verify pass/fail**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay.GiveBackArmA -v`
Expected: PASS (arm A was implemented in Task 1). If any assertion fails, fix `replay_overlay` bank/re-add/cap logic — not the test — until green. The most likely fix site is the `ov_state`/`cycles` guards.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_sb_overlay.py
git commit -m "test(rig): pin give-back arm A bank/re-add, no-readd-on-trailout, cycle cap

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Trail-tighten (arm C) — the zero-cost control

Arm C fires the same bank signal but, instead of banking, tightens the trail to `TIGHT_TRAIL×range` once and takes no extra trades. It is the mandatory comparison that tells us whether paying the re-add spread is ever worth it.

**Files:**
- Modify: `tests/unit/test_sb_overlay.py`

**Interfaces:**
- Consumes: `sb.replay_overlay(..., arm="C", signal="giveback")`.
- Produces: nothing new — validates existing arm C behavior.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sb_overlay.py`:

```python
class TrailTightenArmC(unittest.TestCase):
    def test_c_takes_no_extra_trades_and_tightens(self):
        bars = _runner_then_pullback()
        tr = _long_trade()
        trace = []
        r_c, extra_c = sb.replay_overlay(tr, bars, arm="C", signal="giveback",
                                         f=0.5, g=0.5, trace=trace)
        self.assertEqual(extra_c, 0.0)                 # no re-adds ever in C
        self.assertEqual(trace, [])                    # C never emits bank/readd events
        # tightened trail (0.10*rng=1.0) exits differently from Control
        r_off, _ = sb.replay_overlay(tr, bars, arm="off")
        self.assertNotAlmostEqual(r_c, r_off, places=6)

    def test_c_tightens_only_once(self):
        # even with multiple pullbacks, C sets DONE after the first tighten
        bars = _bars([
            (100.5, 99.9), (104.0, 103.0), (106.5, 105.5),
            (109.2, 108.0), (108.6, 107.3), (110.0, 109.4),
            (109.3, 108.0), (108.0, 100.0),
        ])
        tr = _long_trade()
        r_c, extra_c = sb.replay_overlay(tr, bars, arm="C", signal="giveback",
                                         f=0.5, g=0.5)
        self.assertEqual(extra_c, 0.0)
```

- [ ] **Step 2: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay.TrailTightenArmC -v`
Expected: PASS. If `test_c_takes_no_extra_trades_and_tightens` fails on the "differs from Control" assertion, confirm `TIGHT_TRAIL=0.10` makes a tighter trail than the runner `0.268` on this path; adjust the synthetic path so the tighter trail changes the exit if needed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_sb_overlay.py
git commit -m "test(rig): pin arm C trail-tighten (no extra trades, single tighten)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: M15 counter-displacement signal source

Add the second bank-signal candidate: an opposing (counter-core) M15 displacement candle. This requires `collect_signals` to also return per-trade-bar displacement flags computed from the M15 sub-bars of each trade-TF bar. Meaningful only when the trade timeframe is coarser than M15 (the validated config is H1); for M5/M15 the flags are all-False and `m15disp` is a no-op.

**Files:**
- Modify: `scripts/poc_sb_stops.py` (`collect_signals` return, ~line 114; new helper `_disp15_by_bar`)
- Modify: `tests/unit/test_sb_overlay.py`

**Interfaces:**
- Consumes: `enr` DataFrame from `SMCAnalyzer(...).process()` with `is_fvg_bull`/`is_fvg_bear`; the trade-TF `times` array; the raw M5 `df`.
- Produces: `collect_signals(...)` now returns `(signals, bars)` where `bars` additionally holds `bars["disp_bull"]` and `bars["disp_bear"]` — boolean numpy arrays aligned to trade-TF bar index. New helper `sb._disp15_by_bar(df, tf_times, tf) -> {"bull": np.array, "bear": np.array}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sb_overlay.py`:

```python
class M15CounterDisplacement(unittest.TestCase):
    def test_counter_disp_banks_with_trend_does_not(self):
        bars = _runner_then_pullback()
        n = len(bars["high"])
        # opposing displacement (bear, for a long core) on the pullback bar 4
        disp_bear = np.zeros(n, dtype=bool); disp_bear[4] = True
        disp_bull = np.zeros(n, dtype=bool)
        disp15 = {"bull": disp_bull, "bear": disp_bear}
        tr = _long_trade()
        trace = []
        sb.replay_overlay(tr, bars, arm="A", signal="m15disp",
                          f=0.5, disp15=disp15, trace=trace)
        self.assertEqual(len([t for t in trace if t[0] == "bank"]), 1, trace)

        # a with-trend (bull) displacement must NOT bank a long core
        disp15_wt = {"bull": np.ones(n, dtype=bool), "bear": np.zeros(n, dtype=bool)}
        trace2 = []
        sb.replay_overlay(tr, bars, arm="A", signal="m15disp",
                          f=0.5, disp15=disp15_wt, trace=trace2)
        self.assertEqual([t for t in trace2 if t[0] == "bank"], [], trace2)

    def test_disp15_all_false_when_tf_not_coarser(self):
        # a tiny M5 frame; at tf="M5" there is no sub-M15 -> all False
        import pandas as pd
        rng = pd.date_range("2024-01-01", periods=20, freq="5min")
        df = pd.DataFrame({"time": rng, "open": 1.0, "high": 1.001,
                           "low": 0.999, "close": 1.0})
        d = sb._disp15_by_bar(df, df["time"].values, "M5")
        self.assertFalse(d["bull"].any())
        self.assertFalse(d["bear"].any())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay.M15CounterDisplacement -v`
Expected: FAIL — `AttributeError: ... has no attribute '_disp15_by_bar'` (and the first test already passes because `m15disp` was wired in Task 1; run both — the helper test drives this task).

- [ ] **Step 3: Implement `_disp15_by_bar` and thread it through `collect_signals`**

Add helper after `collect_signals` (after line 115):

```python
def _disp15_by_bar(df, tf_times, tf):
    """For each trade-TF bar, True if any M15 sub-bar of that bar is an FVG
    displacement (bull/bear). Returns {'bull': bool[], 'bear': bool[]} aligned
    to tf_times. All-False when tf is M5/M15 (no coarser sub-M15 grouping)."""
    n = len(tf_times)
    empty = {"bull": np.zeros(n, dtype=bool), "bear": np.zeros(n, dtype=bool)}
    if tf not in ("H1",):
        return empty
    m15 = (df.set_index("time")
             .resample("15min").agg({"open": "first", "high": "max",
                                     "low": "min", "close": "last"})
             .dropna().reset_index())
    if len(m15) < 60:
        return empty
    enr15 = SMCAnalyzer(m15.copy()).process()
    b_bull = enr15["is_fvg_bull"].values
    b_bear = enr15["is_fvg_bear"].values
    m15_times = pd.to_datetime(enr15["time"]).values
    # map each M15 bar to the trade-TF bar it falls in (last tf bar <= m15 time)
    out = {"bull": np.zeros(n, dtype=bool), "bear": np.zeros(n, dtype=bool)}
    tf_sorted = np.asarray(tf_times)
    for j in range(len(m15_times)):
        idx = int(np.searchsorted(tf_sorted, m15_times[j], side="right")) - 1
        if 0 <= idx < n:
            if b_bull[j]:
                out["bull"][idx] = True
            if b_bear[j]:
                out["bear"][idx] = True
    return out
```

Then extend the `collect_signals` return. Change the final lines (currently `bars = {"high": highs, "low": lows}` / `return signals, bars`, ~line 114):

```python
    disp15 = _disp15_by_bar(df.rename(columns={"time": "time"}), times, tf)
    bars = {"high": highs, "low": lows,
            "disp_bull": disp15["bull"], "disp_bear": disp15["bear"]}
    return signals, bars
```

Note: `df` inside `collect_signals` already has a `time` column (it was renamed from `datetime` at line 62) and, for coarser tf, was resampled — but `_disp15_by_bar` needs the ORIGINAL M5 `df` to build M15. Capture it before resampling: at line 62 after the rename, add `df_m5 = df.copy()` and pass `df_m5` to `_disp15_by_bar` instead of `df`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay.M15CounterDisplacement -v`
Expected: PASS.

- [ ] **Step 5: Run the full overlay test module (regression)**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay -v`
Expected: PASS (all classes).

- [ ] **Step 6: Commit**

```bash
git add scripts/poc_sb_stops.py tests/unit/test_sb_overlay.py
git commit -m "feat(rig): M15 counter-displacement bank signal + per-bar disp flags

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `metrics()` helper + gate verdict

Add a pure `metrics(net_list)` that returns the numbers the gate needs (n, exp, totR, PF, DD, win%), so the new reporting section can print an explicit PASS/FAIL against Control without touching the validated `block()`.

**Files:**
- Modify: `scripts/poc_sb_stops.py` (add `metrics` after `wilson`, ~line 238)
- Modify: `tests/unit/test_sb_overlay.py`

**Interfaces:**
- Consumes: an ordered list of per-trade net R floats.
- Produces: `sb.metrics(net_list) -> dict` with keys `n, exp, totR, pf, dd, winpct`. DD is peak-to-trough of the cumulative equity curve in R (same definition as `block`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sb_overlay.py`:

```python
class Metrics(unittest.TestCase):
    def test_metrics_matches_block_definitions(self):
        net = [1.0, -1.0, 2.0, -0.5, -0.5, 1.0]
        m = sb.metrics(net)
        self.assertEqual(m["n"], 6)
        self.assertAlmostEqual(m["totR"], 2.0, places=6)
        self.assertAlmostEqual(m["exp"], 2.0 / 6, places=6)
        # gross win 4.0, gross loss 2.0 -> PF 2.0
        self.assertAlmostEqual(m["pf"], 2.0, places=6)
        # equity: 1,0,2,1.5,1.0,2.0 ; peak 2 then 1.0 -> max DD 1.0
        self.assertAlmostEqual(m["dd"], 1.0, places=6)

    def test_metrics_empty(self):
        m = sb.metrics([])
        self.assertEqual(m["n"], 0)
        self.assertEqual(m["dd"], 0.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay.Metrics -v`
Expected: FAIL — no attribute `metrics`.

- [ ] **Step 3: Implement `metrics`**

Add after `wilson` (after line 237):

```python
def metrics(net_list):
    """Gate metrics for an ordered list of per-trade net R."""
    n = len(net_list)
    if n == 0:
        return {"n": 0, "exp": 0.0, "totR": 0.0, "pf": 0.0, "dd": 0.0, "winpct": 0.0}
    tot = sum(net_list)
    gw = sum(x for x in net_list if x > 0)
    gl = abs(sum(x for x in net_list if x < 0))
    pf = gw / gl if gl else float("inf")
    eq = pk = dd = 0.0
    for x in net_list:
        eq += x; pk = max(pk, eq); dd = max(dd, pk - eq)
    wins = sum(1 for x in net_list if x > 0)
    return {"n": n, "exp": tot / n, "totR": tot, "pf": pf, "dd": dd,
            "winpct": 100.0 * wins / n}
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_sb_overlay.Metrics -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_sb_stops.py tests/unit/test_sb_overlay.py
git commit -m "feat(rig): metrics() helper for overlay gate verdict

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Reporting section 6 — sweep the grid, print the verdict; smoke-run

Add the new reporting section that runs on the validated model (`ATR10`), sweeps `signal × f × g`, computes Control/A/C per cell with net cost (including the overlay's extra round-trips), prints DD/PF/totR plus the 70/30 OOS split and ×1.5 spread stress, and emits a PASS/FAIL against the pre-registered gate. Then smoke-run the whole rig on one symbol.

**Files:**
- Modify: `scripts/poc_sb_stops.py` (`main`, add Section 6 before `print("[DONE]")`, ~line 423)

**Interfaces:**
- Consumes: `trades_by["ATR10"]`, `bars_by_sym`, `specs`, `sb.replay_overlay`, `sb.cost_r`, `sb.metrics`.
- Produces: console Section 6 output. No return value.

- [ ] **Step 1: Add Section 6 to `main`**

Insert immediately before `print("[DONE]")` (line 423):

```python
    # ---- 6. Pullback Monetizer overlay (runner phase) — gate vs Control
    print("=" * 88)
    print("6. PULLBACK MONETIZER OVERLAY — model ATR10, runner phase (meaningful at --tf H1)")
    print("   Gate: DD <= 18R (vs Control 24R) & PF >= 1.26 & netR >= 90% of Control, OOS + 1.5x")
    print("=" * 88)
    ov = trades_by["ATR10"]

    def _overlay_net(ts, *, arm, signal, f, g, spread_mult=1.0):
        out = []
        for t in ts:
            r, extra = replay_overlay(t, bars_by_sym[t["sym"]], arm=arm,
                                      signal=signal, f=f, g=g,
                                      disp15={"bull": bars_by_sym[t["sym"]].get("disp_bull"),
                                              "bear": bars_by_sym[t["sym"]].get("disp_bear")}
                                      if signal == "m15disp" else None)
            c = cost_r(t, t["sym"], specs, spread_mult)
            out.append(r - c - extra * c)
        return out

    ov_sorted = sorted(ov, key=lambda t: t["time"])
    ctrl = [replay_overlay(t, bars_by_sym[t["sym"]], arm="off")[0]
            - cost_r(t, t["sym"], specs) for t in ov_sorted]
    cm = metrics(ctrl)
    print(f"CONTROL (ratchet+runner): n={cm['n']} exp={cm['exp']:+.3f}R "
          f"totR={cm['totR']:+.1f} PF={cm['pf']:.2f} DD={cm['dd']:.0f}R\n")

    grid = []
    for signal in ["giveback", "m15disp"]:
        for f in [0.5, 1.0]:
            for g in ([0.5, 0.75] if signal == "giveback" else [0.5]):
                grid.append((signal, f, g))

    for signal, f, g in grid:
        gtag = f"g{g}" if signal == "giveback" else "g-"
        for arm in ["A", "C"]:
            net = _overlay_net(ov_sorted, arm=arm, signal=signal, f=f, g=g)
            m = metrics(net)
            k = int(len(net) * 0.7)
            oos = metrics(net[k:])
            stress = metrics(_overlay_net(ov_sorted, arm=arm, signal=signal,
                                          f=f, g=g, spread_mult=1.5))
            passed = (m["dd"] <= 18.0 and m["pf"] >= 1.26
                      and m["totR"] >= 0.90 * cm["totR"]
                      and oos["exp"] > 0 and stress["exp"] > 0)
            print(f"[{signal:9} f{f} {gtag} arm{arm}] "
                  f"exp={m['exp']:+.3f}R totR={m['totR']:+.1f} PF={m['pf']:.2f} "
                  f"DD={m['dd']:.0f}R | OOS exp={oos['exp']:+.3f} "
                  f"1.5x exp={stress['exp']:+.3f}  -> {'PASS' if passed else 'fail'}")
        print()
```

- [ ] **Step 2: Smoke-run the rig on one symbol at H1**

Run: `.venv/bin/python scripts/poc_sb_stops.py --sym EURUSD --tf H1 --quick`
Expected: runs to `[DONE]`; Section 6 prints a CONTROL line and one line per grid cell per arm with a `PASS`/`fail` tag. No exceptions. (Numbers on one symbol/quick are not the verdict — just proof the section executes.)

- [ ] **Step 3: Run the full unit suite (no regressions)**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK (existing count + the new `test_sb_overlay` cases).

- [ ] **Step 4: Commit**

```bash
git add scripts/poc_sb_stops.py
git commit -m "feat(rig): Section 6 overlay gate report (grid x arms, OOS + spread stress)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Full 3-year run + research note

Run the rig across the validated 9-symbol universe at H1, capture the log, and write the verdict note that either greenlights the live-plumbing plan or kills the feature.

**Files:**
- Create: `docs/research/2026-07-11-pullback-monetizer-overlay-results.md`
- Output: `data/history/sb_overlay_H1.log` (git-ignored data dir; the note cites it)

- [ ] **Step 1: Run the full study at H1, tee to a log**

Run (background it — it processes ~2.2k H1 trades × 11 syms):

```bash
.venv/bin/python scripts/poc_sb_stops.py --tf H1 2>&1 | tee data/history/sb_overlay_H1.log
```

Expected: completes to `[DONE]`; Section 6 shows CONTROL and every grid cell.

- [ ] **Step 2: Write the verdict note**

Create `docs/research/2026-07-11-pullback-monetizer-overlay-results.md` capturing: the CONTROL baseline reproduced (must match the stop study's +0.109R / PF 1.26 / 24R DD within replay tolerance — if it does not, STOP and reconcile before trusting any overlay number); the best cell per signal with its DD/PF/totR/OOS/×1.5; whether ANY cell clears all four pre-registered criteria; and the explicit A-vs-C comparison. End with one of exactly two decisions: **GO** (name the winning cell and arm; next step = write the live-plumbing plan) or **NO-GO** (feature dies; record why). Follow the tone and rigor of `docs/research/2026-07-11-silverbullet-h1-stop-study.md`.

- [ ] **Step 3: Commit**

```bash
git add docs/research/2026-07-11-pullback-monetizer-overlay-results.md
git commit -m "docs(research): pullback monetizer overlay 3yr gate results + GO/NO-GO

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Why DD at the per-trade level captures give-back:** the rig's DD is the peak-to-trough of the trade-sequence equity curve. Runner give-back shows up as *lower realized R on trades that ultimately trail out*; monetizing pullbacks raises those trades' R, which compresses the equity curve's drawdowns. So the existing/`metrics()` DD is the right meter — no intra-trade equity tracking is needed.
- **Re-add accounting (the one subtle line):** banking credits `f*vol*r_of(bank_px)`; re-adding must subtract `banked_vol*r_of(readd_px)` so the re-added parcel's future P&L (which flows through the `vol` bucket as `r_of(exit)` from entry `e`) nets to profit-from-`readd_px`-to-exit. If a parity or hand-computed test is ever off by exactly the bank-to-readd delta, this line is why.
- **Pessimism stance (consistent with the rig):** bank at the `g×trail` threshold price (not the local extreme); re-add at the new-HWM extreme (chasing). This under-promises the overlay — a real fill would usually be better — so a PASS here is conservative.
- **Live plumbing is deliberately out of scope.** Do not add StateManager fields, child tickets, Telegram, or ExposureManager changes in this plan. Those land in a follow-up plan authored only after a GO verdict, per the spec's gate.
