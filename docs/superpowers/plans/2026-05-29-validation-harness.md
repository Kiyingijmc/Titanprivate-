# Validation Harness Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backtester realistic ($ + costs), statistically honest (significance), and out-of-sample-validated (train/test), and fast enough for ~6 months of data — **without changing any strategy's signals**.

**Architecture:** Add pure, unit-tested functions to `tests/backtest/backtest_engine.py` (`trade_dollars`, `split_trades`, `win_rate_ci`), a behavior-preserving performance optimization (cache HTF bias per H1 bar), a bridge spec-cache script, and report/CLI wiring. Spec: `docs/superpowers/specs/2026-05-29-validation-harness-design.md`.

**Tech Stack:** Python 3.12, pandas, stdlib `unittest` (no pytest), `.venv`. Run from repo root. Tests: `.venv/bin/python -m unittest ...`. Commit each task with explicit pathspec (unrelated staged changes exist — never `git add -A`).

---

### Task 1: `trade_dollars` — dollar PnL + cost model (pure)

**Files:** Modify `tests/backtest/backtest_engine.py` (add module fn); Test `tests/unit/test_harness.py` (create).

- [ ] **Step 1: Write failing tests** — create `tests/unit/test_harness.py`:

```python
import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
import backtest_engine as bt  # noqa: E402


class TradeDollars(unittest.TestCase):
    def test_winning_trade_net_of_costs(self):
        spec = {"tick_value": 1.0, "tick_size": 0.0001, "vol_step": 0.01}
        # entry/sl 50 pips = 500 ticks; money/lot = 500*1 = $500; risk $100 -> 0.20 lots
        d = bt.trade_dollars(r=2.0, entry=1.1000, sl=1.0950, spec=spec,
                             spread_points=10, commission_per_lot=7.0, risk_dollars=100.0)
        self.assertAlmostEqual(d["lots"], 0.20, places=2)
        self.assertAlmostEqual(d["gross"], 200.0, places=2)        # 2R * $100
        self.assertAlmostEqual(d["commission"], 1.40, places=2)    # 0.20 * 7
        self.assertAlmostEqual(d["spread_cost"], 2.0, places=2)    # 10 * 1.0 * 0.20
        self.assertAlmostEqual(d["net"], 196.60, places=2)

    def test_zero_money_per_lot_is_safe(self):
        spec = {"tick_value": 0.0, "tick_size": 0.0001, "vol_step": 0.01}
        d = bt.trade_dollars(2.0, 1.1, 1.09, spec, 10, 7.0, 100.0)
        self.assertEqual(d["lots"], 0.0)
        self.assertEqual(d["net"], 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m unittest tests.unit.test_harness -v` → FAIL `module 'backtest_engine' has no attribute 'trade_dollars'`.

- [ ] **Step 3: Implement** — add at module scope in `tests/backtest/backtest_engine.py` (after `simulate_signals`):

```python
import math as _math

def trade_dollars(r, entry, sl, spec, spread_points, commission_per_lot, risk_dollars):
    """Convert an R-multiple trade into dollars net of spread + commission, sizing from
    broker tick specs at a fixed risk. Indicative costs (spread is an assumption)."""
    tick_size = float(spec.get("tick_size") or 0.0)
    tick_value = float(spec.get("tick_value") or 0.0)
    step = float(spec.get("vol_step") or 0.01) or 0.01
    stop_ticks = abs(float(entry) - float(sl)) / tick_size if tick_size > 0 else 0.0
    money_per_lot = stop_ticks * tick_value
    if money_per_lot <= 0:
        return {"lots": 0.0, "gross": 0.0, "commission": 0.0, "spread_cost": 0.0, "net": 0.0}
    lots = _math.floor((risk_dollars / money_per_lot) / step) * step
    gross = r * risk_dollars
    commission = lots * commission_per_lot
    spread_cost = spread_points * tick_value * lots
    return {"lots": round(lots, 2), "gross": gross, "commission": commission,
            "spread_cost": spread_cost, "net": gross - commission - spread_cost}
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m unittest tests.unit.test_harness -v` → PASS (2).
- [ ] **Step 5: Commit** — `git commit tests/backtest/backtest_engine.py tests/unit/test_harness.py -m "feat(backtest): dollar PnL + spread/commission cost model" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 2: `split_trades` — chronological train/test (pure)

**Files:** Modify `tests/backtest/backtest_engine.py`; Modify `tests/unit/test_harness.py`.

- [ ] **Step 1: Write failing test** — append to `test_harness.py` before `if __name__`:

```python
class SplitTrades(unittest.TestCase):
    def test_70_30_chronological(self):
        trades = [{"bar_idx": i, "r": 0.0} for i in [5, 1, 9, 3, 7, 2, 8, 4, 6, 10]]
        train, test = bt.split_trades(trades, train_frac=0.7)
        self.assertEqual([t["bar_idx"] for t in train], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([t["bar_idx"] for t in test], [8, 9, 10])

    def test_empty(self):
        self.assertEqual(bt.split_trades([], 0.7), ([], []))
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m unittest tests.unit.test_harness.SplitTrades -v` → FAIL (no attribute).
- [ ] **Step 3: Implement** — add at module scope after `trade_dollars`:

```python
def split_trades(trades, train_frac=0.7):
    """Chronological (by bar_idx) train/test partition."""
    if not trades:
        return [], []
    ordered = sorted(trades, key=lambda t: t.get("bar_idx", 0))
    k = int(len(ordered) * train_frac)
    return ordered[:k], ordered[k:]
```

- [ ] **Step 4: Run, verify pass** → PASS (2).
- [ ] **Step 5: Commit** — `git commit tests/backtest/backtest_engine.py tests/unit/test_harness.py -m "feat(backtest): chronological train/test split" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 3: `win_rate_ci` — Wilson interval + significance (pure)

**Files:** Modify `tests/backtest/backtest_engine.py`; Modify `tests/unit/test_harness.py`.

- [ ] **Step 1: Write failing test** — append to `test_harness.py`:

```python
class WinRateCI(unittest.TestCase):
    def test_known_wilson_interval(self):
        p, lo, hi = bt.win_rate_ci(50, 100)
        self.assertAlmostEqual(p, 0.50, places=3)
        self.assertAlmostEqual(lo, 0.404, places=2)
        self.assertAlmostEqual(hi, 0.596, places=2)

    def test_zero_n_safe(self):
        self.assertEqual(bt.win_rate_ci(0, 0), (0.0, 0.0, 0.0))
```

- [ ] **Step 2: Run, verify fail** → FAIL (no attribute).
- [ ] **Step 3: Implement** — add at module scope after `split_trades`:

```python
def win_rate_ci(wins, n, z=1.96):
    """Wilson score 95% CI for a win rate. Returns (p, low, high)."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * _math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, centre - margin), min(1.0, centre + margin))
```

- [ ] **Step 4: Run, verify pass** → PASS (2).
- [ ] **Step 5: Commit** — `git commit tests/backtest/backtest_engine.py tests/unit/test_harness.py -m "feat(backtest): Wilson CI for win-rate significance" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 4: Performance pass — cache HTF bias per H1 bar (behavior-preserving)

**Files:** Create fixture `tests/backtest/fixtures/golden_smoke.csv` + `tests/backtest/fixtures/golden_trades.csv`; Modify `tests/backtest/backtest_engine.py` (`run()`); Test `tests/unit/test_perf_equivalence.py`.

- [ ] **Step 1: Generate the golden fixture from the CURRENT (un-optimized) engine.** Make a small fixed CSV and capture today's output as the contract:

```bash
mkdir -p tests/backtest/fixtures
head -n 2001 test_data.csv > tests/backtest/fixtures/golden_smoke.csv   # header + 2000 bars
.venv/bin/python tests/backtest/backtest_engine.py --csv tests/backtest/fixtures/golden_smoke.csv --trades-out tests/backtest/fixtures/golden_trades.csv >/dev/null 2>&1
wc -l tests/backtest/fixtures/golden_trades.csv   # confirm it has trades
```

- [ ] **Step 2: Write the characterization test** — create `tests/unit/test_perf_equivalence.py`:

```python
import os, sys, asyncio, csv, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
os.chdir(REPO)
import backtest_engine as bt  # noqa: E402

FIX = "tests/backtest/fixtures"

def _rows(path):
    with open(path) as f:
        return [(r["bar_idx"], r["strat"], r["outcome"], r["r"]) for r in csv.DictReader(f)]

class PerfEquivalence(unittest.TestCase):
    def test_optimized_engine_matches_golden_trades(self):
        out = "/tmp/perf_check_trades.csv"
        engine = bt.Backtester(f"{FIX}/golden_smoke.csv", shift_hours=-7)
        asyncio.run(engine.run(trades_out=out))
        self.assertEqual(_rows(out), _rows(f"{FIX}/golden_trades.csv"))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run, verify it PASSES now** (no change yet — this is a characterization/refactor guard, not RED):
`.venv/bin/python -m unittest tests.unit.test_perf_equivalence -v` → PASS. If it fails here, STOP and report (fixture/path issue) before optimizing.

- [ ] **Step 4: Implement the optimization in `run()`.** Today the per-candle loop rebuilds `BiasEngine` every M5 bar. Cache it per H1 bar. Locate this block in `run()`:

```python
            h1_context = self.h1_df[self.h1_df['time'] < current_time]

            htf_bias = "NEUTRAL"
            liquidity = {}

            if len(h1_context) > 20:
                bias_eng = BiasEngine(h1_context.iloc[-100:])
                htf_bias, liquidity = bias_eng.get_bias_context()
```

Replace it with a version that recomputes only when the number of available H1 bars changes (i.e. a new H1 bar has closed), caching the last result on `self`:

```python
            h1_context = self.h1_df[self.h1_df['time'] < current_time]
            h1_n = len(h1_context)

            if h1_n != getattr(self, "_bias_h1_n", -1):
                # New H1 bar available -> recompute and cache (bias is constant within an H1 bar)
                if h1_n > 20:
                    self._bias_cache = BiasEngine(h1_context.iloc[-100:]).get_bias_context()
                else:
                    self._bias_cache = ("NEUTRAL", {})
                self._bias_h1_n = h1_n

            htf_bias, liquidity = self._bias_cache
```

Initialise the cache in `Backtester.__init__` (add near the other attributes): `self._bias_h1_n = -1; self._bias_cache = ("NEUTRAL", {})`.

NOTE: this is signal-preserving ONLY IF bias depends solely on the set of closed H1 bars (it does — `BiasEngine` reads `h1_context.iloc[-100:]`). It changes nothing about which signals fire; it only avoids recomputation. Do NOT alter any strategy code.

- [ ] **Step 5: Run the equivalence test — MUST still pass** (identical trades):
`.venv/bin/python -m unittest tests.unit.test_perf_equivalence -v` → PASS. If output differs, the optimization changed behavior — revert and report BLOCKED.

- [ ] **Step 6: Sanity-check the speedup** (informational): time the bundled run before mental model — run `time .venv/bin/python tests/backtest/backtest_engine.py --csv tests/backtest/fixtures/golden_smoke.csv >/dev/null 2>&1` and note it's faster than the pre-change baseline.

- [ ] **Step 7: Commit** — `git commit tests/backtest/backtest_engine.py tests/unit/test_perf_equivalence.py tests/backtest/fixtures/golden_smoke.csv tests/backtest/fixtures/golden_trades.csv -m "perf(backtest): cache HTF bias per H1 bar (signal-preserving)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 5: Spec-cache script (bridge → data/specs.json)

**Files:** Create `scripts/cache_specs.py`.

- [ ] **Step 1: Implement** — create `scripts/cache_specs.py`:

```python
#!/usr/bin/env python3
# Pull per-instrument tick specs from MT5 via the ZMQ bridge into data/specs.json.
# Run only when the bot is NOT running (shared ZMQ ports) and the EA is connected.
#   .venv/bin/python scripts/cache_specs.py EURUSD GBPUSD XAUUSD US30 BTCUSD ...
import asyncio, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.bridge_zmq import ZMQBridge
from scripts.export_history import fetch_history  # reuses GET_HISTORY round-trip

DEFAULT = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","GBPCAD","GBPJPY","XAUUSD","US30","BTCUSD","XBRUSD"]

async def _run(symbols, out):
    bridge = ZMQBridge()
    if not await asyncio.wait_for(bridge.ping(), 6):
        print("bridge down — attach the EA and retry"); return 1
    specs = {}
    for s in symbols:
        await bridge.send_command("GET_HISTORY", {"symbol": s, "tf": "M5", "count": 5})
        end = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < end:
            for m in await bridge.poll_data():
                if m.get("type") == "HISTORY" and m.get("symbol") == s:
                    specs[s] = {"tick_value": m.get("tv"), "tick_size": m.get("ts"),
                                "vol_min": m.get("vm"), "vol_step": m.get("vs")}
                    break
            if s in specs: break
            await asyncio.sleep(0.1)
        print(f"  {s}: {specs.get(s, 'NO DATA')}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f: json.dump(specs, f, indent=2)
    print(f"wrote {len(specs)} specs -> {out}")
    return 0

def main():
    symbols = sys.argv[1:] or DEFAULT
    raise SystemExit(asyncio.run(_run(symbols, "data/specs.json")))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports cleanly** (no bridge needed): `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import scripts.cache_specs"` → no error.
- [ ] **Step 3: Commit** — `git commit scripts/cache_specs.py -m "feat: cache per-instrument MT5 tick specs to data/specs.json" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

(The actual `data/specs.json` is generated at run time and is git-ignored under `data/`.)

---

### Task 6: Wire dollars + split + significance into the report + CLI

**Files:** Modify `tests/backtest/backtest_engine.py` (`run()` signature, `_report`, `__main__`).

- [ ] **Step 1: Add CLI args + load specs.** In `__main__`, after the existing args, add:

```python
    p.add_argument("--equity", type=float, default=10000.0)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--split", type=float, default=0.7)
    p.add_argument("--specs", default="data/specs.json")
    p.add_argument("--no-costs", action="store_true")
```

and pass them through: `asyncio.run(engine.run(trades_out=a.trades_out, equity=a.equity, risk_pct=a.risk_pct, split=a.split, specs_path=a.specs, costs=not a.no_costs))`.

- [ ] **Step 2: Extend `run()` signature and dollarize trades.** Change to `async def run(self, trades_out=None, equity=10000.0, risk_pct=1.0, split=0.7, specs_path="data/specs.json", costs=True):`. After `trades = simulate_signals(signals, bars)` and before reporting, attach dollars to each resolved trade:

```python
        import json
        SPREADS = {  # indicative spread in points (price/tick_size units); tune later
            "EURUSD": 8, "GBPUSD": 12, "USDJPY": 10, "AUDUSD": 10, "USDCAD": 12,
            "GBPCAD": 30, "GBPJPY": 25, "XAUUSD": 20, "US30": 200, "BTCUSD": 1000, "XBRUSD": 30,
        }
        specs = {}
        if costs and os.path.exists(specs_path):
            with open(specs_path) as f:
                specs = json.load(f)
        risk_dollars = equity * risk_pct / 100.0
        sym = os.path.splitext(os.path.basename(self.csv_path))[0].split("_")[0]
        spec = specs.get(sym)
        for t in trades:
            if spec and t["outcome"] in ("TP", "SL"):
                t.update(trade_dollars(t["r"], t["entry"], t["sl"], spec,
                                       SPREADS.get(sym, 20), 7.0, risk_dollars))
        self._report(trades, time.time() - start_time, trades_out, split=split, has_costs=bool(spec))
        return trades
```

- [ ] **Step 2b: Confirm `self.csv_path` exists** on the Backtester (it is set in `__init__`). If the attribute has a different name, use the real one.

- [ ] **Step 3: Upgrade `_report`** to show train/test blocks, dollars, and significance. Replace the `_report` method with:

```python
    def _report(self, trades, duration, trades_out=None, split=0.7, has_costs=False):
        print("\n" + "=" * 64)
        print(f"BACKTEST COMPLETE in {duration:.1f}s | {len(trades)} trade records")
        print("=" * 64)

        def block(title, ts):
            print(f"\n--- {title} ({len(ts)} records) ---")
            by = {}
            for t in ts:
                by.setdefault(t["strat"], []).append(t)
            for name in sorted(by) + ["COMBINED"]:
                grp = ts if name == "COMBINED" else by[name]
                m = aggregate_metrics(grp)
                p, lo, hi = win_rate_ci(m["wins"], m["trades"])
                flag = "  [INSUFFICIENT n<30]" if m["trades"] < 30 else ""
                pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
                line = (f"  {name:12} n={m['trades']:4d} win={p*100:4.1f}% "
                        f"CI[{lo*100:.0f}-{hi*100:.0f}] exp={m['expectancy']:+.2f}R "
                        f"totR={m['total_r']:+.1f} PF={pf} DD={m['max_drawdown_r']:.0f}R")
                if has_costs:
                    net = sum(t.get("net", 0.0) for t in grp)
                    cost = sum(t.get("commission", 0.0) + t.get("spread_cost", 0.0) for t in grp)
                    line += f" | net=${net:+.0f} cost=${cost:.0f}"
                print(line + flag)

        train, test = split_trades(trades, split)
        block("TRAIN (in-sample)", train)
        block("TEST (out-of-sample)", test)
        block("ALL", trades)

        if trades_out:
            import csv
            keys = ["time","strat","dir","cmd","entry","sl","tp","outcome","r","bar_idx",
                    "fill_offset","exit_offset","lots","gross","commission","spread_cost","net"]
            with open(trades_out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                for t in trades:
                    w.writerow(t)
            print(f"\n[CSV] wrote {len(trades)} trades -> {trades_out}")
```

- [ ] **Step 4: Run the full unit suite** — `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` → all green (existing 24 + harness 6 + perf 1).
- [ ] **Step 5: Smoke-run** on the golden fixture (no specs file needed; costs gracefully skipped):
`.venv/bin/python tests/backtest/backtest_engine.py --csv tests/backtest/fixtures/golden_smoke.csv` → prints TRAIN / TEST / ALL blocks with win% + Wilson CI + insufficient flags.
- [ ] **Step 6: Commit** — `git commit tests/backtest/backtest_engine.py -m "feat(backtest): train/test + dollars + significance in report and CLI" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 7 (operational, not code): generate the validated dataset + results
After the build, with the bridge up and bot not running:
- [ ] `.venv/bin/python scripts/cache_specs.py` → `data/specs.json`.
- [ ] Export ~50k M5 bars per instrument (re-run the multi-export with count=50000; accept fewer if FBS caps).
- [ ] Run the harness on each instrument (background), saving reports + trade CSVs.
- [ ] Produce an updated, realistic, OOS-validated results report (supersedes the frictionless one), and use it to decide Phase 2 (which strategies/instruments clear a positive-expectancy, statistically-adequate bar).

---

## Notes for the implementer
- **Never `git add -A`** — unrelated work is staged in this repo; commit only the named files per task.
- The perf task's contract is the **identical-trades** test — if it can't stay green, the optimization is wrong; revert and escalate, don't weaken the test.
- Don't touch any file under `src/strategies/` or `src/analysis/` — Phase 1 must not change signals.
