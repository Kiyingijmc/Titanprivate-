# Confidence–Skew Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a preregistered screen that tests whether Titan's shipped `SignalGrader` score, or any of 8 candidate market-state features, predicts entry skew — the falsifier for the proposed Market Intent Engine programme.

**Architecture:** A new `scripts/confidence_screen/` package of small, pure, independently-testable modules (population → grading → excursions → features → inference → controls → promotion), driven by a thin CLI. Nothing under `src/` is touched: this is research tooling, and the live trading path must not move. The screen *calls* shipped production code (`SignalGrader`, `BiasEngine`) rather than reimplementing it.

**Tech Stack:** Python 3.10+, pandas, numpy (both already in `requirements.txt`), stdlib `unittest`. No new dependencies — if you find yourself wanting scipy, implement the statistic directly; it is a dozen lines and adding a dependency to this repo requires an ADR.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-04-confidence-skew-screen-design.md`. Read it before starting. Every numeric constant below is copied from it verbatim.
- **Branch:** `research/confidence-skew-screen` (already created and holding the spec).
- **Tests:** stdlib `unittest` in `tests/unit/`. There is **no pytest** in this repo.
- Run one module: `.venv/bin/python -m unittest tests.unit.<module> -v`
- Run all: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
- **The full suite takes ~50 minutes** and exceeds the mig gate timeout. During this plan, run only your task's own test module. Run the full suite once, at Task 9.
- **Do not modify anything under `src/`.** If a shipped module seems wrong, record it in the results doc; do not fix it here.
- **No `resolve()`, no `busy_until`, no fill filter, no expiry drop** when building the population (spec §2.7). These are the three selection layers this study exists to avoid.
- Frozen constants: `H_BARS = 12`, `W_BARS = 12`, `RR = 2.0`, `ATR10_MULT = 1.0`, `NY_SHIFT = -7`, `Q_FDR = 0.10`, `ECONOMIC_FLOOR_R = 0.25`, `SPLIT_FRAC = 0.70`, `EMBARGO_BUFFER_BARS = 4`, `BOOTSTRAP_DRAWS = 10000`, `SEED = 20260804`, `INJECT_TARGET_RHO = 0.15`, `MIN_CELL_N = 30`.
- **Intrabar convention: adverse before favourable.** Within a single M5 bar the true ordering is unknowable; resolve pessimistically, matching `poc_sb_stops.resolve`'s existing SL-first rule.
- Commit after every task. Conventional-commit prefixes, and end each message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/confidence_screen/__init__.py` | Frozen constants only |
| `scripts/confidence_screen/population.py` | Build the unfiltered signal population + ATR10 stop/target |
| `scripts/confidence_screen/grading.py` | Adapter onto the shipped `SignalGrader` |
| `scripts/confidence_screen/excursions.py` | MFE/MAE/skew with 1R truncation and unfilled handling |
| `scripts/confidence_screen/features.py` | 8 candidate features + 2 placebos, strictly causal |
| `scripts/confidence_screen/inference.py` | Rank normalization, Spearman, cluster bootstrap, BH, ICC |
| `scripts/confidence_screen/splits.py` | Calendar-date IS/OOS cut with purge + embargo |
| `scripts/confidence_screen/controls.py` | Permuted dry run + synthetic signal injection |
| `scripts/confidence_screen/promotion.py` | Economic floor, sign consistency, tie-break |
| `scripts/confidence_skew_screen.py` | CLI: wires the above, writes run artifacts |
| `tests/unit/test_confidence_screen_*.py` | One test module per source module |

---

## Task 1: Constants and population builder

**Files:**
- Create: `scripts/confidence_screen/__init__.py`
- Create: `scripts/confidence_screen/population.py`
- Test: `tests/unit/test_confidence_screen_population.py`

**Interfaces:**
- Consumes: `scripts.poc_sb_stops.collect_signals(sym, quick=False, tf="H1")` → `(signals, bars)`. Each signal dict has keys `bar_idx, time, dir, entry, far_extreme, sig_high, sig_low, atr, body_atr, bias, liq_status, hour, year`.
- Produces: `add_stop_and_target(sig) -> dict` (adds `sl`, `tp`, `risk`); `build_population(symbols, collect=None, tf="H1", quick=False) -> list[dict]` (adds `symbol` to each signal).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_population.py
import unittest
import pandas as pd

from scripts.confidence_screen.population import add_stop_and_target, build_population


def _sig(bar_idx=100, direction="BUY", entry=1.1000, atr=0.0010, **kw):
    base = {
        "bar_idx": bar_idx, "time": pd.Timestamp("2024-01-02 10:00:00"),
        "dir": direction, "entry": entry, "far_extreme": entry - 0.002,
        "sig_high": entry + 0.001, "sig_low": entry - 0.001,
        "atr": atr, "body_atr": 1.2, "bias": "BULLISH", "liq_status": "DISCOUNT",
        "hour": 10, "year": 2024,
    }
    base.update(kw)
    return base


class TestStopAndTarget(unittest.TestCase):
    def test_buy_stop_is_one_atr_below_entry(self):
        out = add_stop_and_target(_sig(direction="BUY", entry=1.1000, atr=0.0010))
        self.assertAlmostEqual(out["sl"], 1.0990, places=9)
        self.assertAlmostEqual(out["risk"], 0.0010, places=9)

    def test_sell_stop_is_one_atr_above_entry(self):
        out = add_stop_and_target(_sig(direction="SELL", entry=1.1000, atr=0.0010))
        self.assertAlmostEqual(out["sl"], 1.1010, places=9)

    def test_target_is_exactly_two_r(self):
        for direction, expected in (("BUY", 1.1020), ("SELL", 1.0980)):
            out = add_stop_and_target(_sig(direction=direction, entry=1.1000, atr=0.0010))
            self.assertAlmostEqual(out["tp"], expected, places=9)

    def test_zero_atr_signal_is_rejected_not_silently_zero_risk(self):
        with self.assertRaises(ValueError):
            add_stop_and_target(_sig(atr=0.0))


class TestBuildPopulation(unittest.TestCase):
    def test_overlapping_signals_are_all_retained(self):
        """The spec forbids busy_until: a signal arriving while a prior trade
        would still be open must NOT be dropped. Three signals one bar apart
        must all survive."""
        signals = [_sig(bar_idx=100), _sig(bar_idx=101), _sig(bar_idx=102)]

        def fake_collect(sym, quick=False, tf="H1"):
            return list(signals), {}

        pop = build_population(["EURUSD"], collect=fake_collect)
        self.assertEqual(len(pop), 3)
        self.assertEqual([p["bar_idx"] for p in pop], [100, 101, 102])

    def test_symbol_is_stamped_on_every_signal(self):
        def fake_collect(sym, quick=False, tf="H1"):
            return [_sig()], {}

        pop = build_population(["EURUSD", "XAUUSD"], collect=fake_collect)
        self.assertEqual(sorted(p["symbol"] for p in pop), ["EURUSD", "XAUUSD"])

    def test_symbol_with_no_data_is_skipped_not_crashed(self):
        def fake_collect(sym, quick=False, tf="H1"):
            return (None, None) if sym == "MISSING" else ([_sig()], {})

        pop = build_population(["MISSING", "EURUSD"], collect=fake_collect)
        self.assertEqual(len(pop), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_population -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_screen'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/__init__.py
"""Confidence–Skew Screen (spec 2026-08-04). Frozen constants only.

Every value here is preregistered. Changing one after the run has started
invalidates the study — see spec §5.3 on bounded re-specification.
"""

H_BARS = 12                 # excursion horizon, H1 bars
W_BARS = 12                 # max wait for the entry level to be touched
RR = 2.0                    # SilverBullet's fixed reward:risk
ATR10_MULT = 1.0            # the live stop model: sl = entry -/+ 1.0 * ATR
NY_SHIFT = -7               # broker -> NY hour offset (poc_sb_stops.py:42)
Q_FDR = 0.10
ECONOMIC_FLOOR_R = 0.25
SPLIT_FRAC = 0.70
EMBARGO_BUFFER_BARS = 4
BOOTSTRAP_DRAWS = 10000
SEED = 20260804
INJECT_TARGET_RHO = 0.15
MIN_CELL_N = 30

# Primary universe (11) and the live cost-viable subset (9), spec §2.1.
UNIVERSE_11 = ("AUDUSD", "BTCUSD", "EURUSD", "GBPCAD", "GBPJPY", "GBPUSD",
               "US30", "USDCAD", "USDJPY", "XAUUSD", "XBRUSD")
UNIVERSE_LIVE_9 = ("AUDUSD", "BTCUSD", "EURUSD", "GBPJPY", "GBPUSD",
                   "US30", "USDCAD", "USDJPY", "XAUUSD")
```

```python
# scripts/confidence_screen/population.py
"""Build the screen's signal population.

Deliberately does NOT call poc_sb_stops.resolve(): that function applies a
`busy_until` one-open-per-symbol cursor, a limit-fill filter and a 12-bar
expiry drop. All three select on post-signal events and would bias the
sampling frame (spec §2.7). We take collect_signals()'s raw output instead.
"""
from scripts.confidence_screen import ATR10_MULT, RR


def add_stop_and_target(sig):
    """Attach the live (ATR10) stop, the fixed 2R target, and risk."""
    atr = float(sig["atr"])
    if atr <= 0.0:
        raise ValueError(f"signal at bar {sig.get('bar_idx')} has non-positive ATR {atr!r}")
    entry = float(sig["entry"])
    dist = ATR10_MULT * atr
    is_long = sig["dir"] == "BUY"
    sl = entry - dist if is_long else entry + dist
    risk = abs(entry - sl)
    tp = entry + RR * risk if is_long else entry - RR * risk
    return {**sig, "sl": sl, "tp": tp, "risk": risk}


def build_population(symbols, collect=None, tf="H1", quick=False):
    """Every signal for every symbol — no fill, expiry or overlap filtering."""
    if collect is None:
        from scripts.poc_sb_stops import collect_signals as collect
    population = []
    for sym in symbols:
        signals, _bars = collect(sym, quick=quick, tf=tf)
        if not signals:
            continue
        for sig in signals:
            population.append(add_stop_and_target({**sig, "symbol": sym}))
    return population
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_population -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/ tests/unit/test_confidence_screen_population.py
git commit -m "feat(screen): unfiltered signal population with ATR10 stop and 2R target

No resolve(), no busy_until, no expiry drop — the three post-signal
selection layers the spec's §2.7 exists to remove.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Grading adapter onto the shipped SignalGrader

**Files:**
- Create: `scripts/confidence_screen/grading.py`
- Test: `tests/unit/test_confidence_screen_grading.py`

**Interfaces:**
- Consumes: `add_stop_and_target` output from Task 1; `src.analysis.signal_grader.SignalGrader`.
- Produces: `grade_signal(sig, grader=None) -> dict` with keys `score`, `grade`, `factors`, and the four decomposed factor columns `bias_class` (str), `displacement_bucket` (int), `pd_array` (int), `killzone` (int).

**Why this task exists:** `poc_sb_stops.py:549` reimplements the grader offline and has drifted from it (RR hardcoded at 15, epsilon tolerances and the degenerate-risk guard missing). Every conclusion in the stop study §4 rests on that mirror. This adapter calls the real class so the study tests shipped behaviour.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_grading.py
import unittest
import pandas as pd

from scripts.confidence_screen.grading import grade_signal
from scripts.confidence_screen.population import add_stop_and_target


def _sig(**kw):
    base = {
        "bar_idx": 100, "time": pd.Timestamp("2024-01-02 10:00:00"),
        "dir": "BUY", "entry": 1.1000, "far_extreme": 1.0980,
        "sig_high": 1.1010, "sig_low": 1.0990, "atr": 0.0010, "body_atr": 1.6,
        "bias": "BULLISH", "liq_status": "DISCOUNT", "hour": 16, "year": 2024,
        "symbol": "EURUSD",
    }
    base.update(kw)
    return add_stop_and_target(base)


class TestGradeSignal(unittest.TestCase):
    def test_perfect_signal_scores_95_and_grades_a_plus_plus(self):
        """bias_aligned 30 + rr(2.0) 15 + displacement(1.6) 20
        + pd_array(BUY in DISCOUNT) 15 + killzone 15 = 95.
        hour 16 broker -> NY 9 -> inside the 07-11 killzone."""
        out = grade_signal(_sig())
        self.assertEqual(out["score"], 95)
        self.assertEqual(out["grade"], "A++")

    def test_counter_bias_loses_exactly_thirty(self):
        out = grade_signal(_sig(bias="BEARISH"))
        self.assertEqual(out["score"], 65)

    def test_outside_killzone_loses_exactly_fifteen(self):
        # hour 0 broker -> NY 17 -> outside all three killzones
        out = grade_signal(_sig(hour=0))
        self.assertEqual(out["score"], 80)

    def test_rr_factor_is_constant_fifteen_for_every_signal(self):
        """SilverBullet pins rr=2.0, so the grader's 20-point RR factor is a
        constant 15. This is the spec's §1.2 finding; if it ever varies, the
        panel's exclusion of RR is no longer valid."""
        for atr in (0.0005, 0.0010, 0.0050):
            for direction in ("BUY", "SELL"):
                out = grade_signal(_sig(atr=atr, dir=direction))
                rr_factors = [f for f in out["factors"] if f.startswith("rr=")]
                self.assertEqual(rr_factors, ["rr=2.00 +15"])

    def test_decomposed_factor_columns_match_the_score(self):
        out = grade_signal(_sig())
        self.assertEqual(out["bias_class"], "aligned")
        self.assertEqual(out["displacement_bucket"], 20)
        self.assertEqual(out["pd_array"], 15)
        self.assertEqual(out["killzone"], 15)

    def test_neutral_bias_is_its_own_class_not_counter(self):
        out = grade_signal(_sig(bias="NEUTRAL"))
        self.assertEqual(out["bias_class"], "neutral")
        self.assertEqual(out["score"], 75)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_grading -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_screen.grading'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/grading.py
"""Adapter onto the SHIPPED SignalGrader.

Do not reimplement the scoring here. scripts/poc_sb_stops.py:549 already
carries an offline mirror that has drifted from src/analysis/signal_grader.py
(RR hardcoded, epsilon tolerances and the degenerate-risk guard missing);
reproducing that mistake is the specific failure this module prevents.
"""
from src.analysis.signal_grader import SignalGrader

from scripts.confidence_screen import NY_SHIFT

_DEFAULT_GRADER = SignalGrader({"signal_grading": {"enabled": True, "min_grade": "C"}})


def _ny_hour(broker_hour):
    return (int(broker_hour) + NY_SHIFT) % 24


def _bias_class(bias, direction):
    if (bias == "BULLISH" and direction == "BUY") or (bias == "BEARISH" and direction == "SELL"):
        return "aligned"
    return "neutral" if bias == "NEUTRAL" else "counter"


def grade_signal(sig, grader=None):
    """Score one signal with the shipped grader, plus decomposed factors."""
    grader = grader or _DEFAULT_GRADER
    direction = sig["dir"]

    decision = {"signal": direction, "price": sig["entry"], "sl": sig["sl"], "tp": sig["tp"]}
    context = {
        "bias": sig["bias"],
        "liquidity": {"STATUS": sig["liq_status"]},
        "ny_time": f"{_ny_hour(sig['hour'])}:00",
    }
    # The grader needs body/ATR; reconstruct a candle with the recorded ratio.
    body = float(sig["body_atr"]) * float(sig["atr"])
    candle = {"open": sig["entry"], "close": sig["entry"] + body, "ATR": sig["atr"]}

    result = grader.grade(decision, context, candle)

    ratio = float(sig["body_atr"])
    displacement = 20 if ratio >= 1.5 else 15 if ratio >= 1.0 else 10 if ratio >= 0.8 else 0
    status = sig["liq_status"]
    pd_array = 15 if (direction == "BUY" and status == "DISCOUNT") or \
                     (direction == "SELL" and status == "PREMIUM") else 0
    killzone = 15 if any(a <= _ny_hour(sig["hour"]) < b for a, b in SignalGrader.KILLZONES) else 0

    return {
        **result,
        "bias_class": _bias_class(sig["bias"], direction),
        "displacement_bucket": displacement,
        "pd_array": pd_array,
        "killzone": killzone,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_grading -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/grading.py tests/unit/test_confidence_screen_grading.py
git commit -m "feat(screen): grading adapter calling the shipped SignalGrader

Pins RR at a constant 15 by test — the spec §1.2 finding that makes
excluding RR from the panel valid.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Excursion engine — MFE/MAE with 1R truncation

**Files:**
- Create: `scripts/confidence_screen/excursions.py`
- Test: `tests/unit/test_confidence_screen_excursions.py`

**Interfaces:**
- Consumes: Task 1 signals (needs `entry`, `risk`, `dir`, `time`).
- Produces: `excursions(sig, m5, h_bars=H_BARS, w_bars=W_BARS) -> dict` with keys `filled` (bool), `touch_idx` (int|None), `mfe` (float, R), `mae` (float, R), `skew` (float, R), `hit_2r_before_1r` (bool). `m5` is a dict of numpy arrays `{"time", "high", "low"}` for that symbol.

**This is the highest-risk task in the plan.** Two behaviours here are counter-intuitive and will be "simplified away" by anyone who does not read the spec: MFE truncates at the first 1R adverse touch (§2.3), and unfilled signals score exactly 0.0 and stay in the sample (§2.3). The tests below exist to make both non-negotiable.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_excursions.py
import unittest
import numpy as np
import pandas as pd

from scripts.confidence_screen.excursions import excursions

ENTRY = 1.1000
RISK = 0.0010  # 1R
T0 = pd.Timestamp("2024-01-02 10:00:00")


def _sig(direction="BUY"):
    return {"entry": ENTRY, "risk": RISK, "dir": direction,
            "time": T0, "symbol": "EURUSD"}


def _m5(bars, start=T0, step_min=5):
    """bars: list of (high, low) starting one M5 bar AFTER the signal time."""
    times = [start + pd.Timedelta(minutes=step_min * (i + 1)) for i in range(len(bars))]
    return {
        "time": np.array([t.to_datetime64() for t in times]),
        "high": np.array([b[0] for b in bars], dtype=float),
        "low": np.array([b[1] for b in bars], dtype=float),
    }


class TestTruncation(unittest.TestCase):
    def test_adverse_1r_first_truncates_the_favourable_path(self):
        """MAE reaches 1R, THEN price runs 3R favourable. The +3R is
        unrealizable — the position was already stopped. skew must be -1.0,
        not +2.0."""
        m5 = _m5([
            (ENTRY, ENTRY),                          # touch the limit
            (ENTRY, ENTRY - 1.0 * RISK),             # -1R adverse
            (ENTRY + 3.0 * RISK, ENTRY),             # +3R AFTER the stop
        ])
        out = excursions(_sig(), m5)
        self.assertTrue(out["filled"])
        self.assertAlmostEqual(out["mae"], 1.0, places=6)
        self.assertAlmostEqual(out["mfe"], 0.0, places=6)
        self.assertAlmostEqual(out["skew"], -1.0, places=6)

    def test_favourable_first_is_kept_in_full(self):
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY + 3.0 * RISK, ENTRY),             # +3R first
            (ENTRY, ENTRY - 1.0 * RISK),             # then stopped
        ])
        out = excursions(_sig(), m5)
        self.assertAlmostEqual(out["mfe"], 3.0, places=6)
        self.assertAlmostEqual(out["mae"], 1.0, places=6)
        self.assertAlmostEqual(out["skew"], 2.0, places=6)
        self.assertTrue(out["hit_2r_before_1r"])

    def test_same_bar_ambiguity_resolves_adverse_first(self):
        """A bar containing both +3R and -1R cannot be ordered. Resolve
        pessimistically, matching poc_sb_stops.resolve's SL-first rule."""
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY + 3.0 * RISK, ENTRY - 1.0 * RISK),
        ])
        out = excursions(_sig(), m5)
        self.assertAlmostEqual(out["mfe"], 0.0, places=6)
        self.assertAlmostEqual(out["mae"], 1.0, places=6)
        self.assertFalse(out["hit_2r_before_1r"])

    def test_sell_direction_mirrors_the_geometry(self):
        m5 = _m5([
            (ENTRY, ENTRY),
            (ENTRY, ENTRY - 3.0 * RISK),             # favourable for a SELL
            (ENTRY + 1.0 * RISK, ENTRY),             # adverse for a SELL
        ])
        out = excursions(_sig(direction="SELL"), m5)
        self.assertAlmostEqual(out["mfe"], 3.0, places=6)
        self.assertAlmostEqual(out["mae"], 1.0, places=6)


class TestUnfilled(unittest.TestCase):
    def test_untouched_level_scores_zero_and_is_still_returned(self):
        """Never touched within W. The realizable outcome of a signal that
        never becomes a position is exactly 0 — and it must NOT be dropped,
        because dropping it selects on a post-signal event."""
        m5 = _m5([(ENTRY + 5 * RISK, ENTRY + 4 * RISK)] * 200)
        out = excursions(_sig(), m5)
        self.assertFalse(out["filled"])
        self.assertIsNone(out["touch_idx"])
        self.assertEqual(out["skew"], 0.0)
        self.assertEqual(out["mfe"], 0.0)
        self.assertEqual(out["mae"], 0.0)

    def test_touch_after_the_wait_window_does_not_count(self):
        """W_BARS = 12 H1 bars = 144 M5 bars. A touch at bar 200 is too late."""
        bars = [(ENTRY + 5 * RISK, ENTRY + 4 * RISK)] * 200
        bars.append((ENTRY, ENTRY))
        out = excursions(_sig(), _m5(bars))
        self.assertFalse(out["filled"])


class TestLookAhead(unittest.TestCase):
    def test_bars_beyond_the_horizon_do_not_change_skew(self):
        """The horizon is as leakable as the features. H_BARS = 12 H1 bars
        = 144 M5 bars from the touch; anything past that is the future."""
        head = [(ENTRY, ENTRY)] + [(ENTRY, ENTRY)] * 200
        short = excursions(_sig(), _m5(head))
        long = excursions(_sig(), _m5(head + [(ENTRY + 99 * RISK, ENTRY)] * 50))
        self.assertAlmostEqual(short["skew"], long["skew"], places=9)
        self.assertAlmostEqual(short["mfe"], long["mfe"], places=9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_excursions -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_screen.excursions'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/excursions.py
"""Entry-skew excursions: MFE/MAE in R, measured from the entry LEVEL.

Two rules that look like bugs and are not (spec §2.3):

1. MFE truncates at the first 1R adverse touch. Favourable movement after the
   stop would have fired is unrealizable; crediting it inverts the ranking of
   exactly the trades a confidence score exists to separate.
2. A signal whose entry level is never touched within W scores 0.0 and is
   RETURNED, not dropped. Zero is the realizable outcome of a signal that never
   becomes a position; dropping it selects on a post-signal event.

Intrabar ordering is unknowable, so a bar containing both the favourable and
the adverse extreme resolves ADVERSE FIRST — pessimistic, matching the SL-first
convention already used by poc_sb_stops.resolve.
"""
import numpy as np

from scripts.confidence_screen import H_BARS, W_BARS

_M5_PER_H1 = 12


def excursions(sig, m5, h_bars=H_BARS, w_bars=W_BARS):
    entry = float(sig["entry"])
    risk = float(sig["risk"])
    is_long = sig["dir"] == "BUY"

    empty = {"filled": False, "touch_idx": None, "mfe": 0.0, "mae": 0.0,
             "skew": 0.0, "hit_2r_before_1r": False}
    if risk <= 0.0:
        return empty

    start = np.searchsorted(m5["time"], np.datetime64(sig["time"]), side="right")
    highs, lows = m5["high"], m5["low"]
    n = len(highs)

    wait_end = min(start + w_bars * _M5_PER_H1, n)
    touch = None
    for k in range(start, wait_end):
        if lows[k] <= entry <= highs[k]:
            touch = k
            break
    if touch is None:
        return empty

    mfe = 0.0
    mae = 0.0
    hit_2r = False
    window_end = min(touch + h_bars * _M5_PER_H1, n)
    for k in range(touch, window_end):
        if is_long:
            adverse = (entry - lows[k]) / risk
            favourable = (highs[k] - entry) / risk
        else:
            adverse = (highs[k] - entry) / risk
            favourable = (entry - lows[k]) / risk

        # Adverse first (pessimistic) — see module docstring.
        if adverse >= 1.0:
            mae = 1.0
            break
        mae = max(mae, max(adverse, 0.0))
        favourable = max(favourable, 0.0)
        if favourable >= 2.0:
            hit_2r = True
        mfe = max(mfe, favourable)

    return {"filled": True, "touch_idx": int(touch), "mfe": float(mfe),
            "mae": float(mae), "skew": float(mfe - mae),
            "hit_2r_before_1r": bool(hit_2r)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_excursions -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/excursions.py tests/unit/test_confidence_screen_excursions.py
git commit -m "feat(screen): MFE/MAE excursions with 1R truncation and unfilled=0

Truncation fixture asserts a -1R-then-+3R path scores skew -1.0, not +2.0:
the defect most likely to be simplified away during implementation.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Candidate feature panel with strict causality

**Files:**
- Create: `scripts/confidence_screen/features.py`
- Test: `tests/unit/test_confidence_screen_features.py`

**Interfaces:**
- Consumes: Task 1 signals; `src.analysis.bias_engine.BiasEngine`.
- Produces: `build_features(sig, h1, seed=SEED) -> dict` keyed by the names in `FEATURE_SPECS`; `FEATURE_SPECS: dict[str, str]` mapping feature name → kind (`"continuous"` | `"binary"` | `"categorical"`); `PLACEBO_NAMES: tuple[str, str]`. `h1` is a dict of full numpy arrays `{"high","low","close","open","atr","time"}`; the function truncates internally at `sig["bar_idx"]`.

**Causality is enforced by construction:** `build_features` receives the *full* H1 arrays and slices to `bar_idx` itself. Passing pre-truncated arrays would make the look-ahead test vacuous.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_features.py
import unittest
import numpy as np
import pandas as pd

from scripts.confidence_screen.features import (
    FEATURE_SPECS, PLACEBO_NAMES, build_features,
)

N = 400
IDX = 300


def _h1(n=N):
    rng = np.random.default_rng(7)
    close = 1.10 + np.cumsum(rng.normal(0, 0.0005, n))
    return {
        "open": close - 0.0001,
        "close": close,
        "high": close + 0.0008,
        "low": close - 0.0008,
        "atr": np.full(n, 0.0010),
        "time": np.array([np.datetime64("2024-01-01T00") + np.timedelta64(i, "h")
                          for i in range(n)]),
    }


def _sig(bar_idx=IDX, direction="BUY", **kw):
    h1 = kw.pop("h1", None) or _h1()
    base = {
        "bar_idx": bar_idx, "time": pd.Timestamp(str(h1["time"][bar_idx])),
        "dir": direction, "entry": float(h1["close"][bar_idx]),
        "atr": 0.0010, "risk": 0.0010, "body_atr": 1.2,
        "bias": "BULLISH", "liq_status": "DISCOUNT",
        "hour": 10, "year": 2024, "symbol": "EURUSD",
    }
    base.update(kw)
    return base


class TestLookAhead(unittest.TestCase):
    def test_appending_future_bars_changes_no_feature(self):
        """The single most important test in this module. A feature that
        reads past bar_idx surfaces only as an impossibly good result."""
        h1 = _h1()
        sig = _sig(h1=h1)
        before = build_features(sig, h1)

        extended = {k: np.concatenate([v, v[-50:]]) for k, v in h1.items()}
        extended["time"] = np.concatenate([
            h1["time"],
            np.array([h1["time"][-1] + np.timedelta64(i + 1, "h") for i in range(50)]),
        ])
        after = build_features(sig, extended)

        for name in FEATURE_SPECS:
            self.assertEqual(before[name], after[name], msg=f"{name} leaked future data")

    def test_mutating_bars_after_the_signal_changes_no_feature(self):
        h1 = _h1()
        sig = _sig(h1=h1)
        before = build_features(sig, h1)

        tampered = {k: v.copy() for k, v in h1.items()}
        tampered["close"][IDX + 1:] += 5.0
        tampered["high"][IDX + 1:] += 5.0
        after = build_features(sig, tampered)

        for name in FEATURE_SPECS:
            self.assertEqual(before[name], after[name], msg=f"{name} read a future bar")


class TestDirectionOrientation(unittest.TestCase):
    def test_range_position_is_inverted_for_buys(self):
        """Higher must always mean 'more favourable to THIS trade'. A BUY is
        better low in the range; a SELL is better high."""
        h1 = _h1()
        buy = build_features(_sig(h1=h1, direction="BUY"), h1)
        sell = build_features(_sig(h1=h1, direction="SELL"), h1)
        self.assertAlmostEqual(buy["f7_range_pos"] + sell["f7_range_pos"], 1.0, places=9)

    def test_return_vol_feature_flips_sign_with_direction(self):
        h1 = _h1()
        buy = build_features(_sig(h1=h1, direction="BUY"), h1)
        sell = build_features(_sig(h1=h1, direction="SELL"), h1)
        self.assertAlmostEqual(buy["f8_ret_vol"], -sell["f8_ret_vol"], places=9)


class TestPlacebos(unittest.TestCase):
    def test_placebos_are_deterministic_across_calls(self):
        h1 = _h1()
        sig = _sig(h1=h1)
        a = build_features(sig, h1)
        b = build_features(sig, h1)
        for name in PLACEBO_NAMES:
            self.assertEqual(a[name], b[name])

    def test_placebos_differ_from_each_other(self):
        h1 = _h1()
        out = build_features(_sig(h1=h1), h1)
        self.assertNotEqual(out[PLACEBO_NAMES[0]], out[PLACEBO_NAMES[1]])

    def test_placebos_differ_across_signals(self):
        h1 = _h1()
        a = build_features(_sig(h1=h1, bar_idx=300), h1)
        b = build_features(_sig(h1=h1, bar_idx=301), h1)
        self.assertNotEqual(a[PLACEBO_NAMES[0]], b[PLACEBO_NAMES[0]])


class TestSessions(unittest.TestCase):
    def test_every_broker_hour_maps_to_exactly_one_session(self):
        h1 = _h1()
        seen = {build_features(_sig(h1=h1, hour=h), h1)["f5_session"] for h in range(24)}
        self.assertEqual(seen, {"ASIA", "LONDON", "NY_AM", "NY_PM"})


class TestSpecTable(unittest.TestCase):
    def test_panel_has_exactly_eight_candidates_and_two_placebos(self):
        self.assertEqual(len(FEATURE_SPECS), 8)
        self.assertEqual(len(PLACEBO_NAMES), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_features -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_screen.features'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/features.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_features -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/features.py tests/unit/test_confidence_screen_features.py
git commit -m "feat(screen): frozen 8-feature candidate panel plus 2 placebos

Look-ahead test appends AND mutates post-signal bars and asserts no feature
value moves — build_features slices to bar_idx itself so the test can bite.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: H4 bias wiring with the NEUTRAL tripwire

**Files:**
- Modify: `scripts/confidence_screen/features.py` (add `h4_bias_at`)
- Modify: `tests/unit/test_confidence_screen_features.py` (append the class below)

**Interfaces:**
- Consumes: `src.analysis.bias_engine.BiasEngine`.
- Produces: `h4_bias_at(h1_frame, signal_time) -> str` returning `"BULLISH" | "BEARISH" | "NEUTRAL"`; `neutral_rate_report(values) -> dict` with keys `neutral_rate`, `n`.

**Why separate from Task 4:** `BiasEngine.get_bias_context` returns `"NEUTRAL"` for a genuine range, for *any caught exception* (`bias_engine.py:66`), and for fewer than 50 bars (`:38`). A broken H4 resample therefore presents as a legitimate constant, and feature 6 would be reported as a null when it was never computed (spec §3.2).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_confidence_screen_features.py
import pandas as pd  # already imported at top; keep one import only

from scripts.confidence_screen.features import h4_bias_at, neutral_rate_report


class TestH4Bias(unittest.TestCase):
    def _frame(self, n=600):
        t = pd.date_range("2024-01-01", periods=n, freq="h")
        close = pd.Series(range(n), dtype=float) * 0.001 + 1.10
        return pd.DataFrame({"time": t, "open": close - 0.0002, "high": close + 0.0005,
                             "low": close - 0.0005, "close": close})

    def test_returns_a_valid_bias_label(self):
        frame = self._frame()
        out = h4_bias_at(frame, frame["time"].iloc[500])
        self.assertIn(out, ("BULLISH", "BEARISH", "NEUTRAL"))

    def test_short_history_yields_neutral_not_a_crash(self):
        frame = self._frame(n=20)
        self.assertEqual(h4_bias_at(frame, frame["time"].iloc[-1]), "NEUTRAL")

    def test_uses_only_bars_closed_at_or_before_the_signal(self):
        frame = self._frame()
        cut = frame["time"].iloc[400]
        tampered = frame.copy()
        tampered.loc[401:, ["close", "high", "low"]] += 50.0
        self.assertEqual(h4_bias_at(frame, cut), h4_bias_at(tampered, cut))


class TestNeutralTripwire(unittest.TestCase):
    def test_reports_the_neutral_rate(self):
        report = neutral_rate_report(["BULLISH", "NEUTRAL", "NEUTRAL", "BEARISH"])
        self.assertAlmostEqual(report["neutral_rate"], 0.5, places=9)
        self.assertEqual(report["n"], 4)

    def test_empty_input_is_reported_as_fully_neutral(self):
        self.assertEqual(neutral_rate_report([])["neutral_rate"], 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_features -v`
Expected: FAIL — `ImportError: cannot import name 'h4_bias_at'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/confidence_screen/features.py
import pandas as pd

from src.analysis.bias_engine import BiasEngine


def h4_bias_at(h1_frame, signal_time):
    """Bias of the last CLOSED H4 bar at signal_time, via the shipped BiasEngine.

    Not reimplemented: a null on a bias definition Titan does not use would
    answer the wrong question (spec §3.2, same reasoning as §5.4).
    """
    closed = h1_frame[h1_frame["time"] <= signal_time]
    if len(closed) < 4:
        return "NEUTRAL"
    h4 = (closed.set_index("time")
                .resample("4h")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna()
                .reset_index())
    if len(h4) < 50:
        return "NEUTRAL"
    bias, _liq = BiasEngine(h4).get_bias_context()
    return bias


def neutral_rate_report(values):
    """Tripwire for feature 6: BiasEngine returns NEUTRAL on ANY exception
    (bias_engine.py:66) and on <50 bars (:38), so a broken resample is
    indistinguishable from a genuine range without this."""
    values = list(values)
    if not values:
        return {"neutral_rate": 1.0, "n": 0}
    neutral = sum(1 for v in values if v == "NEUTRAL")
    return {"neutral_rate": neutral / len(values), "n": len(values)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_features -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/features.py tests/unit/test_confidence_screen_features.py
git commit -m "feat(screen): H4 bias via shipped BiasEngine with NEUTRAL tripwire

BiasEngine swallows every exception into NEUTRAL, so an unreported neutral
rate would let a never-computed feature 6 be published as a clean null.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Inference core — rank normalization, cluster bootstrap, BH, ICC

**Files:**
- Create: `scripts/confidence_screen/inference.py`
- Test: `tests/unit/test_confidence_screen_inference.py`

**Interfaces:**
- Produces:
  - `rank_within_symbol(values, symbols) -> np.ndarray` — mid-rank ties, scaled to [0,1] within each symbol.
  - `spearman_rho(x, y) -> float`
  - `benjamini_hochberg(pvalues, q=Q_FDR) -> np.ndarray[bool]`
  - `cluster_bootstrap(x, y, clusters, n_draws=BOOTSTRAP_DRAWS, seed=SEED) -> dict` with keys `rho`, `pvalue`, `ci_lo`, `ci_hi`.
  - `icc(values, clusters) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_inference.py
import unittest
import numpy as np

from scripts.confidence_screen.inference import (
    benjamini_hochberg, cluster_bootstrap, icc, rank_within_symbol, spearman_rho,
)


class TestRankWithinSymbol(unittest.TestCase):
    def test_ranks_are_computed_per_symbol_not_pooled(self):
        values = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
        symbols = np.array(["A", "A", "A", "B", "B", "B"])
        out = rank_within_symbol(values, symbols)
        np.testing.assert_allclose(out[:3], out[3:], atol=1e-12)

    def test_invariant_to_symbol_level_rescaling(self):
        """Directly tests the confound this exists to remove: BTCUSD and
        EURUSD have structurally different R distributions."""
        values = np.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0])
        symbols = np.array(["A", "A", "A", "B", "B", "B"])
        scaled = values.copy()
        scaled[3:] *= 1000.0
        np.testing.assert_allclose(
            rank_within_symbol(values, symbols), rank_within_symbol(scaled, symbols))

    def test_ties_get_midranks(self):
        out = rank_within_symbol(np.array([5.0, 5.0]), np.array(["A", "A"]))
        self.assertAlmostEqual(out[0], out[1], places=12)


class TestBenjaminiHochberg(unittest.TestCase):
    def test_known_answer_rejects_all_five(self):
        """Classic BH worked example: with m=5 and q=0.05, p_(5)=0.042 <= 0.05
        so k=5 and every hypothesis is rejected, including p=0.041 which fails
        its own individual threshold. A naive per-test comparison gets this
        wrong, which is exactly the bug this test catches."""
        p = np.array([0.001, 0.008, 0.039, 0.041, 0.042])
        np.testing.assert_array_equal(
            benjamini_hochberg(p, q=0.05), np.array([True] * 5))

    def test_known_answer_rejects_only_the_first(self):
        p = np.array([0.01, 0.5, 0.6])
        np.testing.assert_array_equal(
            benjamini_hochberg(p, q=0.10), np.array([True, False, False]))

    def test_result_order_matches_input_order_not_sorted_order(self):
        p = np.array([0.6, 0.01, 0.5])
        np.testing.assert_array_equal(
            benjamini_hochberg(p, q=0.10), np.array([False, True, False]))

    def test_no_rejections_when_everything_is_null(self):
        p = np.array([0.4, 0.5, 0.6, 0.7])
        self.assertFalse(benjamini_hochberg(p, q=0.10).any())


class TestSpearman(unittest.TestCase):
    def test_perfect_monotone_is_one(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(spearman_rho(x, x ** 3), 1.0, places=9)

    def test_perfect_inverse_is_minus_one(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(spearman_rho(x, -x), -1.0, places=9)


class TestClusterBootstrap(unittest.TestCase):
    def _data(self, n=400, seed=3):
        rng = np.random.default_rng(seed)
        x = rng.normal(size=n)
        y = 0.6 * x + rng.normal(size=n)
        clusters = np.repeat(np.arange(n // 10), 10)
        return x, y, clusters

    def test_is_deterministic_for_a_fixed_seed(self):
        x, y, c = self._data()
        a = cluster_bootstrap(x, y, c, n_draws=200, seed=11)
        b = cluster_bootstrap(x, y, c, n_draws=200, seed=11)
        self.assertEqual(a["pvalue"], b["pvalue"])
        self.assertEqual(a["ci_lo"], b["ci_lo"])

    def test_detects_a_strong_real_relationship(self):
        x, y, c = self._data()
        out = cluster_bootstrap(x, y, c, n_draws=500, seed=5)
        self.assertGreater(out["rho"], 0.3)
        self.assertLess(out["pvalue"], 0.05)

    def test_pure_noise_is_not_significant(self):
        rng = np.random.default_rng(9)
        n = 400
        x, y = rng.normal(size=n), rng.normal(size=n)
        c = np.repeat(np.arange(n // 10), 10)
        self.assertGreater(cluster_bootstrap(x, y, c, n_draws=500, seed=5)["pvalue"], 0.05)


class TestICC(unittest.TestCase):
    def test_identical_within_clusters_is_near_one(self):
        values = np.repeat(np.arange(20, dtype=float), 10)
        clusters = np.repeat(np.arange(20), 10)
        self.assertGreater(icc(values, clusters), 0.9)

    def test_pure_noise_is_near_zero(self):
        rng = np.random.default_rng(1)
        values = rng.normal(size=400)
        clusters = np.repeat(np.arange(40), 10)
        self.assertLess(abs(icc(values, clusters)), 0.2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_inference -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_screen.inference'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/inference.py
"""Clustered inference for the screen (spec §4).

Naive p-values would assume ~2,200 independent observations against a far
lower effective count — eleven symbols share GBP/USD factors and signals
cluster within sessions. That is the standard way a panel study manufactures
a false positive, so every p-value here comes from a cluster bootstrap over
calendar-week blocks.
"""
import numpy as np

from scripts.confidence_screen import BOOTSTRAP_DRAWS, Q_FDR, SEED


def _midrank(values):
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)
    # Average ranks within tie groups.
    sorted_vals = values[order]
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or sorted_vals[i] != sorted_vals[start]:
            ranks[order[start:i]] = ranks[order[start:i]].mean()
            start = i
    return ranks


def rank_within_symbol(values, symbols):
    """Mid-rank within each symbol, scaled to [0,1].

    Removes cross-symbol level differences so a feature cannot score merely
    by proxying symbol identity (spec §4.2).
    """
    values = np.asarray(values, dtype=float)
    symbols = np.asarray(symbols)
    out = np.zeros(len(values), dtype=float)
    for sym in np.unique(symbols):
        mask = symbols == sym
        n = int(mask.sum())
        out[mask] = (_midrank(values[mask]) - 0.5) / n if n > 1 else 0.5
    return out


def spearman_rho(x, y):
    rx, ry = _midrank(x), _midrank(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


def benjamini_hochberg(pvalues, q=Q_FDR):
    """Reject H_(1..k) where k = max{i : p_(i) <= i*q/m}. Returns a mask in
    INPUT order."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    if m == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p, kind="mergesort")
    thresholds = (np.arange(1, m + 1) * q) / m
    passing = np.where(p[order] <= thresholds)[0]
    mask = np.zeros(m, dtype=bool)
    if len(passing):
        mask[order[: passing[-1] + 1]] = True
    return mask


def cluster_bootstrap(x, y, clusters, n_draws=BOOTSTRAP_DRAWS, seed=SEED):
    """Cluster bootstrap over calendar-week blocks.

    Whole clusters are resampled with replacement (all symbols move together),
    preserving serial AND cross-sectional dependence. The null distribution
    permutes the feature across clusters, so dependence survives while the
    feature-outcome link is broken.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    clusters = np.asarray(clusters)
    observed = spearman_rho(x, y)

    unique = np.unique(clusters)
    index_by_cluster = {c: np.where(clusters == c)[0] for c in unique}
    rng = np.random.default_rng(seed)

    boot, null = np.empty(n_draws), np.empty(n_draws)
    for d in range(n_draws):
        picked = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([index_by_cluster[c] for c in picked])
        boot[d] = spearman_rho(x[idx], y[idx])

        shuffled = rng.permutation(unique)
        remap = np.concatenate([index_by_cluster[c] for c in shuffled])
        straight = np.concatenate([index_by_cluster[c] for c in unique])
        null[d] = spearman_rho(x[remap], y[straight])

    pvalue = float((np.abs(null) >= abs(observed)).mean())
    return {"rho": float(observed), "pvalue": pvalue,
            "ci_lo": float(np.quantile(boot, 0.025)),
            "ci_hi": float(np.quantile(boot, 0.975))}


def icc(values, clusters):
    """One-way ICC: between-cluster variance share. Feeds the design effect."""
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    unique = np.unique(clusters)
    if len(unique) < 2:
        return 0.0
    grand = values.mean()
    between, within, sizes = 0.0, 0.0, []
    for c in unique:
        group = values[clusters == c]
        sizes.append(len(group))
        between += len(group) * (group.mean() - grand) ** 2
        within += ((group - group.mean()) ** 2).sum()
    k = len(unique)
    n_bar = float(np.mean(sizes))
    ms_between = between / (k - 1)
    ms_within = within / max(len(values) - k, 1)
    denom = ms_between + (n_bar - 1) * ms_within
    return float((ms_between - ms_within) / denom) if denom > 0 else 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_inference -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/inference.py tests/unit/test_confidence_screen_inference.py
git commit -m "feat(screen): clustered inference — rank normalization, BH, bootstrap, ICC

BH known-answer fixture pins the k = max{i : p_(i) <= i*q/m} rule, where a
naive per-test comparison would wrongly reject only 2 of 5.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Calendar-date split with purge and embargo

**Files:**
- Create: `scripts/confidence_screen/splits.py`
- Test: `tests/unit/test_confidence_screen_splits.py`

**Interfaces:**
- Produces: `split_masks(times, symbols, frac=SPLIT_FRAC, horizon_bars=H_BARS, buffer_bars=EMBARGO_BUFFER_BARS, bar_minutes=60) -> dict` with keys `cut_time`, `is_mask`, `oos_mask`, `purged_mask`; `week_clusters(times) -> np.ndarray` of ISO year-week labels.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_splits.py
import unittest
import numpy as np
import pandas as pd

from scripts.confidence_screen.splits import split_masks, week_clusters


def _times(n, start="2024-01-01", freq="6h"):
    return pd.to_datetime(pd.date_range(start, periods=n, freq=freq)).values


class TestSplit(unittest.TestCase):
    def test_cut_is_a_calendar_date_not_a_row_index(self):
        """Symbols with denser signal counts must not dominate the training
        period. A has 90 signals, B has 10, both over the same span; the cut
        must sit at a time, so B's early rows land in IS too."""
        times = np.concatenate([_times(90, freq="6h"), _times(10, freq="54h")])
        symbols = np.array(["A"] * 90 + ["B"] * 10)
        out = split_masks(times, symbols)
        self.assertTrue(out["is_mask"][symbols == "B"].any())
        self.assertTrue((times[out["is_mask"]] <= out["cut_time"]).all())

    def test_masks_are_disjoint_and_cover_everything_with_purged(self):
        times = _times(200)
        symbols = np.array(["A"] * 200)
        out = split_masks(times, symbols)
        total = out["is_mask"].astype(int) + out["oos_mask"].astype(int) + \
            out["purged_mask"].astype(int)
        np.testing.assert_array_equal(total, np.ones(200, dtype=int))

    def test_signals_whose_window_crosses_the_cut_are_in_neither_set(self):
        """H_BARS + EMBARGO_BUFFER_BARS = 16 H1 bars of forward window. Any
        signal inside that band before the cut leaks into OOS."""
        times = _times(400, freq="1h")
        symbols = np.array(["A"] * 400)
        out = split_masks(times, symbols)
        cut = out["cut_time"]
        band = (times > cut - np.timedelta64(16, "h")) & (times <= cut)
        self.assertTrue(out["purged_mask"][band].all())
        self.assertFalse(out["is_mask"][band].any())
        self.assertFalse(out["oos_mask"][band].any())

    def test_roughly_seventy_percent_lands_in_train(self):
        times = _times(1000, freq="1h")
        symbols = np.array(["A"] * 1000)
        out = split_masks(times, symbols)
        self.assertGreater(out["is_mask"].mean(), 0.60)
        self.assertLess(out["is_mask"].mean(), 0.72)


class TestWeekClusters(unittest.TestCase):
    def test_same_week_shares_a_label(self):
        times = pd.to_datetime(["2024-01-02", "2024-01-04"]).values
        labels = week_clusters(times)
        self.assertEqual(labels[0], labels[1])

    def test_different_weeks_differ(self):
        times = pd.to_datetime(["2024-01-02", "2024-01-12"]).values
        labels = week_clusters(times)
        self.assertNotEqual(labels[0], labels[1])

    def test_all_symbols_in_one_week_share_the_cluster(self):
        times = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]).values
        self.assertEqual(len(set(week_clusters(times))), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_splits -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_screen.splits'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/splits.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_splits -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/splits.py tests/unit/test_confidence_screen_splits.py
git commit -m "feat(screen): calendar-date IS/OOS split with purge and embargo

Boundary test asserts a signal whose 16-bar forward window crosses the cut
lands in NEITHER set — leakage is otherwise silent and inflates OOS.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: Validity controls and promotion criteria

**Files:**
- Create: `scripts/confidence_screen/controls.py`
- Create: `scripts/confidence_screen/promotion.py`
- Test: `tests/unit/test_confidence_screen_controls.py`
- Test: `tests/unit/test_confidence_screen_promotion.py`

**Interfaces:**
- Produces (controls): `permute_within_symbol(y, symbols, seed) -> np.ndarray`; `inject_synthetic(y, target_rho=INJECT_TARGET_RHO, seed=SEED) -> np.ndarray`.
- Produces (promotion): `economic_spread(values, skew, kind, min_cell_n=MIN_CELL_N) -> float`; `sign_consistency(values, skew, groups, kind) -> dict` with keys `agree`, `total`, `sign`; `select_winner(results) -> dict|None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_controls.py
import unittest
import numpy as np

from scripts.confidence_screen.controls import inject_synthetic, permute_within_symbol
from scripts.confidence_screen.inference import spearman_rho


class TestPermutation(unittest.TestCase):
    def test_permutes_only_inside_each_symbol(self):
        y = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
        symbols = np.array(["A", "A", "A", "B", "B", "B"])
        out = permute_within_symbol(y, symbols, seed=1)
        np.testing.assert_array_equal(np.sort(out[:3]), np.array([1.0, 2.0, 3.0]))
        np.testing.assert_array_equal(np.sort(out[3:]), np.array([10.0, 20.0, 30.0]))

    def test_is_deterministic_for_a_fixed_seed(self):
        y = np.arange(50, dtype=float)
        symbols = np.array(["A"] * 50)
        np.testing.assert_array_equal(
            permute_within_symbol(y, symbols, seed=3),
            permute_within_symbol(y, symbols, seed=3))

    def test_actually_shuffles(self):
        y = np.arange(200, dtype=float)
        symbols = np.array(["A"] * 200)
        self.assertFalse(np.array_equal(permute_within_symbol(y, symbols, seed=3), y))


class TestInjection(unittest.TestCase):
    def test_recovers_close_to_the_target_correlation(self):
        rng = np.random.default_rng(2)
        y = rng.normal(size=4000)
        injected = inject_synthetic(y, target_rho=0.15, seed=7)
        self.assertAlmostEqual(spearman_rho(injected, y), 0.15, delta=0.04)

    def test_is_deterministic_for_a_fixed_seed(self):
        y = np.random.default_rng(4).normal(size=500)
        np.testing.assert_array_equal(
            inject_synthetic(y, seed=7), inject_synthetic(y, seed=7))

    def test_a_zero_target_produces_no_relationship(self):
        rng = np.random.default_rng(6)
        y = rng.normal(size=4000)
        self.assertLess(abs(spearman_rho(inject_synthetic(y, target_rho=0.0, seed=7), y)), 0.06)


if __name__ == "__main__":
    unittest.main()
```

```python
# tests/unit/test_confidence_screen_promotion.py
import unittest
import numpy as np

from scripts.confidence_screen.promotion import (
    economic_spread, select_winner, sign_consistency,
)


class TestEconomicSpread(unittest.TestCase):
    def test_continuous_uses_top_minus_bottom_quintile(self):
        # n=200 so each quintile holds 40 >= MIN_CELL_N(30). With n=100 the
        # quintiles hold 20 and economic_spread correctly returns 0.0.
        values = np.arange(200, dtype=float)
        skew = np.arange(200, dtype=float) / 200.0
        self.assertAlmostEqual(economic_spread(values, skew, "continuous"), 0.8, delta=0.05)

    def test_quintiles_below_the_minimum_cell_size_return_zero(self):
        values = np.arange(100, dtype=float)
        skew = np.arange(100, dtype=float) / 100.0
        self.assertEqual(economic_spread(values, skew, "continuous"), 0.0)

    def test_binary_uses_the_group_mean_difference(self):
        values = np.array([0, 0, 1, 1] * 25)
        skew = np.array([0.0, 0.0, 0.5, 0.5] * 25)
        self.assertAlmostEqual(economic_spread(values, skew, "binary"), 0.5, places=9)

    def test_categorical_uses_max_minus_min_group_mean(self):
        values = np.array(["A", "B", "C"] * 40)
        skew = np.array([0.0, 1.0, 2.0] * 40)
        self.assertAlmostEqual(economic_spread(values, skew, "categorical"), 2.0, places=9)

    def test_thin_cells_are_excluded_so_they_cannot_manufacture_a_spread(self):
        """MIN_CELL_N = 30. A 5-signal group with a wild mean must not create
        the illusion of a 10R spread."""
        values = np.array(["BIG"] * 100 + ["TINY"] * 5)
        skew = np.concatenate([np.zeros(100), np.full(5, 10.0)])
        self.assertAlmostEqual(economic_spread(values, skew, "categorical"), 0.0, places=9)


class TestSignConsistency(unittest.TestCase):
    def test_counts_groups_agreeing_with_the_pooled_sign(self):
        values = np.tile(np.array([0.0, 1.0]), 30)
        skew = np.tile(np.array([0.0, 1.0]), 30)
        groups = np.repeat(np.array(["s1", "s2", "s3"]), 20)
        out = sign_consistency(values, skew, groups, "continuous")
        self.assertEqual(out["agree"], 3)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["sign"], 1)

    def test_a_group_with_the_opposite_sign_is_counted_as_disagreeing(self):
        values = np.concatenate([np.tile([0.0, 1.0], 20), np.tile([0.0, 1.0], 10)])
        skew = np.concatenate([np.tile([0.0, 1.0], 20), np.tile([1.0, 0.0], 10)])
        groups = np.array(["s1"] * 40 + ["s2"] * 20)
        out = sign_consistency(values, skew, groups, "continuous")
        self.assertEqual(out["agree"], 1)
        self.assertEqual(out["total"], 2)


class TestSelectWinner(unittest.TestCase):
    def _r(self, name, spread, pvalue):
        return {"feature": name, "spread": spread, "pvalue": pvalue, "promoted": True}

    def test_ranks_on_economic_spread_not_on_pvalue(self):
        """p-values under clustered inference are the noisier quantity;
        ranking on them selects on sampling error."""
        winner = select_winner([self._r("a", 0.30, 0.001), self._r("b", 0.90, 0.04)])
        self.assertEqual(winner["feature"], "b")

    def test_ignores_features_that_did_not_pass(self):
        losing = {"feature": "c", "spread": 5.0, "pvalue": 0.9, "promoted": False}
        winner = select_winner([losing, self._r("a", 0.30, 0.001)])
        self.assertEqual(winner["feature"], "a")

    def test_returns_none_when_nothing_passed(self):
        self.assertIsNone(select_winner([
            {"feature": "c", "spread": 5.0, "pvalue": 0.9, "promoted": False}]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
.venv/bin/python -m unittest tests.unit.test_confidence_screen_controls tests.unit.test_confidence_screen_promotion -v
```
Expected: FAIL — `ModuleNotFoundError` for both new modules

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/confidence_screen/controls.py
"""Validity controls (spec §5.1, §5.2).

The permuted dry run validates calibration WITHOUT consuming a look at the
real data — it must run before any real outcome is touched.
"""
import numpy as np

from scripts.confidence_screen import INJECT_TARGET_RHO, SEED


def permute_within_symbol(y, symbols, seed=SEED):
    """Shuffle outcomes inside each symbol, preserving symbol-level structure."""
    y = np.asarray(y, dtype=float)
    symbols = np.asarray(symbols)
    rng = np.random.default_rng(seed)
    out = y.copy()
    for sym in np.unique(symbols):
        idx = np.where(symbols == sym)[0]
        out[idx] = y[rng.permutation(idx)]
    return out


def inject_synthetic(y, target_rho=INJECT_TARGET_RHO, seed=SEED):
    """A feature that is a known noisy function of the outcome.

    The pipeline MUST recover this at ~target_rho; failure means it cannot see
    an effect it was built to detect, and the run is void.
    """
    y = np.asarray(y, dtype=float)
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=len(y))
    signal = (y - y.mean()) / (y.std() or 1.0)
    # Pearson blend; Spearman lands near it for these ranges.
    weight = float(np.clip(target_rho, -1.0, 1.0))
    return weight * signal + np.sqrt(max(1.0 - weight ** 2, 0.0)) * noise
```

```python
# scripts/confidence_screen/promotion.py
"""Promotion criteria (spec §4.5) — economic floor, sign consistency, tie-break."""
import numpy as np

from scripts.confidence_screen import MIN_CELL_N


def _group_means(values, skew, min_cell_n):
    means = []
    for level in np.unique(values):
        cell = skew[values == level]
        if len(cell) >= min_cell_n:
            means.append(float(cell.mean()))
    return means


def economic_spread(values, skew, kind, min_cell_n=MIN_CELL_N):
    """Top-vs-bottom spread in R. Cells below min_cell_n are excluded so a
    thin group cannot manufacture a spread."""
    values = np.asarray(values)
    skew = np.asarray(skew, dtype=float)
    if len(skew) == 0:
        return 0.0

    if kind == "continuous":
        vals = values.astype(float)
        lo_cut, hi_cut = np.quantile(vals, 0.2), np.quantile(vals, 0.8)
        bottom, top = skew[vals <= lo_cut], skew[vals >= hi_cut]
        if len(bottom) < min_cell_n or len(top) < min_cell_n:
            return 0.0
        return float(top.mean() - bottom.mean())

    means = _group_means(values, skew, min_cell_n)
    return float(max(means) - min(means)) if len(means) >= 2 else 0.0


def sign_consistency(values, skew, groups, kind, min_cell_n=MIN_CELL_N):
    """How many groups (symbols or years) agree with the pooled direction."""
    values, skew, groups = np.asarray(values), np.asarray(skew, dtype=float), np.asarray(groups)
    pooled = economic_spread(values, skew, kind, min_cell_n)
    sign = int(np.sign(pooled))
    agree = 0
    total = 0
    for g in np.unique(groups):
        mask = groups == g
        cell = economic_spread(values[mask], skew[mask], kind, min_cell_n=1)
        if cell == 0.0:
            continue
        total += 1
        if int(np.sign(cell)) == sign:
            agree += 1
    return {"agree": agree, "total": total, "sign": sign}


def select_winner(results):
    """Exactly one feature is promoted, ranked on economic-floor MAGNITUDE.

    Not on p-value: under clustered inference the p-value is the noisier
    quantity, and ranking on it selects on sampling error (spec §4.4).
    """
    passing = [r for r in results if r.get("promoted")]
    if not passing:
        return None
    return max(passing, key=lambda r: abs(r["spread"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
.venv/bin/python -m unittest tests.unit.test_confidence_screen_controls tests.unit.test_confidence_screen_promotion -v
```
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/confidence_screen/controls.py scripts/confidence_screen/promotion.py \
        tests/unit/test_confidence_screen_controls.py tests/unit/test_confidence_screen_promotion.py
git commit -m "feat(screen): validity controls and promotion criteria

Tie-break ranks on economic-spread magnitude, not p-value, and thin cells
below MIN_CELL_N are excluded so they cannot manufacture a spread.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: CLI, preregistration document, and the full-suite gate

**Files:**
- Create: `scripts/confidence_skew_screen.py`
- Create: `docs/research/2026-08-04-confidence-skew-screen.md` (§§1–3 only)
- Test: `tests/unit/test_confidence_screen_cli.py`

**Interfaces:**
- Consumes: every module from Tasks 1–8.
- Produces: `run_screen(population, m5_by_symbol, h1_by_symbol, mode="real") -> dict` with keys `results` (list of per-feature dicts), `winner`, `void`, `diagnostics`; CLI entry `main(argv)`.

**Order matters and is enforced by the tests:** the permuted dry run and the injected-signal recovery run BEFORE any real outcome is scored. A pipeline that scores real outcomes first has already consumed the look the dry run exists to protect.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confidence_screen_cli.py
import unittest

from scripts.confidence_skew_screen import PHASES, run_screen


class TestPhaseOrder(unittest.TestCase):
    def test_permuted_dry_run_precedes_the_real_run(self):
        """Spec §5.1: calibration must be validated without consuming a look
        at the real data."""
        self.assertLess(PHASES.index("permuted_dry_run"), PHASES.index("real"))

    def test_injection_recovery_precedes_the_real_run(self):
        self.assertLess(PHASES.index("injection_recovery"), PHASES.index("real"))


class TestVoidConditions(unittest.TestCase):
    def _diagnostics(self, **kw):
        base = {"placebo_rejected": False, "injection_recovered": True,
                "permuted_fpr": 0.10}
        base.update(kw)
        return base

    def test_a_rejected_placebo_voids_the_run(self):
        from scripts.confidence_skew_screen import is_void
        self.assertTrue(is_void(self._diagnostics(placebo_rejected=True)))

    def test_a_failed_injection_recovery_voids_the_run(self):
        from scripts.confidence_skew_screen import is_void
        self.assertTrue(is_void(self._diagnostics(injection_recovered=False)))

    def test_a_clean_diagnostic_set_is_not_void(self):
        from scripts.confidence_skew_screen import is_void
        self.assertFalse(is_void(self._diagnostics()))


class TestVoidBlocksResults(unittest.TestCase):
    def test_a_void_run_reports_no_winner(self):
        """Spec §5.3: 'No result reported.' A void must not leak a winner."""
        out = run_screen(population=[], m5_by_symbol={}, h1_by_symbol={},
                         force_void=True)
        self.assertTrue(out["void"])
        self.assertIsNone(out["winner"])
        self.assertEqual(out["results"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.confidence_skew_screen'`

- [ ] **Step 3: Write the implementation**

Create `scripts/confidence_skew_screen.py` wiring the modules in this exact order:

```python
# scripts/confidence_skew_screen.py
"""Confidence–Skew Screen CLI (spec 2026-08-04).

Phase order is load-bearing: calibration is validated on permuted outcomes
and on an injected synthetic signal BEFORE any real outcome is scored, so a
miscalibrated pipeline is caught without consuming a look at the real data.
"""
import argparse
import json
import os

import numpy as np

from scripts.confidence_screen import (
    ECONOMIC_FLOOR_R, Q_FDR, SEED, UNIVERSE_11, UNIVERSE_LIVE_9,
)
from scripts.confidence_screen.controls import inject_synthetic, permute_within_symbol
from scripts.confidence_screen.excursions import excursions
from scripts.confidence_screen.features import (
    FEATURE_SPECS, PLACEBO_NAMES, build_features,
)
from scripts.confidence_screen.grading import grade_signal
from scripts.confidence_screen.inference import (
    benjamini_hochberg, cluster_bootstrap, icc, rank_within_symbol,
)
from scripts.confidence_screen.population import build_population
from scripts.confidence_screen.promotion import (
    economic_spread, select_winner, sign_consistency,
)
from scripts.confidence_screen.splits import split_masks, week_clusters

PHASES = ("permuted_dry_run", "injection_recovery", "real")

GRADER_SPECS = {
    "bias_class": "categorical",
    "displacement_bucket": "binary",
    "pd_array": "binary",
    "killzone": "binary",
    "composite_score": "categorical",
}


def is_void(diagnostics):
    """Spec §5.1/§5.3. A void reports NO result — not a patched one."""
    return bool(diagnostics.get("placebo_rejected")) or \
        not bool(diagnostics.get("injection_recovered", True))


def run_screen(population, m5_by_symbol, h1_by_symbol, force_void=False, seed=SEED):
    if force_void:
        return {"results": [], "winner": None, "void": True,
                "diagnostics": {"placebo_rejected": True}}
    # ... assemble the frame (grade + features + excursions per signal),
    # run PHASES in order, then BH over the 15-test family.
    raise NotImplementedError("assemble per the docstring order")
```

Complete `run_screen` so it:
1. For each signal: `grade_signal(sig)`, `build_features(sig, h1_by_symbol[sig["symbol"]])`, `excursions(sig, m5_by_symbol[sig["symbol"]])`. Assemble arrays for `skew`, `symbols`, `times`.
2. `y = rank_within_symbol(skew, symbols)`; `clusters = week_clusters(times)`; record `icc(y, clusters)` and the design effect.
3. `split_masks(times, symbols)` → IS/OOS.
4. Phase `permuted_dry_run`: `permute_within_symbol(y, symbols, seed)`, run the full 15-test panel, record the observed rejection rate as `permuted_fpr`.
5. Phase `injection_recovery`: `inject_synthetic(y)` as a 16th column (excluded from BH), assert its null is rejected and its recovered rho falls inside the bootstrap CI → `injection_recovered`.
6. Phase `real`: for each of the 15 tests (5 grader + 8 candidates + 2 placebos), `cluster_bootstrap(x_is, y_is, clusters_is)`; `benjamini_hochberg(pvalues, Q_FDR)`; `placebo_rejected` = any placebo in the rejected set.
7. For survivors: `economic_spread(...) >= ECONOMIC_FLOOR_R`, OOS same-sign, `sign_consistency` by symbol (≥8/11) and by year (≥3/4), and same sign on `UNIVERSE_LIVE_9`. Set `promoted` accordingly.
8. `winner = select_winner(results)` — but return `None` and empty `results` if `is_void(diagnostics)`.
9. Write `run.json` + `panel.jsonl` under `data/results/confidence_screen/<UTC-timestamp>/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_confidence_screen_cli -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Write the preregistration document, §§1–3 only**

Create `docs/research/2026-08-04-confidence-skew-screen.md`. Copy the hypothesis, the frozen panel (§3), and the promotion criteria (§4.5) verbatim from the spec. Include the status marker used by the fill-model-correction doc:

```markdown
> **Status: panel frozen, measurement pending.** Sections 1-3 were written
> *before* any outcome was produced, so the denominator could not be chosen
> to flatter the result. Sections 4-6 are filled from the runs.
```

Record the SHA-256 of `scripts/confidence_skew_screen.py` and of every module under `scripts/confidence_screen/`:

```bash
sha256sum scripts/confidence_skew_screen.py scripts/confidence_screen/*.py
```

**Leave §§4–6 as empty headed sections.** Do not run the screen before this file is committed.

- [ ] **Step 6: Run the full unit suite once**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK. Takes ~50 minutes — check `uptime` and `ps aux | grep 'unittest discover'` first to confirm the box is idle, since a concurrent suite has previously corrupted timing readings in this repo.

Record the pass count. If anything outside `test_confidence_screen_*` fails, stop and report — do not fix unrelated failures inside this plan.

- [ ] **Step 7: Commit**

```bash
git add scripts/confidence_skew_screen.py tests/unit/test_confidence_screen_cli.py \
        docs/research/2026-08-04-confidence-skew-screen.md
git commit -m "feat(screen): CLI with preregistered phase order, plus prereg doc

Permuted dry run and injection recovery both run BEFORE any real outcome is
scored; a void returns no winner and no results.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Freeze, run, and record the verdict

**Files:**
- Modify: `docs/research/2026-08-04-confidence-skew-screen.md` (§§4–6)
- Modify: `docs/strategies/ARSENAL.md`, `docs/strategies/IMPROVEMENTS.md`

**This task must not begin until Task 9's preregistration is committed.** The commit hash of that document is the evidence that the panel was frozen before the measurement.

- [ ] **Step 1: Freeze the dataset**

```bash
.venv/bin/python scripts/freeze_gate_dataset.py --help
```
Follow its interface to freeze the regenerated population. Record the manifest hash in §4 of the results doc.

- [ ] **Step 2: Reconcile against the inherited file**

Spec §2.7 requires the regenerated population to reproduce `sb_stops_trades_H1.csv`'s 2,217 `ATR10` filled signals, within the fill-model correction's expected direction-asymmetric difference. Write the comparison into §4: counts by symbol, by direction, and the set difference. **A larger or oppositely-signed discrepancy blocks the run** — it means the regeneration is wrong, not the original.

- [ ] **Step 3: Run the screen**

```bash
.venv/bin/python scripts/confidence_skew_screen.py --universe 11 --out data/results/confidence_screen
```

- [ ] **Step 4: Fill §§4–6 from the artifacts**

Report, without exception: measured ICC and design effect; realised detectable |ρ| against that design effect (not the spec's projection); the permuted-run false-positive rate; injection recovery; the zero-mass fraction from unfilled signals; feature 6's H4 NEUTRAL rate against its tripwire; the full 15-row panel with ρ, p, BH outcome, and economic spread; and the verdict per the spec's §6 decision table.

**If the outcome is Flat, say so plainly and completely.** That is the expected result and the one with the highest value per unit cost — it retires a proposed rewrite of 70–90% of the decision layer. Do not hedge it, and do not go looking for a subgroup where something worked.

- [ ] **Step 5: Adversarial review**

Spec §5.5 requires an adversarial review of the results document **before** the verdict is recorded. Dispatch `mig-reviewer` against the results doc and the diff. Address findings before Step 6.

- [ ] **Step 6: Update the arsenal docs and commit**

Add the verdict to `ARSENAL.md`'s status board and, if a follow-up gate was authorized, add the row to `IMPROVEMENTS.md`.

```bash
git add docs/research/2026-08-04-confidence-skew-screen.md docs/strategies/ARSENAL.md \
        docs/strategies/IMPROVEMENTS.md data/results/confidence_screen/
git commit -m "research(screen): confidence–skew screen verdict

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review notes

**Spec coverage.** §1.2 grader coarseness → Task 2. §2.1 population/universe → Task 1 + `__init__`. §2.2–2.3 anchoring, truncation, unfilled → Task 3. §2.7 regeneration and the three selection layers → Task 1 (no `resolve()`) + Task 10 Step 2 (reconciliation). §3.1–3.2 panel → Tasks 4–5. §3.3 placebos → Task 4. §3.4 causality → Task 4. §4.1–4.4 inference → Task 6. §4.3 purge/embargo → Task 7. §4.5 promotion → Task 8. §5.1–5.3 controls and void → Tasks 8–9. §5.4 no reimplementation → Task 2. §5.5 adversarial review → Task 10 Step 5. §6 decision table → Task 10 Step 4. §7 tests → distributed across all tasks. §8 deliverables → Tasks 9–10.

**Known deferrals, deliberate.** The `H = 24` and fill-conditional robustness cells (§2.3, §2.6) and the `UNIVERSE_LIVE_9` subset check run as re-invocations of `run_screen` with different parameters rather than as separate code paths — they are confirmations of a selected hypothesis, not new hypotheses, and need no new machinery. The `f6_h4_agree` wiring in `build_features` takes `h4_bias` as an injected parameter (Task 4) and is populated by `h4_bias_at` at assembly time in Task 9; keeping the pure function free of resampling is what lets Task 4's look-ahead test stay fast.
