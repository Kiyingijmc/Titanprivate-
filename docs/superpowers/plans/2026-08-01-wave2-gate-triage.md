# Wave-2 Gate-Triage + Aftershock Kill-Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit a pre-registered Wave-2 triage document, build the `HawkesIntensity` detector by TDD, and run the Aftershock IS-only event-study kill-screen whose six ANDed criteria decide PASS / NO-GO / INSUFFICIENT-N.

**Architecture:** Pure-function detector in `src/analysis/hawkes_intensity.py` (event flagging + scale-invariant excitation index, no MLE), pure-numpy stats helpers in `src/analysis/event_study_stats.py`, and a thin research script `scripts/event_study_aftershock.py` that reads only the IS 70% of the frozen lake and writes results + verdict. Spec: `docs/superpowers/specs/2026-08-01-wave2-gate-triage-design.md`.

**Tech Stack:** Python 3.10+, pandas 3.0 / numpy 2.4 only (NO scipy, NO statsmodels — not installed; do not add dependencies), stdlib `unittest` (there is no pytest), frozen parquet lake at `data/lake/frozen/fbs/<SYM>/H1/*.parquet`.

## Global Constraints

- Branch: `feat/wave2-gate-triage` (already exists, off main). Commit order is load-bearing: triage doc BEFORE detector, detector BEFORE screen run (pre-registration discipline).
- Tests: `.venv/bin/python -m unittest tests.unit.<module> -v`; full suite `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` must be green before each commit.
- NEVER commit `data/db/*`, `data/logs/*` churn from the running demo bot. `git add` explicit paths only.
- The frozen lake is read-only. The OOS 30% (per-symbol bars beyond the first `floor(0.7·N)`) must never be read by the study — slice it off immediately after load.
- No new dependencies of any kind (house rule: ask first; this plan needs none).
- Symbols (9): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, BTCUSD.
- All RNG: `numpy.random.default_rng(20260801)` created once per script run.
- Registered parameters (primary cell): q=2.5, TR median window=200 (trailing, excludes current bar), excitation half-life=24 bars, s_lo pctile=20, primary horizon=+8; robustness grid q∈{2.0,2.5,3.0} × half-life∈{12,24,48}.

---

### Task 1: Pre-registered triage document (docs only — MUST be the first commit)

**Files:**
- Create: `docs/research/2026-08-01-wave2-gate-triage.md`
- Modify: `docs/sessions/_BACKLOG.md:127` (one row's description text only)

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-01-wave2-gate-triage-design.md` (the approved design), `docs/strategies/{aftershock,rubicon,rainflow}.md`.
- Produces: the registered protocol every later task implements verbatim. Later tasks must NOT deviate from the definitions written here; if implementation reveals a defect in a definition, STOP and surface it to the operator rather than silently adjusting.

- [ ] **Step 1: Write the triage document**

Create `docs/research/2026-08-01-wave2-gate-triage.md` with exactly these sections (prose may be expanded, definitions must be verbatim):

```markdown
# Wave-2 Gate-Triage — Pre-Registered (Aftershock kill-screen)

Registered BEFORE the detector is built or any market data is read (this
file's commit precedes src/analysis/hawkes_intensity.py in git history —
the same discipline as docs/research/2026-07-14-gyroscope-gate.md).

## Triage ranking (owner-ratified 2026-08-01)

| Rank | Candidate | This cycle? | Rationale |
|---|---|---|---|
| 1 | Aftershock | Yes — kill-screen below | Best GO prior: 5/5 cost-survival (brainstorm §12), volatility clustering is the best-replicated stylized fact in finance; screen is self-contained. |
| 2 | Rubicon | Next cycle | Weakest documented hypothesis (post-break drift persistence), highest salvage value — BOCPD + regime.run_length_posterior ship as infrastructure even on trading NO-GO. |
| 3 | Rainflow (+Coil) | After — shared two-arm gate | One research question, two detectors (docs/strategies/rainflow.md §6); single-sided entry geometry is BINDING for both arms, which drops the P2/OCO dependency previously claimed by the backlog row. |

## Aftershock screen — registered protocol

Dataset: data/lake/frozen/fbs/<SYM>/H1/*.parquet, 9 symbols (EURUSD,
GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, BTCUSD). Per
symbol: concatenate year files, sort by `time`, drop duplicate
timestamps (keep first), then keep ONLY the first floor(0.7·N) bars
(IS). The OOS remainder is never read by this study.

Definitions (verbatim contract for src/analysis/hawkes_intensity.py):
- TR_t = max(high_t, close_{t-1}) − min(low_t, close_{t-1}); TR_0 = high_0 − low_0.
- tr_med_t = median of TR over the previous 200 bars, EXCLUDING bar t
  (pandas: tr.shift(1).rolling(200).median()). Bars with index < 200
  are never events (warmup).
- Event: TR_t > q × tr_med_t, q = 2.5 primary.
- event_dir_t = +1 if close_t > open_t, −1 if close_t < open_t, else 0
  (0 → never eligible).
- closes_beyond_mid: up events close_t > (high_t+low_t)/2; down events
  close_t < (high_t+low_t)/2.
- Excitation (scale-invariant, no MLE): decay = exp(−ln 2 / half_life),
  half_life = 24 bars primary; S⁻_0 = 0;
  S⁻_t = (S⁻_{t−1} + 1{event at t−1}) × decay.
  S⁻ is the excitation JUST BEFORE bar t and never includes bar t's own
  event.
- s_lo = 20th percentile of S⁻ over all IS bars with index ≥ 200, per
  symbol, per parameter cell.
- Eligible (continuation signal) at t: event_t AND event_dir_t ≠ 0 AND
  closes_beyond_mid_t AND S⁻_t < s_lo AND confirm at t+1, where confirm
  means close_{t+1} > mid_t for up events / close_{t+1} < mid_t for
  down events (mid_t = (high_t+low_t)/2).
- Signal time = t+1 (the confirm bar). Signed forward log return at
  horizon h ∈ {1,4,8,24}: y = event_dir_t × (ln close_{t+1+h} − ln
  close_{t+1}). Rows where t+1+h exceeds the IS slice are dropped.
- Control population (for criteria 2–3): ALL IS bars b with index ≥ 200,
  dir_b ≠ 0, and b+1+h inside IS: y = dir_b × (ln close_{b+1+h} − ln
  close_{b+1}) — "any bar's naive continuation", no event/confirm
  conditions. Signal rows are a subset of control rows by construction;
  they are EXCLUDED from the control cell.
- Session buckets from broker-time hour of bar t: Asia [0,8), London
  [8,15), NY-overlap [15,19), NY-late [19,24).
- Spread (price units) for symbol s: SPREADS[s] ticks (scripts/
  poc_sb_stops.py table) × tick_size from data/specs.json.

Kill criteria — ALL six must pass at the PRIMARY cell (q=2.5,
half_life=24, horizon +8) for verdict PASS; any failure → NO-GO;
criterion 5 below floor → INSUFFICIENT-N:
1. Pooled (cost-alive symbols) mean signed forward return at +8 > 0,
   bootstrap 95% CI (5000 draws, seed 20260801) excludes 0.
2. Mean difference (signal cell − control cell), bootstrap 95% CI
   (5000 draws, independent resampling per cell) excludes 0 and is
   positive.
3. OLS of y on {1, signal_dummy, london, ny_overlap, ny_late} over
   control ∪ signal rows (Asia is the dropped reference bucket; numpy
   lstsq): signal coefficient > 0 with case-resampling bootstrap 95% CI
   (2000 refits) excluding 0.
4. ≥6/9 symbols with per-symbol mean signed forward return at +8 > 0.
   Cost-dead symbols (criterion 6) count as NEGATIVE here.
5. Pooled eligible-event count (cost-alive symbols) ≥ 150, else
   INSUFFICIENT-N.
6. Cost sanity per symbol: median (high−low) of that symbol's eligible
   event bars ≥ 8 × spread. Failing symbols are excluded from pooled
   criteria 1–3 and count negative in criterion 4.

Robustness: all 9 (q × half_life) cells reported (pooled +8 mean, CI,
N); the primary cell ALONE decides. Horizons +1/+4/+24 reported,
never deciding. Exhaustion leg: out of scope (continuation-only v1).

## Verdict handling (registered dispositions)
- PASS → draft the full backtest gate mirroring
  docs/research/2026-07-14-gyroscope-gate.md (separate session).
- NO-GO / INSUFFICIENT-N → record in this doc's appendix, update
  docs/strategies/aftershock.md + ARSENAL.md standing, promote Rubicon.
```

- [ ] **Step 2: Reconcile the backlog row**

In `docs/sessions/_BACKLOG.md` line 127 (`coil-rainflow-shared-two-arm-compression` row), replace the description fragment `needs P2 OCO + P8 grading policy + bias-exemption policy` with `single-sided arms per rainflow.md §6 (P2/OCO NOT required); needs P8 grading policy + bias-exemption policy`. Touch nothing else in the file.

- [ ] **Step 3: Verify suite is green (no code changed, cheap insurance)**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 4: Commit (docs only)**

```bash
git add docs/research/2026-08-01-wave2-gate-triage.md docs/sessions/_BACKLOG.md
git commit -m "docs(research): Wave-2 gate-triage pre-registration — Aftershock kill-screen protocol

Registered before any detector code or market-data read. Rubicon next
cycle, Rainflow+Coil shared two-arm gate (single-sided arms, P2 dropped)."
```

---

### Task 2: `true_range` + `flag_events` (TDD)

**Files:**
- Create: `src/analysis/hawkes_intensity.py`
- Test: `tests/unit/test_hawkes_intensity.py`

**Interfaces:**
- Consumes: a pandas DataFrame with columns `open, high, low, close` (RangeIndex, chronological — the frozen-lake shape after load).
- Produces:
  - `true_range(df: pd.DataFrame) -> pd.Series` (float, aligned to df.index)
  - `flag_events(df: pd.DataFrame, q: float = 2.5, window: int = 200) -> pd.DataFrame` — returns a NEW frame of columns `tr` (float), `tr_med` (float, NaN during warmup), `is_event` (bool), `event_dir` (int8: −1/0/+1), `closes_beyond_mid` (bool), same index as df. Tasks 3–4 and 6 rely on these exact names.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_hawkes_intensity.py`:

```python
import unittest

import numpy as np
import pandas as pd

from src.analysis.hawkes_intensity import flag_events, true_range


def _flat_df(n, price=100.0, spread=1.0):
    """n quiet bars: range `spread`, close == open (dir 0)."""
    return pd.DataFrame({
        "open": [price] * n,
        "high": [price + spread / 2] * n,
        "low": [price - spread / 2] * n,
        "close": [price] * n,
    })


class TestTrueRange(unittest.TestCase):
    def test_first_bar_is_high_minus_low(self):
        df = _flat_df(3)
        tr = true_range(df)
        self.assertAlmostEqual(tr.iloc[0], 1.0)

    def test_gap_uses_prev_close(self):
        # bar 1 gaps up: high=112, low=111, prev close=100 -> TR = 12
        df = pd.DataFrame({
            "open": [100.0, 111.0],
            "high": [100.5, 112.0],
            "low": [99.5, 111.0],
            "close": [100.0, 111.5],
        })
        tr = true_range(df)
        self.assertAlmostEqual(tr.iloc[1], 12.0)


class TestFlagEvents(unittest.TestCase):
    def _spike_df(self, n_warm=250, spike_range=10.0):
        """Quiet bars (range 1.0) then one big up bar closing above mid."""
        df = _flat_df(n_warm)
        spike = pd.DataFrame({
            "open": [100.0], "high": [100.0 + spike_range],
            "low": [100.0], "close": [100.0 + spike_range * 0.9],
        })
        return pd.concat([df, spike], ignore_index=True)

    def test_spike_after_warmup_is_event(self):
        out = flag_events(self._spike_df(), q=2.5, window=200)
        self.assertTrue(bool(out["is_event"].iloc[-1]))
        self.assertEqual(int(out["event_dir"].iloc[-1]), 1)
        self.assertTrue(bool(out["closes_beyond_mid"].iloc[-1]))

    def test_no_events_during_warmup(self):
        # spike at index 100 < window 200 must NOT be an event
        df = self._spike_df(n_warm=100)
        out = flag_events(df, q=2.5, window=200)
        self.assertFalse(out["is_event"].any())

    def test_median_excludes_current_bar(self):
        # 250 quiet bars, tr_med at the spike must be the QUIET median (1.0),
        # not influenced by the spike itself
        out = flag_events(self._spike_df(), q=2.5, window=200)
        self.assertAlmostEqual(out["tr_med"].iloc[-1], 1.0)

    def test_quiet_bars_are_not_events(self):
        out = flag_events(_flat_df(300), q=2.5, window=200)
        self.assertFalse(out["is_event"].any())

    def test_doji_event_dir_zero(self):
        # spike bar with close == open -> dir 0, closes_beyond_mid False
        df = _flat_df(250)
        spike = pd.DataFrame({
            "open": [100.0], "high": [105.0], "low": [95.0], "close": [100.0],
        })
        df = pd.concat([df, spike], ignore_index=True)
        out = flag_events(df, q=2.5, window=200)
        self.assertTrue(bool(out["is_event"].iloc[-1]))
        self.assertEqual(int(out["event_dir"].iloc[-1]), 0)
        self.assertFalse(bool(out["closes_beyond_mid"].iloc[-1]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_hawkes_intensity -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.hawkes_intensity'`

- [ ] **Step 3: Implement `true_range` and `flag_events`**

Create `src/analysis/hawkes_intensity.py`:

```python
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
```

(`math` import is used by Task 3's `excitation`; keeping it now avoids a churn commit.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_hawkes_intensity -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/hawkes_intensity.py tests/unit/test_hawkes_intensity.py
git commit -m "feat(analysis): Aftershock event flagging — TR + trailing-median event detector (TDD)"
```

---

### Task 3: `excitation` recursion (TDD, closed-form checks)

**Files:**
- Modify: `src/analysis/hawkes_intensity.py`
- Test: `tests/unit/test_hawkes_intensity.py` (append a class)

**Interfaces:**
- Consumes: `is_event` boolean Series from `flag_events`.
- Produces: `excitation(is_event: pd.Series, half_life: int = 24) -> pd.Series` — S⁻ per the registered recurrence, float, same index. Task 4 and Task 6 rely on this exact name/signature.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_hawkes_intensity.py`:

```python
from src.analysis.hawkes_intensity import excitation  # top of file with other imports


class TestExcitation(unittest.TestCase):
    def test_zero_without_events(self):
        s = excitation(pd.Series([False] * 10), half_life=24)
        self.assertTrue((s == 0.0).all())

    def test_single_event_closed_form(self):
        # event at index 3: S_minus at index 3+k must be decay**k, k >= 1
        ev = pd.Series([False] * 10)
        ev.iloc[3] = True
        hl = 24
        decay = np.exp(-np.log(2) / hl)
        s = excitation(ev, half_life=hl)
        self.assertAlmostEqual(s.iloc[3], 0.0)  # excludes own bar
        for k in (1, 2, 5):
            self.assertAlmostEqual(s.iloc[3 + k], decay**k, places=12)

    def test_half_life_halves_contribution(self):
        ev = pd.Series([False] * 60)
        ev.iloc[0] = True
        s = excitation(ev, half_life=24)
        self.assertAlmostEqual(s.iloc[24], 0.5, places=12)

    def test_two_events_superpose(self):
        ev = pd.Series([False] * 20)
        ev.iloc[2] = True
        ev.iloc[5] = True
        decay = np.exp(-np.log(2) / 24)
        s = excitation(ev, half_life=24)
        self.assertAlmostEqual(s.iloc[8], decay**6 + decay**3, places=12)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest tests.unit.test_hawkes_intensity -v`
Expected: FAIL — `ImportError: cannot import name 'excitation'`

- [ ] **Step 3: Implement**

Append to `src/analysis/hawkes_intensity.py`:

```python
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
```

(A python loop over ~13k IS bars × 9 symbols × 9 cells is ≪1s total; do not prematurely vectorize.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_hawkes_intensity -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/hawkes_intensity.py tests/unit/test_hawkes_intensity.py
git commit -m "feat(analysis): excitation index S-minus with closed-form-verified decay (TDD)"
```

---

### Task 4: eligibility + percentile banding (TDD)

**Files:**
- Modify: `src/analysis/hawkes_intensity.py`
- Test: `tests/unit/test_hawkes_intensity.py` (append a class)

**Interfaces:**
- Consumes: `flag_events` output frame, `excitation` output, the raw OHLC df.
- Produces: `eligible_signals(df: pd.DataFrame, q: float = 2.5, window: int = 200, half_life: int = 24, s_lo_pctile: float = 20.0) -> pd.DataFrame` — one row per ELIGIBLE event, columns: `event_idx` (int, position of the event bar), `signal_idx` (int, = event_idx+1, the confirm bar), `direction` (int), `event_range` (float, high−low of the event bar), `s_minus` (float), `hour` (int, broker hour of the EVENT bar if a `time` column exists, else −1). Also produces module-level helper `s_lo_threshold(s_minus: pd.Series, warmup: int = 200, pctile: float = 20.0) -> float` (numpy percentile, linear interpolation). Task 6 relies on these exact names.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_hawkes_intensity.py`:

```python
from src.analysis.hawkes_intensity import eligible_signals, s_lo_threshold


def _spike_at(df, i, up=True, rng=10.0):
    """Overwrite bar i with a directional spike; bar i+1 with a confirm bar."""
    o = 100.0
    if up:
        df.loc[i, ["open", "high", "low", "close"]] = [o, o + rng, o, o + rng * 0.9]
        df.loc[i + 1, ["open", "high", "low", "close"]] = [
            o + rng * 0.9, o + rng, o + rng * 0.6, o + rng * 0.8]
    else:
        df.loc[i, ["open", "high", "low", "close"]] = [o, o, o - rng, o - rng * 0.9]
        df.loc[i + 1, ["open", "high", "low", "close"]] = [
            o - rng * 0.9, o - rng * 0.6, o - rng, o - rng * 0.8]
    return df


class TestEligibleSignals(unittest.TestCase):
    def test_fresh_confirmed_spike_is_eligible(self):
        df = _spike_at(_flat_df(260), 250, up=True)
        out = eligible_signals(df)
        self.assertEqual(len(out), 1)
        row = out.iloc[0]
        self.assertEqual(int(row["event_idx"]), 250)
        self.assertEqual(int(row["signal_idx"]), 251)
        self.assertEqual(int(row["direction"]), 1)
        self.assertAlmostEqual(float(row["event_range"]), 10.0)

    def test_unconfirmed_spike_not_eligible(self):
        # confirm bar closes back BELOW the event bar's midpoint -> reject
        df = _spike_at(_flat_df(260), 250, up=True)
        df.loc[251, "close"] = 100.0 + 10.0 * 0.3  # below mid (105.0)
        self.assertEqual(len(eligible_signals(df)), 0)

    def test_hot_s_minus_not_eligible(self):
        # two spikes close together: the second arrives with S-minus elevated
        df = _spike_at(_flat_df(280), 250, up=True)
        df = _spike_at(df, 255, up=True)
        out = eligible_signals(df)
        self.assertEqual(list(out["event_idx"]), [250])

    def test_down_event_direction(self):
        df = _spike_at(_flat_df(260), 250, up=False)
        out = eligible_signals(df)
        self.assertEqual(len(out), 1)
        self.assertEqual(int(out.iloc[0]["direction"]), -1)

    def test_s_lo_threshold_is_percentile_after_warmup(self):
        s = pd.Series(np.arange(400, dtype=float))
        # warmup 200 -> population is s[200:400] = 200..399; 20th pctile = 239.8
        self.assertAlmostEqual(s_lo_threshold(s, warmup=200, pctile=20.0), 239.8)


class TestEligibleSignalsHour(unittest.TestCase):
    def test_hour_from_time_column(self):
        df = _spike_at(_flat_df(260), 250, up=True)
        df["time"] = pd.date_range("2024-01-01", periods=260, freq="h")
        out = eligible_signals(df)
        self.assertEqual(int(out.iloc[0]["hour"]), 250 % 24)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest tests.unit.test_hawkes_intensity -v`
Expected: FAIL — `ImportError: cannot import name 'eligible_signals'`

- [ ] **Step 3: Implement**

Append to `src/analysis/hawkes_intensity.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_hawkes_intensity -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Run the FULL unit suite, then commit**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK`

```bash
git add src/analysis/hawkes_intensity.py tests/unit/test_hawkes_intensity.py
git commit -m "feat(analysis): continuation-eligibility + percentile banding for Aftershock screen (TDD)"
```

---

### Task 5: pure-numpy stats helpers (TDD)

**Files:**
- Create: `src/analysis/event_study_stats.py`
- Test: `tests/unit/test_event_study_stats.py`

**Interfaces:**
- Consumes: numpy arrays.
- Produces (Task 6 relies on these exact signatures):
  - `bootstrap_mean_ci(x: np.ndarray, rng: np.random.Generator, n_draws: int = 5000) -> tuple[float, float, float]` → (mean, lo95, hi95)
  - `bootstrap_diff_ci(a: np.ndarray, b: np.ndarray, rng, n_draws: int = 5000) -> tuple[float, float, float]` → (mean_a − mean_b, lo95, hi95), independent resampling per cell
  - `ols_signal_coef(y: np.ndarray, signal: np.ndarray, hours: np.ndarray, rng, n_draws: int = 2000) -> tuple[float, float, float]` → (beta_signal, lo95, hi95); design matrix = [1, signal, london, ny_overlap, ny_late] with buckets Asia [0,8) reference, London [8,15), NY-overlap [15,19), NY-late [19,24); case-resampling bootstrap refits
  - `session_bucket(hours: np.ndarray) -> np.ndarray` (int codes 0=Asia,1=London,2=NYov,3=NYlate)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_event_study_stats.py`:

```python
import unittest

import numpy as np

from src.analysis.event_study_stats import (
    bootstrap_diff_ci,
    bootstrap_mean_ci,
    ols_signal_coef,
    session_bucket,
)


class TestSessionBucket(unittest.TestCase):
    def test_boundaries(self):
        hours = np.array([0, 7, 8, 14, 15, 18, 19, 23])
        np.testing.assert_array_equal(
            session_bucket(hours), [0, 0, 1, 1, 2, 2, 3, 3])


class TestBootstrapMeanCI(unittest.TestCase):
    def test_positive_sample_ci_excludes_zero(self):
        rng = np.random.default_rng(20260801)
        x = rng.normal(1.0, 0.1, size=500)
        mean, lo, hi = bootstrap_mean_ci(x, np.random.default_rng(1))
        self.assertGreater(lo, 0.0)
        self.assertLess(abs(mean - 1.0), 0.05)

    def test_zero_mean_sample_ci_straddles_zero(self):
        rng = np.random.default_rng(20260801)
        x = rng.normal(0.0, 1.0, size=500)
        _, lo, hi = bootstrap_mean_ci(x, np.random.default_rng(1))
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, 0.0)

    def test_deterministic_given_seed(self):
        x = np.arange(50, dtype=float)
        a = bootstrap_mean_ci(x, np.random.default_rng(7))
        b = bootstrap_mean_ci(x, np.random.default_rng(7))
        self.assertEqual(a, b)


class TestBootstrapDiffCI(unittest.TestCase):
    def test_separated_cells(self):
        rng = np.random.default_rng(2)
        a = rng.normal(1.0, 0.5, 300)
        b = rng.normal(0.0, 0.5, 3000)
        diff, lo, hi = bootstrap_diff_ci(a, b, np.random.default_rng(3))
        self.assertGreater(lo, 0.0)
        self.assertLess(abs(diff - 1.0), 0.2)


class TestOlsSignalCoef(unittest.TestCase):
    def test_recovers_planted_effect_net_of_session(self):
        rng = np.random.default_rng(4)
        n = 4000
        hours = rng.integers(0, 24, n)
        signal = (rng.random(n) < 0.05).astype(float)
        # session effect on London bars + true signal effect 0.8
        y = 0.3 * ((hours >= 8) & (hours < 15)) + 0.8 * signal
        y = y + rng.normal(0.0, 0.3, n)
        beta, lo, hi = ols_signal_coef(y, signal, hours, np.random.default_rng(5))
        self.assertLess(abs(beta - 0.8), 0.1)
        self.assertGreater(lo, 0.0)

    def test_pure_session_effect_yields_null_signal(self):
        # signal fires ONLY in London; y is driven ONLY by session ->
        # session dummies must absorb it and the signal CI must straddle 0
        rng = np.random.default_rng(6)
        n = 6000
        hours = rng.integers(0, 24, n)
        london = (hours >= 8) & (hours < 15)
        signal = np.zeros(n)
        lon_idx = np.flatnonzero(london)
        signal[rng.choice(lon_idx, size=len(lon_idx) // 5, replace=False)] = 1.0
        y = 0.5 * london + rng.normal(0.0, 0.3, n)
        _, lo, hi = ols_signal_coef(y, signal, hours, np.random.default_rng(7))
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest tests.unit.test_event_study_stats -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.event_study_stats'`

- [ ] **Step 3: Implement**

Create `src/analysis/event_study_stats.py`:

```python
"""Pure-numpy bootstrap/OLS helpers for the Aftershock kill-screen.

No scipy/statsmodels in this repo — do not add them. Registered
protocol: docs/research/2026-08-01-wave2-gate-triage.md.
"""
from __future__ import annotations

import numpy as np


def session_bucket(hours: np.ndarray) -> np.ndarray:
    """0=Asia [0,8), 1=London [8,15), 2=NY-overlap [15,19), 3=NY-late [19,24)."""
    h = np.asarray(hours)
    return np.select([h < 8, h < 15, h < 19], [0, 1, 2], default=3)


def bootstrap_mean_ci(x, rng, n_draws: int = 5000):
    x = np.asarray(x, dtype=float)
    idx = rng.integers(0, len(x), size=(n_draws, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(x.mean()), float(lo), float(hi)


def bootstrap_diff_ci(a, b, rng, n_draws: int = 5000):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ia = rng.integers(0, len(a), size=(n_draws, len(a)))
    ib = rng.integers(0, len(b), size=(n_draws, len(b)))
    diffs = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(a.mean() - b.mean()), float(lo), float(hi)


def _design(signal: np.ndarray, hours: np.ndarray) -> np.ndarray:
    buckets = session_bucket(hours)
    return np.column_stack([
        np.ones(len(signal)),
        signal,
        (buckets == 1).astype(float),
        (buckets == 2).astype(float),
        (buckets == 3).astype(float),
    ])


def ols_signal_coef(y, signal, hours, rng, n_draws: int = 2000):
    """OLS beta of the signal dummy net of session buckets, + case-resampling CI."""
    y = np.asarray(y, dtype=float)
    signal = np.asarray(signal, dtype=float)
    hours = np.asarray(hours)
    X = _design(signal, hours)
    beta = np.linalg.lstsq(X, y, rcond=None)[0][1]
    n = len(y)
    betas = np.empty(n_draws)
    for d in range(n_draws):
        idx = rng.integers(0, n, size=n)
        betas[d] = np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][1]
    lo, hi = np.percentile(betas, [2.5, 97.5])
    return float(beta), float(lo), float(hi)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest tests.unit.test_event_study_stats -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/event_study_stats.py tests/unit/test_event_study_stats.py
git commit -m "feat(analysis): pure-numpy bootstrap + session-controlled OLS for the kill-screen (TDD)"
```

---

### Task 6: the event-study script

**Files:**
- Create: `scripts/event_study_aftershock.py`

**Interfaces:**
- Consumes: `eligible_signals`, `flag_events`, `excitation`, `s_lo_threshold` (Task 2–4 signatures); `bootstrap_mean_ci`, `bootstrap_diff_ci`, `ols_signal_coef` (Task 5); frozen lake parquets (columns `time, open, high, low, close, tick_volume`, RangeIndex); `data/specs.json` (`tick_size` per symbol); `SPREADS` dict copied verbatim from `scripts/poc_sb_stops.py:43`.
- Produces: `data/results/aftershock_screen/run_card.json`, `per_symbol.csv`, `cells.csv`; prints the verdict block to stdout. Task 7 relies on the run-card keys: `verdict` (`"PASS"|"NO-GO"|"INSUFFICIENT-N"`), `criteria` (dict of 6 booleans), `params`, `pooled`, `per_symbol`, `robustness`.

- [ ] **Step 1: Write the script**

Create `scripts/event_study_aftershock.py` (no test-first here — it is a research runner whose logic units are already tested; its own guarantee is determinism + the registered protocol):

```python
"""Aftershock kill-screen — IS-only event study (registered protocol).

Registered: docs/research/2026-08-01-wave2-gate-triage.md (committed
before this script existed). Reads ONLY the first 70% of each symbol's
frozen H1 lake. Never touches the OOS remainder, data/db, or the bridge.

Usage: .venv/bin/python scripts/event_study_aftershock.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.event_study_stats import (  # noqa: E402
    bootstrap_diff_ci, bootstrap_mean_ci, ols_signal_coef)
from src.analysis.hawkes_intensity import eligible_signals  # noqa: E402

SEED = 20260801
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
           "GBPJPY", "XAUUSD", "US30", "BTCUSD"]
SPREADS = {                 # verbatim from scripts/poc_sb_stops.py:43
    "EURUSD": 8, "GBPUSD": 12, "USDJPY": 10, "AUDUSD": 10, "USDCAD": 12,
    "GBPCAD": 30, "GBPJPY": 25, "XAUUSD": 20, "US30": 200, "BTCUSD": 1000, "XBRUSD": 30,
}
LAKE = "data/lake/frozen/fbs"
OUT_DIR = "data/results/aftershock_screen"
HORIZONS = (1, 4, 8, 24)
PRIMARY_H = 8
Q_GRID = (2.0, 2.5, 3.0)
HL_GRID = (12, 24, 48)
PRIMARY = (2.5, 24)
WINDOW = 200
S_LO_PCTILE = 20.0
IS_FRAC = 0.70
MIN_POOLED_N = 150
COST_MULT = 8.0


def load_is(sym: str) -> pd.DataFrame:
    files = sorted(glob.glob(f"{LAKE}/{sym}/H1/*.parquet"))
    if not files:
        raise SystemExit(f"FATAL: no frozen lake files for {sym}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    cutoff = int(len(df) * IS_FRAC)
    return df.iloc[:cutoff].reset_index(drop=True)  # OOS never leaves this function


def forward_returns(df, sig, horizon):
    """Signed forward log return from the confirm-bar close; drops rows leaving IS."""
    close = df["close"].to_numpy()
    logc = np.log(close)
    s_idx = sig["signal_idx"].to_numpy()
    keep = s_idx + horizon < len(df)
    s_idx, d = s_idx[keep], sig["direction"].to_numpy()[keep]
    y = d * (logc[s_idx + horizon] - logc[s_idx])
    return y, keep


def control_rows(df, horizon, window=WINDOW, exclude=()):
    """All-bar naive continuation cell: dir-signed forward return per bar."""
    close, opn = df["close"].to_numpy(), df["open"].to_numpy()
    logc = np.log(close)
    d = np.sign(close - opn)
    idx = np.arange(window, len(df) - 1 - horizon)
    idx = idx[d[idx] != 0]
    idx = idx[~np.isin(idx, np.asarray(exclude, dtype=int))]
    y = d[idx] * (logc[idx + 1 + horizon] - logc[idx + 1])
    hours = pd.to_datetime(df["time"]).dt.hour.to_numpy()[idx]
    return y, hours


def run_cell(q, hl, per_symbol_out=None):
    """One (q, half_life) parameter cell; returns pooled arrays + per-symbol stats."""
    rng = np.random.default_rng(SEED)
    pooled_y, pooled_sig_hours = [], []
    ctl_y, ctl_hours = [], []
    per_sym = {}
    for sym in SYMBOLS:
        df = load_is(sym)
        sig = eligible_signals(df, q=q, window=WINDOW, half_life=hl,
                               s_lo_pctile=S_LO_PCTILE)
        y8, keep = forward_returns(df, sig, PRIMARY_H)
        spread = SPREADS[sym] * SPECS[sym]["tick_size"]
        med_range = float(np.median(sig["event_range"])) if len(sig) else 0.0
        cost_alive = med_range >= COST_MULT * spread and len(sig) > 0
        stats = {
            "n_events": int(len(sig)), "n_used": int(keep.sum()),
            "mean_signed_fwd_8": float(y8.mean()) if len(y8) else float("nan"),
            "median_event_range": med_range, "spread": spread,
            "cost_alive": bool(cost_alive),
            "positive": bool(cost_alive and len(y8) and y8.mean() > 0),
        }
        if per_symbol_out is not None:
            for h in HORIZONS:
                yh, _ = forward_returns(df, sig, h)
                stats[f"mean_h{h}"] = float(yh.mean()) if len(yh) else float("nan")
            per_symbol_out[sym] = stats
        per_sym[sym] = stats
        if cost_alive:
            pooled_y.append(y8)
            pooled_sig_hours.append(sig["hour"].to_numpy()[keep])
            cy, ch = control_rows(df, PRIMARY_H,
                                  exclude=sig["event_idx"].to_numpy())
            ctl_y.append(cy)
            ctl_hours.append(ch)
    cat = (lambda parts: np.concatenate(parts) if parts else np.array([]))
    return (cat(pooled_y), cat(pooled_sig_hours), cat(ctl_y), cat(ctl_hours),
            per_sym, rng)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    global SPECS
    with open("data/specs.json") as f:
        SPECS = json.load(f)

    per_symbol = {}
    y, sig_hours, cy, chours, per_sym, rng = run_cell(*PRIMARY, per_symbol)

    n_pooled = len(y)
    pos_syms = sum(1 for s in per_sym.values() if s["positive"])

    c5 = n_pooled >= MIN_POOLED_N
    if c5:
        m, lo, hi = bootstrap_mean_ci(y, rng)
        c1 = m > 0 and lo > 0
        dm, dlo, dhi = bootstrap_diff_ci(y, cy, rng)
        c2 = dm > 0 and dlo > 0
        ally = np.concatenate([cy, y])
        allsig = np.concatenate([np.zeros(len(cy)), np.ones(len(y))])
        allh = np.concatenate([chours, sig_hours])
        b, blo, bhi = ols_signal_coef(ally, allsig, allh, rng)
        c3 = b > 0 and blo > 0
    else:
        m = lo = hi = dm = dlo = dhi = b = blo = bhi = float("nan")
        c1 = c2 = c3 = False
    c4 = pos_syms >= 6
    c6 = all(s["cost_alive"] for s in per_sym.values() if s["n_events"] > 0) \
        or True  # criterion 6 acts THROUGH c1-c4 (exclusion+negative), see triage doc

    criteria = {"c1_pooled_ci": bool(c1), "c2_separation": bool(c2),
                "c3_session_control": bool(c3), "c4_consistency": bool(c4),
                "c5_sample_floor": bool(c5),
                "c6_cost_sanity_all_counted": True}
    if not c5:
        verdict = "INSUFFICIENT-N"
    elif all([c1, c2, c3, c4]):
        verdict = "PASS"
    else:
        verdict = "NO-GO"

    robustness = []
    for q in Q_GRID:
        for hl in HL_GRID:
            ry, _, _, _, rps, rrng = run_cell(q, hl)
            if len(ry) >= 2:
                rm, rlo, rhi = bootstrap_mean_ci(ry, rrng)
            else:
                rm = rlo = rhi = float("nan")
            robustness.append({"q": q, "half_life": hl, "n": int(len(ry)),
                               "mean_h8": rm, "lo95": rlo, "hi95": rhi,
                               "primary": (q, hl) == PRIMARY})

    card = {
        "study": "aftershock_kill_screen",
        "registered": "docs/research/2026-08-01-wave2-gate-triage.md",
        "provenance": "data/lake/frozen/PROVENANCE.md",
        "params": {"q": PRIMARY[0], "half_life": PRIMARY[1], "window": WINDOW,
                   "s_lo_pctile": S_LO_PCTILE, "is_frac": IS_FRAC,
                   "primary_horizon": PRIMARY_H, "seed": SEED,
                   "cost_mult": COST_MULT, "min_pooled_n": MIN_POOLED_N},
        "pooled": {"n": n_pooled, "mean_h8": m, "lo95": lo, "hi95": hi,
                   "diff_mean": dm, "diff_lo95": dlo, "diff_hi95": dhi,
                   "ols_beta": b, "ols_lo95": blo, "ols_hi95": bhi,
                   "positive_symbols": pos_syms},
        "criteria": criteria,
        "verdict": verdict,
        "per_symbol": per_symbol,
        "robustness": robustness,
    }
    with open(f"{OUT_DIR}/run_card.json", "w") as f:
        json.dump(card, f, indent=2)
    pd.DataFrame(per_symbol).T.to_csv(f"{OUT_DIR}/per_symbol.csv")
    pd.DataFrame(robustness).to_csv(f"{OUT_DIR}/cells.csv", index=False)

    print("=" * 64)
    print(f"AFTERSHOCK KILL-SCREEN VERDICT: {verdict}")
    print(f"pooled N={n_pooled}  mean+8={m:.6f}  CI[{lo:.6f},{hi:.6f}]")
    print(f"separation diff={dm:.6f}  CI[{dlo:.6f},{dhi:.6f}]")
    print(f"session-controlled beta={b:.6f}  CI[{blo:.6f},{bhi:.6f}]")
    print(f"positive symbols: {pos_syms}/9   criteria: {criteria}")
    print("=" * 64)


if __name__ == "__main__":
    main()
```

Note on `c6`: cost sanity is not a separate pass/fail bit — per the registered protocol it acts by excluding cost-dead symbols from pooled cells and counting them negative in criterion 4. The run-card records per-symbol `cost_alive` so the reviewer can audit exactly which symbols were excluded.

- [ ] **Step 2: Dry-run determinism check (two runs, identical output)**

```bash
.venv/bin/python scripts/event_study_aftershock.py && cp data/results/aftershock_screen/run_card.json /tmp/claude-1000/-home-kiyingijmc-projects-Titan-ICT-Bot-v14-3pro/*/scratchpad/run1.json 2>/dev/null || .venv/bin/python scripts/event_study_aftershock.py
.venv/bin/python scripts/event_study_aftershock.py
diff <(python3 -c "import json;print(json.load(open('data/results/aftershock_screen/run_card.json')))") <(python3 -c "import json;print(json.load(open('/tmp/claude-1000/-home-kiyingijmc-projects-Titan-ICT-Bot-v14-3pro/f75226d3-63ac-4333-b869-8f7a19113b36/scratchpad/run1.json')))") && echo DETERMINISTIC
```

Expected: `DETERMINISTIC` (adjust the scratchpad path to the session's actual one; the point is two runs → byte-identical verdict payloads).

- [ ] **Step 3: Full suite green**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 4: Commit script + results**

```bash
git add scripts/event_study_aftershock.py data/results/aftershock_screen/
git commit -m "feat(research): run Aftershock kill-screen — IS-only event study per registered protocol"
```

---

### Task 7: verdict appendix + dispositions

**Files:**
- Modify: `docs/research/2026-08-01-wave2-gate-triage.md` (append appendix)
- Modify (NO-GO/INSUFFICIENT-N path only): `docs/strategies/aftershock.md` (status line), `docs/strategies/ARSENAL.md` (Aftershock standing)

**Interfaces:**
- Consumes: `data/results/aftershock_screen/run_card.json` (`verdict`, `criteria`, `pooled`, `per_symbol`, `robustness` keys from Task 6).

- [ ] **Step 1: Append the verdict appendix to the triage doc**

Append to `docs/research/2026-08-01-wave2-gate-triage.md`:

```markdown
## Appendix — screen outcome (added after the run; protocol above unchanged)

Run: <date> · commit of protocol: <sha of Task-1 commit> · results:
`data/results/aftershock_screen/run_card.json`

Verdict: **<PASS | NO-GO | INSUFFICIENT-N>**

| Criterion | Result | Value |
|---|---|---|
| 1 pooled +8 CI > 0 | <pass/fail> | mean=<>, CI=[<>, <>] |
| 2 separation vs control | <pass/fail> | diff=<>, CI=[<>, <>] |
| 3 session-controlled beta | <pass/fail> | beta=<>, CI=[<>, <>] |
| 4 symbols positive | <pass/fail> | <n>/9 |
| 5 pooled N ≥ 150 | <pass/fail> | N=<> |
| 6 cost-dead symbols | (acts via 1–4) | excluded: <list or none> |

Robustness cells: <one-line summary — how many of the 9 cells agree in
sign with the primary; verbatim table in cells.csv>.

Disposition: <registered disposition from "Verdict handling" — which one
fired and the follow-up created>.
```

Fill every `<>` from `run_card.json`. Do NOT soften a NO-GO with "but the robustness cells looked promising" editorializing — the registered protocol already says the primary cell alone decides.

- [ ] **Step 2 (only if NO-GO or INSUFFICIENT-N): update strategy-doc standings**

In `docs/strategies/aftershock.md` line 3, change `**Status:** candidate (Wave 2, pre-registration pending)` to `**Status:** NO-GO at kill-screen (2026-08-XX, docs/research/2026-08-01-wave2-gate-triage.md)` (or `INSUFFICIENT-N at kill-screen (…)`). In `docs/strategies/ARSENAL.md`, update the Aftershock row's Standing cell to match. If PASS: leave both docs unchanged (the full gate, not the screen, changes status).

- [ ] **Step 3: Create the follow-on mig row**

PASS path: `mig idea "Aftershock full backtest gate: pre-register mirroring 2026-07-14-gyroscope-gate.md (70/30 IS/OOS, ±30% sweeps q/half-life/tp-multiple, spread stress x1.5/x2, MaSlopeBaseline arm) — screen PASSED, see docs/research/2026-08-01-wave2-gate-triage.md appendix"`

NO-GO / INSUFFICIENT-N path: `mig idea "Rubicon Wave-2 cycle: build BOCPD (TDD synthetic) + detection sanity + event study per docs/strategies/rubicon.md §6 stages 1-2 — promoted by Aftershock kill-screen verdict, see 2026-08-01-wave2-gate-triage.md appendix"`

(⚠️ `mig idea --help` ADDS a row named "help" — never pass --help.)

- [ ] **Step 4: Full suite green, then commit**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK`

```bash
git add docs/research/2026-08-01-wave2-gate-triage.md docs/sessions/_BACKLOG.md
# plus, on the NO-GO path only:
# git add docs/strategies/aftershock.md docs/strategies/ARSENAL.md
git commit -m "docs(research): Aftershock kill-screen verdict appendix + disposition"
```

---

## Self-review notes (already applied)

- Spec coverage: §1 sequencing→Tasks 1/2-5/6 commit order; §2 ranking+backlog reconcile→Task 1; §3 detector params→Tasks 2-4; §4 six criteria→Task 6 (`criteria` dict) with c6-as-exclusion clarified in both the triage doc and the script comment; §5 verdicts→Task 7; §6 testing/reproducibility→every task's suite-green step + Task 6 determinism check.
- Type consistency: `eligible_signals` output columns (`event_idx/signal_idx/direction/event_range/s_minus/hour`) match Task 6's consumers; stats helpers' tuple returns match call sites.
- The `math` import lands in Task 2 but is first used in Task 3 — intentional, noted in Task 2 Step 3.
