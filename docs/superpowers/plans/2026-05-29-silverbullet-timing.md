# SilverBullet Timing-Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Generalize SilverBullet's timing to a configurable multi-window gate (logic frozen), pause the other strategies, then sweep candidate windows on the harness to find one shared broker-time rule that gives a robust out-of-sample edge — or conclude none exists.

**Architecture:** A small seam in `SilverBullet` (`_in_window` + windows config), a `--only` strategy filter on the backtester, a pure `trades_in_window` helper, and a sweep/analysis script. Spec: `docs/superpowers/specs/2026-05-29-silverbullet-timing-design.md`.

**Tech Stack:** Python 3.12, pandas, stdlib `unittest`, `.venv`. Run from repo root. Commit each task with explicit pathspec (never `git add -A`).

---

### Task 1: Generalize SilverBullet timing (logic frozen) + pause others

**Files:** Modify `src/strategies/models/silver_bullet.py`; Modify `config/config.yaml`; Test `tests/unit/test_silverbullet_timing.py` (create).

- [ ] **Step 1: Write failing tests** — create `tests/unit/test_silverbullet_timing.py`:

```python
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.strategies.models.silver_bullet import SilverBullet


class _Log:
    def log_event(self, *a, **k):
        pass


def sb(cfg):
    return SilverBullet(cfg, _Log())


class Timing(unittest.TestCase):
    def test_multi_window(self):
        s = sb({"windows": [[2, 4], [10, 11]]})
        self.assertTrue(s._in_window(2))
        self.assertTrue(s._in_window(3))
        self.assertFalse(s._in_window(4))   # end exclusive
        self.assertTrue(s._in_window(10))
        self.assertFalse(s._in_window(11))
        self.assertFalse(s._in_window(0))

    def test_legacy_session_ny_still_works(self):
        s = sb({"session_ny": ["10:00", "11:00"]})
        self.assertTrue(s._in_window(10))
        self.assertFalse(s._in_window(11))

    def test_string_windows_parse(self):
        s = sb({"windows": [["14:00", "16:00"]]})
        self.assertTrue(s._in_window(14))
        self.assertTrue(s._in_window(15))
        self.assertFalse(s._in_window(16))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m unittest tests.unit.test_silverbullet_timing -v` → FAIL (`_in_window` missing).

- [ ] **Step 3: Implement.** In `src/strategies/models/silver_bullet.py` `__init__`, replace the current timing-parse block:

```python
        # Parse Config Time (Robust)
        times = config.get('session_ny', ["10:00", "11:00"])
        try:
            self.start_h = int(times[0].split(':')[0])
            self.end_h = int(times[1].split(':')[0])
        except (ValueError, IndexError):
            self.logger.log_event("WARN", "STRATEGY", "SilverBullet Config Invalid. Defaulting to 10:00-11:00.")
            self.start_h = 10
            self.end_h = 11

        self.rr = config.get('risk_reward', 2.0)
```

with:

```python
        # Timing windows (broker-time hours, end exclusive). Prefer multi-window
        # 'windows'; fall back to the legacy single 'session_ny' window.
        self.windows = self._parse_windows(config)
        self.rr = config.get('risk_reward', 2.0)
```

and add these two methods to the class (e.g. just below `__init__`):

```python
    def _parse_windows(self, config):
        raw = config.get('windows')
        if raw:
            out = []
            for w in raw:
                try:
                    out.append((int(str(w[0]).split(':')[0]), int(str(w[1]).split(':')[0])))
                except (ValueError, IndexError, TypeError):
                    continue
            if out:
                return out
        times = config.get('session_ny', ["10:00", "11:00"])
        try:
            return [(int(str(times[0]).split(':')[0]), int(str(times[1]).split(':')[0]))]
        except (ValueError, IndexError):
            self.logger.log_event("WARN", "STRATEGY", "SilverBullet timing config invalid; default 10-11.")
            return [(10, 11)]

    def _in_window(self, hour):
        return any(start <= hour < end for start, end in self.windows)
```

Then in `on_new_candle`, replace the gate line:

```python
        # Strict Window Check (e.g. 10 <= Hour < 11)
        if not (self.start_h <= h_part < self.end_h): 
            return None
```

with:

```python
        # Timing gate: bar hour must fall in one of the configured windows.
        if not self._in_window(h_part):
            return None
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m unittest tests.unit.test_silverbullet_timing -v` → 3 OK. Also full suite stays green.

- [ ] **Step 5: Pause the other strategies for live** — in `config/config.yaml`, set `enabled: false` for `unicorn_model`, `ict_ote`, and `crt` (leave `silver_bullet` enabled). Leave all other config untouched.

- [ ] **Step 6: Commit** — `git commit src/strategies/models/silver_bullet.py config/config.yaml tests/unit/test_silverbullet_timing.py -m "feat(silverbullet): configurable multi-window timing; pause other strategies" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 2: Backtester `--only <Strategy>` filter

**Files:** Modify `tests/backtest/backtest_engine.py`; Test `tests/unit/test_backtest_only.py` (create).

- [ ] **Step 1: Write failing test** — create `tests/unit/test_backtest_only.py`:

```python
import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
os.chdir(REPO)
import backtest_engine as bt  # noqa: E402

FIX = "tests/backtest/fixtures/golden_smoke.csv"

class OnlyFilter(unittest.TestCase):
    def test_only_runs_one_strategy(self):
        engine = bt.Backtester(FIX, shift_hours=0, only="SilverBullet")
        self.assertEqual([s.name for s in engine.strategies], ["SilverBullet"])

    def test_default_runs_all_four(self):
        engine = bt.Backtester(FIX, shift_hours=0)
        self.assertEqual(len(engine.strategies), 4)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m unittest tests.unit.test_backtest_only -v` → FAIL (`Backtester() got unexpected keyword 'only'`).

- [ ] **Step 3: Implement.** In `Backtester.__init__`, add an `only=None` parameter and store it BEFORE `_init_strategies()` is called. Change the signature `def __init__(self, csv_path, shift_hours=-7):` to `def __init__(self, csv_path, shift_hours=-7, only=None):` and add `self.only = only` near the top of `__init__` (before the `self._init_strategies()` call). Then at the END of `_init_strategies`, after `self.strategies` is built, add:

```python
        if self.only:
            self.strategies = [s for s in self.strategies if s.name == self.only]
```

In the `__main__` block, add the CLI arg `p.add_argument("--only", default=None)` and pass `only=a.only` to the `Backtester(...)` constructor.

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m unittest tests.unit.test_backtest_only -v` → 2 OK. Full suite green.
- [ ] **Step 5: Commit** — `git commit tests/backtest/backtest_engine.py tests/unit/test_backtest_only.py -m "feat(backtest): --only filter to run a single strategy" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 3: `trades_in_window` pure helper

**Files:** Modify `tests/backtest/backtest_engine.py`; Modify `tests/unit/test_harness.py`.

- [ ] **Step 1: Write failing test** — append to `tests/unit/test_harness.py` before `if __name__`:

```python
class TradesInWindow(unittest.TestCase):
    def _t(self, hour, outcome="TP", r=1.0):
        return {"time": f"2026-01-01 {hour:02d}:30:00", "outcome": outcome, "r": r}

    def test_filters_by_entry_hour(self):
        trades = [self._t(2), self._t(3), self._t(10), self._t(11), self._t(23)]
        got = [int(t["time"][11:13]) for t in bt.trades_in_window(trades, [(2, 4), (10, 11)])]
        self.assertEqual(got, [2, 3, 10])  # end exclusive; 11 and 23 dropped

    def test_empty_window(self):
        self.assertEqual(bt.trades_in_window([self._t(5)], [(8, 9)]), [])
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m unittest tests.unit.test_harness.TradesInWindow -v` → FAIL (no attribute).
- [ ] **Step 3: Implement.** Add at module scope in `tests/backtest/backtest_engine.py` (after `win_rate_ci`):

```python
def _trade_hour(t):
    tm = t["time"]
    if hasattr(tm, "hour"):
        return tm.hour            # pandas Timestamp / datetime
    return int(str(tm).split()[1].split(":")[0])  # "YYYY-MM-DD HH:MM:SS"

def trades_in_window(trades, windows):
    """Keep trades whose entry hour falls in any (start, end] -> [start, end) window."""
    return [t for t in trades if any(s <= _trade_hour(t) < e for s, e in windows)]
```

- [ ] **Step 4: Run, verify pass** — 2 OK. Full suite green.
- [ ] **Step 5: Commit** — `git commit tests/backtest/backtest_engine.py tests/unit/test_harness.py -m "feat(backtest): trades_in_window helper for timing sweeps" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 4: Sweep + analysis script

**Files:** Create `scripts/sweep_silverbullet.py`.

- [ ] **Step 1: Implement** — create `scripts/sweep_silverbullet.py`:

```python
#!/usr/bin/env python3
# Sweep SilverBullet trading-hour windows on the validation harness.
# Runs SB-only, all-hours, per instrument; buckets resolved trades by entry hour
# (broker time, --shift 0); scores every candidate window with train/test split
# + significance. Reports the full ranked table (no cherry-picking).
#   .venv/bin/python scripts/sweep_silverbullet.py
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "tests", "backtest"))
import backtest_engine as bt

SYMS = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","GBPCAD","GBPJPY","XAUUSD","US30","BTCUSD","XBRUSD"]

async def collect():
    bt.TEST_CONFIG["silver_bullet"]["windows"] = [[0, 24]]  # un-gate: all hours
    pooled = []
    for s in SYMS:
        path = f"data/history/{s}_M5.csv"
        if not os.path.exists(path):
            continue
        engine = bt.Backtester(path, shift_hours=0, only="SilverBullet")
        trades = await engine.run()  # broker-time bars; no report needed
        pooled += [t for t in trades if t["outcome"] in ("TP", "SL")]
    return pooled

def score(trades, windows):
    sub = bt.trades_in_window(trades, windows)
    train, test = bt.split_trades(sub, 0.7)
    def row(ts):
        m = bt.aggregate_metrics(ts); p, lo, hi = bt.win_rate_ci(m["wins"], m["trades"])
        return m["trades"], p, m["expectancy"], m["total_r"], (lo, hi)
    return row(sub), row(train), row(test)

def main():
    pooled = asyncio.run(collect())
    print(f"Total SB resolved trades (all hours, pooled): {len(pooled)}\n")
    candidates = [("H%02d" % h, [(h, h + 1)]) for h in range(24)]
    candidates += [("H%02d-%02d" % (h, h + 2), [(h, h + 2)]) for h in range(0, 23, 2)]
    candidates += [("CANON(broker)", [[16, 17], [9, 10], [20, 21]])]  # NY 10/03/14 mapped ~UTC+3 broker; adjust after seeing data
    print(f"{'window':14}{'n':>5}{'win%':>6}{'expR':>7}{'totR':>7} | {'TESTn':>6}{'TESTwin':>8}{'TESTexp':>8}  {'flag'}")
    rows = []
    for name, win in candidates:
        (n, p, e, tr, ci), _, (tn, tp, te, ttr, tci) = score(pooled, win)
        rows.append((e, name, n, p, e, tr, tn, tp, te))
    for e, name, n, p, ex, tr, tn, tp, te in sorted(rows, reverse=True):
        flag = "ADOPT?" if (ex > 0 and te > 0 and tn >= 30) else ("insuf" if tn < 30 else "")
        print(f"{name:14}{n:5d}{p*100:6.1f}{ex:+7.2f}{tr:+7.1f} | {tn:6d}{tp*100:8.1f}{te:+8.2f}  {flag}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify import** — `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import scripts.sweep_silverbullet"` → no error.
- [ ] **Step 3: Commit** — `git commit scripts/sweep_silverbullet.py -m "feat: SilverBullet timing-window sweep + significance scoring" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 5 (operational): run the sweep, decide, confirm
- [ ] Run `.venv/bin/python scripts/sweep_silverbullet.py` (uses the existing 20k CSVs).
- [ ] Read the ranked table. Identify any window(s) that clear the adoption bar (positive expectancy in **full sample AND test**, test **n ≥ 30**, win CI lower bound near/above breakeven). Note the canonical-broker mapping may need adjusting once the per-hour profile is visible.
- [ ] If a candidate clears the bar: set it as SB `windows` in `TEST_CONFIG` (or config) and re-run the FULL gated backtester per instrument (`--only SilverBullet`) to confirm concurrency-correct train/test + dollar metrics.
- [ ] Write a short results note (which window, train/test stats, verdict). If nothing clears the bar, state that plainly — SB has no robust timing edge on this data.

---

## Notes for the implementer
- Never `git add -A`. Do NOT change SilverBullet's entry logic (FVG/displacement/SL/TP) — only timing.
- The sweep runs with `--shift 0` so bar hour = broker-server hour (consistent with the live feed).
