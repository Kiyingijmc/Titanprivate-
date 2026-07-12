# Plan 03: Kernel v15.0 — FeatureBus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the live signal path's analytics (SMCAnalyzer + BiasEngine) behind a dependency-aware, event-keyed FeatureBus — computed once per invalidation token instead of once per candle close — with a committed golden fixture proving the signal stream is byte-identical before and after, plus the two golden-tape gaps from Plan 02's final review closed.

**Architecture:** Per `docs/research/2026-07-12-trading-os-blueprint.md` §3–4. A `ResourceSpec` registry forming a DAG, memoized per `(name, symbol, tf, token)` where the token IS the invalidation event (own-bar time, or the H1 bar time for HTF resources). The headline win: `smc.bias_context` currently recomputes the full H1 bias analysis on **every M5 close of every symbol** (`_run_strategies`); keyed to the H1 bar token it recomputes ~12× less, with identical semantics — and the golden fixture proves "identical."

**Scope decision (recorded):** the offline `tests/backtest/backtest_engine.py` is NOT migrated in v15.0. It enriches in batch (full-frame once + `_bias_cache`), so per-close FeatureBus evaluation would be O(n²) without incremental resources. Research-path unification arrives with Plan 06's replay router, as the roadmap already sequences. v15.0's parity evidence covers the LIVE path.

**Tech Stack:** Python 3.11, pandas, stdlib unittest. No new dependencies.

## Global Constraints

- Test command: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`. Baseline entering: **215 OK**; green after every task.
- **Task 1 MUST run before any refactor task** — the golden fixture is captured from PRE-refactor code; capturing it after any change to the signal path voids the whole plan.
- Signal-path parity is the gate: after Task 4 the parity test must pass against the UNCHANGED Task-1 fixture. If it fails, fix the FeatureBus/pack — never regenerate the fixture to make it pass (regeneration requires a controller-approved reason recorded in this plan).
- FeatureBus `compute` functions must be pure (inputs from context + deps only; no wall-clock, no I/O, no controller state).
- Determinism: single-threaded evaluation; no wall-clock TTLs (tokens only).
- Do NOT touch: `mql5_bridge/Experts/Titan_Gateway.mq5`, `data/specs.json`, `scripts/poc_sb_stops.py`, `src/strategies/models/silver_bullet.py` (strategy code unchanged in v15.0 — the adapter is the controller passing the same `enriched_df`/ctx it always passed).
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Branch: `feat/trade-mgmt-pipeline`.

## File Structure

```
scripts/capture_parity_golden.py       # T1: harness (drives real _run_strategies over test_data.csv H1)
tests/backtest/fixtures/parity_golden_h1.json   # T1: committed golden signal stream
tests/unit/test_signal_parity.py       # T1: replays harness, asserts == fixture (the plan's gate)
src/features/__init__.py               # T2
src/features/feature_bus.py            # T2: ResourceSpec, FeatureBus, stats
src/features/packs/__init__.py         # T3
src/features/packs/smc_pack.py         # T3: smc.enriched_df + smc.bias_context resources
tests/unit/test_feature_bus.py         # T2
tests/unit/test_smc_pack.py            # T3
src/core/system_controller.py          # T4: _run_strategies consumes the bus; T5: warmup snapshot
src/core/events.py                     # T5: SpecsUpdated fields + WarmupSnapshot
tests/unit/test_tape_fidelity.py       # T5
CLAUDE.md                              # T4: architecture sentence update
```

---

### Task 1: Parity harness + golden fixture (PRE-refactor — run first)

**Files:**
- Create: `scripts/capture_parity_golden.py`, `tests/unit/test_signal_parity.py`, `tests/backtest/fixtures/parity_golden_h1.json` (generated then committed)

**Interfaces:**
- Produces: `capture_stream(csv_path) -> list[dict]` in the script — each element `{"i": int, "bias": str, "signal": str|None, "price": float|None, "sl": float|None, "tp": float|None, "grade": str|None}`, one per H1 close evaluated. The test imports and reruns it, comparing to the fixture with exact equality (floats serialized via `repr` for bit-stability).

- [ ] **Step 1: Build the harness** in `scripts/capture_parity_golden.py`:
  1. Load `test_data.csv` (repo root; tab-separated MT5 M5 export with `<DATE>/<TIME>/<OPEN>...` headers). Reuse the loading+H1-resample logic by instantiating `tests/backtest/backtest_engine.BacktestEngine(csv_path)` the same way `tests/unit/test_harness.py` imports it, and take its H1 frame (READ `_load_and_process_data` first to learn the attribute name; if the engine shifts hours, keep its default so timestamps match live conventions). Do not modify the engine.
  2. Build a controller fixture exactly like `tests/unit/test_controller_events.py::make_controller` (via `SystemController.__new__`), plus: real `SignalGrader(cfg)` from the repo's `config/config.yaml` (`yaml.safe_load`), real `SilverBullet(cfg['strategies']['silver_bullet'], logger=_StubLogger())`, `strategies=[that SB]`, a stub `time_engine` whose `get_current_ny_string()` returns the constant `"10:00:00 EST"` (deterministic; AMENDED during execution — the originally planned ISO-style constant broke `SilverBullet`'s `int(ny_time.split(':')[0])` hour parse, since the real `TimeNormalizer` format is `"HH:MM:SS EST"`; with the amended constant the golden carries 13 graded signals across A++→B, and the always-in-window hour is an accepted coverage limit because the window gate lives in strategy code untouched by this refactor), `market_data = {"TESTUSD": _StubStore(h1_df=None)}` where `_StubStore.get_data("H1")` returns the current window (set per iteration), a capturing `async _execute_signal` stub recording `(symbol, decision, name, bias, grade)`, and a `_StubLogger` with no-op `log_event`. **Crucially**, end the fixture builder with:

```python
    try:  # post-refactor (Task 4+) the harness must exercise the BUS path,
          # pre-refactor these modules don't exist and the inline path runs.
        from src.features.feature_bus import FeatureBus
        from src.features.packs.smc_pack import register_smc_pack
        c.feature_bus = FeatureBus()
        register_smc_pack(c.feature_bus)
        c.feature_bus.validate()
    except ImportError:
        pass
    return c
```

Without this, the Task-4 fallback branch (`getattr(self, 'feature_bus', None)`) would silently route the parity test through the OLD inline path forever, and the gate would prove nothing.
  3. Iterate `end` from 60 to `len(h1)` (step 1): `window = h1.iloc[max(0, end-300):end].reset_index(drop=True)`
     (AMENDED during execution: the original unbounded `iloc[:end]` made the parity test
     O(n²) — the full suite went 10s → 862s. The 300-bar cap mirrors the live rolling-store
     behavior and bounds per-iteration cost. FIXTURE REGENERATED under this amendment while
     still pre-refactor — the one sanctioned regeneration; the refactor tasks remain bound
     to the regenerated fixture); set the stub store's H1 frame to `window`; run `asyncio.run(controller._run_strategies("TESTUSD", window, "H1"))`. After each call, record the bias used — obtain it the same way `_run_strategies` does (call `BiasEngine(window).get_bias_context()[0]` in the harness for the record; this duplicates the computation for RECORDING only and is identical pre/post refactor) — plus the captured signal (or None) and grade. Reset the capture list between iterations.
  4. `main()` writes the list to `tests/backtest/fixtures/parity_golden_h1.json` (floats via `repr`, `indent=1`).

- [ ] **Step 2: Generate the fixture**

Run: `.venv/bin/python scripts/capture_parity_golden.py`
Expected: fixture file written; print the stream length and the count of non-None signals (record both in the report; if signal count is 0, STOP — a golden with zero signals can't prove signal parity; report BLOCKED so the controller can widen the window range or relax the grader floor FOR THE HARNESS ONLY via explicit config override recorded here).

- [ ] **Step 3: Write the lock test** `tests/unit/test_signal_parity.py`:

```python
import json, unittest
from pathlib import Path
from scripts.capture_parity_golden import capture_stream

GOLDEN = Path(__file__).resolve().parents[1] / "backtest" / "fixtures" / "parity_golden_h1.json"

class TestSignalParity(unittest.TestCase):
    def test_signal_stream_matches_golden(self):
        got = capture_stream("test_data.csv")
        want = json.loads(GOLDEN.read_text())
        self.assertEqual(len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            self.assertEqual(g, w, f"divergence at element {i}")
```

- [ ] **Step 4: Run it** — `.venv/bin/python -m unittest tests.unit.test_signal_parity -v` → PASS (trivially: fixture just captured from the same code). Then full suite → `Ran 216 tests ... OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/capture_parity_golden.py tests/unit/test_signal_parity.py tests/backtest/fixtures/parity_golden_h1.json
git commit -m "test(v15): golden signal-parity fixture captured from pre-FeatureBus live path

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: FeatureBus core

**Files:**
- Create: `src/features/__init__.py` (empty), `src/features/feature_bus.py`
- Test: `tests/unit/test_feature_bus.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ResourceSpec:
    name: str                              # "smc.bias_context"
    deps: tuple = ()                       # upstream resource names
    scope: str = "symbol_tf"               # "symbol_tf" | "symbol" | "global"
    compute: Callable = None               # fn(ctx: ResourceCtx) -> Any  (PURE)
    version: str = "1"                     # bumping cold-starts this resource

class ResourceCtx:                         # what compute() sees
    window: pd.DataFrame | None            # the requesting close's frame (or None)
    deps: dict                             # resolved dep name -> value
    extra: dict                            # evaluation-call kwargs (e.g. h1_df)

class FeatureBus:
    def register(self, spec: ResourceSpec) -> None            # dup name -> ValueError
    def validate(self) -> None                                 # unknown dep / cycle -> ValueError
    def evaluate(self, name, symbol, tf, token, window=None, **extra) -> Any
    def stats(self) -> dict   # per resource: {"hits": int, "misses": int, "compute_ms": float}
```

- `evaluate` resolves the dep closure in topological order; each node is cached under `(name, symbol_key, token, version)` where `symbol_key` honors scope (`symbol_tf` → `(symbol, tf)`, `symbol` → symbol, `global` → None). Only the LATEST entry per `(name, symbol_key)` is kept — a new token overwrites (cache size is structurally bounded by resources × symbols × tfs; no LRU machinery needed at this scale, recorded as a deliberate simplification).
- Deps inherit the CALLER's token unless the dep declares its own via `token_of` (v15.0 keeps it simple: deps share the evaluate() token; independent-token resources are evaluated by separate evaluate() calls — `smc.bias_context` is called with the H1 token, `smc.enriched_df` with the own-bar token; neither depends on the other).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_feature_bus.py
import unittest
from src.features.feature_bus import FeatureBus, ResourceSpec

def counter_spec(name, deps=(), calls=None, value=1):
    def compute(ctx):
        calls.append(name)
        return value + sum(ctx.deps.get(d, 0) for d in deps)
    return ResourceSpec(name=name, deps=tuple(deps), compute=compute)

class TestFeatureBus(unittest.TestCase):
    def test_memo_hit_on_same_token_recompute_on_new(self):
        calls, bus = [], FeatureBus()
        bus.register(counter_spec("a", calls=calls)); bus.validate()
        v1 = bus.evaluate("a", "EURUSD", "H1", token="t1")
        v2 = bus.evaluate("a", "EURUSD", "H1", token="t1")
        self.assertEqual((v1, v2, calls), (1, 1, ["a"]))          # hit
        bus.evaluate("a", "EURUSD", "H1", token="t2")
        self.assertEqual(calls, ["a", "a"])                        # token change -> miss
        st = bus.stats()["a"]
        self.assertEqual((st["hits"], st["misses"]), (1, 2))

    def test_dep_chain_topological_and_shared(self):
        calls, bus = [], FeatureBus()
        bus.register(counter_spec("base", calls=calls, value=10))
        bus.register(counter_spec("mid", deps=("base",), calls=calls, value=1))
        bus.register(counter_spec("top", deps=("mid", "base"), calls=calls, value=0))
        bus.validate()
        v = bus.evaluate("top", "X", "M5", token="t")
        self.assertEqual(v, 0 + (1 + 10) + 10)                     # top = mid + base
        self.assertEqual(calls, ["base", "mid", "top"])            # each computed ONCE, in order

    def test_scope_symbol_vs_symbol_tf(self):
        calls, bus = [], FeatureBus()
        s = counter_spec("sym", calls=calls); s = ResourceSpec(name="sym", compute=s.compute, scope="symbol")
        bus.register(s); bus.validate()
        bus.evaluate("sym", "X", "M5", token="t")
        bus.evaluate("sym", "X", "H1", token="t")                  # same symbol, diff tf -> HIT (scope=symbol)
        self.assertEqual(len(calls), 1)

    def test_cycle_and_unknown_dep_rejected(self):
        bus = FeatureBus()
        bus.register(ResourceSpec(name="a", deps=("b",), compute=lambda c: 1))
        bus.register(ResourceSpec(name="b", deps=("a",), compute=lambda c: 1))
        with self.assertRaises(ValueError):
            bus.validate()
        bus2 = FeatureBus()
        bus2.register(ResourceSpec(name="a", deps=("nope",), compute=lambda c: 1))
        with self.assertRaises(ValueError):
            bus2.validate()

    def test_duplicate_name_and_unknown_evaluate(self):
        bus = FeatureBus()
        bus.register(ResourceSpec(name="a", compute=lambda c: 1))
        with self.assertRaises(ValueError):
            bus.register(ResourceSpec(name="a", compute=lambda c: 2))
        with self.assertRaises(KeyError):
            bus.evaluate("missing", "X", "M5", token="t")

    def test_version_bump_cold_starts(self):
        calls, bus = [], FeatureBus()
        bus.register(counter_spec("a", calls=calls)); bus.validate()
        bus.evaluate("a", "X", "M5", token="t")
        bus._registry["a"] = ResourceSpec(name="a", compute=bus._registry["a"].compute, version="2")
        bus.evaluate("a", "X", "M5", token="t")
        self.assertEqual(len(calls), 2)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure** (`ModuleNotFoundError`), **Step 3: implement** `src/features/feature_bus.py` to satisfy exactly these semantics (topological resolution via DFS with visiting-set cycle detection in `validate()`; `time.perf_counter()` around compute for `compute_ms`; `ResourceCtx` a tiny class with `window`, `deps`, `extra`). Keep it under ~120 lines; docstring states the purity contract and the latest-entry-only cache decision.

- [ ] **Step 4: Module tests pass (6/6), full suite** `Ran 222 tests ... OK`.

- [ ] **Step 5: Commit** — `feat(v15): FeatureBus core — token-keyed memoized resource DAG` (+trailer).

---

### Task 3: SMC pack

**Files:**
- Create: `src/features/packs/__init__.py` (empty), `src/features/packs/smc_pack.py`
- Test: `tests/unit/test_smc_pack.py`

**Interfaces:**
- Produces: `register_smc_pack(bus: FeatureBus) -> None`, registering:
  - `smc.enriched_df` — scope `symbol_tf`; compute: `SMCAnalyzer(ctx.window).process()`. Token at call site = the window's last bar time.
  - `smc.bias_context` — scope `symbol`; compute: `BiasEngine(ctx.extra["h1_df"]).get_bias_context()` returning the `(bias_str, liquidity)` tuple. Token at call site = the H1 frame's last bar time (so M5 closes between H1 closes are cache hits — the 12× mechanism).

- [ ] **Step 1: Failing tests** — three tests: (a) `smc.enriched_df` equals `SMCAnalyzer(df).process()` called directly (`pandas.testing.assert_frame_equal`) on a 120-bar synthetic OHLC frame; (b) `smc.bias_context` equals direct `BiasEngine(h1).get_bias_context()` on the same frame; (c) **the cache-hit pin**: evaluate `smc.bias_context` 12 times with the same H1 token → `stats()["smc.bias_context"]["misses"] == 1, hits == 11`; then once with a new token → misses == 2. Build the synthetic frame with a fixed `numpy.random.default_rng(7)` walk plus `time` column so it's deterministic.

- [ ] **Step 2-4:** fail → implement (`smc_pack.py` is ~25 lines) → module 3/3 + full suite `Ran 225 tests ... OK`.

- [ ] **Step 5: Commit** — `feat(v15): smc feature pack — enriched_df + bias_context as bus resources` (+trailer).

---

### Task 4: Controller migration (the refactor the fixture guards)

**Files:**
- Modify: `src/core/system_controller.py` (`__init__`, `_run_strategies`, `get_status_report`), `CLAUDE.md` (one sentence)

**Interfaces:**
- Consumes: FeatureBus, `register_smc_pack`.
- Produces: `self.feature_bus` on the controller; `_run_strategies` obtains `enriched_df` and `(bias_str, liq)` from the bus. Everything downstream of those two variables is byte-identical to today.

- [ ] **Step 1:** In `__init__` (next to the B0 block): create `self.feature_bus = FeatureBus()`, `register_smc_pack(self.feature_bus)`, `self.feature_bus.validate()`.
- [ ] **Step 2:** Rewrite ONLY the enrichment head of `_run_strategies` (current lines ~518-530):

```python
        h1 = self.market_data[symbol].get_data("H1")
        h1_token = str(h1.iloc[-1]['time']) if h1 is not None and len(h1) else "warmup"
        own_token = str(tf_df.iloc[-1]['time'])
        fb = getattr(self, 'feature_bus', None)
        if fb is not None:
            enriched_df = fb.evaluate('smc.enriched_df', symbol, tf, token=own_token, window=tf_df)
            bias_str, liq = fb.evaluate('smc.bias_context', symbol, tf, token=h1_token, h1_df=h1)
        else:  # __new__-built test fixtures without a bus: original inline path
            enriched_df = SMCAnalyzer(tf_df).process()
            bias_str, liq = BiasEngine(h1).get_bias_context()
```

The `ctx` dict, bias filter, grader block, and `_execute_signal` call remain UNTOUCHED (same variables feed them). Keep the existing `SMCAnalyzer`/`BiasEngine` imports (used by the fallback).
- [ ] **Step 3:** In `get_status_report`, append a `Feature cache: <n> resources, hit-rate <x>%` line from `self.feature_bus.stats()` (guarded with `getattr` like the other report fields).
- [ ] **Step 4:** CLAUDE.md architecture bullet: change "The controller enriches data via `SMCAnalyzer` + `BiasEngine`" to "The controller enriches data via the FeatureBus (`src/features/`, smc pack wrapping `SMCAnalyzer`/`BiasEngine`; HTF bias cached per H1 bar)".
- [ ] **Step 5: THE GATE** — run in order: `tests.unit.test_signal_parity` (MUST pass against the unchanged Task-1 fixture), then the full suite (`Ran 225 tests ... OK`; zero pre-existing tests modified). If parity fails: debug the bus/pack — do not touch the fixture.
- [ ] **Step 6: Commit** — `feat(v15): live signal path consumes FeatureBus; H1 bias cached per bar (parity-proven)` (+trailer).

---

### Task 5: Golden-tape fidelity (Plan-02 final-review advisory)

**Files:**
- Modify: `src/core/events.py` (SpecsUpdated fields; new WarmupSnapshot), `src/core/system_controller.py` (two insertions)
- Test: `tests/unit/test_tape_fidelity.py`

**Interfaces:**
- `SpecsUpdated` gains `tick_value: float = 0.0, tick_size: float = 0.0, vol_min: float = 0.0, vol_step: float = 0.0` (defaults keep OLD tape records parseable — pin with a test feeding a legacy dict without the new keys into `Event.from_dict`).
- New `WarmupSnapshot(symbol: str, tf: str, n_bars: int, path: str, sha256: str)` registered event.
- Controller: (a) the HISTORY-branch publish becomes `SpecsUpdated(symbol=sym, tick_value=float(msg.get('tv',0) or 0), tick_size=float(msg.get('ts',0) or 0), vol_min=float(msg.get('vm',0) or 0), vol_step=float(msg.get('vs',0) or 0))` — an in-place widening of the Task-6/P02 insertion, allowed; (b) in `run()` immediately after the ACTIVE `SystemStateChanged` publish, insert a call to a new `_snapshot_warmup()` method: for each symbol and each tf the store holds (`M5`,`M15`,`H1` via `get_data`), write non-empty frames to `data/journal/warmup/<UTC ts>/<sym>_<tf>.csv`, compute sha256 of the file bytes, publish `WarmupSnapshot`; entire method body wrapped in try/except that logs and continues (tape enrichment must never block go-live).
- Tests: legacy-dict compatibility; SpecsUpdated round-trip with values; `_snapshot_warmup` on a fixture controller with a stub store writes the CSV, publishes the event with a correct sha256 (recompute in the test), and swallows a store that raises.

- [ ] Steps: failing tests → implement → module green → full suite (**expect ~229 OK**) → commit `feat(v15): tape fidelity — spec values + warmup snapshots (replay advisory)` (+trailer).

---

### Task 6: Final verification

- [ ] **Step 1:** Full suite + parity test one final time; record counts.
- [ ] **Step 2:** Cache-efficiency smoke (include output in report): drive `_run_strategies` via the Task-1 harness pattern for 50 consecutive M5-style closes with an unchanged H1 token and assert/inspect `feature_bus.stats()` shows `smc.bias_context` misses==1 — the 12× claim, demonstrated (script inline via `python - <<EOF`, no committed file).
- [ ] **Step 3:** `git log --oneline` span listing for the ledger. No push (no remote).

---

## Definition of done (Plan 03)

1. Parity: `test_signal_parity` green against the PRE-refactor fixture, post-refactor. This is the plan's contract.
2. Suite ~229 OK; zero pre-existing tests modified.
3. Cache pin: `smc.bias_context` demonstrably computed once per H1 bar regardless of M5 close count (unit pin in T3 + smoke in T6).
4. Tape: `SpecsUpdated` carries broker numbers; warmup buffers snapshotted + journaled at ACTIVE; legacy tape records still parse.
5. Roadmap unblocked: Plan 04 (registry) builds on `src/features/`; Plan 06 (replay router) inherits a tape that can seed a warm buffer.
