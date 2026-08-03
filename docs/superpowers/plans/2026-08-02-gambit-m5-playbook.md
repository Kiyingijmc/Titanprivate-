# Gambit M5 Session Playbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Gambit M5 session-playbook strategy (chassis + Judas and Reprise setups), the flat-by-close time-exit variant, and the offline research harness that gates each setup independently — per the approved spec `docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md`.

**Architecture:** A `Gambit` chassis (`BaseStrategy`, timeframe M5) owns session windows, pre-session-range state, cost floor, and one-trade-per-session; two pure detector functions (`detect_judas`, `detect_reprise`) produce intents. Flat-by-close rides the **existing** `trade_management.time_exits` hook as a new `flat_at_ny` variant (spec deviation, approved rationale: zero schema change, mirrors Almanac/Gyroscope patterns). The research harness (`scripts/poc_gambit.py`) imports the same detector functions the live chassis calls, so research and live logic cannot drift.

**Tech Stack:** Python 3.10+, pandas/numpy, stdlib `unittest` (there is NO pytest), pytz. No new dependencies.

## Global Constraints

- Tests: `.venv/bin/python -m unittest tests.unit.<module> -v`; full suite `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` (baseline ~843 tests OK; takes >10 min — run single modules during TDD, full suite once at the end).
- Work on branch `feat/gambit-m5-playbook` off current `main`. Commit after every green test cycle.
- Live-inert until gated: manifest `status: research` (registry loads but never activates it), config `enabled: false`. No EA/MQL5 changes anywhere in this plan.
- Never touch `data/db/*`, `data/logs/*` (live demo bot owns them); never run `scripts/` bridge tools (bot owns ports 32768–70).
- Spec values are pre-registered — do not tune: `rr: 2.0`, `body_min_atr: 0.8`, `stop_buffer_atr: 0.2`, `sweep_ttl_bars: 12`, `cost_floor_mult: 4`, windows London 02:00–05:00 / NY-AM 08:30–11:00 NY (end-exclusive), pre-session ranges London 18:00→02:00 / NY 02:00→08:30.
- Universe: gate set `US30, US100, XAUUSD, BTCUSD`; research-only arms `ETHUSD, XTIUSD`. All six `data/history/<SYM>_M5.csv` files already exist — there is no data-export step.
- The repo's headers say `STATUS: PRODUCTION READY` — historical commentary, not ground truth. Match existing code style (module banner comments, log_event conventions).

## File Structure

| File | Responsibility |
|---|---|
| `src/execution/trade_manager.py` (modify) | `flat_at_ny` time-exit variant |
| `src/strategies/models/gambit_setups.py` (create) | Pure functions: pre-session range, Judas detector, Reprise detector |
| `src/strategies/models/gambit.py` (create) | Chassis: sessions, one-per-session, cost floor, spread guard |
| `config/manifests/gambit.yaml` (create) | Manifest, `status: research` |
| `config/config.yaml` (modify) | `gambit:` block, `time_exits.Gambit` row |
| `scripts/poc_sb_stops.py` + `tests/backtest/backtest_engine.py` (modify) | SPREADS += US100/ETHUSD/XTIUSD (closes STRAT-04) |
| `scripts/poc_gambit.py` (create) | Signal collection + FIXED/MANAGED resolution, session-capped |
| `scripts/gambit_gate.py` (create) | Kill-screen + 7-criterion gate evaluator over trades CSVs |
| `tests/unit/test_trade_manager_flat_at.py`, `test_gambit_range.py`, `test_gambit_setups.py`, `test_gambit_strategy.py`, `test_spreads_table_sync.py` (create) | Unit tests |

---

### Task 1: `flat_at_ny` time-exit variant in TradeManager

**Files:**
- Modify: `src/execution/trade_manager.py` (`__init__` time_exits parsing ~lines 54–75; `_time_exit_due` ~lines 77–98)
- Modify: `docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md` (§4 "New plumbing" paragraph)
- Test: `tests/unit/test_trade_manager_flat_at.py`

**Interfaces:**
- Consumes: `state_manager.get_order_meta(ticket) -> (strategy_name, time_placed_epoch) | None` (exists, `state_manager.py:299`).
- Produces: config rule `trade_management.time_exits.<StratName>: { flat_at_ny: ["HH:MM", ...] }` — position closed by the existing `sync_positions` CLOSE_POS path once any listed NY wall-clock boundary has been crossed since placement. Task 6 adds the `Gambit: { flat_at_ny: ["05:00","11:00"] }` config row.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_trade_manager_flat_at.py
# flat_at_ny time-exit variant: close once any listed NY wall-clock time has
# been crossed since placement. Epochs are fixed so DST is exercised for real
# (Jan = EST/UTC-5, Jul = EDT/UTC-4).
import unittest
from datetime import datetime
import pytz

from src.execution.trade_manager import TradeManager

NY = pytz.timezone("US/Eastern")
UTC = pytz.utc


def ny_epoch(y, mo, d, h, mi):
    """Epoch seconds for an NY wall-clock instant."""
    return NY.localize(datetime(y, mo, d, h, mi)).timestamp()


class _Logger:
    def log_event(self, *a, **k):
        pass


class _State:
    def __init__(self, meta):
        self._meta = meta

    def get_order_meta(self, ticket):
        return self._meta.get(ticket)


def make_tm(meta, rule):
    cfg = {"trade_management": {"time_exits": {"Gambit": rule}}}
    return TradeManager(_Logger(), _State(meta), risk_manager=None, config=cfg)


class TestFlatAtNY(unittest.TestCase):
    RULE = {"flat_at_ny": ["05:00", "11:00"]}

    def test_not_due_before_boundary(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)      # EDT, in London window
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 4, 59)))

    def test_due_at_boundary(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 5, 0)))

    def test_ny_am_trade_ignores_morning_boundary_already_past(self):
        # Placed 08:35 — the 05:00 boundary is already behind it; only 11:00 counts.
        placed = ny_epoch(2026, 7, 15, 8, 35)
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 10, 59)))
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 11, 0)))

    def test_outage_spanning_boundary_closes_on_restart(self):
        # Bot down over the 05:00 boundary and past midnight: still due.
        placed = ny_epoch(2026, 7, 15, 4, 0)
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 7, 16, 3, 0)))

    def test_est_winter_dates(self):
        placed = ny_epoch(2026, 1, 15, 8, 35)      # EST
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 1, 15, 10, 59)))
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 1, 15, 11, 1)))

    def test_other_strategy_inert(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)
        tm = make_tm({1: ("SilverBullet", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 16, 12, 0)))

    def test_unknown_ticket_inert(self):
        tm = make_tm({}, self.RULE)
        self.assertFalse(tm._time_exit_due(99, ny_epoch(2026, 7, 15, 12, 0)))

    def test_bad_time_string_rule_is_dropped(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)
        tm = make_tm({1: ("Gambit", placed)}, {"flat_at_ny": ["nonsense"]})
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 16, 12, 0)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_trade_manager_flat_at -v`
Expected: FAIL/ERROR (flat_at_ny rule currently falls into the calendar-int branch and raises/returns wrong).

- [ ] **Step 3: Implement the variant**

In `TradeManager.__init__`, extend the `time_exits` parsing loop (keep the two existing dicts untouched, add a third):

```python
        self.time_exits = {}
        self.time_exits_bars = {}
        # flat_at_ny (Gambit): {"flat_at_ny": ["05:00","11:00"]} -- close once
        # any listed NY wall-clock time has been CROSSED since placement
        # (session-end flat for intraday strategies). DST handled by pytz.
        self.time_exits_flat_ny = {}
        for name, rule in (mgmt.get('time_exits') or {}).items():
            try:
                if isinstance(rule, dict) and 'flat_at_ny' in rule:
                    parsed = []
                    for s in rule['flat_at_ny']:
                        hh, mm = str(s).split(':')
                        parsed.append((int(hh), int(mm)))
                    if parsed:
                        self.time_exits_flat_ny[str(name)] = parsed
                    continue
                if isinstance(rule, dict) and 'max_bars' in rule:
                    self.time_exits_bars[str(name)] = int(rule['max_bars'])
                    continue
                day = rule.get('exit_trading_day', 3) if isinstance(rule, dict) else rule
                self.time_exits[str(name)] = int(day)
            except (ValueError, TypeError, AttributeError):
                continue
```

Add `pytz` to the module imports (`import pytz`; module already imports `time` and `datetime`/`timezone`). Cache the tz once in `__init__`: `self._ny_tz = pytz.timezone('US/Eastern')`.

In `_time_exit_due`, update the empty-guard and add the branch **before** the `max_bars` branch:

```python
        if not self.time_exits and not self.time_exits_bars and not self.time_exits_flat_ny:
            return False
        ...
        flat_times = self.time_exits_flat_ny.get(strat_name)
        if flat_times is not None:
            placed_ny = datetime.fromtimestamp(placed, tz=timezone.utc).astimezone(self._ny_tz)
            now_ny = datetime.fromtimestamp(now, tz=timezone.utc).astimezone(self._ny_tz)
            day = placed_ny.date()
            # Walk each NY calendar day from placement to now (bounded: a
            # flat-by-close trade should never span days, but an outage might).
            while day <= now_ny.date():
                for hh, mm in flat_times:
                    b = self._ny_tz.localize(
                        datetime(day.year, day.month, day.day, hh, mm))
                    if placed_ny < b <= now_ny:
                        return True
                day += timedelta(days=1)
            return False
```

(`timedelta` is already imported? Check the module header — if not, add it to the existing `datetime` import line.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_trade_manager_flat_at tests.unit.test_trade_manager_time_exit tests.unit.test_trade_manager -v`
Expected: ALL PASS (the two existing modules prove the calendar/max_bars variants are untouched).

- [ ] **Step 5: Amend the spec**

In `docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md` §4, replace the "New plumbing — `flat_at`" paragraph with:

```markdown
**New plumbing — flat-by-close (amended at plan time):** implemented as a third
variant of the existing `trade_management.time_exits` hook (joining Almanac's
calendar rule and Gyroscope's `max_bars`): `Gambit: { flat_at_ny:
["05:00","11:00"] }` closes any Gambit position once a listed NY wall-clock
time has been crossed since placement. Strategy-name-keyed config — no new
decision-dict field, no state-DB column, no heartbeat backfill concern. The
original per-trade `flat_at` metadata design was dropped as strictly more
plumbing for identical behavior.
```

Also update the §3 config sketch: replace the `sessions:`/`symbol_sessions:` lines with the per-session `window`/`range` shape used by Task 5:

```yaml
  sessions:
    london: {window: ["02:00","05:00"], range: ["18:00","02:00"]}
    ny_am:  {window: ["08:30","11:00"], range: ["02:00","08:30"]}
  symbol_sessions:
    US30: [ny_am]
    US100: [ny_am]
    XAUUSD: [london, ny_am]
    BTCUSD: [london, ny_am]
```

- [ ] **Step 6: Commit**

```bash
git add src/execution/trade_manager.py tests/unit/test_trade_manager_flat_at.py docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md
git commit -m "feat(trade-manager): flat_at_ny time-exit variant for session-flat strategies"
```

---

### Task 2: Pre-session range (pure function)

**Files:**
- Create: `src/strategies/models/gambit_setups.py`
- Test: `tests/unit/test_gambit_range.py`

**Interfaces:**
- Produces: `compute_presession_range(ny_times, highs, lows, range_start_min, range_end_min, min_bars=12) -> (hi, lo, n) | None`.
  - `ny_times`: sequence of tz-aware NY datetimes (bar OPEN times), ascending, aligned with `highs`/`lows` (sequences of float).
  - `range_start_min`/`range_end_min`: minutes-since-midnight NY. `start > end` means the range crosses midnight (start belongs to the previous NY day).
  - Anchors to the most recent `range_end` boundary at or before the LAST bar; returns the high/low over bars whose NY open time falls in `[anchor - duration, anchor)`; `None` if fewer than `min_bars` bars fall inside (holiday/backfill gap safety).
- Tasks 3–5 and the harness (Task 8) all call this exact signature.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_gambit_range.py
import unittest
from datetime import datetime, timedelta
import pytz

from src.strategies.models.gambit_setups import compute_presession_range

NY = pytz.timezone("US/Eastern")


def bars(start_ny, n, step_min=5):
    """n bar-open datetimes from start (NY wall clock), M5 spacing."""
    t0 = NY.localize(start_ny)
    return [t0 + timedelta(minutes=step_min * i) for i in range(n)]


class TestPresessionRange(unittest.TestCase):
    def test_ny_am_range_basic(self):
        # Bars 02:00 .. 08:55 NY; last bar inside the NY-AM window (09:00).
        ts = bars(datetime(2026, 7, 15, 2, 0), 85)   # 02:00 .. 09:00
        highs = [10.0 + i for i in range(85)]
        lows = [5.0 - i for i in range(85)]
        # range 02:00 (120) -> 08:30 (510): bars idx 0..77 (opens < 08:30)
        out = compute_presession_range(ts, highs, lows, 120, 510)
        self.assertIsNotNone(out)
        hi, lo, n = out
        self.assertEqual(n, 78)
        self.assertEqual(hi, 10.0 + 77)
        self.assertEqual(lo, 5.0 - 77)

    def test_bar_at_range_end_excluded(self):
        # A bar opening exactly at 08:30 belongs to the session, not the range.
        ts = bars(datetime(2026, 7, 15, 8, 25), 3)   # 08:25, 08:30, 08:35
        out = compute_presession_range(ts, [1, 99, 99], [0, -99, -99],
                                       120, 510, min_bars=1)
        hi, lo, n = out
        self.assertEqual(n, 1)
        self.assertEqual(hi, 1)

    def test_london_range_crosses_midnight(self):
        # 18:00 prev day -> 02:00: start > end. Bars 18:00 Jul14 .. 03:00 Jul15.
        ts = bars(datetime(2026, 7, 14, 18, 0), 109)  # 18:00 .. 03:00 next day
        highs = [float(i) for i in range(109)]
        lows = [float(-i) for i in range(109)]
        # range bars: opens in [18:00 Jul14, 02:00 Jul15) = idx 0..95 (96 bars)
        out = compute_presession_range(ts, highs, lows, 18 * 60, 120)
        hi, lo, n = out
        self.assertEqual(n, 96)
        self.assertEqual(hi, 95.0)

    def test_too_few_bars_returns_none(self):
        ts = bars(datetime(2026, 7, 15, 8, 0), 8)    # only 6 bars before 08:30
        out = compute_presession_range(ts, [1] * 8, [0] * 8, 120, 510)
        self.assertIsNone(out)

    def test_anchor_is_most_recent_boundary(self):
        # Two days of bars: the range must come from TODAY's pre-session,
        # not yesterday's.
        ts = (bars(datetime(2026, 7, 14, 2, 0), 78)          # yesterday's range bars
              + bars(datetime(2026, 7, 15, 2, 0), 79))       # today's range + 08:30 bar
        highs = [1.0] * 78 + [50.0] * 79
        lows = [-1.0] * 78 + [-50.0] * 79
        out = compute_presession_range(ts, highs, lows, 120, 510)
        hi, lo, n = out
        self.assertEqual(hi, 50.0)
        self.assertEqual(lo, -50.0)
        self.assertEqual(n, 78)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_range -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.strategies.models.gambit_setups'`

- [ ] **Step 3: Implement**

```python
# ==============================================================================
# FILE: src/strategies/models/gambit_setups.py
# Gambit playbook — pure setup logic (no I/O, no state, no pandas dependency
# beyond duck-typed sequences). The live chassis (gambit.py) AND the research
# harness (scripts/poc_gambit.py) both import these functions, so live and
# research logic cannot drift.
# Spec: docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md
# ==============================================================================
from datetime import timedelta


def _minutes(dt):
    return dt.hour * 60 + dt.minute


def compute_presession_range(ny_times, highs, lows,
                             range_start_min, range_end_min, min_bars=12):
    """High/low of the pre-session range anchored to the most recent
    range_end boundary at or before the last bar. start > end means the
    range window crosses midnight. Returns (hi, lo, n_bars) or None."""
    if not len(ny_times):
        return None
    last = ny_times[-1]
    # Most recent range_end boundary at or before `last`.
    anchor = last.replace(hour=range_end_min // 60, minute=range_end_min % 60,
                          second=0, microsecond=0)
    if anchor > last:
        anchor -= timedelta(days=1)
    duration_min = (range_end_min - range_start_min) % (24 * 60)
    start = anchor - timedelta(minutes=duration_min)
    hi = lo = None
    n = 0
    for i in range(len(ny_times) - 1, -1, -1):     # walk back; bars ascend
        t = ny_times[i]
        if t >= anchor:
            continue
        if t < start:
            break
        hi = highs[i] if hi is None else max(hi, highs[i])
        lo = lows[i] if lo is None else min(lo, lows[i])
        n += 1
    if n < min_bars:
        return None
    return hi, lo, n
```

Note on `anchor.replace(...)`: for tz-aware datetimes from pytz, `replace` keeps the existing tzinfo object. Within one trading day this is exact; on the two DST-transition days per year the anchor can be offset by the changed UTC offset — the same ±1h wobble the 2026-07-11 study accepted for its NY_SHIFT. Do not add DST-renormalization logic; note it in the docstring if the reviewer asks.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_range -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/strategies/models/gambit_setups.py tests/unit/test_gambit_range.py
git commit -m "feat(gambit): pre-session range computation (pure, shared live/research)"
```

---

### Task 3: Judas detector

**Files:**
- Modify: `src/strategies/models/gambit_setups.py`
- Test: `tests/unit/test_gambit_setups.py`

**Interfaces:**
- Consumes: `compute_presession_range` output `(hi, lo, n)` as `rng=(hi, lo)`.
- Produces:
  `detect_judas(bars, ny_times, rng, session_start_min, bias, cfg) -> dict | None`
  - `bars`: dict of aligned sequences `{"open","high","low","close","atr","is_fvg_bull","is_fvg_bear","fvg_top","fvg_bottom"}` (exactly the SMCAnalyzer enriched-column names; the chassis passes `df[col].values`).
  - `ny_times`: aligned NY bar-open datetimes; the LAST element is the just-closed candle being evaluated.
  - `rng`: `(range_hi, range_lo)`; `session_start_min`: minutes-since-midnight NY of the session window open.
  - `bias`: `"BULLISH" | "BEARISH" | "NEUTRAL"` (from `smc.bias_context`).
  - `cfg`: dict with `sweep_ttl_bars` (int), `body_min_atr` (float), `stop_buffer_atr` (float), `rr` (float).
  - Returns `{'signal','type','price','sl','tp','setup':'judas'}` (type always `'LIMIT'`) or `None`. The `setup` key is journal metadata; the controller ignores unknown keys.
- Rules (spec §3, all boundaries strict as written): sweep = trade **strictly beyond** a range extreme after session open; **exactly one** side swept so far (both → None); within `sweep_ttl_bars` of the FIRST breach bar, current bar must be a displacement candle (body ≥ `body_min_atr`×ATR) closing strictly back inside the range, carrying an FVG, direction = against the swept side and equal to H1 bias. Entry = FVG edge; SL = sweep extreme ± `stop_buffer_atr`×ATR; TP = entry ∓ `rr`×risk.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_gambit_setups.py
import unittest
from datetime import datetime, timedelta
import pytz

from src.strategies.models.gambit_setups import detect_judas, detect_reprise

NY = pytz.timezone("US/Eastern")
CFG = {"sweep_ttl_bars": 12, "body_min_atr": 0.8, "stop_buffer_atr": 0.2, "rr": 2.0}


def ny_seq(start_ny, n):
    t0 = NY.localize(start_ny)
    return [t0 + timedelta(minutes=5 * i) for i in range(n)]


def flat_bars(n, price=100.0, atr=1.0):
    """n quiet bars: no sweep, no displacement, no FVG."""
    return {
        "open": [price] * n, "high": [price + 0.1] * n,
        "low": [price - 0.1] * n, "close": [price] * n,
        "atr": [atr] * n,
        "is_fvg_bull": [False] * n, "is_fvg_bear": [False] * n,
        "fvg_top": [0.0] * n, "fvg_bottom": [0.0] * n,
    }


def judas_sell_fixture(n_after_sweep=1):
    """Session bars from 08:30; bar 1 sweeps range-high 105 (high 106),
    then after n_after_sweep-1 quiet bars the LAST bar is a bearish
    displacement closing back inside with a bear FVG."""
    n = 2 + n_after_sweep
    b = flat_bars(n)
    b["high"][1] = 106.0                      # sweep: strictly above 105
    i = n - 1                                  # current bar
    b["open"][i] = 104.5
    b["close"][i] = 103.0                      # body 1.5 >= 0.8*ATR(1.0)
    b["high"][i] = 104.8
    b["low"][i] = 102.9
    b["is_fvg_bear"][i] = True
    b["fvg_bottom"][i] = 104.0                 # entry (SELL limit at gap edge)
    b["fvg_top"][i] = 104.6
    ts = ny_seq(datetime(2026, 7, 15, 8, 30), n)
    return b, ts


class TestJudas(unittest.TestCase):
    RNG = (105.0, 95.0)
    S = 8 * 60 + 30   # session opens 08:30

    def test_sell_after_high_sweep(self):
        b, ts = judas_sell_fixture()
        out = detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG)
        self.assertIsNotNone(out)
        self.assertEqual(out["signal"], "SELL")
        self.assertEqual(out["type"], "LIMIT")
        self.assertEqual(out["price"], 104.0)
        # SL beyond the sweep extreme: 106 + 0.2*1.0
        self.assertAlmostEqual(out["sl"], 106.2)
        risk = out["sl"] - out["price"]
        self.assertAlmostEqual(out["tp"], out["price"] - 2.0 * risk)
        self.assertEqual(out["setup"], "judas")

    def test_bias_must_agree(self):
        b, ts = judas_sell_fixture()
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BULLISH", CFG))
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "NEUTRAL", CFG))

    def test_touch_is_not_a_sweep(self):
        b, ts = judas_sell_fixture()
        b["high"][1] = 105.0                   # exactly the extreme: NOT swept
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_close_back_inside_is_strict(self):
        b, ts = judas_sell_fixture()
        b["close"][-1] = 105.0                 # close AT range-hi: not inside
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_both_sides_swept_is_ambiguous(self):
        b, ts = judas_sell_fixture(n_after_sweep=2)
        b["low"][2] = 94.0                     # second side swept too
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_ttl_boundary(self):
        # Breach at bar 1; current bar index 1+12 -> still eligible;
        # 1+13 -> expired.
        b, ts = judas_sell_fixture(n_after_sweep=12)   # last idx = 13 = 1+12
        self.assertIsNotNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))
        b, ts = judas_sell_fixture(n_after_sweep=13)   # last idx = 14 = 1+13
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_weak_body_rejected(self):
        b, ts = judas_sell_fixture()
        b["open"][-1] = 103.5                  # body 0.5 < 0.8*ATR
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_no_fvg_rejected(self):
        b, ts = judas_sell_fixture()
        b["is_fvg_bear"][-1] = False
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_sweep_before_session_open_ignored(self):
        # The sweep bar sits BEFORE the session window: not a Judas.
        b, ts = judas_sell_fixture()
        ts = ny_seq(datetime(2026, 7, 15, 8, 20), len(ts))  # bar1=08:25 < 08:30
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_buy_mirror(self):
        n = 3
        b = flat_bars(n)
        b["low"][1] = 94.0                     # sweep of range-lo 95
        b["open"][2] = 95.5
        b["close"][2] = 97.0
        b["high"][2] = 97.1
        b["low"][2] = 95.4
        b["is_fvg_bull"][2] = True
        b["fvg_top"][2] = 96.0                 # BUY limit at gap edge
        b["fvg_bottom"][2] = 95.6
        ts = ny_seq(datetime(2026, 7, 15, 8, 30), n)
        out = detect_judas(b, ts, self.RNG, self.S, "BULLISH", CFG)
        self.assertEqual(out["signal"], "BUY")
        self.assertEqual(out["price"], 96.0)
        self.assertAlmostEqual(out["sl"], 94.0 - 0.2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_setups -v`
Expected: FAIL with ImportError (`detect_judas` not defined).

- [ ] **Step 3: Implement `detect_judas`** (append to `gambit_setups.py`)

```python
def _session_first_idx(ny_times, session_start_min):
    """Index of the first bar of the CURRENT session instance (most recent
    crossing of session_start at or before the last bar), or None."""
    last = ny_times[-1]
    anchor = last.replace(hour=session_start_min // 60,
                          minute=session_start_min % 60,
                          second=0, microsecond=0)
    if anchor > last:
        anchor -= timedelta(days=1)
    first = None
    for i in range(len(ny_times) - 1, -1, -1):
        if ny_times[i] < anchor:
            break
        first = i
    return first


def detect_judas(bars, ny_times, rng, session_start_min, bias, cfg):
    """Session-open sweep of the pre-session range, then displacement back
    inside, traded with H1 bias. Evaluates the LAST bar; pure. Spec section 3."""
    rng_hi, rng_lo = rng
    i = len(ny_times) - 1
    first = _session_first_idx(ny_times, session_start_min)
    if first is None:
        return None

    hi_breach = lo_breach = None
    for k in range(first, i + 1):
        if hi_breach is None and bars["high"][k] > rng_hi:
            hi_breach = k
        if lo_breach is None and bars["low"][k] < rng_lo:
            lo_breach = k
    if (hi_breach is None) == (lo_breach is None):
        return None                    # no sweep, or both sides = ambiguous

    atr = float(bars["atr"][i])
    if atr <= 0:
        return None
    body = abs(bars["close"][i] - bars["open"][i])
    if body < cfg["body_min_atr"] * atr:
        return None
    close = float(bars["close"][i])
    if not (rng_lo < close < rng_hi):
        return None                    # must close strictly back inside

    if hi_breach is not None:          # highs swept -> reversal SELL
        if i - hi_breach > cfg["sweep_ttl_bars"]:
            return None
        if bias != "BEARISH" or close >= bars["open"][i]:
            return None
        if not bars["is_fvg_bear"][i]:
            return None
        entry = float(bars["fvg_bottom"][i])
        sweep_ext = max(bars["high"][k] for k in range(hi_breach, i + 1))
        sl = sweep_ext + cfg["stop_buffer_atr"] * atr
        risk = sl - entry
        if risk <= 0:
            return None
        return {"signal": "SELL", "type": "LIMIT", "price": entry,
                "sl": sl, "tp": entry - cfg["rr"] * risk, "setup": "judas"}

    # lows swept -> reversal BUY
    if i - lo_breach > cfg["sweep_ttl_bars"]:
        return None
    if bias != "BULLISH" or close <= bars["open"][i]:
        return None
    if not bars["is_fvg_bull"][i]:
        return None
    entry = float(bars["fvg_top"][i])
    sweep_ext = min(bars["low"][k] for k in range(lo_breach, i + 1))
    sl = sweep_ext - cfg["stop_buffer_atr"] * atr
    risk = entry - sl
    if risk <= 0:
        return None
    return {"signal": "BUY", "type": "LIMIT", "price": entry,
            "sl": sl, "tp": entry + cfg["rr"] * risk, "setup": "judas"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_setups -v`
Expected: PASS (the `TestReprise` class comes in Task 4; only Judas tests exist yet).

- [ ] **Step 5: Commit**

```bash
git add src/strategies/models/gambit_setups.py tests/unit/test_gambit_setups.py
git commit -m "feat(gambit): Judas sweep-reversal detector (pure, boundary-tested)"
```

---

### Task 4: Reprise detector

**Files:**
- Modify: `src/strategies/models/gambit_setups.py`
- Test: `tests/unit/test_gambit_setups.py` (append `TestReprise`)

**Interfaces:**
- Produces: `detect_reprise(bars, bias, cfg) -> dict | None` — same `bars` dict as Task 3 (no times/range needed; the chassis does the window check). Frozen SilverBullet entry with the STRUCT stop from `scripts/poc_sb_stops.py:162-163`: `far_extreme = high[i-2]` (SELL) / `low[i-2]` (BUY); `d = abs(entry - far_extreme) + stop_buffer_atr*ATR`; `sl = entry ± d`. Returns `{'signal','type','price','sl','tp','setup':'reprise'}` or None.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_gambit_setups.py`)

```python
class TestReprise(unittest.TestCase):
    def sell_fixture(self):
        b = flat_bars(4)
        i = 3
        b["high"][1] = 106.0                   # far extreme two bars back
        b["open"][i] = 105.0
        b["close"][i] = 103.5                  # body 1.5 >= 0.8
        b["is_fvg_bear"][i] = True
        b["fvg_bottom"][i] = 104.5
        b["fvg_top"][i] = 105.2
        return b

    def test_sell_struct_stop(self):
        out = detect_reprise(self.sell_fixture(), "BEARISH", CFG)
        self.assertEqual(out["signal"], "SELL")
        self.assertEqual(out["price"], 104.5)
        # d = |104.5 - 106.0| + 0.2*1.0 = 1.7 ; sl = entry + d
        self.assertAlmostEqual(out["sl"], 106.2)
        self.assertAlmostEqual(out["tp"], 104.5 - 2.0 * 1.7)
        self.assertEqual(out["setup"], "reprise")

    def test_bias_gate(self):
        self.assertIsNone(detect_reprise(self.sell_fixture(), "BULLISH", CFG))

    def test_body_boundary(self):
        b = self.sell_fixture()
        b["open"][3] = 104.29                  # body 0.79 < 0.8*ATR
        self.assertIsNone(detect_reprise(b, "BEARISH", CFG))

    def test_zero_atr_rejected(self):
        b = self.sell_fixture()
        b["atr"][3] = 0.0
        self.assertIsNone(detect_reprise(b, "BEARISH", CFG))

    def test_buy_mirror(self):
        b = flat_bars(4)
        b["low"][1] = 94.0
        b["open"][3] = 95.0
        b["close"][3] = 96.5
        b["is_fvg_bull"][3] = True
        b["fvg_top"][3] = 95.5
        b["fvg_bottom"][3] = 94.9
        out = detect_reprise(b, "BULLISH", CFG)
        self.assertEqual(out["signal"], "BUY")
        self.assertEqual(out["price"], 95.5)
        # d = |95.5 - 94.0| + 0.2 = 1.7 ; sl = entry - d
        self.assertAlmostEqual(out["sl"], 93.8)
```

- [ ] **Step 2: Run to verify the new class fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_setups -v`
Expected: Judas tests PASS, Reprise tests ERROR (ImportError on `detect_reprise` — add it to the import line at the top of the test file).

- [ ] **Step 3: Implement `detect_reprise`** (append to `gambit_setups.py`)

```python
def detect_reprise(bars, bias, cfg):
    """Frozen SilverBullet FVG-displacement entry with the STRUCT stop model
    (poc_sb_stops stop_price, model='STRUCT'). Evaluates the LAST bar; pure."""
    i = len(bars["close"]) - 1
    if i < 2:
        return None
    atr = float(bars["atr"][i])
    if atr <= 0:
        return None
    if abs(bars["close"][i] - bars["open"][i]) < cfg["body_min_atr"] * atr:
        return None

    if bars["is_fvg_bear"][i] and bias == "BEARISH":
        entry = float(bars["fvg_bottom"][i])
        d = abs(entry - float(bars["high"][i - 2])) + cfg["stop_buffer_atr"] * atr
        return {"signal": "SELL", "type": "LIMIT", "price": entry,
                "sl": entry + d, "tp": entry - cfg["rr"] * d, "setup": "reprise"}

    if bars["is_fvg_bull"][i] and bias == "BULLISH":
        entry = float(bars["fvg_top"][i])
        d = abs(entry - float(bars["low"][i - 2])) + cfg["stop_buffer_atr"] * atr
        return {"signal": "BUY", "type": "LIMIT", "price": entry,
                "sl": entry - d, "tp": entry + cfg["rr"] * d, "setup": "reprise"}
    return None
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_setups -v`
Expected: PASS (Judas + Reprise, ~16 tests)

- [ ] **Step 5: Commit**

```bash
git add src/strategies/models/gambit_setups.py tests/unit/test_gambit_setups.py
git commit -m "feat(gambit): Reprise detector — frozen SB entry with STRUCT stop"
```

---

### Task 5: Gambit chassis

**Files:**
- Create: `src/strategies/models/gambit.py`
- Test: `tests/unit/test_gambit_strategy.py`

**Interfaces:**
- Consumes: `compute_presession_range`, `detect_judas`, `detect_reprise` (Tasks 2–4, exact signatures above); `BaseStrategy` (`__init__(name, config, logger)`, `validate_data`, `self.pairs`, `self.timeframe`); `TimeNormalizer(broker_gmt_offset).convert_broker_to_ny(ts)` (`src/analysis/time_math.py:34`); controller context dict `{'symbol','bias','liquidity','ny_time','smc_df','spread'}` where `ny_time` is `"HH:MM:SS EST"`-style and `spread` is price units or None.
- Produces: `Gambit(config, logger)` strategy class, `class_path` `src.strategies.models.gambit:Gambit`. `on_new_candle(df, context)` returns the standard decision dict (with extra `setup` key) or None. Config schema (all keys read in `__init__`):

```yaml
gambit:
  enabled: false
  timeframe: "M5"
  rr: 2.0
  broker_gmt_offset: 2            # mirror of connection.broker.timezone_offset
  sessions:
    london: {window: ["02:00","05:00"], range: ["18:00","02:00"]}
    ny_am:  {window: ["08:30","11:00"], range: ["02:00","08:30"]}
  symbol_sessions:
    US30: [ny_am]
    US100: [ny_am]
    XAUUSD: [london, ny_am]
    BTCUSD: [london, ny_am]
  setups:
    judas:   {enabled: false, sweep_ttl_bars: 12, body_min_atr: 0.8, stop_buffer_atr: 0.2}
    reprise: {enabled: false, body_min_atr: 0.8, stop_buffer_atr: 0.2}
  # Fail-safe floors/caps in PRICE units, derived offline from the shared
  # SPREADS table + data/specs.json (Task 6 computes real values):
  # min_stop_price = cost_floor_mult * (spread + commission) in price units.
  cost_floor_mult: 4
  min_stop_price: {}              # symbol -> float; missing symbol = skip (fail-safe)
  max_spread_price: {}            # symbol -> float; live spread above this = skip
  pairs: [US30, US100, XAUUSD, BTCUSD]
```

Behavior contract: no session window active for the symbol → None; already fired this (symbol, session, NY-date) → None (fired = *emitted an intent*, regardless of downstream fate — conservative); range unavailable → only Reprise may run (Judas needs the range); Judas has same-bar precedence over Reprise; risk below `min_stop_price[symbol]` (or symbol absent from the map) → skip with a `RISK`-level log; `ctx['spread']` above `max_spread_price[symbol]` → skip with log.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_gambit_strategy.py
# Chassis behavior: windows, one-per-session, precedence, cost floor,
# spread guard. Detector internals are covered by test_gambit_setups.
import unittest
from datetime import datetime, timezone as dt_tz, timedelta
import pandas as pd
import pytz

from src.strategies.models.gambit import Gambit

NY = pytz.timezone("US/Eastern")

CONFIG = {
    "enabled": True,
    "timeframe": "M5",
    "rr": 2.0,
    "broker_gmt_offset": 0,       # tests use UTC epochs == broker time
    "sessions": {
        "london": {"window": ["02:00", "05:00"], "range": ["18:00", "02:00"]},
        "ny_am": {"window": ["08:30", "11:00"], "range": ["02:00", "08:30"]},
    },
    "symbol_sessions": {"US30": ["ny_am"], "XAUUSD": ["london", "ny_am"]},
    "setups": {
        "judas": {"enabled": True, "sweep_ttl_bars": 12,
                  "body_min_atr": 0.8, "stop_buffer_atr": 0.2},
        "reprise": {"enabled": True, "body_min_atr": 0.8,
                    "stop_buffer_atr": 0.2},
    },
    "cost_floor_mult": 4,
    "min_stop_price": {"US30": 10.0, "XAUUSD": 1.0},
    "max_spread_price": {"US30": 12.0, "XAUUSD": 0.9},
    "pairs": ["US30", "XAUUSD"],
}


class _Logger:
    def __init__(self):
        self.events = []

    def log_event(self, *a, **k):
        self.events.append(a)


def m5_frame(last_ny, n=150, price=100.0, atr=1.0):
    """Enriched-look M5 frame ending at NY wall-clock `last_ny`.
    'time' = epoch seconds (broker_gmt_offset=0 => UTC == broker)."""
    end = NY.localize(last_ny).astimezone(dt_tz.utc)
    times = [(end - timedelta(minutes=5 * (n - 1 - i))).timestamp()
             for i in range(n)]
    df = pd.DataFrame({
        "time": times,
        "open": [price] * n, "high": [price + 0.1] * n,
        "low": [price - 0.1] * n, "close": [price] * n,
        "ATR": [atr] * n,
        "is_swing_high": False, "is_swing_low": False,
        "is_fvg_bull": False, "is_fvg_bear": False,
        "fvg_top": 0.0, "fvg_bottom": 0.0,
    })
    return df


def arm_reprise_sell(df, entry=99.5, far_hi=106.0):
    i = len(df) - 1
    df.loc[i, "open"] = 100.5
    df.loc[i, "close"] = 99.0          # body 1.5 >= 0.8*ATR
    df.loc[df.index[i - 2], "high"] = far_hi
    df.loc[i, "is_fvg_bear"] = True
    df.loc[i, "fvg_bottom"] = entry
    df.loc[i, "fvg_top"] = 100.2
    return df


def ctx(symbol, ny_hhmmss, bias="BEARISH", spread=None):
    return {"symbol": symbol, "bias": bias, "liquidity": {},
            "ny_time": f"{ny_hhmmss} EDT", "smc_df": None, "spread": spread}


def run(strat, df, c):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        strat.on_new_candle(df, context=c))


class TestGambitChassis(unittest.TestCase):
    def setUp(self):
        self.log = _Logger()
        self.strat = Gambit(CONFIG, self.log)

    def test_outside_window_returns_none(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 7, 0)))
        self.assertIsNone(run(self.strat, df, ctx("US30", "07:00:00")))

    def test_reprise_fires_in_window(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        out = run(self.strat, df, ctx("US30", "09:00:00"))
        self.assertIsNotNone(out)
        self.assertEqual(out["setup"], "reprise")
        self.assertEqual(out["signal"], "SELL")

    def test_window_end_exclusive(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 11, 0)))
        self.assertIsNone(run(self.strat, df, ctx("US30", "11:00:00")))

    def test_symbol_not_scoped_to_session(self):
        # US30 is ny_am-only; 03:00 is the london window.
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 3, 0)))
        self.assertIsNone(run(self.strat, df, ctx("US30", "03:00:00")))

    def test_one_intent_per_session(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNotNone(run(self.strat, df, ctx("US30", "09:00:00")))
        df2 = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 30)))
        self.assertIsNone(run(self.strat, df2, ctx("US30", "09:30:00")))

    def test_cost_floor_blocks_thin_stop(self):
        # risk = |sl-entry| = |106+0.2 - 99.5|? No: STRUCT d includes far
        # extreme. Use a NEAR far-extreme so d < min_stop_price (10.0).
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)),
                              far_hi=100.6)     # d = 1.1 + 0.2 = 1.3 < 10
        self.assertIsNone(run(self.strat, df, ctx("US30", "09:00:00")))

    def test_missing_min_stop_symbol_fails_safe(self):
        cfg = dict(CONFIG, min_stop_price={}, pairs=["US30"])
        strat = Gambit(cfg, self.log)
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNone(run(strat, df, ctx("US30", "09:00:00")))

    def test_spread_guard(self):
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNone(
            run(self.strat, df, ctx("US30", "09:00:00", spread=13.0)))
        # at/below the cap trades normally
        df2 = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNotNone(
            run(self.strat, df2, ctx("US30", "09:00:00", spread=11.0)))

    def test_disabled_setup_never_fires(self):
        cfg = dict(CONFIG)
        cfg["setups"] = {"judas": dict(CONFIG["setups"]["judas"]),
                         "reprise": {"enabled": False, "body_min_atr": 0.8,
                                     "stop_buffer_atr": 0.2}}
        strat = Gambit(cfg, self.log)
        df = arm_reprise_sell(m5_frame(datetime(2026, 7, 15, 9, 0)))
        self.assertIsNone(run(strat, df, ctx("US30", "09:00:00")))

    def test_timeframe_and_pairs(self):
        self.assertEqual(self.strat.timeframe, "M5")
        self.assertEqual(self.strat.pairs, ["US30", "XAUUSD"])


if __name__ == "__main__":
    unittest.main()
```

Note for the implementer: if `asyncio.get_event_loop()` deprecation-warns or errors on this Python, use `asyncio.run(...)` inside `run()` instead — match whatever `tests/unit/test_almanac_strategy.py` does for async strategy calls.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_strategy -v`
Expected: FAIL with `ModuleNotFoundError` (gambit.py absent).

- [ ] **Step 3: Implement the chassis**

```python
# ==============================================================================
# FILE: src/strategies/models/gambit.py
# Gambit — M5 session playbook chassis (spec 2026-08-02).
# Owns: session windows, pre-session range, one-intent-per-symbol-per-session,
# cost floor, live-spread guard, setup precedence (judas > reprise same-bar).
# Setup logic lives in gambit_setups.py (pure; shared with scripts/poc_gambit).
# Flat-by-close is NOT here: trade_management.time_exits.Gambit.flat_at_ny.
# ==============================================================================
from src.strategies.base_strategy import BaseStrategy
from src.analysis.time_math import TimeNormalizer
from src.strategies.models.gambit_setups import (
    compute_presession_range, detect_judas, detect_reprise)

_BAR_COLS = ("open", "high", "low", "close", "atr",
             "is_fvg_bull", "is_fvg_bear", "fvg_top", "fvg_bottom")
_TAIL = 320   # bars converted to NY per close: covers the 96-bar London range
              # plus a full session with margin; keeps per-close tz cost flat.


def _parse_min(hhmm):
    hh, mm = str(hhmm).split(":")
    return int(hh) * 60 + int(mm)


class Gambit(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("Gambit", config, logger)
        self.timeframe = str(config.get("timeframe", "M5"))
        self.rr = float(config.get("rr", 2.0))
        self.tz = TimeNormalizer(config.get("broker_gmt_offset", 2))
        self.sessions = {}
        for name, s in (config.get("sessions") or {}).items():
            self.sessions[name] = {
                "window": (_parse_min(s["window"][0]), _parse_min(s["window"][1])),
                "range": (_parse_min(s["range"][0]), _parse_min(s["range"][1])),
            }
        self.symbol_sessions = config.get("symbol_sessions") or {}
        self.setups = config.get("setups") or {}
        self.min_stop_price = config.get("min_stop_price") or {}
        self.max_spread_price = config.get("max_spread_price") or {}
        self._fired = {}   # (symbol, session, ny_date) -> True

    async def analyze_tick(self, tick_data, history_df):
        pass

    def _setup_cfg(self, key):
        c = self.setups.get(key) or {}
        if not c.get("enabled", False):
            return None
        return {"sweep_ttl_bars": int(c.get("sweep_ttl_bars", 12)),
                "body_min_atr": float(c.get("body_min_atr", 0.8)),
                "stop_buffer_atr": float(c.get("stop_buffer_atr", 0.2)),
                "rr": self.rr}

    async def on_new_candle(self, df, context=None):
        if not self.validate_data(df, min_length=100) or not context:
            return None
        symbol = context.get("symbol", "")
        try:
            hh, mm = context["ny_time"].split(":")[:2]
            now_min = int(hh) * 60 + int(mm)
        except (KeyError, ValueError, IndexError, AttributeError):
            return None

        session = None
        for name in self.symbol_sessions.get(symbol, []):
            s = self.sessions.get(name)
            if s and s["window"][0] <= now_min < s["window"][1]:
                session, sname = s, name
                break
        if session is None:
            return None

        tail = df.tail(_TAIL)
        ny_times = [self.tz.convert_broker_to_ny(t) for t in tail["time"]]
        key = (symbol, sname, ny_times[-1].date())
        if key in self._fired:
            return None

        spread = context.get("spread")
        cap = self.max_spread_price.get(symbol)
        if spread is not None and cap is not None and spread > cap:
            self.log(f"{symbol} skipped: live spread {spread} > cap {cap}")
            return None

        bars = {c: tail[c if c != "atr" else "ATR"].values for c in _BAR_COLS}
        bias = context.get("bias", "NEUTRAL")

        intent = None
        jcfg = self._setup_cfg("judas")
        if jcfg is not None:
            rng = compute_presession_range(
                ny_times, bars["high"], bars["low"],
                session["range"][0], session["range"][1])
            if rng is not None:
                intent = detect_judas(bars, ny_times, (rng[0], rng[1]),
                                      session["window"][0], bias, jcfg)
        if intent is None:
            rcfg = self._setup_cfg("reprise")
            if rcfg is not None:
                intent = detect_reprise(bars, bias, rcfg)
        if intent is None:
            return None

        # Cost floor: fail-safe if the symbol has no configured floor.
        floor = self.min_stop_price.get(symbol)
        risk = abs(intent["sl"] - intent["price"])
        if floor is None or risk < floor:
            self.log(f"{symbol} {intent['setup']} skipped: risk {risk:.5f} "
                     f"below cost floor {floor}")
            return None

        self._fired[key] = True
        if len(self._fired) > 64:      # prune stale session keys
            for k in sorted(self._fired, key=lambda k: str(k[2]))[:-32]:
                del self._fired[k]
        self.log(f"♟️ GAMBIT {intent['setup']} {intent['signal']} @ {intent['price']}")
        return intent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_strategy tests.unit.test_gambit_setups tests.unit.test_gambit_range -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/strategies/models/gambit.py tests/unit/test_gambit_strategy.py
git commit -m "feat(gambit): M5 session-playbook chassis (windows, cost floor, one-per-session)"
```

---

### Task 6: Manifest + config wiring (live-inert)

**Files:**
- Create: `config/manifests/gambit.yaml`
- Modify: `config/config.yaml` (`strategies:` block + `trade_management.time_exits`)
- Test: `tests/unit/test_gambit_strategy.py` (append registry test)

**Interfaces:**
- Consumes: `StrategyRegistry` semantics — `status: research` loads but is NOT activated by `activate_eligible()` (`src/strategies/registry.py:88-113`); manifest schema per `config/manifests/silver_bullet.yaml`.
- Produces: Gambit registered and provably inert on the live path.

- [ ] **Step 1: Write the failing registry test** (append to `tests/unit/test_gambit_strategy.py`)

```python
class TestGambitRegistry(unittest.TestCase):
    def test_manifest_loads_and_stays_research(self):
        from pathlib import Path
        from src.strategies.manifest import load_manifests
        from src.strategies.registry import StrategyRegistry
        root = Path(__file__).resolve().parents[2]
        manifests = load_manifests(root / "config" / "manifests")
        ids = {m.id for m in manifests}
        self.assertIn("gambit", ids)
        gm = next(m for m in manifests if m.id == "gambit")
        self.assertEqual(gm.status, "research")
        self.assertEqual(gm.timeframe, "M5")
        # Registry with ONLY the gambit manifest: other strategies' config
        # blocks aren't this test's concern.
        reg = StrategyRegistry([gm], {"gambit": dict(CONFIG)}, _Logger())
        reg.load_all()
        reg.activate_eligible()
        names = [s.name for s in reg.active_instances()]
        self.assertNotIn("Gambit", names)
```

Note: match `StrategyRegistry.__init__`'s real signature — check `src/strategies/registry.py` (the controller passes `publish=` and `feature_bus=` kwargs; both should be optional/defaultable. If not, pass `publish=lambda *a, **k: None, feature_bus=None`).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_strategy.TestGambitRegistry -v`
Expected: FAIL (`gambit` not in manifest ids).

- [ ] **Step 3: Create the manifest and config entries**

`config/manifests/gambit.yaml`:

```yaml
# config/manifests/gambit.yaml
# Gambit — M5 session playbook (Judas + Reprise), spec 2026-08-02.
# status research: loads for the research/registry path, NEVER activated live
# until a setup passes its pre-registered gate (docs spec section 6).
id: gambit
version: "0.1.0"
class_path: "src.strategies.models.gambit:Gambit"
family: smc
timeframe: M5
requires: [smc.enriched_df, smc.bias_context]
status: research
priority: 50
```

`config/config.yaml` — append to `strategies:` (after `ma_slope_baseline`):

```yaml
  # 5. Gambit — M5 session playbook (Judas sweep-reversal + Reprise SB-M5).
  # SPEC: docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md.
  # RESEARCH-ONLY: manifest status research + enabled false + both setups
  # false. Each setup is enabled INDIVIDUALLY by its own gate GO — never
  # flip these without a recorded verdict in docs/research/.
  # min_stop_price = cost_floor_mult x (spread + commission) in PRICE units
  # (values computed from data/specs.json + the shared SPREADS table; the
  # derivation command is in the 2026-08-02 implementation plan, Task 6).
  # max_spread_price = 1.5 x assumed spread (live analogue of the gate's
  # x1.5 stress cell).
  gambit:
    enabled: false
    timeframe: "M5"
    rr: 2.0
    broker_gmt_offset: 2          # keep equal to connection.broker.timezone_offset
    sessions:
      london: {window: ["02:00","05:00"], range: ["18:00","02:00"]}
      ny_am:  {window: ["08:30","11:00"], range: ["02:00","08:30"]}
    symbol_sessions:
      US30: [ny_am]
      US100: [ny_am]
      XAUUSD: [london, ny_am]
      BTCUSD: [london, ny_am]
    setups:
      judas:   {enabled: false, sweep_ttl_bars: 12, body_min_atr: 0.8, stop_buffer_atr: 0.2}
      reprise: {enabled: false, body_min_atr: 0.8, stop_buffer_atr: 0.2}
    cost_floor_mult: 4
    min_stop_price: {}            # FILLED IN by the derivation step below
    max_spread_price: {}          # FILLED IN by the derivation step below
    pairs: ["US30", "US100", "XAUUSD", "BTCUSD"]
```

And in `trade_management.time_exits` add:

```yaml
    Gambit: { flat_at_ny: ["05:00", "11:00"] }  # session-flat (spec 2026-08-02)
```

- [ ] **Step 4: Derive and fill the price floors**

Run this one-off (after Task 7 so the SPREADS table has all six symbols):

```bash
.venv/bin/python - <<'EOF'
import json, sys
sys.path.insert(0, ".")
from scripts.poc_sb_stops import SPREADS, COMMISSION_USD_PER_LOT
specs = json.load(open("data/specs.json"))
for sym in ["US30", "US100", "XAUUSD", "BTCUSD"]:
    sp = specs.get(sym, {})
    tick = float(sp.get("tick_size") or 0) or 1e-5
    tv = float(sp.get("tick_value") or 0) or 1.0
    spread_px = SPREADS[sym] * tick
    comm_px = (COMMISSION_USD_PER_LOT / tv) * tick
    print(f"{sym}: min_stop_price {4*(spread_px+comm_px):.5g}  "
          f"max_spread_price {1.5*spread_px:.5g}")
EOF
```

Paste the printed values into `min_stop_price:` / `max_spread_price:` in the config block. Sanity-check against the spec's arithmetic (e.g. US30 spread 200 ticks — if a printed floor looks absurd vs the symbol's typical M5 ATR, stop and investigate `data/specs.json` for that symbol before committing).

- [ ] **Step 5: Run tests — registry test passes, nothing else regressed**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_strategy tests.unit.test_strategy_timeframe tests.unit.test_almanac_strategy -v`
Expected: ALL PASS. Also boot-parse the config: `.venv/bin/python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"` → no error.

- [ ] **Step 6: Commit**

```bash
git add config/manifests/gambit.yaml config/config.yaml tests/unit/test_gambit_strategy.py
git commit -m "feat(gambit): research-status manifest + inert config wiring"
```

---

### Task 7: SPREADS table extension (closes STRAT-04)

**Files:**
- Modify: `scripts/poc_sb_stops.py:43-46` (SPREADS)
- Modify: `tests/backtest/backtest_engine.py:410` area (its duplicate SPREADS)
- Test: `tests/unit/test_spreads_table_sync.py`

**Interfaces:**
- Produces: both SPREADS tables gain `"US100": 200, "ETHUSD": 193, "XTIUSD": 2` (values measured 2026-07-28, used by the Gyroscope-2 gate — `docs/research/2026-08-01-gyroscope2-gate.md`). A sync test pins the two tables identical forever.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_spreads_table_sync.py
# STRAT-04 guard: the indicative-spread table is duplicated in the research
# script and the backtest engine; they must stay identical and must cover
# the full Gambit universe.
import unittest


class TestSpreadsSync(unittest.TestCase):
    def test_tables_identical(self):
        from scripts.poc_sb_stops import SPREADS as a
        from tests.backtest.backtest_engine import SPREADS as b
        self.assertEqual(a, b)

    def test_gambit_universe_covered(self):
        from scripts.poc_sb_stops import SPREADS
        for sym in ["US30", "US100", "XAUUSD", "BTCUSD", "ETHUSD", "XTIUSD"]:
            self.assertIn(sym, SPREADS)


if __name__ == "__main__":
    unittest.main()
```

If `tests.backtest.backtest_engine` isn't importable (missing `__init__.py` or import-time side effects), import it via `importlib.util.spec_from_file_location` on the file path instead — do NOT restructure the backtest package for this.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_spreads_table_sync -v`
Expected: FAIL (US100/ETHUSD/XTIUSD missing).

- [ ] **Step 3: Add the three symbols to BOTH tables**

In each file the dict becomes:

```python
SPREADS = {                 # indicative FBS spread in ticks (same table as harness)
    "EURUSD": 8, "GBPUSD": 12, "USDJPY": 10, "AUDUSD": 10, "USDCAD": 12,
    "GBPCAD": 30, "GBPJPY": 25, "XAUUSD": 20, "US30": 200, "BTCUSD": 1000, "XBRUSD": 30,
    # Measured 2026-07-28 (Gyroscope-2 gate; closes audit STRAT-04):
    "US100": 200, "ETHUSD": 193, "XTIUSD": 2,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_spreads_table_sync -v`
Expected: PASS. Then confirm the Task 6 derivation step has been run with the final table (re-run it if Task 6 landed first with placeholder floors).

- [ ] **Step 5: Commit**

```bash
git add scripts/poc_sb_stops.py tests/backtest/backtest_engine.py tests/unit/test_spreads_table_sync.py
git commit -m "feat(research): add US100/ETHUSD/XTIUSD to shared SPREADS (closes STRAT-04)"
```

---

### Task 8: Research harness — `scripts/poc_gambit.py`

**Files:**
- Create: `scripts/poc_gambit.py`

**Interfaces:**
- Consumes: `data/history/<SYM>_M5.csv` (columns `datetime,open,high,low,close`, 3y); `SMCAnalyzer`, `BiasEngine` (poc_sb_stops pattern); `compute_presession_range` / `detect_judas` / `detect_reprise` from `src.strategies.models.gambit_setups` — the SAME functions the live chassis runs; `SPREADS`/`COMMISSION_USD_PER_LOT`/`cost_r`-style math from `scripts/poc_sb_stops.py`; `data/specs.json`.
- Produces: per-setup trades CSV `data/results/gambit/trades_<setup>.csv` with columns `sym,setup,session,time,dir,entry,sl,tp,risk,outcome,gross_r,managed_r,fill_idx,exit_idx` — the gate evaluator (Task 9) consumes exactly these columns. `time` is the broker bar time of the signal bar (ISO). `gross_r` is FIXED-exit R (+2/−1/flat-cap partial), `managed_r` is the session-capped ratchet replay R. Costs are NOT baked into the CSV — the gate recomputes net at any spread multiple from `risk` + the tables.
- CLI: `--syms US30,US100,XAUUSD,BTCUSD` (default gate set; `--arms` adds ETHUSD,XTIUSD), `--quick` (tail 30k bars), `--override key=value` (repeatable; overrides a detector cfg key — used by the ±30% sweeps), `--out-dir data/results/gambit`.

- [ ] **Step 1: Write the harness**

```python
#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/poc_gambit.py
# Gambit playbook — offline signal collection + resolution (spec 2026-08-02).
# Imports the LIVE detector functions (gambit_setups) so research and live
# logic cannot drift. Session windows/ranges mirror config/config.yaml gambit.
# NY conversion: fixed NY_SHIFT like poc_sb_stops (+/-1h DST wobble accepted,
# same as the 2026-07-11 study).
#
#   .venv/bin/python scripts/poc_gambit.py                     # gate universe
#   .venv/bin/python scripts/poc_gambit.py --quick --syms US30
#   .venv/bin/python scripts/poc_gambit.py --override body_min_atr=1.04
# ==============================================================================
import argparse
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.analysis.smc_analyzer import SMCAnalyzer                 # noqa: E402
from src.analysis.bias_engine import BiasEngine                    # noqa: E402
from src.strategies.models.gambit_setups import (                  # noqa: E402
    compute_presession_range, detect_judas, detect_reprise)
from scripts.poc_sb_stops import SPREADS, COMMISSION_USD_PER_LOT   # noqa: E402,F401

GATE_SYMS = ["US30", "US100", "XAUUSD", "BTCUSD"]
ARM_SYMS = ["ETHUSD", "XTIUSD"]
NY_SHIFT = -7                    # broker -> NY approx (poc_sb_stops convention)
RR = 2.0
TTL_BARS = 12                    # limit fill TTL (bars after signal bar)
TAIL = 320                       # bars handed to the detectors (chassis _TAIL)
BASE_CFG = {"sweep_ttl_bars": 12, "body_min_atr": 0.8,
            "stop_buffer_atr": 0.2, "rr": RR}

SESSIONS = {                     # minutes-since-midnight NY; mirror config.yaml
    "london": {"window": (120, 300), "range": (1080, 120)},
    "ny_am": {"window": (510, 660), "range": (120, 510)},
}
SYMBOL_SESSIONS = {
    "US30": ["ny_am"], "US100": ["ny_am"],
    "XAUUSD": ["london", "ny_am"], "BTCUSD": ["london", "ny_am"],
    "ETHUSD": ["london", "ny_am"], "XTIUSD": ["ny_am"],
}
# v14.4 ratchet levels (trade_manager.py)
L1, L2, L3 = 0.382, 0.618, 0.886
RUNNER_TRAIL = 0.268


def load_enriched(sym, quick):
    path = f"data/history/{sym}_M5.csv"
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if quick:
        df = df.tail(30000).reset_index(drop=True)
    df = df.rename(columns={"datetime": "time"})
    enr = SMCAnalyzer(df.copy()).process()
    enr["time"] = pd.to_datetime(enr["time"])
    return enr


def make_bias_fn(enr):
    """H1-resampled BiasEngine, cached per closed-H1 count (poc pattern)."""
    h1 = (enr.set_index("time")
             .resample("1h").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"})
             .dropna().reset_index())
    h1_times = h1["time"].values
    cache = {}

    def bias_at(t):
        n = int(np.searchsorted(h1_times, np.datetime64(t)))
        if n not in cache:
            cache[n] = (BiasEngine(h1.iloc[max(0, n - 100):n])
                        .get_bias_context()[0] if n > 20 else "NEUTRAL")
        return cache[n]
    return bias_at


def collect(sym, cfg, quick=False):
    """Walk every M5 bar through the live detector path. Returns signal list
    + bar arrays for resolution."""
    enr = load_enriched(sym, quick)
    if enr is None:
        return None, None
    ny = enr["time"] + timedelta(hours=NY_SHIFT)
    ny_min = (ny.dt.hour * 60 + ny.dt.minute).values
    ny_date = ny.dt.date.values
    ny_py = list(ny.dt.to_pydatetime())          # naive; fine for the pure fns
    cols = {c: enr[c].values for c in
            ("open", "high", "low", "close", "ATR",
             "is_fvg_bull", "is_fvg_bear", "fvg_top", "fvg_bottom")}
    n = len(enr)
    signals = []
    fired = set()                                 # (setup, session, date)
    bias_at = make_bias_fn(enr)

    # Candidate mask: displacement body + FVG (cheap prefilter — the ONLY
    # bars either detector can fire on; everything else returns None).
    body = np.abs(cols["close"] - cols["open"])
    cand = ((cols["is_fvg_bull"] | cols["is_fvg_bear"])
            & (cols["ATR"] > 0)
            & (body >= cfg["body_min_atr"] * cols["ATR"]))
    cand[:TAIL] = False

    for i in np.where(cand)[0]:
        sname = None
        for name in SYMBOL_SESSIONS[sym]:
            w = SESSIONS[name]["window"]
            if w[0] <= ny_min[i] < w[1]:
                sname = name
                break
        if sname is None:
            continue
        lo = i - TAIL + 1
        tail_times = ny_py[lo:i + 1]
        bars = {k.lower() if k == "ATR" else k: v[lo:i + 1]
                for k, v in cols.items()}
        bars["atr"] = cols["ATR"][lo:i + 1]
        bias = bias_at(enr["time"].iloc[i])
        sess = SESSIONS[sname]

        for setup in ("judas", "reprise"):        # same-bar precedence
            if (setup, sname, ny_date[i]) in fired:
                continue
            if setup == "judas":
                rng = compute_presession_range(
                    tail_times, bars["high"], bars["low"],
                    sess["range"][0], sess["range"][1])
                intent = (detect_judas(bars, tail_times, (rng[0], rng[1]),
                                       sess["window"][0], bias, cfg)
                          if rng is not None else None)
            else:
                intent = detect_reprise(bars, bias, cfg)
            if intent is None:
                continue
            end_min = sess["window"][1]
            # Flat-by-close cap: the exit bar is the LAST bar strictly before
            # the flat boundary (11:00 / 05:00 == window end == flat_at_ny).
            j = i + 1
            while j < n:
                if ny_date[j] != ny_date[i] or ny_min[j] >= end_min:
                    break
                j += 1
            end_idx = max(i, j - 1)
            signals.append({"sym": sym, "setup": intent["setup"],
                            "session": sname, "bar_idx": int(i),
                            "time": str(enr["time"].iloc[i]),
                            "dir": intent["signal"], "entry": intent["price"],
                            "sl": intent["sl"], "tp": intent["tp"],
                            "risk": abs(intent["sl"] - intent["price"]),
                            "end_idx": int(end_idx)})
            fired.add((setup, sname, ny_date[i]))
            break                                  # one intent per bar
    bars_out = {"high": cols["high"], "low": cols["low"],
                "close": cols["close"]}
    return signals, bars_out


def resolve_fixed(sig, bars):
    """Limit fill within TTL, then SL/TP scan capped at session end
    (flat at close of end_idx bar). Same-bar SL+TP -> SL (pessimistic,
    poc convention). Returns (outcome, gross_r, fill_idx, exit_idx) or None."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    i, end = sig["bar_idx"], sig["end_idx"]
    entry, sl, tp = sig["entry"], sig["sl"], sig["tp"]
    risk = sig["risk"]
    is_long = sig["dir"] == "BUY"
    fill = None
    for k in range(i + 1, min(i + 1 + TTL_BARS, end + 1)):
        if lows[k] <= entry <= highs[k]:
            fill = k
            break
    if fill is None:
        return None
    for k in range(fill, end + 1):
        sl_hit = (lows[k] <= sl) if is_long else (highs[k] >= sl)
        tp_hit = (highs[k] >= tp) if is_long else (lows[k] <= tp)
        if sl_hit:
            return "SL", -1.0, fill, k
        if tp_hit:
            return "TP", RR, fill, k
    px = closes[end]
    r = ((px - entry) if is_long else (entry - px)) / risk
    return "FLAT", float(r), fill, end


def replay_managed_capped(sig, bars, fill):
    """v14.4 ratchet + runner, capped at session end. Mirrors trade_manager:
    L1 0.382 -> BE; L2 0.618 -> bank 30%, SL to L1; L3 0.886 -> bank 50% of
    remainder, SL to L2, drop TP, trail 0.268*range (arm-C tighten omitted:
    session-capped trades rarely reach deep runner territory; noted in the
    results doc). Bar path approx: SL checked before TP (pessimistic)."""
    highs, lows = bars["high"], bars["low"]
    entry, risk = sig["entry"], sig["risk"]
    is_long = sig["dir"] == "BUY"
    rng = RR * risk                                  # entry->TP distance
    lv = [entry + s * rng * (1 if is_long else -1) for s in (L1, L2, L3)]
    tp = sig["tp"]
    sl = sig["sl"]
    vol = 1.0
    banked = 0.0
    stage = 0
    hwm = entry
    for k in range(fill, sig["end_idx"] + 1):
        hi, lo = highs[k], lows[k]
        adverse = lo if is_long else hi
        favor = hi if is_long else lo
        hwm = max(hwm, favor) if is_long else min(hwm, favor)
        sl_hit = (adverse <= sl) if is_long else (adverse >= sl)
        if sl_hit:
            r_sl = ((sl - entry) if is_long else (entry - sl)) / risk
            return banked + vol * r_sl
        if stage >= 3:
            trail = RUNNER_TRAIL * rng
            new_sl = (hwm - trail) if is_long else (hwm + trail)
            sl = max(sl, new_sl) if is_long else min(sl, new_sl)
        else:
            if stage < 1 and ((favor >= lv[0]) if is_long else (favor <= lv[0])):
                sl, stage = entry, 1
            if stage < 2 and stage >= 1 and (
                    (favor >= lv[1]) if is_long else (favor <= lv[1])):
                r_here = ((lv[1] - entry) if is_long else (entry - lv[1])) / risk
                banked += 0.30 * vol * r_here
                vol *= 0.70
                sl, stage = lv[0], 2
            if stage == 2 and ((favor >= lv[2]) if is_long else (favor <= lv[2])):
                r_here = ((lv[2] - entry) if is_long else (entry - lv[2])) / risk
                banked += 0.50 * vol * r_here
                vol *= 0.50
                sl, stage = lv[1], 3
                tp = None
            if tp is not None and ((favor >= tp) if is_long else (favor <= tp)):
                return banked + vol * RR
    px = bars["close"][sig["end_idx"]]
    r = ((px - entry) if is_long else (entry - px)) / risk
    return banked + vol * r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", default=",".join(GATE_SYMS))
    ap.add_argument("--arms", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--override", action="append", default=[])
    ap.add_argument("--out-dir", default="data/results/gambit")
    a = ap.parse_args()
    cfg = dict(BASE_CFG)
    for ov in a.override:
        k, v = ov.split("=")
        cfg[k] = type(BASE_CFG[k])(float(v))
    syms = a.syms.split(",") + (ARM_SYMS if a.arms else [])
    os.makedirs(a.out_dir, exist_ok=True)
    rows = []
    for sym in syms:
        sigs, bars = collect(sym, cfg, quick=a.quick)
        if sigs is None:
            print(f"  {sym}: no data")
            continue
        opened = 0
        for s in sigs:
            res = resolve_fixed(s, bars)
            if res is None:
                continue
            outcome, gross, fill, exit_k = res
            managed = replay_managed_capped(s, bars, fill)
            rows.append({**{k: s[k] for k in
                            ("sym", "setup", "session", "time", "dir",
                             "entry", "sl", "tp", "risk")},
                         "outcome": outcome, "gross_r": gross,
                         "managed_r": managed, "fill_idx": fill,
                         "exit_idx": exit_k})
            opened += 1
        print(f"  {sym}: {len(sigs)} intents, {opened} filled")
    df = pd.DataFrame(rows)
    tag = "_".join(f"{k}{cfg[k]}" for k in sorted(cfg) if cfg[k] != BASE_CFG[k])
    for setup in ("judas", "reprise"):
        sub = df[df["setup"] == setup] if len(df) else df
        out = os.path.join(a.out_dir,
                           f"trades_{setup}{('_' + tag) if tag else ''}.csv")
        sub.to_csv(out, index=False)
        print(f"{setup}: n={len(sub)} -> {out}")


if __name__ == "__main__":
    main()
```

Implementer notes:
- Sanity property of the session-end cap: `exit_idx - fill_idx` must never span more than one session (≤ ~40 bars) — assert this by eye on the smoke run; a multi-day span means the cap logic regressed.
- `bars` dict keys passed to detectors must be exactly `open/high/low/close/atr/is_fvg_bull/is_fvg_bear/fvg_top/fvg_bottom` (lower-case `atr`) — the construction above builds `ATR` then fixes it; clean that up to a single dict-comprehension with a rename.
- `detect_*` receives naive datetimes here vs tz-aware live — both work: the pure functions only use `.hour/.minute/.date()/.replace/-timedelta` and comparisons within one list.

- [ ] **Step 2: Smoke-run and sanity-check**

```bash
.venv/bin/python scripts/poc_gambit.py --quick --syms US30
```

Expected: runs to completion in minutes; prints intent/filled counts; writes `data/results/gambit/trades_judas.csv` and `trades_reprise.csv`. Sanity checks (do them, don't skip): every trade's NY-converted signal time falls inside a window; `exit_idx - fill_idx` never spans more than one session (≤ ~40 bars); Reprise `risk` ≥ the symbol's derived floor is NOT enforced here (the harness reports raw economics; the cost floor is applied in the gate via the cost model) — confirm `risk` distribution is plausible vs US30 ATR.

- [ ] **Step 3: Full run (background, both setups, gate universe + arms)**

```bash
mkdir -p data/results/gambit
nohup .venv/bin/python scripts/poc_gambit.py --arms > data/results/gambit/collect.log 2>&1 &
```

Expected: completes without error (3y × 6 symbols; SMC enrichment dominates runtime — comparable to a poc_sb_stops full run). Do NOT run while a full unit-suite run is timing anything (memory: concurrent-load contamination).

- [ ] **Step 4: Commit**

```bash
git add scripts/poc_gambit.py
git commit -m "feat(research): poc_gambit harness — session-capped collection/resolution via live detectors"
```

(Results CSVs are committed later with the verdict docs, matching plan07 convention of artifacts under `data/results/`.)

---

### Task 9: Gate evaluator — `scripts/gambit_gate.py`

**Files:**
- Create: `scripts/gambit_gate.py`
- Test: `tests/unit/test_gambit_gate.py`

**Interfaces:**
- Consumes: trades CSVs from Task 8 (columns as specified there); `SPREADS`, `COMMISSION_USD_PER_LOT` from `scripts.poc_sb_stops`; `data/specs.json`.
- Produces: `evaluate_kill(df, spread_mult=1.0) -> dict` and `evaluate_gate(main_df, sweep_dfs) -> dict` importable by tests; CLI printing PASS/FAIL per criterion. Pre-registered thresholds (spec §6) as module constants — never CLI-tunable:

```python
KILL_MIN_N = 150
KILL_BOOT_DRAWS = 5000
KILL_SEED = 11
GATE_OOS_MIN_R = 0.10
GATE_COST_MAX_R = 0.25
GATE_STRESS_MULT = 1.5
GATE_BREADTH_MIN = 3          # of 4 gate symbols
GATE_SWEEP_MAX_FLIPS = 1      # of 4 sweep runs
GATE_BOOT_LB = -0.05
GATE_MAX_SIGNALS_PER_DAY = 2.0
IS_FRAC = 0.70
```

- Net math: `net_r = managed_r - cost_r` (and a `--exit fixed` mode using `gross_r`), where `cost_r = (SPREADS[sym]*mult*tick + (COMMISSION/tick_value)*tick) / risk` (poc_sb_stops `cost_r`, `scripts/poc_sb_stops.py:395`).

- [ ] **Step 1: Write failing tests for the criterion math**

```python
# tests/unit/test_gambit_gate.py
# Gate math on hand-built fixtures — thresholds are pre-registered constants.
import unittest
import pandas as pd

from scripts.gambit_gate import (
    KILL_MIN_N, evaluate_kill, evaluate_gate, add_net, split_is_oos)


def frame(n, sym="US30", net=0.5, t0="2024-01-01"):
    times = pd.date_range(t0, periods=n, freq="6h")
    return pd.DataFrame({
        "sym": [sym] * n, "setup": ["judas"] * n, "session": ["ny_am"] * n,
        "time": times.astype(str), "dir": ["SELL"] * n,
        # risk deliberately LARGE (100 price units) so real US30/XAUUSD spec
        # costs stay far below the 0.25R sanity bound — these tests exercise
        # criterion logic, not cost economics.
        "entry": 100.0, "sl": 200.0, "tp": -100.0, "risk": 100.0,
        "outcome": ["TP"] * n, "gross_r": [net] * n, "managed_r": [net] * n,
    })


class TestGate(unittest.TestCase):
    def test_insufficient_n(self):
        out = evaluate_kill(add_net(frame(KILL_MIN_N - 1), 1.0), "managed")
        self.assertEqual(out["verdict"], "INSUFFICIENT-N")

    def test_kill_pass_on_strong_positive(self):
        out = evaluate_kill(add_net(frame(200, net=0.5), 1.0), "managed")
        self.assertEqual(out["verdict"], "PASS")
        self.assertGreater(out["ci_lo"], 0.0)

    def test_kill_fail_on_negative(self):
        out = evaluate_kill(add_net(frame(200, net=-0.3), 1.0), "managed")
        self.assertEqual(out["verdict"], "FAIL")

    def test_is_oos_split_is_chronological_per_symbol(self):
        df = add_net(pd.concat([frame(100, sym="US30"),
                                frame(100, sym="XAUUSD")]), 1.0)
        is_df, oos_df = split_is_oos(df)
        for sym in ("US30", "XAUUSD"):
            a = is_df[is_df["sym"] == sym]["time"].max()
            b = oos_df[oos_df["sym"] == sym]["time"].min()
            self.assertLess(a, b)
            self.assertEqual(len(is_df[is_df["sym"] == sym]), 70)

    def test_gate_all_criteria_reported(self):
        df = add_net(frame(400, net=0.5), 1.0)
        out = evaluate_gate(df, sweep_dfs=[df, df, df, df])
        self.assertEqual(sorted(out["criteria"].keys()),
                         ["breadth", "calibration", "confidence", "cost",
                          "economics", "robustness", "stress"])
        self.assertIn(out["verdict"], ("GO", "NO-GO"))


if __name__ == "__main__":
    unittest.main()
```

Note: `add_net(df, spread_mult)` needs `data/specs.json` + SPREADS for real symbols; fixtures use US30/XAUUSD so real spec values apply — assertions above avoid exact net values on purpose (risk=10.0 price units makes cost small but nonzero).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_gate -v`
Expected: FAIL (module absent).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/gambit_gate.py
# Gambit kill-screen + 7-criterion gate evaluator (spec 2026-08-02 section 6,
# pre-registered — thresholds are constants, not flags).
#
#   .venv/bin/python scripts/gambit_gate.py --phase kill --setup judas
#   .venv/bin/python scripts/gambit_gate.py --phase gate --setup judas \
#       --sweeps data/results/gambit/trades_judas_body_min_atr0.56.csv,...
# ==============================================================================
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.poc_sb_stops import SPREADS, COMMISSION_USD_PER_LOT  # noqa: E402

KILL_MIN_N = 150
KILL_BOOT_DRAWS = 5000
KILL_SEED = 11
GATE_OOS_MIN_R = 0.10
GATE_COST_MAX_R = 0.25
GATE_STRESS_MULT = 1.5
GATE_BREADTH_MIN = 3
GATE_SWEEP_MAX_FLIPS = 1
GATE_BOOT_LB = -0.05
GATE_MAX_SIGNALS_PER_DAY = 2.0
IS_FRAC = 0.70
GATE_SYMS = ["US30", "US100", "XAUUSD", "BTCUSD"]

_SPECS = json.load(open(os.path.join(
    os.path.dirname(__file__), "..", "data", "specs.json")))


def _cost_r(sym, risk, mult):
    sp = _SPECS.get(sym, {})
    tick = float(sp.get("tick_size") or 0) or 1e-5
    tv = float(sp.get("tick_value") or 0) or 1.0
    spread = SPREADS.get(sym, 20) * mult * tick
    comm = (COMMISSION_USD_PER_LOT / tv) * tick
    return (spread + comm) / risk


def add_net(df, spread_mult, exit_model="managed"):
    df = df.copy()
    col = "managed_r" if exit_model == "managed" else "gross_r"
    df["cost_r"] = [
        _cost_r(s, r, spread_mult) for s, r in zip(df["sym"], df["risk"])]
    df["net_r"] = df[col] - df["cost_r"]
    return df


def _boot_ci(net, draws, seed, lo_q, hi_q):
    rng = np.random.default_rng(seed)
    means = [rng.choice(net, size=len(net), replace=True).mean()
             for _ in range(draws)]
    return float(np.quantile(means, lo_q)), float(np.quantile(means, hi_q))


def split_is_oos(df):
    parts_is, parts_oos = [], []
    for sym, g in df.groupby("sym"):
        g = g.sort_values("time")
        k = int(len(g) * IS_FRAC)
        parts_is.append(g.iloc[:k])
        parts_oos.append(g.iloc[k:])
    return pd.concat(parts_is), pd.concat(parts_oos)


def evaluate_kill(df, exit_model="managed"):
    """Phase-1 kill-screen: N floor, bootstrap 95% CI excludes 0 upward,
    majority of symbols positive, median cost sane."""
    out = {"n": len(df)}
    if len(df) < KILL_MIN_N:
        out["verdict"] = "INSUFFICIENT-N"
        return out
    net = df["net_r"].values
    lo, hi = _boot_ci(net, KILL_BOOT_DRAWS, KILL_SEED, 0.025, 0.975)
    out["mean"] = float(net.mean())
    out["ci_lo"], out["ci_hi"] = lo, hi
    per_sym = df.groupby("sym")["net_r"].mean()
    out["syms_pos"] = int((per_sym > 0).sum())
    out["syms_total"] = len(per_sym)
    out["median_cost"] = float(df["cost_r"].median())
    ok = (lo > 0
          and out["syms_pos"] * 2 > out["syms_total"]
          and out["median_cost"] <= GATE_COST_MAX_R)
    out["verdict"] = "PASS" if ok else "FAIL"
    return out


def evaluate_gate(df, sweep_dfs):
    """Phase-2, all seven pre-registered criteria on ALREADY-NETTED frames
    (df from add_net at 1x). Stress renets at 1.5x internally."""
    c = {}
    is_df, oos_df = split_is_oos(df)
    c["economics"] = (df["net_r"].mean() > 0
                      and oos_df["net_r"].mean() >= GATE_OOS_MIN_R)
    c["cost"] = df["cost_r"].median() <= GATE_COST_MAX_R
    stress = add_net(df, GATE_STRESS_MULT)
    c["stress"] = stress["net_r"].mean() >= 0
    per_sym = df[df["sym"].isin(GATE_SYMS)].groupby("sym")["net_r"].mean()
    c["breadth"] = int((per_sym >= 0).sum()) >= GATE_BREADTH_MIN
    base_sign = df["net_r"].mean() > 0
    flips = sum(1 for sw in sweep_dfs
                if (sw["net_r"].mean() > 0) != base_sign)
    c["robustness"] = flips <= GATE_SWEEP_MAX_FLIPS
    lb, _ = _boot_ci(df["net_r"].values, 2000, KILL_SEED, 0.05, 0.95)
    c["confidence"] = lb > GATE_BOOT_LB
    days = pd.to_datetime(df["time"]).dt.date.nunique()
    c["calibration"] = (len(df) / max(days, 1)) <= GATE_MAX_SIGNALS_PER_DAY
    return {"criteria": c,
            "verdict": "GO" if all(c.values()) else "NO-GO",
            "flips": flips, "oos_mean": float(oos_df["net_r"].mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["kill", "gate"], required=True)
    ap.add_argument("--setup", choices=["judas", "reprise"], required=True)
    ap.add_argument("--exit", choices=["managed", "fixed"], default="managed")
    ap.add_argument("--dir", default="data/results/gambit")
    ap.add_argument("--sweeps", default="")
    a = ap.parse_args()
    df = pd.read_csv(os.path.join(a.dir, f"trades_{a.setup}.csv"))
    df = add_net(df, 1.0, a.exit)
    if a.phase == "kill":
        out = evaluate_kill(df, a.exit)
    else:
        sweeps = [add_net(pd.read_csv(p), 1.0, a.exit)
                  for p in a.sweeps.split(",") if p]
        if len(sweeps) != 4:
            print(f"WARNING: expected 4 sweep files, got {len(sweeps)}")
        out = evaluate_gate(df, sweeps)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
```

(Adjust `evaluate_kill`'s signature/usage so tests and CLI agree — tests call `evaluate_kill(add_net(...), "managed")`; make the second parameter optional metadata or drop it, whichever keeps both green. `_SPECS` loading at import time must not crash the test run — `data/specs.json` exists in-repo; if a test environment lacks it, lazy-load inside `_cost_r`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_gambit_gate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/gambit_gate.py tests/unit/test_gambit_gate.py
git commit -m "feat(research): gambit gate evaluator — pre-registered kill-screen + 7-criterion gate"
```

---

### Task 10: Full-suite verification + research runbook

**Files:**
- Create: `docs/research/2026-08-02-gambit-runbook.md`

- [ ] **Step 1: Run the full unit suite**

```bash
ps aux | grep 'unittest discover' | grep -v grep; uptime   # no concurrent suites
.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
```

Expected: OK, count ≥ baseline 843 + the ~45 new tests. Any failure in a pre-existing module = stop and fix before proceeding.

- [ ] **Step 2: Write the runbook** (verbatim skeleton, fill the commands):

```markdown
# Gambit research runbook (Phase 1-3)

Pre-registered: spec 2026-08-02 §6. One-pass rule — any failure is a recorded
NO-GO, no re-tune. Baselines: MaSlopeBaseline; Reprise is Judas's
mechanism-vs-habitat control.

## Phase 1 — collection + kill-screen (per setup)
1. `nohup .venv/bin/python scripts/poc_gambit.py --arms > data/results/gambit/collect.log 2>&1 &`
2. `.venv/bin/python scripts/gambit_gate.py --phase kill --setup judas`
3. `.venv/bin/python scripts/gambit_gate.py --phase kill --setup reprise`
4. Record both verdicts in docs/research/2026-08-XX-gambit-killscreen.md
   (numbers, INSUFFICIENT-N included) and add a Gambit row to
   docs/strategies/ARSENAL.md. Commit CSVs + doc.

## Phase 2 — full gate (only for setups whose kill-screen PASSED)
Sweeps (+/-30% one-at-a-time, 4 runs — pre-registered parameter pairs):
  judas:   body_min_atr 0.56/1.04, sweep_ttl_bars 8/16 (12*0.7 rounded to 8;
           12*1.3 rounded to 16)
  reprise: body_min_atr 0.56/1.04, stop_buffer_atr 0.14/0.26
  `.venv/bin/python scripts/poc_gambit.py --arms --override body_min_atr=0.56` (etc.)
Then: `.venv/bin/python scripts/gambit_gate.py --phase gate --setup judas \
       --sweeps <4 sweep csvs>`
Also run `--exit fixed` — the dual-exit-model gate requires the positive to
hold under BOTH exits. Record GO/NO-GO doc per setup.

## Phase 3 — demo canary (GO setups only)
- config: gambit.enabled true + <setup>.enabled true; manifest status -> demo;
  min_stop_price/max_spread_price re-derived against current specs.
- Confirm time_exits.Gambit flat_at_ny row present. Restart per
  demo-forward-test memory (ss -tlnp PID, not pgrep). ~2-week checkpoint.
```

- [ ] **Step 3: Commit and merge decision**

```bash
git add docs/research/2026-08-02-gambit-runbook.md
git commit -m "docs(gambit): research runbook (phases 1-3, pre-registered)"
```

Then use superpowers:finishing-a-development-branch — merge `feat/gambit-m5-playbook` to `main` is the owner's call (code is live-inert by construction, so merging before research verdicts is safe and keeps the branch from rotting like feat/equity-timeseries did at 83-behind).

---

## Self-Review Notes (done at plan time)

- **Spec coverage:** §3 shared rules → Tasks 1,5,6; §3 Judas → Task 3; §3 Reprise → Task 4; §4 architecture → Tasks 2–6 (flat_at amended, spec updated in Task 1); §5 guardrails → Task 5 (spread guard, cost floor) + Task 6 (config) + standard path untouched; §6 research → Tasks 8–10; §7 testing → each task's tests (boundary strictness, DST, one-per-session, disabled-setup, mutation-visible flat_at guard); STRAT-04 → Task 7. NOT in scope, matching spec §8: ORB setup, D1/H4 stack, range-target exits, research_run.py changes, EA changes.
- **Deliberate deviations from spec, both recorded in the spec by Task 1:** (a) flat-by-close via `time_exits.flat_at_ny` instead of per-trade `flat_at` metadata; (b) sessions config carries `window`+`range` per session.
- **Known approximations, to be stated in the results doc:** harness NY_SHIFT fixed −7 (±1h DST wobble, precedent 2026-07-11 study); managed replay omits arm-C tighten; `_fired` marks intent emission, not execution.
- **Type consistency:** detector cfg dict keys (`sweep_ttl_bars`, `body_min_atr`, `stop_buffer_atr`, `rr`) identical across Tasks 3/4/5/8; trades-CSV columns identical across Tasks 8/9; `bars` dict keys identical across Tasks 3/4/5/8.
