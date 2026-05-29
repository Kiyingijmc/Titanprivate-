# Signal-Edge PnL Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backtester report strategy edge (win rate, expectancy, drawdown, profit factor) in R-multiples by simulating each signal's outcome.

**Architecture:** Add three pure, unit-testable functions to `tests/backtest/backtest_engine.py` — `resolve_trade` (one signal → outcome), `aggregate_metrics` (trades → stats), `simulate_signals` (apply one-open-per-symbol concurrency) — then wire them into `Backtester.run()` and replace the signal-count printout with a metrics report.

**Tech Stack:** Python 3.12, pandas (already used), stdlib `unittest` (no pytest), `.venv` interpreter.

Spec: `docs/superpowers/specs/2026-05-29-pnl-backtester-design.md`

---

### Task 1: `resolve_trade` pure function

**Files:**
- Test: `tests/unit/test_backtest_resolver.py` (create)
- Modify: `tests/backtest/backtest_engine.py` (add module-level function)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_backtest_resolver.py`:

```python
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
import backtest_engine as bt  # noqa: E402


def bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


class ResolveTrade(unittest.TestCase):
    def test_market_long_take_profit(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        future = [bar(100, 105, 99, 104), bar(104, 121, 103, 120)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertAlmostEqual(res["r"], 2.0)
        self.assertEqual(res["exit_offset"], 1)
        self.assertTrue(res["filled"])

    def test_market_long_stop_loss(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 101, 89, 95)])
        self.assertEqual(res["outcome"], "SL")
        self.assertAlmostEqual(res["r"], -1.0)

    def test_market_short_take_profit(self):
        sig = {"dir": "SELL", "cmd": "MARKET", "entry": 100, "sl": 110, "tp": 80, "ttl_bars": 24}
        future = [bar(100, 101, 99, 100), bar(100, 101, 79, 80)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertAlmostEqual(res["r"], 2.0)

    def test_limit_never_touched_expires(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 90, "sl": 85, "tp": 100, "ttl_bars": 3}
        future = [bar(100, 101, 95, 96)] * 5
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "EXPIRED")
        self.assertFalse(res["filled"])

    def test_limit_fills_then_take_profit(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 90, "sl": 85, "tp": 100, "ttl_bars": 5}
        future = [bar(95, 96, 92, 94), bar(93, 93, 89, 91), bar(91, 101, 90, 100)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertEqual(res["fill_offset"], 1)
        self.assertAlmostEqual(res["r"], 2.0)

    def test_same_bar_sl_and_tp_is_stop_loss(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 95, "tp": 105, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 106, 94, 100)])
        self.assertEqual(res["outcome"], "SL")

    def test_open_at_end(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 101, 99, 100)])
        self.assertEqual(res["outcome"], "OPEN_AT_END")

    def test_zero_risk_is_invalid(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 100, "tp": 110, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 111, 99, 110)])
        self.assertEqual(res["outcome"], "INVALID")
        self.assertFalse(res["filled"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_backtest_resolver -v`
Expected: FAIL — `AttributeError: module 'backtest_engine' has no attribute 'resolve_trade'`.

- [ ] **Step 3: Implement `resolve_trade`**

In `tests/backtest/backtest_engine.py`, add this at module level (after the imports, before the `Backtester` class):

```python
def resolve_trade(signal, future_bars):
    """Resolve one signal into an outcome over the bars that follow it.

    signal: {dir 'BUY'/'SELL', cmd 'MARKET'/'LIMIT', entry, sl, tp, ttl_bars}.
    future_bars: ordered dicts with open/high/low/close, strictly after the signal bar.
    Returns {filled, outcome, r, fill_offset, exit_offset}; outcome in
    {TP, SL, EXPIRED, OPEN_AT_END, INVALID}. R = SL -> -1.0, TP -> +|tp-entry|/risk.
    """
    entry = float(signal["entry"]); sl = float(signal["sl"]); tp = float(signal["tp"])
    risk = abs(entry - sl)
    if risk == 0:
        return {"filled": False, "outcome": "INVALID", "r": 0.0, "fill_offset": None, "exit_offset": 0}

    is_long = signal["dir"] == "BUY"
    n = len(future_bars)
    if n == 0:
        return {"filled": False, "outcome": "OPEN_AT_END", "r": 0.0, "fill_offset": None, "exit_offset": 0}

    # 1. Fill.
    if signal["cmd"] == "MARKET":
        fill_offset = 0
    else:  # LIMIT: filled when a bar's range touches entry, within TTL.
        ttl = min(int(signal["ttl_bars"]), n)
        fill_offset = None
        for k in range(ttl):
            b = future_bars[k]
            if b["low"] <= entry <= b["high"]:
                fill_offset = k
                break
        if fill_offset is None:
            return {"filled": False, "outcome": "EXPIRED", "r": 0.0,
                    "fill_offset": None, "exit_offset": max(0, ttl - 1)}

    # 2. Resolve SL/TP from the fill bar onward (inclusive). Same bar both hit -> SL.
    for j in range(fill_offset, n):
        b = future_bars[j]
        if is_long:
            sl_hit = b["low"] <= sl
            tp_hit = b["high"] >= tp
        else:
            sl_hit = b["high"] >= sl
            tp_hit = b["low"] <= tp
        if sl_hit:
            return {"filled": True, "outcome": "SL", "r": -1.0,
                    "fill_offset": fill_offset, "exit_offset": j}
        if tp_hit:
            return {"filled": True, "outcome": "TP", "r": abs(tp - entry) / risk,
                    "fill_offset": fill_offset, "exit_offset": j}

    # 3. Never resolved.
    return {"filled": True, "outcome": "OPEN_AT_END", "r": 0.0,
            "fill_offset": fill_offset, "exit_offset": n - 1}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_backtest_resolver -v`
Expected: PASS (8 tests, OK).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_backtest_resolver.py tests/backtest/backtest_engine.py
git commit -m "feat(backtest): add resolve_trade outcome simulation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `aggregate_metrics` pure function

**Files:**
- Modify: `tests/unit/test_backtest_resolver.py` (add a test class)
- Modify: `tests/backtest/backtest_engine.py` (add module-level function)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_backtest_resolver.py` (before the `if __name__` line):

```python
class AggregateMetrics(unittest.TestCase):
    def test_known_trade_list(self):
        trades = [
            {"strat": "A", "outcome": "TP", "r": 2.0},
            {"strat": "A", "outcome": "SL", "r": -1.0},
            {"strat": "A", "outcome": "TP", "r": 2.0},
            {"strat": "A", "outcome": "SL", "r": -1.0},
            {"strat": "A", "outcome": "EXPIRED", "r": 0.0},
            {"strat": "A", "outcome": "OPEN_AT_END", "r": 0.0},
        ]
        m = bt.aggregate_metrics(trades)
        self.assertEqual(m["trades"], 4)
        self.assertEqual(m["wins"], 2)
        self.assertEqual(m["losses"], 2)
        self.assertAlmostEqual(m["win_rate"], 0.5)
        self.assertAlmostEqual(m["expectancy"], 0.5)
        self.assertAlmostEqual(m["total_r"], 2.0)
        self.assertAlmostEqual(m["profit_factor"], 2.0)
        self.assertAlmostEqual(m["max_drawdown_r"], 1.0)
        self.assertEqual(m["max_losing_streak"], 1)
        self.assertEqual(m["expired"], 1)
        self.assertEqual(m["open_at_end"], 1)

    def test_empty_is_safe(self):
        m = bt.aggregate_metrics([])
        self.assertEqual(m["trades"], 0)
        self.assertEqual(m["expectancy"], 0.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_backtest_resolver.AggregateMetrics -v`
Expected: FAIL — `AttributeError: module 'backtest_engine' has no attribute 'aggregate_metrics'`.

- [ ] **Step 3: Implement `aggregate_metrics`**

In `tests/backtest/backtest_engine.py`, add at module level (after `resolve_trade`):

```python
def aggregate_metrics(trades):
    """Summarise resolved trades (TP/SL only) in R-multiples."""
    resolved = [t for t in trades if t["outcome"] in ("TP", "SL")]
    wins = [t["r"] for t in resolved if t["r"] > 0]
    losses = [t["r"] for t in resolved if t["r"] < 0]
    total_r = sum(t["r"] for t in resolved)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    equity = peak = max_dd = 0.0
    for t in resolved:
        equity += t["r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    streak = max_streak = 0
    for t in resolved:
        if t["r"] < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    n = len(resolved)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / n) if n else 0.0,
        "expectancy": (total_r / n) if n else 0.0,
        "total_r": total_r,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "max_drawdown_r": max_dd,
        "max_losing_streak": max_streak,
        "expired": sum(1 for t in trades if t["outcome"] == "EXPIRED"),
        "open_at_end": sum(1 for t in trades if t["outcome"] == "OPEN_AT_END"),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_backtest_resolver.AggregateMetrics -v`
Expected: PASS (2 tests, OK).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_backtest_resolver.py tests/backtest/backtest_engine.py
git commit -m "feat(backtest): add aggregate_metrics (expectancy, PF, max DD in R)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `simulate_signals` (one-open-per-symbol concurrency)

**Files:**
- Modify: `tests/unit/test_backtest_resolver.py` (add a test class)
- Modify: `tests/backtest/backtest_engine.py` (add module-level function)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_backtest_resolver.py` (before the `if __name__` line):

```python
class SimulateSignals(unittest.TestCase):
    def test_skips_overlapping_then_takes_later(self):
        # 10 bars; flat at 100 except TP spikes at index 3 and 6.
        bars = [bar(100, 101, 99, 100) for _ in range(10)]
        bars[3] = bar(100, 111, 99, 110)  # A's TP
        bars[6] = bar(100, 111, 99, 110)  # C's TP
        common = {"dir": "BUY", "cmd": "MARKET", "sl": 90, "tp": 110, "ttl_bars": 24}
        signals = [
            {**common, "entry": 100, "bar_idx": 0, "strat": "A"},  # fills at bar1 open, TP bar3 -> busy_until 3
            {**common, "entry": 100, "bar_idx": 1, "strat": "B"},  # 1 <= 3 -> skipped
            {**common, "entry": 100, "bar_idx": 5, "strat": "C"},  # 5 > 3 -> taken, TP bar6
        ]
        trades = bt.simulate_signals(signals, bars)
        self.assertEqual([t["bar_idx"] for t in trades], [0, 5])
        self.assertTrue(all(t["outcome"] == "TP" for t in trades))

    def test_invalid_signal_does_not_occupy_symbol(self):
        bars = [bar(100, 111, 99, 110) for _ in range(5)]
        signals = [
            {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 100, "tp": 110, "ttl_bars": 24, "bar_idx": 0, "strat": "A"},
            {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 110, "ttl_bars": 24, "bar_idx": 1, "strat": "B"},
        ]
        trades = bt.simulate_signals(signals, bars)
        self.assertEqual(len(trades), 1)          # invalid dropped, B taken
        self.assertEqual(trades[0]["strat"], "B")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_backtest_resolver.SimulateSignals -v`
Expected: FAIL — `AttributeError: module 'backtest_engine' has no attribute 'simulate_signals'`.

- [ ] **Step 3: Implement `simulate_signals`**

In `tests/backtest/backtest_engine.py`, add at module level (after `aggregate_metrics`):

```python
def simulate_signals(signals, bars):
    """Resolve signals under one-open-per-symbol concurrency.

    signals: chronologically ordered, each with bar_idx + resolve_trade fields.
    bars: full 0-indexed list of OHLC dicts (positionally aligned with bar_idx).
    Returns trade dicts (signal fields merged with the resolution).
    """
    trades = []
    busy_until = -1
    for sig in signals:
        if sig["bar_idx"] <= busy_until:
            continue  # a trade/limit is live for this symbol
        future = bars[sig["bar_idx"] + 1:]
        res = resolve_trade(sig, future)
        if res["outcome"] == "INVALID":
            continue  # never placed -> does not occupy the symbol
        trades.append({**sig, **res})
        busy_until = sig["bar_idx"] + 1 + res["exit_offset"]
    return trades
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_backtest_resolver.SimulateSignals -v`
Expected: PASS (2 tests, OK).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_backtest_resolver.py tests/backtest/backtest_engine.py
git commit -m "feat(backtest): add simulate_signals one-open-per-symbol loop

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire simulation into `Backtester` + metrics report + CLI

**Files:**
- Modify: `tests/backtest/backtest_engine.py` — the signal-collection block in `run()`, the `run()` signature, replace `_print_results` with `_report`, and the `__main__` block.

- [ ] **Step 1: Capture full signal fields during the simulation loop**

In `Backtester.run()`, replace the existing signal-recording block:

```python
                if decision:
                    sig_type = decision['signal']
                    price = decision['price']

                    if strat.name != "CRT":
                        if (htf_bias == "BULLISH" and sig_type == "SELL") or \
                           (htf_bias == "BEARISH" and sig_type == "BUY"):
                               continue

                    signals.append({
                        'time': current_time,
                        'strat': strat.name,
                        'type': sig_type,
                        'price': price,
                        'bias_confluence': (sig_type == "BUY" and htf_bias=="BULLISH") or (sig_type == "SELL" and htf_bias=="BEARISH")
                    })
```

with:

```python
                if decision:
                    sig_type = decision['signal']

                    if strat.name != "CRT":
                        if (htf_bias == "BULLISH" and sig_type == "SELL") or \
                           (htf_bias == "BEARISH" and sig_type == "BUY"):
                               continue

                    signals.append({
                        'time': current_time,
                        'strat': strat.name,
                        'dir': sig_type,
                        'cmd': decision['type'],
                        'entry': float(decision['price']),
                        'sl': float(decision['sl']),
                        'tp': float(decision['tp']),
                        'ttl_bars': 12 if "Silver" in strat.name else 24,
                        'bar_idx': i,
                    })
```

- [ ] **Step 2: Change `run()` to simulate + report instead of counting**

Change the method signature `async def run(self):` to `async def run(self, trades_out=None):`.

Then replace the final two lines of `run()`:

```python
        duration = time.time() - start_time
        self._print_results(signals, duration)
```

with:

```python
        bars = enriched_m5[['open', 'high', 'low', 'close']].to_dict('records')
        trades = simulate_signals(signals, bars)
        duration = time.time() - start_time
        self._report(trades, duration, trades_out)
        return trades
```

- [ ] **Step 3: Replace `_print_results` with `_report`**

Delete the entire `_print_results` method and add in its place:

```python
    def _report(self, trades, duration, trades_out=None):
        print("\n" + "=" * 60)
        print(f"BACKTEST COMPLETE in {duration:.1f}s | {len(trades)} trades taken")
        print("=" * 60)

        def line(name, m):
            print(f"\n[{name}]")
            print(f"  trades={m['trades']}  win%={m['win_rate']*100:.1f}  "
                  f"expectancy={m['expectancy']:+.2f}R  totalR={m['total_r']:+.2f}")
            pf = m['profit_factor']
            pf_str = "inf" if pf == float('inf') else f"{pf:.2f}"
            print(f"  PF={pf_str}  maxDD={m['max_drawdown_r']:.2f}R  "
                  f"avgW={m['avg_win']:+.2f}R avgL={m['avg_loss']:+.2f}R  "
                  f"streak={m['max_losing_streak']}  expired={m['expired']} open={m['open_at_end']}")

        by_strat = {}
        for t in trades:
            by_strat.setdefault(t['strat'], []).append(t)
        for name in sorted(by_strat):
            line(name, aggregate_metrics(by_strat[name]))
        line("COMBINED", aggregate_metrics(trades))

        if trades_out:
            import csv
            keys = ['time', 'strat', 'dir', 'cmd', 'entry', 'sl', 'tp',
                    'outcome', 'r', 'bar_idx', 'fill_offset', 'exit_offset']
            with open(trades_out, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
                w.writeheader()
                for t in trades:
                    w.writerow(t)
            print(f"\n[CSV] wrote {len(trades)} trades -> {trades_out}")
```

- [ ] **Step 4: Replace the `__main__` block with a CLI**

Replace the existing `if __name__ == "__main__":` block with:

```python
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Signal-edge PnL backtest (R-multiples).")
    p.add_argument("--csv", default=None, help="path to OHLC CSV (default: auto-discover)")
    p.add_argument("--shift", type=int, default=-7, help="hours to shift broker time toward NY")
    p.add_argument("--trades-out", default=None, help="optional path to write a per-trade CSV")
    a = p.parse_args()

    target = a.csv
    if not target:
        for c in ["test_data.csv", "../../test_data.csv", "data/history/EURUSD_M5.csv"]:
            if os.path.exists(c):
                target = c
                break
    if not target:
        print("❌ No CSV found. Pass --csv <path>.")
        sys.exit(1)

    engine = Backtester(target, shift_hours=a.shift)
    asyncio.run(engine.run(trades_out=a.trades_out))
```

- [ ] **Step 5: Verify the full unit suite still passes**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK, 0 failures — 22 tests total (10 pre-existing + 12 new: 8 ResolveTrade + 2 AggregateMetrics + 2 SimulateSignals).

- [ ] **Step 6: Run the backtester end-to-end on the bundled data**

Run: `.venv/bin/python tests/backtest/backtest_engine.py --trades-out /tmp/bt_trades.csv`
Expected: loads `test_data.csv`, prints a `[SilverBullet] / [Unicorn] / [ICT_OTE] / [CRT] / [COMBINED]` report with `win%`, `expectancy`, `totalR`, `PF`, `maxDD`; writes `/tmp/bt_trades.csv`. Sanity-check: `COMBINED trades` ≤ the old signal count (concurrency drops overlaps), and every row in the CSV has an `outcome` of TP/SL/EXPIRED/OPEN_AT_END.

- [ ] **Step 7: Commit**

```bash
git add tests/backtest/backtest_engine.py
git commit -m "feat(backtest): report R-multiple PnL metrics from simulated trades

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Run from the repo root** (`/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro`) so relative paths and `tests.unit...` discovery resolve.
- The backtest is slow (~100s) because `SMCAnalyzer` runs over the full series — that's pre-existing; don't optimise it as part of this work.
- Do **not** add spread/commission/dollar PnL or the Fibonacci ratchet — explicitly out of scope (see spec).
