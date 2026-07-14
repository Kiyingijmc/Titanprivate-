# Plan 07 — Gyroscope Gate Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Gyroscope (Kalman drift + SPRT) as a `status: research` manifest plugin and run its pre-registered 9-symbol gate study through the Plan-06 research pipeline.

**Architecture:** A pure stateful `KalmanDrift` analysis module feeds a `GyroscopeStrategy(BaseStrategy)` plugin; an `MaSlopeBaseline` sibling plugin is the beat-the-baseline reference. Two one-time parity-gated controller generalizations (manifest priority plumbing, manifest-driven HTF-bias exemption) let non-SMC strategies through the kernel. `research_run` gains MARKET fills, one-open-per-symbol resolution (via the already-validated `backtest_engine.simulate_signals`), a pooled multi-symbol mode, `--set` config overrides, per-symbol FBS spreads with a stress multiplier, and a deterministic bootstrap lower-bound. The gate dataset is frozen under `data/lake/frozen/` and loadable from a clean clone via a new `Lake.load` glob fallback.

**Tech Stack:** Python 3.11, pandas/pyarrow, stdlib `unittest` (NO pytest), stdlib `math`/`random` only for new math (no numpy in new modules).

**Spec:** `docs/superpowers/specs/2026-07-14-plan-07-gyroscope-gate-design.md` (approved + hardened, commit 0681f76).
**SDD ledger:** `.superpowers/sdd/progress.md` — append one entry per task.
**Suite baseline entering:** 337 OK (~8–13 min).

## Global Constraints

- **FROZEN, never modify:** `scripts/capture_parity_golden.py`, `tests/backtest/fixtures/*`, `tests/unit/test_signal_parity.py`. Parity must be green at the end of every task: `.venv/bin/python -m unittest tests.unit.test_signal_parity -v`.
- **Only Task 6 may diff `src/core/` or `src/strategies/manifest.py`/`registry.py`. NOTHING in this plan touches `src/execution/`.**
- **NEVER stage** (user's parallel in-flight work): `mql5_bridge/Experts/Titan_Gateway.mq5`, `scripts/check_bridge.py`, `data/specs.json`, `tests/unit/test_check_bridge_ip.py`, `docs/superpowers/plans/2026-07-12-control-gui-backend.md`, `docs/superpowers/specs/2026-07-12-control-gui-phase1-design.md`, `docs/superpowers/specs/2026-07-14-control-gui-phase1-v15-design.md`. **Stage ONLY the exact paths each task's commit step names. Never `git add -A`, `-u`, or `.`**
- Validated math is IMPORTED from `tests/backtest/backtest_engine.py` (`resolve_trade`, `simulate_signals`, `trade_dollars`, `split_trades`, `aggregate_metrics`) — never duplicated.
- Test command (run in FOREGROUND, Bash timeout 600000): `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`. Single module: `.venv/bin/python -m unittest tests.unit.test_<name> -v`.
- Commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- No git remote — never push. Never merge to `main`. Branch `feat/trade-mgmt-pipeline` is SHARED — never rebase.
- New code style: match existing modules (docstring header explaining the why, plain stdlib, no type-annotation ceremony beyond what neighbors use).

---

### Task 1: `Lake.load` frozen/ disk-glob fallback

**Files:**
- Modify: `src/data/lake.py` (the `load()` method, lines ~214-262)
- Test: `tests/unit/test_lake.py` (append new test class)

**Interfaces:**
- Consumes: existing `Lake(root)`, `LakeError`, `_FROZEN_DIR = "frozen"` module constant.
- Produces: `Lake.load(symbol, tf, broker, start, end)` now resolves `data/lake/frozen/<broker>/<symbol>/<tf>/*.parquet` by disk glob when the manifest has no entry for that key. Private helpers `Lake._load_frozen(broker, symbol, tf) -> list[pd.DataFrame]` and `Lake._combine(frames, start, end) -> pd.DataFrame`. Task 2's committed dataset and Task 8's pooled loader rely on this.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_lake.py` (mirror the file's existing tmpdir/setUp conventions; adjust only import names if they differ):

```python
class TestFrozenGlobFallback(unittest.TestCase):
    """Plan 07 / D1: frozen/ partitions are committed to git while
    manifest.json is gitignored -- load() must fall back to a disk glob
    under frozen/ so a fresh clone can load committed gate datasets."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lake_frozen_")
        self.lake = Lake(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _frame(self, times, base=1.0):
        return pd.DataFrame({
            "time": pd.to_datetime(times),
            "open": [base] * len(times), "high": [base + 1] * len(times),
            "low": [base - 1] * len(times), "close": [base] * len(times),
            "tick_volume": [1] * len(times),
        })

    def _write_frozen(self, broker, symbol, tf, year, frame):
        pdir = Path(self.tmp) / "frozen" / broker / symbol / tf
        pdir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(pdir / f"{year}.parquet", engine="pyarrow", index=False)

    def test_frozen_partition_loads_without_manifest_entry(self):
        self._write_frozen("fbs", "EURUSD", "H1", 2024,
                           self._frame(["2024-01-01 00:00", "2024-01-01 01:00"]))
        self._write_frozen("fbs", "EURUSD", "H1", 2023,
                           self._frame(["2023-06-01 05:00"]))
        df = self.lake.load("EURUSD", tf="H1", broker="fbs")
        self.assertEqual(len(df), 3)
        # chronological across year files, oldest first
        self.assertEqual(str(df["time"].iloc[0]), "2023-06-01 05:00:00")
        self.assertEqual(str(df["time"].iloc[-1]), "2024-01-01 01:00:00")

    def test_frozen_load_respects_start_end_slicing(self):
        self._write_frozen("fbs", "EURUSD", "H1", 2024,
                           self._frame(["2024-01-01 00:00", "2024-01-01 01:00",
                                        "2024-01-01 02:00"]))
        df = self.lake.load("EURUSD", tf="H1", broker="fbs",
                            start="2024-01-01 01:00", end="2024-01-01 01:00")
        self.assertEqual(len(df), 1)

    def test_manifest_path_still_wins_and_glob_miss_still_raises(self):
        # ingest() writes through the manifest path -- untouched behavior
        self.lake.ingest(self._frame(["2024-01-01 00:00"]), "GBPUSD", "H1", broker="fbs")
        df = self.lake.load("GBPUSD", tf="H1", broker="fbs")
        self.assertEqual(len(df), 1)
        # no manifest entry AND no frozen dir -> the existing clear error
        with self.assertRaises(LakeError) as ctx:
            self.lake.load("USDJPY", tf="H1", broker="fbs")
        self.assertIn("no lake partitions", str(ctx.exception))
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `.venv/bin/python -m unittest tests.unit.test_lake -v`
Expected: the two frozen tests FAIL with `LakeError: no lake partitions for fbs/EURUSD/H1` (the third may already pass — that's the regression pin).

- [ ] **Step 3: Implement** — in `src/data/lake.py`, add the two helpers right above `load()` and rewire `load()`:

```python
    def _load_frozen(self, broker: str, symbol: str, tf: str) -> list:
        """Disk-glob fallback for committed frozen datasets. frozen/ is
        deliberately manifest-less (manifest.json is gitignored while
        frozen/ parquet is committed -- P06 final-review pre-req), so a
        fresh clone can still load committed gate datasets."""
        fdir = self.root / _FROZEN_DIR / broker / symbol / tf
        frames = []
        for path in sorted(fdir.glob("*.parquet")):
            frame = pd.read_parquet(path, engine="pyarrow")
            frame["time"] = pd.to_datetime(frame["time"])
            frames.append(frame)
        return frames

    @staticmethod
    def _combine(frames, start, end) -> pd.DataFrame:
        combined = (
            pd.concat(frames, ignore_index=True)
            .sort_values("time", kind="mergesort")
            .reset_index(drop=True)
        )
        if start is not None:
            combined = combined[combined["time"] >= pd.Timestamp(start)]
        if end is not None:
            combined = combined[combined["time"] <= pd.Timestamp(end)]
        return combined.reset_index(drop=True)
```

In `load()`, replace the `if not sym_years:` block with:

```python
        if not sym_years:
            frozen = self._load_frozen(broker, symbol, tf)
            if frozen:
                return self._combine(frozen, start, end)
            existing = sorted(manifest.get(broker, {}).keys())
            raise LakeError(
                f"no lake partitions for {broker}/{symbol}/{tf}; "
                f"symbols available for broker '{broker}': {existing}"
            )
```

and replace the manifest path's inline concat/sort/slice (the `combined = (...)` block through `combined = combined.reset_index(drop=True)`) with `combined = self._combine(frames, start, end)`, keeping the `last_used` manifest update and `return combined` exactly as they are. Frozen loads do NOT touch the manifest (no `last_used` write — frozen is exempt from prune by design).

- [ ] **Step 4: Run the module test, then parity, then the full suite (foreground)**

Run: `.venv/bin/python -m unittest tests.unit.test_lake -v` → all pass.
Run: `.venv/bin/python -m unittest tests.unit.test_signal_parity -v` → OK.
Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` → 340 OK (337 + 3).

- [ ] **Step 5: Commit**

```bash
git add src/data/lake.py tests/unit/test_lake.py
git commit -m "feat(lake): frozen/ disk-glob fallback in load() — committed frozen datasets loadable from a fresh clone (P06 pre-req)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Freeze the 9-symbol H1 gate dataset (+ provenance sidecar)

**Files:**
- Create: `scripts/freeze_gate_dataset.py`
- Create (generated, committed): `data/lake/frozen/fbs/<SYM>/H1/<year>.parquet` for the 9 symbols, `data/lake/frozen/PROVENANCE.md`

**Interfaces:**
- Consumes: `scripts/lake_import.py::sniff_and_read`, `src/research/kernel_replay.py::load_h1_from_m5` (the validated resampler), Task 1's frozen glob fallback (for verification).
- Produces: the pinned gate universe — `EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, BTCUSD` (SilverBullet's validated `pairs` from `config/config.yaml`, for cross-strategy comparability) — as frozen H1 parquet Tasks 8/10 load via `--lake-symbols`.

No unit test (data + generation script); verification steps below stand in.

- [ ] **Step 1: Write the freeze script**

```python
#!/usr/bin/env python3
# scripts/freeze_gate_dataset.py
"""Freeze the Plan-07 Gyroscope gate dataset: 9 symbols' data/history/
<SYM>_M5.csv -> H1 via load_h1_from_m5 (the validated resampler, pinned
byte-identical to backtest_engine.h1_df by tests/unit/test_kernel_replay.py)
-> year-partitioned parquet under data/lake/frozen/fbs/<SYM>/H1/ plus a
PROVENANCE.md sidecar (source sha256, rows, ranges) so the committed,
manifest-less dataset stays auditable from a fresh clone (spec hardening #6a).

Idempotent: re-running overwrites the same partitions deterministically.
"""
import hashlib
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from lake_import import sniff_and_read  # noqa: E402
from src.research.kernel_replay import load_h1_from_m5  # noqa: E402

# The validated SilverBullet universe (config.yaml strategies.silver_bullet.pairs);
# GBPCAD/XBRUSD stay excluded (cost-excluded in the SB stop study).
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
           "GBPJPY", "XAUUSD", "US30", "BTCUSD"]
FROZEN_ROOT = Path(REPO_ROOT) / "data" / "lake" / "frozen"


def main() -> int:
    lines = [
        "# Frozen gate dataset provenance (Plan 07 — Gyroscope gate)",
        "",
        "Generated by scripts/freeze_gate_dataset.py. Source: data/history/<SYM>_M5.csv",
        "(FBS bridge export, ~2023-06..2026-06), resampled H1 with",
        "src.research.kernel_replay.load_h1_from_m5. Loadable WITHOUT the gitignored",
        "lake manifest via Lake.load()'s frozen/ glob fallback.",
        "",
        "| symbol | year | h1_rows | first | last | source_csv_sha256 |",
        "|---|---|---|---|---|---|",
    ]
    for sym in SYMBOLS:
        src = Path(REPO_ROOT) / "data" / "history" / f"{sym}_M5.csv"
        if not src.exists():
            print(f"[FREEZE] ERROR: missing {src}")
            return 1
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        raw = sniff_and_read(str(src))
        if "tick_volume" not in raw.columns:
            raw["tick_volume"] = raw["volume"] if "volume" in raw.columns else 1
        h1 = load_h1_from_m5(raw)
        h1["time"] = pd.to_datetime(h1["time"])
        outdir = FROZEN_ROOT / "fbs" / sym / "H1"
        outdir.mkdir(parents=True, exist_ok=True)
        for year, group in h1.groupby(h1["time"].dt.year):
            group = group.reset_index(drop=True)
            group.to_parquet(outdir / f"{int(year)}.parquet", engine="pyarrow", index=False)
            lines.append(
                f"| {sym} | {int(year)} | {len(group)} | {group['time'].iloc[0]} "
                f"| {group['time'].iloc[-1]} | {sha} |"
            )
        print(f"[FREEZE] {sym}: {len(h1)} H1 rows -> {outdir}")
    (FROZEN_ROOT / "PROVENANCE.md").write_text("\n".join(lines) + "\n")
    print(f"[FREEZE] wrote {FROZEN_ROOT / 'PROVENANCE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it** — `.venv/bin/python scripts/freeze_gate_dataset.py`
Expected: 9 `[FREEZE] <SYM>: ~18000-26000 H1 rows` lines + the PROVENANCE line, exit 0.

- [ ] **Step 3: Verify loadability through the Task-1 fallback** (this is the acceptance check):

```bash
.venv/bin/python - <<'EOF'
from src.data.lake import Lake
lake = Lake("data/lake")
for sym in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY", "XAUUSD", "US30", "BTCUSD"]:
    df = Lake("data/lake")._load_frozen("fbs", sym, "H1") and lake.load(sym, tf="H1", broker="fbs")
    print(sym, len(df), df["time"].iloc[0], "->", df["time"].iloc[-1])
EOF
```

CAUTION: if the local (gitignored) lake manifest already has `fbs/<SYM>/H1` entries from earlier imports, `load()` will serve the manifest path, not frozen. That is correct precedence; for the verification, additionally check the frozen dir directly: `find data/lake/frozen/fbs -name '*.parquet' | wc -l` → expect ~36 (9 symbols × ~4 years).

- [ ] **Step 4: Confirm git sees ONLY frozen files + script** — `git status --short` must show `?? data/lake/frozen/` content and `?? scripts/freeze_gate_dataset.py` (plus the pre-existing user files, which stay unstaged). `.gitignore` already whitelists `!data/lake/frozen/**`.

- [ ] **Step 5: Full suite (unchanged code, sanity)** — `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` → 340 OK.

- [ ] **Step 6: Commit**

```bash
git add scripts/freeze_gate_dataset.py data/lake/frozen/
git commit -m "data(plan07): freeze 9-symbol H1 gate dataset + provenance sidecar

SB-universe symbols (EURUSD..BTCUSD), M5->H1 via load_h1_from_m5, year
partitions under data/lake/frozen/fbs/, PROVENANCE.md pins source sha256s.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `KalmanDrift` — filter + SPRT + NIS integrity monitor

**Files:**
- Create: `src/analysis/kalman_drift.py`
- Test: `tests/unit/test_kalman_drift.py`

**Interfaces:**
- Consumes: stdlib only (`math`, `collections.deque`, `dataclasses`).
- Produces: `KalmanDrift(warmup_bars=200, q_atr_frac=0.05, r_frac=1.0, alpha=0.05, beta=0.20, delta=0.40, nis_window=50, nis_z=2.576)` with `.update(log_close: float, atr: float) -> Reading` and attributes `.A`, `.B`, `.suspended`, `.n`. `Reading` frozen dataclass with fields `level, velocity, S, sqrt_S_price, nis, nis_mean, lam_long, lam_short, crossed, state` where `crossed ∈ {"LONG","SHORT",""}` and `state ∈ {"WARMUP","OBSERVE","SUSPENDED"}`. Task 4 constructs one per symbol and reads `.crossed`, `.state`, `.sqrt_S_price`.

Design notes the implementer must preserve (from the approved spec §5.1 and blueprint §14.2):
- SPRT runs on the **whitened innovation** `u = ε/√S`, so it detects drift the filter has *not yet absorbed* — i.e., drift **onsets**. On a series that drifts from bar 1, the filter converges during warmup and the SPRT correctly stays quiet; tests must therefore use flat-then-drift series.
- Wald boundaries: `A = ln((1−β)/α) ≈ 2.7726` at defaults, `B = ln(β/(1−α)) ≈ −1.5581`. A test reaching `B` resets to 0 (restart accumulation). A crossing resets **both** Λ to 0 (one decision at a time; strategy owns the cooldown).
- NIS band on the rolling mean of `ε²/S` over `nis_window` bars: mean of W iid χ²₁ has mean 1, variance 2/W → band `1 ± nis_z·√(2/W)` (nis_z=2.576 ≈ 99% two-sided — pre-registered). Violation ⇒ `SUSPENDED`, Λs zeroed, NIS window cleared (re-warm: a fresh full in-band window resumes).
- No wall-clock, no randomness, no numpy — pure deterministic stdlib math.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_kalman_drift.py
# Plan 07 / Task 3: KalmanDrift filter + SPRT + NIS on synthetic series.
# Deterministic: seeded random.Random for noise; no market data.
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.kalman_drift import KalmanDrift, Reading

ATR = 0.002  # constant synthetic ATR (price units around price ~ e^0 = 1.0)


def _noise(n, sigma, seed=42):
    rng = random.Random(seed)
    return [rng.gauss(0.0, sigma) for _ in range(n)]


def _feed(filt, log_prices):
    readings = []
    for y in log_prices:
        readings.append(filt.update(y, ATR))
    return readings


class TestKalmanFilterCore(unittest.TestCase):
    def test_boundaries_match_wald_formulas(self):
        f = KalmanDrift(alpha=0.05, beta=0.20)
        self.assertAlmostEqual(f.A, math.log(0.95 / 0.05), places=9)
        self.assertAlmostEqual(f.B, math.log(0.20 / 0.95), places=9)

    def test_velocity_recovers_known_drift_after_onset(self):
        # 250 flat noisy bars, then 300 bars of +0.0015/bar drift: the
        # filtered velocity must approach the true drift.
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        noise = _noise(550, 0.0005)
        ys = []
        level = 0.0
        for i in range(550):
            if i >= 250:
                level += 0.0015
            ys.append(level + noise[i])
        readings = _feed(f, ys)
        self.assertAlmostEqual(readings[-1].velocity, 0.0015, delta=0.0008)

    def test_first_reading_initializes_warmup(self):
        f = KalmanDrift(warmup_bars=10)
        r = f.update(0.0, ATR)
        self.assertIsInstance(r, Reading)
        self.assertEqual(r.state, "WARMUP")
        self.assertEqual(r.crossed, "")
        self.assertEqual(r.velocity, 0.0)


class TestSprtLayer(unittest.TestCase):
    def test_pure_noise_rarely_crosses(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        ys, level = [], 0.0
        for step in _noise(2000, 0.0005, seed=7):
            level += step * 0.0  # zero drift; iid noise around 0
            ys.append(step)
        crossings = sum(1 for r in _feed(f, ys) if r.crossed)
        self.assertLessEqual(crossings, 8)  # generous; alpha budget is per SPRT run

    def test_drift_onset_crosses_long_within_window(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        noise = _noise(400, 0.0005, seed=3)
        ys, level = [], 0.0
        for i in range(400):
            if i >= 300:
                level += 0.0015
            ys.append(level + noise[i])
        readings = _feed(f, ys)
        onset_crossings = [i for i, r in enumerate(readings) if r.crossed == "LONG"]
        self.assertTrue(any(300 <= i <= 360 for i in onset_crossings),
                        f"no LONG crossing within 60 bars of onset: {onset_crossings}")

    def test_crossing_resets_both_lambdas(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        noise = _noise(400, 0.0005, seed=3)
        ys, level = [], 0.0
        for i in range(400):
            if i >= 300:
                level += 0.0015
            ys.append(level + noise[i])
        for r in _feed(f, ys):
            if r.crossed:
                self.assertEqual(r.lam_long, 0.0)
                self.assertEqual(r.lam_short, 0.0)
                break
        else:
            self.fail("no crossing observed")

    def test_short_mirror_crosses_on_negative_drift(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        noise = _noise(400, 0.0005, seed=5)
        ys, level = [], 0.0
        for i in range(400):
            if i >= 300:
                level -= 0.0015
            ys.append(level + noise[i])
        crossings = [r.crossed for r in _feed(f, ys) if r.crossed]
        self.assertIn("SHORT", crossings)


class TestNisIntegrityMonitor(unittest.TestCase):
    def test_vol_regime_jump_suspends(self):
        # sigma x10 after bar 300: NIS (based on the slowly-adapting R)
        # blows the chi^2 band -> SUSPENDED within ~2 windows.
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        ys = _noise(300, 0.0005, seed=11) + _noise(150, 0.005, seed=12)
        readings = _feed(f, ys)
        states = [r.state for r in readings[300:]]
        self.assertIn("SUSPENDED", states)

    def test_no_crossings_while_suspended(self):
        f = KalmanDrift(warmup_bars=60, nis_window=50)
        ys = _noise(300, 0.0005, seed=11) + _noise(150, 0.005, seed=12)
        for r in _feed(f, ys):
            if r.state == "SUSPENDED":
                self.assertEqual(r.crossed, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m unittest tests.unit.test_kalman_drift -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'src.analysis.kalman_drift'`.

- [ ] **Step 3: Implement `src/analysis/kalman_drift.py`** (complete file):

```python
"""KalmanDrift: 2-state Kalman filter (level, velocity) on log-price with a
Wald SPRT decision layer and an NIS (chi-square) integrity monitor.

Blueprint: docs/research/2026-07-12-novel-arsenal-brainstorm.md sections 1
and 14.2. Pure deterministic stdlib math -- no I/O, no wall-clock, no
randomness, no numpy. One instance per symbol, fed exactly once per closed
H1 bar via update(log_close, atr); the SPRT statistic accumulates across
bars, which is why this object is stateful rather than recompute-per-window.

Noise adaptation (asset-agnostic, no per-symbol constants):
  R (measurement) = rolling variance of 1-bar log returns * r_frac
  Q (process)     = constant-velocity discretization scaled by
                    (q_atr_frac * ATR/price)^2
Integrity: rolling mean of NIS = eps^2/S over nis_window bars must sit in
1 +/- nis_z*sqrt(2/W) (mean of W iid chi^2_1 draws); sustained violation =>
SUSPENDED (no SPRT decisions), window cleared, auto-resume on a fresh clean
window. SPRT on whitened innovations u = eps/sqrt(S): unit variance by
construction, so the log-likelihood ratio increment for drift delta (in
whitened units) is delta*u - delta^2/2.
"""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Reading:
    level: float          # filtered log-price
    velocity: float       # filtered drift per bar (log units)
    S: float              # innovation variance (log units^2)
    sqrt_S_price: float   # 1-sigma price-space uncertainty at this level
    nis: float            # this bar's eps^2/S
    nis_mean: float       # rolling NIS mean (1.0 until the window fills)
    lam_long: float       # SPRT statistic, long test
    lam_short: float      # SPRT statistic, short test
    crossed: str          # "LONG" | "SHORT" | "" (no boundary crossing)
    state: str            # "WARMUP" | "OBSERVE" | "SUSPENDED"


def _variance(values) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / (n - 1)


class KalmanDrift:
    def __init__(self, warmup_bars=200, q_atr_frac=0.05, r_frac=1.0,
                 alpha=0.05, beta=0.20, delta=0.40, nis_window=50,
                 nis_z=2.576):
        self.warmup_bars = int(warmup_bars)
        self.q_atr_frac = float(q_atr_frac)
        self.r_frac = float(r_frac)
        self.delta = float(delta)
        self.nis_window = int(nis_window)
        self.A = math.log((1.0 - float(beta)) / float(alpha))
        self.B = math.log(float(beta) / (1.0 - float(alpha)))
        band = float(nis_z) * math.sqrt(2.0 / self.nis_window)
        self.nis_lo = 1.0 - band
        self.nis_hi = 1.0 + band

        self.n = 0
        self.x = None                 # [level, velocity]
        self.P = None                 # 2x2 covariance (list of lists)
        self.lam_long = 0.0
        self.lam_short = 0.0
        self.suspended = False
        self._rets = deque(maxlen=self.nis_window)
        self._nis = deque(maxlen=self.nis_window)
        self._prev_y = None

    def update(self, log_close, atr) -> Reading:
        y = float(log_close)
        self.n += 1

        if self.x is None:
            self.x = [y, 0.0]
            self.P = [[1e-4, 0.0], [0.0, 1e-8]]
            self._prev_y = y
            return Reading(level=y, velocity=0.0, S=1e-4,
                           sqrt_S_price=math.sqrt(1e-4) * math.exp(y),
                           nis=0.0, nis_mean=1.0, lam_long=0.0,
                           lam_short=0.0, crossed="", state="WARMUP")

        self._rets.append(y - self._prev_y)
        self._prev_y = y

        R = max(_variance(self._rets) * self.r_frac, 1e-12)
        price = math.exp(self.x[0])
        atr_log = (float(atr) / price) if price > 0 else 0.0
        q = (self.q_atr_frac * atr_log) ** 2
        # constant-velocity process noise, dt=1: q * [[1/3, 1/2], [1/2, 1]]

        # Predict: F = [[1, 1], [0, 1]]
        x0 = self.x[0] + self.x[1]
        x1 = self.x[1]
        p00 = self.P[0][0] + self.P[1][0] + self.P[0][1] + self.P[1][1] + q / 3.0
        p01 = self.P[0][1] + self.P[1][1] + q / 2.0
        p10 = self.P[1][0] + self.P[1][1] + q / 2.0
        p11 = self.P[1][1] + q

        # Innovate: H = [1, 0]
        eps = y - x0
        S = p00 + R

        # Update
        k0 = p00 / S
        k1 = p10 / S
        x0 += k0 * eps
        x1 += k1 * eps
        self.x = [x0, x1]
        self.P = [[(1.0 - k0) * p00, (1.0 - k0) * p01],
                  [p10 - k1 * p00, p11 - k1 * p01]]

        nis = (eps * eps) / S if S > 0 else 0.0
        self._nis.append(nis)
        window_full = len(self._nis) == self.nis_window
        nis_mean = (sum(self._nis) / len(self._nis)) if window_full else 1.0

        # Integrity monitor (checked BEFORE the SPRT so a violated model
        # never produces a decision this bar).
        if window_full and not (self.nis_lo <= nis_mean <= self.nis_hi):
            if not self.suspended:
                self.suspended = True
                self.lam_long = 0.0
                self.lam_short = 0.0
            self._nis.clear()  # re-warm: demand a fresh, fully clean window
        elif self.suspended and window_full:
            self.suspended = False

        warmed = self.n >= self.warmup_bars
        crossed = ""
        if warmed and not self.suspended:
            u = eps / math.sqrt(S)
            d = self.delta
            self.lam_long += d * u - 0.5 * d * d
            self.lam_short += -d * u - 0.5 * d * d
            if self.lam_long <= self.B:
                self.lam_long = 0.0
            if self.lam_short <= self.B:
                self.lam_short = 0.0
            if self.lam_long >= self.A:
                crossed = "LONG"
            elif self.lam_short >= self.A:
                crossed = "SHORT"
            if crossed:
                self.lam_long = 0.0
                self.lam_short = 0.0

        state = "SUSPENDED" if self.suspended else ("OBSERVE" if warmed else "WARMUP")
        return Reading(level=x0, velocity=x1, S=S,
                       sqrt_S_price=math.sqrt(S) * math.exp(x0),
                       nis=nis, nis_mean=nis_mean,
                       lam_long=self.lam_long, lam_short=self.lam_short,
                       crossed=crossed, state=state)
```

- [ ] **Step 4: Run the module tests** — `.venv/bin/python -m unittest tests.unit.test_kalman_drift -v` → all pass. If a synthetic-series assertion misses its window, widen the drift segment or the assertion window — do NOT loosen α/β/δ or the band constant (they are pre-registered).

- [ ] **Step 5: Parity + full suite (foreground)** — parity OK; discover → 340 + ~8 = ~348 OK (trust actual arithmetic; record the real count in the ledger).

- [ ] **Step 6: Commit**

```bash
git add src/analysis/kalman_drift.py tests/unit/test_kalman_drift.py
git commit -m "feat(analysis): KalmanDrift — Kalman level/velocity filter + Wald SPRT + NIS integrity monitor (arsenal #1 core math)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `GyroscopeStrategy` plugin + manifest + config block

**Files:**
- Create: `src/analysis/atr_simple.py`
- Create: `src/strategies/models/gyroscope.py`
- Create: `config/manifests/gyroscope.yaml`
- Modify: `config/config.yaml` (append to the `strategies:` block)
- Test: `tests/unit/test_gyroscope_strategy.py`

**Interfaces:**
- Consumes: Task 3's `KalmanDrift`/`Reading`; `BaseStrategy.__init__(name, config, logger)` / `.validate_data(df, min_length, check_smc=False)`; registry instantiation contract `cls(params, logger)`.
- Produces: `GyroscopeStrategy(config, logger)` with `timeframe='H1'`, `on_new_candle(df, context) -> dict|None` returning `{signal:'BUY'|'SELL', type:'MARKET', price, sl, tp}`; `last_atr(df, period=14) -> float` in `atr_simple` (Task 5 reuses it). Manifest id `gyroscope` (status `research`, priority 60). NOTE: `honors_htf_bias: false` is added to this manifest in **Task 6** (the field doesn't exist yet — do not add it here).

Design constraints (spec §5.2):
- Strategy computes its **own** ATR via `last_atr` — never reads the SMC `ATR` column, so it is genuinely independent of enrichment.
- Carried state per symbol: `KalmanDrift`, last-seen bar timestamp string (idempotency guard), cooldown counter. First sight of a symbol bootstraps the filter from the whole window (oldest→newest); afterwards only strictly-newer bars are fed. A duplicate window is a no-op returning `None`. Only a crossing on the **newest** bar may signal (bootstrap crossings are historical — never traded).
- `enabled: true` in config + `status: research` in the manifest. **Deliberate deviation from blueprint §14.5's `enabled: false`:** the v15 registry is the actual live gate (`activate_eligible` skips research status; `/enable gyroscope confirm` is the guarded operator override), while `enabled: false` would set `BaseStrategy.active=False` and vacuously kill the offline gate replay too. Record this deviation in the ledger.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_gyroscope_strategy.py
# Plan 07 / Task 4: decision-dict contract, idempotency, cooldown, gating.
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from src.strategies.models.gyroscope import GyroscopeStrategy
from src.analysis.atr_simple import last_atr

CFG = {
    "enabled": True, "timeframe": "H1",
    "warmup_bars": 60, "q_atr_frac": 0.05, "r_frac": 1.0,
    "sprt": {"alpha": 0.05, "beta": 0.20, "delta": 0.40},
    "nis_window": 50, "k_sl": 3.0, "sl_atr_floor": 0.8,
    "rr_target": 2.0, "max_bars_in_trade": 48,
    "reentry_lockout": 5, "max_spread_atr_frac": 0.10,
}


class _NullLogger:
    def log_event(self, *a, **k):
        pass


def _bars(closes, start="2026-01-01 00:00:00"):
    t0 = pd.Timestamp(start)
    rows = []
    for k, c in enumerate(closes):
        rows.append({"time": str(t0 + pd.Timedelta(hours=k)),
                     "open": c, "high": c + 0.0008, "low": c - 0.0008, "close": c})
    return pd.DataFrame(rows)


def _drift_series(n_flat=300, n_drift=80, step=0.0015, seed=3):
    import random
    rng = random.Random(seed)
    closes, level = [], 0.0
    for i in range(n_flat + n_drift):
        if i >= n_flat:
            level += step
        closes.append(1.0 + level + rng.gauss(0.0, 0.0005))
    return closes


def _run(strat, df, ctx=None):
    return asyncio.run(strat.on_new_candle(df, context=ctx or {"symbol": "EURUSD"}))


class TestAtrSimple(unittest.TestCase):
    def test_last_atr_is_mean_true_range(self):
        df = _bars([1.0, 1.0, 1.0])
        # TR per bar = max(high-low, |high-prev_close|, |low-prev_close|) = 0.0016
        self.assertAlmostEqual(last_atr(df, period=14), 0.0016, places=6)

    def test_too_short_returns_zero(self):
        self.assertEqual(last_atr(_bars([1.0])), 0.0)


class TestGyroscopeContract(unittest.TestCase):
    def test_below_warmup_returns_none(self):
        strat = GyroscopeStrategy(CFG, _NullLogger())
        self.assertIsNone(_run(strat, _bars([1.0] * 30)))

    def test_no_time_column_returns_none(self):
        strat = GyroscopeStrategy(CFG, _NullLogger())
        df = _bars([1.0] * 80).drop(columns=["time"])
        self.assertIsNone(_run(strat, df))

    def test_drift_onset_emits_market_buy_with_coherent_levels(self):
        closes = _drift_series()
        strat = GyroscopeStrategy(CFG, _NullLogger())
        decision = None
        # Feed growing windows one bar at a time, like replay does.
        for end in range(60, len(closes) + 1):
            d = _run(strat, _bars(closes[:end]))
            if d is not None:
                decision = d
                break
        self.assertIsNotNone(decision, "drift onset never produced a signal")
        self.assertEqual(decision["signal"], "BUY")
        self.assertEqual(decision["type"], "MARKET")
        self.assertLess(decision["sl"], decision["price"])
        self.assertGreater(decision["tp"], decision["price"])
        # rr_target geometry
        risk = decision["price"] - decision["sl"]
        self.assertAlmostEqual(decision["tp"] - decision["price"], 2.0 * risk, places=9)
        # sl_atr_floor: risk never tighter than 0.8 * ATR
        # (ATR of the synthetic bars is ~0.0016-0.003)
        self.assertGreater(risk, 0.8 * 0.0010)

    def test_duplicate_window_is_noop(self):
        closes = _drift_series()
        strat = GyroscopeStrategy(CFG, _NullLogger())
        first = None
        for end in range(60, len(closes) + 1):
            df = _bars(closes[:end])
            d = _run(strat, df)
            if d is not None:
                first = (df, d)
                break
        self.assertIsNotNone(first)
        df, _ = first
        self.assertIsNone(_run(strat, df), "same window re-fed must be a no-op")

    def test_cooldown_blocks_reentry_for_lockout_bars(self):
        closes = _drift_series(n_drift=200)  # long drift: crossings keep coming
        strat = GyroscopeStrategy(CFG, _NullLogger())
        signal_ends = []
        for end in range(60, len(closes) + 1):
            if _run(strat, _bars(closes[:end])) is not None:
                signal_ends.append(end)
        self.assertGreaterEqual(len(signal_ends), 1)
        for a, b in zip(signal_ends, signal_ends[1:]):
            self.assertGreater(b - a, 5, "re-entry inside reentry_lockout")

    def test_wide_spread_blocks_entry(self):
        closes = _drift_series()
        strat = GyroscopeStrategy(CFG, _NullLogger())
        got_none_on_spread = False
        for end in range(60, len(closes) + 1):
            ctx = {"symbol": "EURUSD", "spread": 1.0}  # absurd spread >> 0.10*ATR
            if _run(strat, _bars(closes[:end]), ctx) is not None:
                self.fail("signal emitted despite spread screen")
            got_none_on_spread = True
        self.assertTrue(got_none_on_spread)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m unittest tests.unit.test_gyroscope_strategy -v`
Expected: `ModuleNotFoundError: No module named 'src.strategies.models.gyroscope'`.

- [ ] **Step 3: Implement `src/analysis/atr_simple.py`** (complete file):

```python
"""last_atr: simple ATR (mean of the last `period` true ranges).

Deliberately self-contained: arsenal strategies compute their own ATR from
raw OHLC instead of reading the SMC enrichment's ATR column, so they stay
independent of the smc pack (spec 5.2). Deterministic, stdlib-only.
"""


def last_atr(df, period=14) -> float:
    n = len(df)
    if n < 2:
        return 0.0
    lo = max(1, n - period)
    highs = df["high"].tolist()[lo - 1:]
    lows = df["low"].tolist()[lo - 1:]
    closes = df["close"].tolist()[lo - 1:]
    trs = []
    for i in range(1, len(highs)):
        h, l, pc = float(highs[i]), float(lows[i]), float(closes[i - 1])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return (sum(trs) / len(trs)) if trs else 0.0
```

- [ ] **Step 4: Implement `src/strategies/models/gyroscope.py`** (complete file):

```python
"""Gyroscope: Kalman drift estimator + Wald SPRT decision gate (H1).

Arsenal strategy #1 (docs/research/2026-07-12-novel-arsenal-brainstorm.md
sections 1 and 14). Consumes raw OHLC only -- no SMC columns, and no HTF
bias context: its own drift estimate IS its bias (the manifest's
honors_htf_bias: false exempts it from the controller's HTF filter, Task 6).

Emits the standard decision dict {signal, type: 'MARKET', price, sl, tp}.
Stop = k_sl * sqrt(S) in price space (the filter's own uncertainty), floored
at sl_atr_floor * ATR so it never undercuts the validated finding that tight
H1 stops die. tp = rr_target * risk (arms the existing partials ladder live).

Carried state per symbol: KalmanDrift instance, last-seen bar timestamp
(idempotency guard -- a re-fed bar is a no-op), cooldown counter. On first
sight of a symbol the whole window bootstraps the filter (mirrors live
warmup history); afterwards only strictly-newer bars are fed, and only a
crossing on the NEWEST bar may signal -- bootstrap crossings are history,
never traded.
"""
import math

from src.strategies.base_strategy import BaseStrategy
from src.analysis.kalman_drift import KalmanDrift
from src.analysis.atr_simple import last_atr


class GyroscopeStrategy(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("Gyroscope", config, logger)
        self.timeframe = str(config.get('timeframe', 'H1'))
        self.warmup_bars = int(config.get('warmup_bars', 200))
        self.q_atr_frac = float(config.get('q_atr_frac', 0.05))
        self.r_frac = float(config.get('r_frac', 1.0))
        sprt = config.get('sprt', {}) or {}
        self.alpha = float(sprt.get('alpha', 0.05))
        self.beta = float(sprt.get('beta', 0.20))
        self.delta = float(sprt.get('delta', 0.40))
        self.nis_window = int(config.get('nis_window', 50))
        self.k_sl = float(config.get('k_sl', 3.0))
        self.sl_atr_floor = float(config.get('sl_atr_floor', 0.8))
        self.rr_target = float(config.get('rr_target', 2.0))
        self.reentry_lockout = int(config.get('reentry_lockout', 5))
        self.max_spread_atr_frac = float(config.get('max_spread_atr_frac', 0.10))
        self.vol_floor = config.get('vol_floor')  # optional ATR band, absent = off
        self.vol_ceil = config.get('vol_ceil')

        self._filters = {}    # symbol -> KalmanDrift
        self._last_ts = {}    # symbol -> last fed bar's time string
        self._cooldown = {}   # symbol -> bars remaining in re-entry lockout

    def _filter_for(self, symbol):
        if symbol not in self._filters:
            self._filters[symbol] = KalmanDrift(
                warmup_bars=self.warmup_bars, q_atr_frac=self.q_atr_frac,
                r_frac=self.r_frac, alpha=self.alpha, beta=self.beta,
                delta=self.delta, nis_window=self.nis_window)
        return self._filters[symbol]

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        if not self.validate_data(df, min_length=self.warmup_bars, check_smc=False):
            return None
        if 'time' not in df.columns:
            return None  # carried-state strategy needs bar identity

        times = df['time'].astype(str).tolist()
        closes = df['close'].tolist()
        last_seen = self._last_ts.get(symbol)
        if last_seen is not None and times[-1] == last_seen:
            return None  # duplicate window: no-op

        # First index strictly newer than last_seen (0 on first sight).
        start_idx = 0
        if last_seen is not None:
            start_idx = len(times)
            for i in range(len(times) - 1, -1, -1):
                if times[i] <= last_seen:
                    start_idx = i + 1
                    break
                start_idx = i

        filt = self._filter_for(symbol)
        reading = None
        for i in range(start_idx, len(times)):
            atr_i = last_atr(df.iloc[:i + 1])
            reading = filt.update(math.log(closes[i]), atr_i)
        self._last_ts[symbol] = times[-1]
        if reading is None:
            return None

        # Cooldown ages once per newly-fed bar.
        n_new = len(times) - start_idx
        cd = max(0, self._cooldown.get(symbol, 0) - n_new)
        self._cooldown[symbol] = cd

        if reading.state != "OBSERVE" or not reading.crossed or cd > 0:
            return None

        atr = last_atr(df)
        if atr <= 0:
            return None
        if self.vol_floor is not None and atr < float(self.vol_floor):
            return None
        if self.vol_ceil is not None and atr > float(self.vol_ceil):
            return None
        spread = context.get('spread')
        if spread is not None and float(spread) > self.max_spread_atr_frac * atr:
            return None

        price = float(closes[-1])
        risk = max(self.k_sl * reading.sqrt_S_price, self.sl_atr_floor * atr)
        self._cooldown[symbol] = self.reentry_lockout
        self.log(f"{symbol} SPRT {reading.crossed} boundary crossing "
                 f"(v={reading.velocity:+.6f}, risk={risk:.5f})")
        if reading.crossed == "LONG":
            return {'signal': 'BUY', 'type': 'MARKET', 'price': price,
                    'sl': price - risk, 'tp': price + self.rr_target * risk}
        return {'signal': 'SELL', 'type': 'MARKET', 'price': price,
                'sl': price + risk, 'tp': price - self.rr_target * risk}
```

- [ ] **Step 5: Create `config/manifests/gyroscope.yaml`** (NO `honors_htf_bias` yet — Task 6 adds it):

```yaml
# config/manifests/gyroscope.yaml
id: gyroscope
version: "1.0.0"
class_path: "src.strategies.models.gyroscope:GyroscopeStrategy"
family: stat
timeframe: H1
requires: []
status: research
priority: 60
```

- [ ] **Step 6: Append to `config/config.yaml` under `strategies:`** (after the `silver_bullet:` block, before the `ops:` top-level key; match 2-space indent):

```yaml
  # 2. Gyroscope (Kalman drift + SPRT, H1) — arsenal #1, Plan 07.
  # status: research in config/manifests/gyroscope.yaml is the live gate
  # (registry never auto-activates research); enabled:true here keeps the
  # offline gate replay alive. Defaults below are the PRE-REGISTERED gate
  # values (docs/research/2026-07-14-gyroscope-gate.md) — do not tune.
  gyroscope:
    enabled: true
    timeframe: "H1"
    warmup_bars: 200
    q_atr_frac: 0.05
    r_frac: 1.0
    sprt: { alpha: 0.05, beta: 0.20, delta: 0.40 }
    nis_window: 50
    k_sl: 3.0
    sl_atr_floor: 0.8
    rr_target: 2.0
    max_bars_in_trade: 48
    reentry_lockout: 5
    max_spread_atr_frac: 0.10
    pairs: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
            "GBPJPY", "XAUUSD", "US30", "BTCUSD"]
```

- [ ] **Step 7: Run module tests** — `.venv/bin/python -m unittest tests.unit.test_gyroscope_strategy -v` → all pass.

- [ ] **Step 8: Boot-safety check** — the live boot now loads this manifest (research → LOADED, never ACTIVE). Verify registry smoke + roster unchanged:

```bash
.venv/bin/python - <<'EOF'
import yaml
from pathlib import Path
from src.strategies.manifest import load_manifests
from src.strategies.registry import StrategyRegistry

class L:
    def log_event(self, *a, **k): pass

config = yaml.safe_load(Path("config/config.yaml").read_text())
ms = load_manifests("config/manifests")
reg = StrategyRegistry(ms, config.get("strategies", {}), L())
reg.load_all(); reg.activate_eligible()
print([(r["id"], r["status"], r["state"]) for r in reg.report()])
print("active:", [s.name for s in reg.active_instances()])
EOF
```

Expected: `gyroscope` present with `('gyroscope', 'research', 'LOADED')`, `silver_bullet ... ACTIVE`, `active: ['SilverBullet']`.

- [ ] **Step 9: Parity + full suite (foreground)** — parity OK; discover → ~356 OK (record real count).

- [ ] **Step 10: Commit**

```bash
git add src/analysis/atr_simple.py src/strategies/models/gyroscope.py config/manifests/gyroscope.yaml config/config.yaml tests/unit/test_gyroscope_strategy.py
git commit -m "feat(strategies): Gyroscope plugin (research status) — KalmanDrift-driven H1 MARKET entries, filter-uncertainty stops, manifest + pre-registered config defaults

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `MaSlopeBaseline` plugin + manifest + config block

**Files:**
- Create: `src/strategies/models/ma_slope_baseline.py`
- Create: `config/manifests/ma_slope_baseline.yaml`
- Modify: `config/config.yaml` (append to `strategies:`)
- Test: `tests/unit/test_ma_slope_baseline.py`

**Interfaces:**
- Consumes: `BaseStrategy`, Task 4's `last_atr`.
- Produces: `MaSlopeBaseline(config, logger)`, manifest id `ma_slope_baseline` (status `research`, priority 90). The §14.7 "beat the baseline" reference: MARKET entry on the sign FLIP of a 24-bar SMA slope, stop = `stop_atr`·ATR(14), tp = `rr_target`·risk — identical exit model/cost pipeline as Gyroscope in the gate. `honors_htf_bias: false` added in Task 6.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ma_slope_baseline.py
# Plan 07 / Task 5: the naive competitor Gyroscope must beat (gate criterion 6).
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from src.strategies.models.ma_slope_baseline import MaSlopeBaseline

CFG = {"enabled": True, "timeframe": "H1", "ma_window": 4,
       "stop_atr": 1.0, "rr_target": 2.0}


class _NullLogger:
    def log_event(self, *a, **k):
        pass


def _bars(closes):
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    return pd.DataFrame([
        {"time": str(t0 + pd.Timedelta(hours=k)), "open": c,
         "high": c + 0.001, "low": c - 0.001, "close": c}
        for k, c in enumerate(closes)
    ])


def _run(strat, df):
    return asyncio.run(strat.on_new_candle(df, context={"symbol": "EURUSD"}))


class TestMaSlopeBaseline(unittest.TestCase):
    def test_uptrend_flip_emits_market_buy_once(self):
        strat = MaSlopeBaseline(CFG, _NullLogger())
        closes = [1.0] * 8 + [1.0 + 0.002 * k for k in range(1, 8)]
        decisions = []
        for end in range(6, len(closes) + 1):
            d = _run(strat, _bars(closes[:end]))
            if d:
                decisions.append(d)
        self.assertEqual(len(decisions), 1, "slope sign flip must fire exactly once")
        d = decisions[0]
        self.assertEqual(d["signal"], "BUY")
        self.assertEqual(d["type"], "MARKET")
        risk = d["price"] - d["sl"]
        self.assertGreater(risk, 0)
        self.assertAlmostEqual(d["tp"] - d["price"], 2.0 * risk, places=9)

    def test_downtrend_flip_emits_sell(self):
        strat = MaSlopeBaseline(CFG, _NullLogger())
        closes = [1.0] * 8 + [1.0 - 0.002 * k for k in range(1, 8)]
        decisions = [d for end in range(6, len(closes) + 1)
                     if (d := _run(strat, _bars(closes[:end])))]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["signal"], "SELL")
        self.assertGreater(decisions[0]["sl"], decisions[0]["price"])

    def test_short_window_returns_none(self):
        strat = MaSlopeBaseline(CFG, _NullLogger())
        self.assertIsNone(_run(strat, _bars([1.0, 1.0, 1.0])))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError` expected.

- [ ] **Step 3: Implement `src/strategies/models/ma_slope_baseline.py`** (complete file):

```python
"""MA-slope baseline for the Gyroscope gate (novel-arsenal 14.7 step 2):
the naive competitor Gyroscope must beat on the identical exit model and
cost pipeline (gate criterion 6). MARKET entry when the sign of the
ma_window-bar SMA slope FLIPS; stop = stop_atr * ATR(14); tp = rr_target *
risk. Memoryless apart from the previous slope sign per symbol -- this is
deliberately the dumbest defensible trend timer.
"""
from src.strategies.base_strategy import BaseStrategy
from src.analysis.atr_simple import last_atr


class MaSlopeBaseline(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("MaSlopeBaseline", config, logger)
        self.timeframe = str(config.get('timeframe', 'H1'))
        self.ma_window = int(config.get('ma_window', 24))
        self.stop_atr = float(config.get('stop_atr', 1.0))
        self.rr_target = float(config.get('rr_target', 2.0))
        self._prev_sign = {}  # symbol -> -1 | 0 | +1

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        if not self.validate_data(df, min_length=self.ma_window + 2, check_smc=False):
            return None
        closes = df['close']
        ma_now = float(closes.iloc[-self.ma_window:].mean())
        ma_prev = float(closes.iloc[-self.ma_window - 1:-1].mean())
        slope = ma_now - ma_prev
        sign = 1 if slope > 0 else (-1 if slope < 0 else 0)
        prev = self._prev_sign.get(symbol, 0)
        self._prev_sign[symbol] = sign
        if sign == 0 or sign == prev:
            return None
        atr = last_atr(df)
        if atr <= 0:
            return None
        price = float(closes.iloc[-1])
        risk = self.stop_atr * atr
        if sign > 0:
            return {'signal': 'BUY', 'type': 'MARKET', 'price': price,
                    'sl': price - risk, 'tp': price + self.rr_target * risk}
        return {'signal': 'SELL', 'type': 'MARKET', 'price': price,
                'sl': price + risk, 'tp': price - self.rr_target * risk}
```

- [ ] **Step 4: Create `config/manifests/ma_slope_baseline.yaml`:**

```yaml
# config/manifests/ma_slope_baseline.yaml
id: ma_slope_baseline
version: "1.0.0"
class_path: "src.strategies.models.ma_slope_baseline:MaSlopeBaseline"
family: stat
timeframe: H1
requires: []
status: research
priority: 90
```

- [ ] **Step 5: Append to `config/config.yaml` `strategies:`** (after the gyroscope block):

```yaml
  # 3. MA-slope baseline — Gyroscope gate criterion 6 reference ONLY.
  # Never a live candidate; stays research forever.
  ma_slope_baseline:
    enabled: true
    timeframe: "H1"
    ma_window: 24
    stop_atr: 1.0
    rr_target: 2.0
```

- [ ] **Step 6: Run module tests, registry smoke (now 3 manifests, active still `['SilverBullet']`), parity, full suite (foreground).** Expected: ~359 OK (record real count).

- [ ] **Step 7: Commit**

```bash
git add src/strategies/models/ma_slope_baseline.py config/manifests/ma_slope_baseline.yaml config/config.yaml tests/unit/test_ma_slope_baseline.py
git commit -m "feat(strategies): MaSlopeBaseline (research) — the beat-the-baseline reference for the Gyroscope gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Controller generalizations — manifest priority plumbing + HTF-bias exemption (PARITY-GATED)

**Files:**
- Modify: `src/strategies/manifest.py` (add `honors_htf_bias` field + validation)
- Modify: `src/strategies/registry.py` (tag instances in `load_all`; add `priority_of`)
- Modify: `src/core/system_controller.py` (two edits inside `_run_strategies`, lines ~669-671 and ~700 — the ONLY `src/core` diffs in this plan)
- Modify: `config/manifests/gyroscope.yaml`, `config/manifests/ma_slope_baseline.yaml` (add `honors_htf_bias: false`)
- Test: `tests/unit/test_manifest.py`, `tests/unit/test_registry.py` (append), Create: `tests/unit/test_bias_exemption.py`

**Interfaces:**
- Consumes: `StrategyManifest`, `StrategyRegistry._by_id`, `Intent(priority=...)`, `kernel_replay.replay`.
- Produces: `StrategyManifest.honors_htf_bias: bool = True`; `StrategyRegistry.priority_of(strategy_id) -> int` (manifest priority, 50 when unknown); registry-loaded instances carry `.honors_htf_bias`; the controller's bias filter honors `getattr(strat, 'honors_htf_bias', True)` and the Intent carries the manifest priority. Task 8's gate runs depend on both.

**Parity-safety invariant (spec §6.2, hardening #6b):** the SB-only parity harness has NO registry, so both lookups MUST default to today's behavior when the attribute/registry is absent — `honors_htf_bias` defaults True (filter applies), priority defaults 50. SilverBullet's manifest has `priority: 50` and omits `honors_htf_bias` → live config byte-identical → frozen fixture green.

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_manifest.py` (match its existing tmpfile-writing helpers — reuse the file's own pattern for writing a YAML and calling `load_manifest`):

```python
    def test_honors_htf_bias_defaults_true(self):
        m = self._load_yaml_manifest(VALID_YAML)  # the file's existing valid fixture
        self.assertTrue(m.honors_htf_bias)

    def test_honors_htf_bias_explicit_false(self):
        m = self._load_yaml_manifest(VALID_YAML + "\nhonors_htf_bias: false\n")
        self.assertFalse(m.honors_htf_bias)

    def test_honors_htf_bias_non_bool_rejected(self):
        with self.assertRaises(ManifestError):
            self._load_yaml_manifest(VALID_YAML + "\nhonors_htf_bias: 'yes'\n")
```

(If `test_manifest.py` has no such helper, write the YAML to a `tempfile.NamedTemporaryFile` exactly as its existing tests do — copy the neighboring test's structure verbatim.)

Append to `tests/unit/test_registry.py` (reuse its existing manifest/params fixtures):

```python
    def test_priority_of_known_and_unknown(self):
        reg = self._make_loaded_registry()  # the file's existing loaded-registry helper/pattern
        self.assertEqual(reg.priority_of("silver_bullet"), 50)
        self.assertEqual(reg.priority_of("nope"), 50)  # unknown -> Intent default

    def test_load_all_tags_instances_with_honors_htf_bias(self):
        reg = self._make_loaded_registry()
        inst = reg.instance_of("silver_bullet")
        self.assertTrue(inst.honors_htf_bias)
```

For a differing-priority assertion, add a second fake manifest (the file already has fake_strategy fixtures from P05-T3) with `priority: 60` and assert `priority_of` returns 60 for it.

Create `tests/unit/test_bias_exemption.py`:

```python
# tests/unit/test_bias_exemption.py
# Plan 07 / Task 6: manifest-driven HTF-bias exemption. An exempt strategy's
# counter-bias signal survives to submission; a bias-honoring strategy's is
# still dropped; ABSENT attribute == honoring (the parity-safety default --
# the SB parity harness has no registry and must stay filtered).
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from src.research.kernel_replay import replay

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Lenient grading floor so the bare MARKET decision executes (mirrors
# tests/unit/test_kernel_replay.py's FakeStrat config -- align with it if
# these dicts have drifted).
CONFIG = {
    "signal_grading": {"enabled": True, "min_grade": "C"},
    "arbiter": {"max_positions_per_symbol": 99, "max_total_positions": 99,
                "thesis_ttl_bars": 1},
}


class _AlwaysBuy:
    """Minimal strategy stub: unconditional BUY MARKET each close."""
    name = "AlwaysBuy"
    timeframe = "H1"
    active = True

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        c = float(df["close"].iloc[-1])
        return {"signal": "BUY", "type": "MARKET",
                "price": c, "sl": c - 0.01, "tp": c + 0.02}


def _h1():
    sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "backtest"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    from research_run import _load_csv_h1
    return _load_csv_h1(os.path.join(REPO_ROOT, "test_data.csv"), "H1")


class TestBiasExemption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h1 = _h1()

    def _counter_bias_signals(self, strat):
        records = replay(self.h1, "EURUSD", [strat], CONFIG, window=300, start=60)
        return [r for r in records
                if r["signal"] == "BUY" and r["bias"] == "BEARISH"]

    def test_exempt_strategy_counter_bias_signal_survives(self):
        strat = _AlwaysBuy()
        strat.honors_htf_bias = False
        self.assertGreater(len(self._counter_bias_signals(strat)), 0,
                           "exempt strategy was still bias-filtered")

    def test_honoring_strategy_counter_bias_signal_still_dropped(self):
        strat = _AlwaysBuy()
        strat.honors_htf_bias = True
        self.assertEqual(len(self._counter_bias_signals(strat)), 0)

    def test_absent_attribute_defaults_to_honoring(self):
        # THE parity-safety invariant: no attribute (registry-less harness,
        # e.g. the frozen SB parity fixture) == filtered, today's behavior.
        strat = _AlwaysBuy()
        self.assertEqual(len(self._counter_bias_signals(strat)), 0)


if __name__ == "__main__":
    unittest.main()
```

NOTE for the implementer: this test drives 2 full replays × 3 tests over ~800 H1 bars (~2-3 min). If `setUpClass`-level reuse of records is possible (run each variant once, share), prefer that — but keep the three assertions distinct.

- [ ] **Step 2: Run to verify failure** — manifest/registry tests fail with `AttributeError`/`TypeError` (no field/method); `test_bias_exemption` fails on `test_exempt_strategy_counter_bias_signal_survives` (BUY dropped by the unconditional filter). If test_data.csv yields ZERO BEARISH windows the exempt test would be vacuous — verify `_counter_bias_signals` sees a nonzero BEARISH count first (the golden fixture has SELL signals, so BEARISH windows exist; assert-and-proceed).

- [ ] **Step 3: Implement.** In `src/strategies/manifest.py` — add to the dataclass (after `priority: int = 50`):

```python
    honors_htf_bias: bool = True
```

In `load_manifest`, after the priority validation block:

```python
    honors_htf_bias = data.get("honors_htf_bias", True)
    if not isinstance(honors_htf_bias, bool):
        raise ManifestError(
            f"{fname}: field 'honors_htf_bias' must be a boolean, got {honors_htf_bias!r}"
        )
```

and pass `honors_htf_bias=honors_htf_bias` in the `StrategyManifest(...)` constructor call.

In `src/strategies/registry.py` — in `load_all()`, right after `self._instances[manifest.id] = instance` add:

```python
            # Tag the live instance so the controller's HTF-bias filter can
            # honor the manifest without a registry lookup on the hot path
            # (and so the registry-less parity/research harnesses default
            # to honoring via getattr(..., True)).
            instance.honors_htf_bias = manifest.honors_htf_bias
```

and add the accessor after `state_of`:

```python
    def priority_of(self, strategy_id) -> int:
        """Manifest priority for an id; 50 (the Intent default) when unknown."""
        manifest = self._by_id.get(strategy_id)
        return manifest.priority if manifest is not None else 50
```

In `src/core/system_controller.py` — EDIT 1 (~line 669), replace:

```python
                if (bias_str == "BULLISH" and decision['signal'] == "SELL") or \
                   (bias_str == "BEARISH" and decision['signal'] == "BUY"):
                    continue
```

with:

```python
                # v15.3 (Plan 07): the HTF filter is manifest-driven. Absent
                # attribute == honors (registry-less fixtures/parity harness
                # keep today's behavior); non-SMC strategies whose manifest
                # sets honors_htf_bias: false carry their own bias.
                if getattr(strat, 'honors_htf_bias', True) and (
                        (bias_str == "BULLISH" and decision['signal'] == "SELL") or
                        (bias_str == "BEARISH" and decision['signal'] == "BUY")):
                    continue
```

EDIT 2 (~line 700), replace `priority=50,` in the `Intent(...)` construction with:

```python
                    priority=(registry.priority_of(strategy_id)
                              if registry is not None else 50),
```

- [ ] **Step 4: Add `honors_htf_bias: false` to BOTH `config/manifests/gyroscope.yaml` and `config/manifests/ma_slope_baseline.yaml`** (append as the last line of each).

- [ ] **Step 5: Run the new/updated module tests** — `test_manifest`, `test_registry`, `test_bias_exemption` → all pass.

- [ ] **Step 6: PARITY GATE (the task's acceptance):**

```bash
.venv/bin/python -m unittest tests.unit.test_signal_parity -v
git diff --stat scripts/capture_parity_golden.py tests/backtest/fixtures tests/unit/test_signal_parity.py
```

Expected: parity OK; empty diff over frozen paths.

- [ ] **Step 7: Full suite (foreground)** — ~365 OK (record real count).

- [ ] **Step 8: Commit**

```bash
git add src/strategies/manifest.py src/strategies/registry.py src/core/system_controller.py config/manifests/gyroscope.yaml config/manifests/ma_slope_baseline.yaml tests/unit/test_manifest.py tests/unit/test_registry.py tests/unit/test_bias_exemption.py
git commit -m "feat(kernel): manifest priority plumbed into Intent (P05 advisory B) + manifest-driven HTF-bias exemption — parity-neutral for the live SB config, test-locked defaults

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `research_run` correctness — signal `type` threading, one-open-per-symbol, MARKET next-open fills

**Files:**
- Modify: `src/research/kernel_replay.py` (`replay()` records gain a `type` field)
- Modify: `scripts/research_run.py` (`_signals_to_trades` rewrite; `main()` wiring)
- Test: `tests/unit/test_research_run.py` (append a fast, no-kernel test class; possibly amend one existing assertion — see Step 6)

**Interfaces:**
- Consumes: `bt.simulate_signals(signals, bars)` (validated, imported — enforces one-open-per-symbol via `busy_until` and resolves via `resolve_trade`), `bt.trade_dollars`.
- Produces: `replay()` records carry `"type": decision['type']` (`None` on no-signal rows); `_signals_to_trades(records, df_h1, spread_points, spec, commission_per_lot, max_lots) -> (trades, skipped)` where `trades` are resolved rows (net-R attached) and `skipped` are `outcome="SKIPPED_BUSY"` rows; run-card gains `n_skipped_busy`; `signals.jsonl` journals BOTH (complete per-signal record). Task 8 pools `trades` across symbols.

Why (spec hardenings #1+#2): the current `_signals_to_trades` resolves EVERY signal independently (fine for SB's sparse LIMIT signals; corrupt for SPRT strategies that can fire on consecutive bars) and hardcodes `cmd:"LIMIT"` (its own docstring flags MARKET as unsupported). `simulate_signals` already implements the one-open constraint — we reuse it rather than reimplementing. MARKET fills at the NEXT bar's open (decision on close *i*, fill at *i+1* open — the look-ahead-safe convention the OTE review verified); resolution consults only `bars[bar_idx+1:]` (that is what `simulate_signals` does).

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_research_run.py` (fast — fabricated records, no kernel replay):

```python
class TestSignalsToTradesResolution(unittest.TestCase):
    """Plan 07 / Task 7: MARKET next-open fills + one-open-per-symbol
    (hardenings #1/#2). Fabricated records -- no kernel replay."""

    SPEC = {"tick_size": 1e-5, "tick_value": 1.0, "vol_step": 0.01}

    def _df(self, bars):
        return pd.DataFrame(bars)

    def _rec(self, i, signal="BUY", typ="MARKET", price=1.0, sl=0.99, tp=1.02):
        return {"i": i, "time": f"2026-01-01 {i:02d}:00:00", "bias": "BULLISH",
                "signal": signal, "price": price, "sl": sl, "tp": tp,
                "grade": "C", "strategy": "X", "type": typ}

    def _bars(self, n, open_=1.001, hi=1.001, lo=0.999, close=1.0):
        return [{"time": f"2026-01-01 {k:02d}:00:00", "open": open_, "high": hi,
                 "low": lo, "close": close} for k in range(n)]

    def test_market_fills_at_next_bar_open(self):
        bars = self._bars(10)
        bars[6]["open"] = 1.005  # the fill bar for a decision on bar 5
        bars[7]["high"] = 1.10   # then TP
        recs = [self._rec(6)]    # rec i=6 -> decided on 0-indexed bar 5
        trades, skipped = _signals_to_trades(
            recs, self._df(bars), 0.0, self.SPEC, 0.0, 5.0)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry"], 1.005)   # next open, NOT rec price
        self.assertEqual(trades[0]["cmd"], "MARKET")
        self.assertEqual(skipped, [])

    def test_limit_still_rests_at_decision_price(self):
        bars = self._bars(10)
        recs = [self._rec(6, typ="LIMIT", price=0.9995)]
        trades, _ = _signals_to_trades(recs, self._df(bars), 0.0, self.SPEC, 0.0, 5.0)
        self.assertEqual(trades[0]["entry"], 0.9995)
        self.assertEqual(trades[0]["cmd"], "LIMIT")

    def test_missing_type_defaults_to_limit(self):
        bars = self._bars(10)
        rec = self._rec(6)
        del rec["type"]
        trades, _ = _signals_to_trades([rec], self._df(bars), 0.0, self.SPEC, 0.0, 5.0)
        self.assertEqual(trades[0]["cmd"], "LIMIT")

    def test_overlapping_signal_is_skipped_busy(self):
        # First MARKET trade fills at bar 6 open and never resolves until the
        # end (no SL/TP touch) -> a second signal at i=8 arrives while busy.
        bars = self._bars(12)
        recs = [self._rec(6), self._rec(8)]
        trades, skipped = _signals_to_trades(
            recs, self._df(bars), 0.0, self.SPEC, 0.0, 5.0)
        self.assertEqual(len(trades), 1)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["outcome"], "SKIPPED_BUSY")
        self.assertFalse(skipped[0]["filled"])
        self.assertEqual(skipped[0]["i"], 8)

    def test_market_on_final_bar_is_dropped(self):
        bars = self._bars(7)
        recs = [self._rec(7)]  # decided on last bar (0-idx 6): no next open
        trades, skipped = _signals_to_trades(
            recs, self._df(bars), 0.0, self.SPEC, 0.0, 5.0)
        self.assertEqual((len(trades), len(skipped)), (0, 0))
```

Add `_signals_to_trades` to the file's existing `from research_run import ...` line (it already imports `_DEFAULT_SPEC` etc. — extend that import).

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m unittest tests.unit.test_research_run.TestSignalsToTradesResolution -v`
Expected: FAIL — current `_signals_to_trades` returns a single list (unpack error) and lacks MARKET handling.

- [ ] **Step 3: Implement.** In `src/research/kernel_replay.py::replay()`, add `"type"` to BOTH record dicts: in the captured branch add `"type": decision.get("type"),` after the `"grade"` line; in the no-signal branch add `"type": None,`. Update the docstring's field list. (`GOLDEN_FIELDS` is untouched; the centerpiece test projects onto it. If any test in `tests/unit/test_kernel_replay.py` asserts an exact record key-set, update that assertion — a sanctioned, note-in-ledger edit. `test_kernel_replay.py` is NOT frozen.)

In `scripts/research_run.py`, replace the whole `_signals_to_trades` function with:

```python
def _signals_to_trades(records, df_h1, spread_points, spec, commission_per_lot, max_lots):
    """Resolve executed signals into trades under ONE-open-per-symbol
    concurrency (tests.backtest.backtest_engine.simulate_signals -- imported,
    never reimplemented; it walks signals chronologically and skips any that
    arrive while a prior trade/limit still occupies the symbol).

    LIMIT signals rest at the decision price with the live 12-bar TTL
    (backtest_engine.py:401 convention). MARKET signals fill at the NEXT
    bar's open -- decision on bar-close i, fill at i+1 open; resolution only
    ever consults bars[bar_idx+1:], so there is no same-bar look-ahead. A
    MARKET decision on the final bar has no next open and is dropped.

    Returns (trades, skipped): `trades` are resolved rows with net R attached
    (gross R -> dollars via trade_dollars -> net R, same as before);
    `skipped` are busy-skipped signals journaled as outcome="SKIPPED_BUSY"
    (filled=False, r=0) so signals.jsonl remains a complete per-signal
    record. (A signal simulate_signals drops as INVALID -- zero risk -- also
    lands in `skipped`; with grader-passed decisions that is theoretical.)
    """
    bars = df_h1.to_dict("records")
    sigs = []
    for rec in records:
        if rec["signal"] is None:
            continue
        bar_idx = rec["i"] - 1
        cmd = rec.get("type") or "LIMIT"
        if cmd == "MARKET":
            if bar_idx + 1 >= len(bars):
                continue  # no next bar to fill on
            entry = float(bars[bar_idx + 1]["open"])
        else:
            entry = float(rec["price"])
        sigs.append({**rec, "bar_idx": bar_idx, "dir": rec["signal"], "cmd": cmd,
                     "entry": entry, "sl": float(rec["sl"]), "tp": float(rec["tp"]),
                     "ttl_bars": 12})

    resolved = bt.simulate_signals(sigs, bars)
    taken_idx = {t["bar_idx"] for t in resolved}

    trades = []
    for t in resolved:
        risk = abs(t["entry"] - t["sl"])
        dollars = bt.trade_dollars(
            t["r"], t["entry"], t["sl"], spec,
            spread_points, commission_per_lot, DEFAULT_RISK_DOLLARS, max_lots=max_lots,
        )
        net_r = (dollars["net"] / DEFAULT_RISK_DOLLARS) if DEFAULT_RISK_DOLLARS else 0.0
        trades.append({**t, "risk": risk, "gross_r": t["r"], "r": net_r})

    skipped = [{**s, "filled": False, "outcome": "SKIPPED_BUSY", "r": 0.0,
                "gross_r": 0.0, "risk": abs(s["entry"] - s["sl"])}
               for s in sigs if s["bar_idx"] not in taken_idx]
    return trades, skipped
```

In `main()`, rewire the call site:

```python
    trades, skipped = _signals_to_trades(records, df_h1, args.spread_pips, spec,
                                         commission_per_lot, max_lots)
    n_trades = sum(1 for t in trades if t["filled"])
```

add `"n_skipped_busy": len(skipped),` to the card (after `"n_trades"`), and write BOTH to the journal, chronologically:

```python
    with open(run_dir / "signals.jsonl", "w") as f:
        for t in sorted(trades + skipped, key=lambda t: t["bar_idx"]):
            f.write(json.dumps(t, default=str) + "\n")
```

- [ ] **Step 4: Run the new test class** — all pass.

- [ ] **Step 5: SilverBullet regression pin (empirical).** The golden CSV e2e must be unchanged IF none of SB's 13 signals overlap. Run the existing suite module:

`.venv/bin/python -m unittest tests.unit.test_research_run -v` (slow, ~3-5 min — foreground).

Then run the CLI once and compare against the pre-change baseline (n_signals=13, n_trades=8 per the P06-T5 ledger):

```bash
.venv/bin/python scripts/research_run.py --csv test_data.csv --symbol BTCUSD --tf H1 --strategy silver_bullet --out /tmp/claude-1000/-home-kiyingijmc-projects-Titan-ICT-Bot-v14-3pro/*/scratchpad/rr_check 2>&1 | grep RESEARCH_RUN
```

Expected: `signals=13 trades=8` and `n_skipped_busy` 0. **If n_trades differs or n_skipped_busy > 0: STOP — do not "fix" the number.** It means SB signals genuinely overlap and the one-open constraint (which matches the live arbiter) changed the SB study accounting. Report to the controller for a plan amendment pinning the new truthful value; do not proceed silently.

- [ ] **Step 6: Existing-assertion check.** `test_research_run.py:154` asserts `len(is)+len(oos) == len(signals.jsonl rows)`. With `n_skipped_busy == 0` on this dataset it stays green. If it went red in Step 5's suite run, amend it to `len(is) + len(oos) + card["n_skipped_busy"] == len(signals)` — sanctioned edit, note in ledger (only alongside the Step-5 amendment path).

- [ ] **Step 7: Parity + full suite (foreground)** — ~370 OK (record real count).

- [ ] **Step 8: Commit**

```bash
git add src/research/kernel_replay.py scripts/research_run.py tests/unit/test_research_run.py
git commit -m "feat(research): MARKET next-open fills + one-open-per-symbol trade resolution in research_run (via validated simulate_signals); replay records carry decision type; SKIPPED_BUSY journaled

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `research_run` pooled multi-symbol mode + `--set` overrides + per-symbol spreads + bootstrap CI

**Files:**
- Modify: `scripts/research_run.py`
- Test: `tests/unit/test_research_run.py` (append two classes: fast helpers + one slow pooled e2e)

**Interfaces:**
- Consumes: Task 7's `(trades, skipped)` contract; Task 1's frozen fallback via `_load_lake_h1`; `scripts/poc_sb_stops.py::SPREADS` (per-symbol FBS spread **in ticks** — the exact unit `trade_dollars(spread_points=...)` takes; `poc_sb_stops` imports cleanly, verified in this file's own header comment).
- Produces: CLI additions `--lake-symbols SYM1,SYM2,…`, `--spread-mult FLOAT`, `--set DOTTED.KEY=VALUE` (repeatable); helpers `_apply_overrides(config, overrides) -> dict`, `_pooled_split(trades, train_frac) -> (is, oos)`, `_expectancy_lower_bound(rs, n_boot=2000, seed=11, q=0.05) -> float`; pooled run-card schema (below). Tasks 9-10 invoke exactly this CLI surface.

Decisions locked here (from the approved spec):
- `--frozen-all` is dropped (YAGNI) — the gate commands list the 9 symbols explicitly.
- `--spread-pips` and `--spread-mult` are mutually exclusive; pooled mode REQUIRES `--spread-mult` (per-symbol spreads differ ~100×: EURUSD 8 ticks vs BTCUSD 1000). Single-symbol mode accepts either.
- `_pooled_split` orders by **timestamp**, not `bar_idx` — `bar_idx` collides across symbols. This is a NEW small function, not a duplicate of `split_trades` (different key, cross-symbol axis); the single-symbol path keeps `bt.split_trades` byte-identical.
- `config_hash` widens to cover `strategies.<id>` + `signal_grading` + `arbiter` (closes the recorded P06 minor: the gate's `--set signal_grading.min_grade=C` must be hash-visible). Applied overrides are ALSO recorded verbatim in the card.
- Bootstrap lower bound (gate criterion 8): deterministic `random.Random(seed)`, resampled means, 5% quantile, computed on the pooled resolved TP/SL net-R list (plus OOS-only as a diagnostic).

- [ ] **Step 1: Write the failing fast tests** (append to `tests/unit/test_research_run.py`; extend the module import line with the three new helpers):

```python
class TestPooledHelpers(unittest.TestCase):
    """Plan 07 / Task 8: pure helpers -- no kernel, no I/O."""

    def test_apply_overrides_nested_dotted_path_and_yaml_types(self):
        cfg = {"strategies": {"gyroscope": {"sprt": {"alpha": 0.05}}}}
        applied = _apply_overrides(cfg, [
            "strategies.gyroscope.sprt.alpha=0.065",
            "signal_grading.min_grade=C",
        ])
        self.assertEqual(cfg["strategies"]["gyroscope"]["sprt"]["alpha"], 0.065)
        self.assertEqual(cfg["signal_grading"]["min_grade"], "C")  # created path
        self.assertEqual(applied["strategies.gyroscope.sprt.alpha"], 0.065)

    def test_apply_overrides_rejects_malformed(self):
        with self.assertRaises(ValueError):
            _apply_overrides({}, ["no_equals_sign"])

    def test_pooled_split_orders_by_time_across_symbols(self):
        trades = [
            {"symbol": "A", "bar_idx": 100, "time": "2024-01-03 00:00:00", "outcome": "TP", "r": 1.0},
            {"symbol": "B", "bar_idx": 5,   "time": "2024-01-04 00:00:00", "outcome": "SL", "r": -1.0},
            {"symbol": "A", "bar_idx": 101, "time": "2024-01-01 00:00:00", "outcome": "TP", "r": 1.0},
            {"symbol": "B", "bar_idx": 6,   "time": "2024-01-02 00:00:00", "outcome": "SL", "r": -1.0},
        ]
        is_t, oos_t = _pooled_split(trades, 0.5)
        self.assertEqual([t["time"][:10] for t in is_t], ["2024-01-01", "2024-01-02"])
        self.assertEqual([t["time"][:10] for t in oos_t], ["2024-01-03", "2024-01-04"])

    def test_expectancy_lower_bound_deterministic_and_sane(self):
        rs = [0.5, 0.4, 0.6, 0.5, 0.45, 0.55] * 20  # clearly positive
        lb1 = _expectancy_lower_bound(rs)
        lb2 = _expectancy_lower_bound(rs)
        self.assertEqual(lb1, lb2)                      # fixed seed
        self.assertGreater(lb1, 0.0)
        self.assertLess(lb1, sum(rs) / len(rs))        # a LOWER bound
        self.assertEqual(_expectancy_lower_bound([]), 0.0)
        mixed = [1.0, -1.0] * 5                         # tiny n, mean 0
        self.assertLess(_expectancy_lower_bound(mixed), 0.0)
```

And the slow pooled e2e (mirrors the file's existing lake e2e fixture pattern — temp lake dir, ingest `test_data.csv` M5 twice under two symbols; ~2 replays, mark/comment as slow like its neighbors):

```python
class TestPooledEndToEnd(unittest.TestCase):
    """Pooled --lake-symbols e2e over two copies of the golden CSV. Slow
    (~2 kernel replays). Pins: pooled n_signals = 2x13, per-symbol sections,
    pooled card schema, spread table applied per symbol."""

    def test_pooled_run_card(self):
        with tempfile.TemporaryDirectory(prefix="rr_pooled_") as tmp:
            lake_root = Path(tmp) / "lake"
            out_dir = Path(tmp) / "results"
            lake = Lake(str(lake_root))
            m5 = sniff_and_read(str(Path(REPO_ROOT) / "test_data.csv"))
            if "tick_volume" not in m5.columns:
                m5["tick_volume"] = m5.get("volume", 1)
            for sym in ("EURUSD", "GBPUSD"):
                lake.ingest(m5, sym, "M5", broker="fbs")
            rc = main([
                "--lake-symbols", "EURUSD,GBPUSD", "--tf", "H1",
                "--strategy", "silver_bullet", "--spread-mult", "1.0",
                "--lake-root", str(lake_root), "--out", str(out_dir),
            ])
            self.assertEqual(rc, 0)
            run_dir = next(out_dir.iterdir())
            card = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(card["mode"], "pooled")
            self.assertEqual(card["symbols"], ["EURUSD", "GBPUSD"])
            self.assertEqual(card["n_signals"], 26)  # 13 golden signals x2
            for sym in ("EURUSD", "GBPUSD"):
                per = card["per_symbol"][sym]
                for key in ("source", "sha256", "n_bars", "n_signals", "n_trades",
                            "n_skipped_busy", "spread_points", "spec_source", "metrics"):
                    self.assertIn(key, per)
                self.assertEqual(per["n_signals"], 13)
            self.assertIn("expectancy_lower_bound", card["ci"])
            self.assertIn("is", card["metrics"])
            self.assertIn("oos", card["metrics"])
            self.assertEqual(card["spread_assumption"]["spread_mult"], 1.0)
            # per-symbol FBS spreads differ (EURUSD 8 vs GBPUSD 12 ticks)
            self.assertNotEqual(card["per_symbol"]["EURUSD"]["spread_points"],
                                card["per_symbol"]["GBPUSD"]["spread_points"])
```

(Reuse the module's existing imports for `Lake`, `sniff_and_read`, `main`, `tempfile`, `Path`, `json`, `REPO_ROOT` — most exist for the current lake e2e test; add what's missing.)

- [ ] **Step 2: Run to verify failure** — fast class fails with `ImportError` (helpers don't exist); pooled e2e fails at argparse (`--lake-symbols` unknown).

- [ ] **Step 3: Implement in `scripts/research_run.py`.** Add near the other imports: `from poc_sb_stops import SPREADS as FBS_SPREADS` (scripts dir is already on `sys.path`), and `import random`. Add the three helpers after `_build_strategy`:

```python
def _apply_overrides(config, overrides) -> dict:
    """Apply repeatable --set DOTTED.KEY=VALUE config overrides in place.
    Values parse via yaml.safe_load (0.065 -> float, C -> str, true -> bool).
    Returns {dotted_key: parsed_value} for the run-card, so every deviation
    from the on-disk config is recorded AND covered by config_hash."""
    applied = {}
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"--set expects DOTTED.KEY=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        value = yaml.safe_load(raw)
        node = config
        parts = key.split(".")
        for part in parts[:-1]:
            nxt = node.setdefault(part, {})
            if not isinstance(nxt, dict):
                raise ValueError(f"--set path {key!r}: {part!r} is not a mapping")
            node = nxt
        node[parts[-1]] = value
        applied[key] = value
    return applied


def _pooled_split(trades, train_frac):
    """Chronological IS/OOS split ACROSS symbols, keyed on the signal bar's
    timestamp. bt.split_trades keys on bar_idx, which collides across
    symbols in a pooled run -- this is a different (cross-symbol) axis, not
    a reimplementation; the single-symbol path still uses bt.split_trades
    unchanged."""
    ordered = sorted(trades, key=lambda t: str(t["time"]))
    k = int(len(ordered) * train_frac)
    return ordered[:k], ordered[k:]


def _expectancy_lower_bound(rs, n_boot=2000, seed=11, q=0.05):
    """Deterministic bootstrap lower confidence bound on mean(rs): fixed-seed
    resampled means, q-quantile. Gate criterion 8 (pre-registered,
    docs/research/2026-07-14-gyroscope-gate.md): must be > 0 for a GO."""
    if not rs:
        return 0.0
    rng = random.Random(seed)
    n = len(rs)
    means = sorted(
        sum(rng.choice(rs) for _ in range(n)) / n for _ in range(n_boot)
    )
    return means[min(n_boot - 1, max(0, int(q * n_boot)))]
```

Parser changes in `_build_parser()`: add to the existing mutually-exclusive source group `src.add_argument("--lake-symbols", help="comma-separated symbols; pooled multi-symbol gate mode (lake/frozen only)")`; make spread flags exclusive by replacing the plain `--spread-pips` add with:

```python
    cost = p.add_mutually_exclusive_group()
    cost.add_argument("--spread-pips", type=float, default=None,
                      help="absolute spread in ticks for a single-symbol run")
    cost.add_argument("--spread-mult", type=float, default=None,
                      help="multiplier on the per-symbol FBS SPREADS table "
                           "(scripts/poc_sb_stops.py); required for --lake-symbols")
    p.add_argument("--set", action="append", default=[], dest="overrides",
                   metavar="DOTTED.KEY=VALUE",
                   help="config override applied after load (repeatable)")
```

`--spread-pips` default changes `0.0` → `None`; in the single-symbol path compute `spread_points = args.spread_pips if args.spread_pips is not None else (FBS_SPREADS[symbol] * args.spread_mult if args.spread_mult is not None else 0.0)` (clean `KeyError`→error message if the symbol is missing from the table).

In `main()`, right after `config = _load_config(args.config)`:

```python
    try:
        applied_overrides = _apply_overrides(config, args.overrides)
    except ValueError as e:
        print(f"[RESEARCH_RUN] ERROR: {e}")
        return 1
```

Widen the hash (both modes):

```python
    config_hash = _sha256_bytes(json.dumps({
        "strategy_params": config.get("strategies", {}).get(args.strategy, {}),
        "signal_grading": config.get("signal_grading", {}),
        "arbiter": config.get("arbiter", {}),
    }, sort_keys=True, default=str).encode())
```

and add `"overrides": applied_overrides,` to BOTH card layouts. Then add the pooled branch — after `_build_strategy` succeeds, `if args.lake_symbols:` (checked BEFORE the `args.lake_symbol` branch):

```python
    if args.lake_symbols:
        if args.spread_mult is None:
            print("[RESEARCH_RUN] ERROR: --lake-symbols (pooled mode) requires --spread-mult")
            return 1
        symbols = [s.strip() for s in args.lake_symbols.split(",") if s.strip()]
        missing = [s for s in symbols if s not in FBS_SPREADS]
        if missing:
            print(f"[RESEARCH_RUN] ERROR: no FBS_SPREADS entry for {missing}; "
                  f"known: {sorted(FBS_SPREADS)}")
            return 1
        specs = _load_specs(args.specs)
        risk_cfg = config.get("risk", {}).get("trade", {})
        commission_per_lot = float(risk_cfg.get("static_commission_usd", 7.0))
        max_lots = float(risk_cfg.get("hard_max_lots", 5.0))

        pooled_trades, pooled_skipped, per_symbol = [], [], {}
        for sym in symbols:
            try:
                df_h1, source = _load_lake_h1(args.lake_root, args.broker, sym, args.tf)
            except LakeError as e:
                print(f"[RESEARCH_RUN] ERROR: {sym}: {e}")
                return 1
            data_sha = _sha256_bytes(df_h1.to_csv(index=False).encode())
            records = replay(df_h1, sym, [strategy], config, window=300, start=60)
            spec = specs.get(sym, _DEFAULT_SPEC)
            spec_source = args.specs if sym in specs else "default"
            spread_points = FBS_SPREADS[sym] * args.spread_mult
            trades, skipped = _signals_to_trades(
                records, df_h1, spread_points, spec, commission_per_lot, max_lots)
            for t in trades + skipped:
                t["symbol"] = sym
            pooled_trades.extend(trades)
            pooled_skipped.extend(skipped)
            per_symbol[sym] = {
                "source": source, "sha256": data_sha, "n_bars": int(len(df_h1)),
                "n_signals": sum(1 for r in records if r["signal"] is not None),
                "n_trades": sum(1 for t in trades if t["filled"]),
                "n_skipped_busy": len(skipped),
                "spread_points": spread_points,
                "tick_size": spec.get("tick_size"), "tick_value": spec.get("tick_value"),
                "vol_step": spec.get("vol_step"), "spec_source": spec_source,
                "metrics": bt.aggregate_metrics(trades),
            }
            print(f"[RESEARCH_RUN] {sym}: bars={len(df_h1)} "
                  f"signals={per_symbol[sym]['n_signals']} trades={per_symbol[sym]['n_trades']} "
                  f"spread={spread_points:.0f}t")

        is_trades, oos_trades = _pooled_split(pooled_trades, args.split)
        metrics_is = bt.aggregate_metrics(is_trades)
        metrics_oos = bt.aggregate_metrics(oos_trades)
        resolved_net = [t["r"] for t in pooled_trades if t["outcome"] in ("TP", "SL")]
        oos_net = [t["r"] for t in oos_trades if t["outcome"] in ("TP", "SL")]

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = Path(args.out) / f"{ts}_{args.strategy}_POOLED{len(symbols)}_{args.tf}"
        run_dir.mkdir(parents=True, exist_ok=True)
        card = {
            "git_sha": _git_sha(),
            "strategy": {"id": manifest.id, "version": manifest.version},
            "config_hash": config_hash,
            "overrides": applied_overrides,
            "mode": "pooled",
            "symbols": symbols,
            "per_symbol": per_symbol,
            "n_signals": sum(p["n_signals"] for p in per_symbol.values()),
            "n_trades": sum(p["n_trades"] for p in per_symbol.values()),
            "n_skipped_busy": len(pooled_skipped),
            "split": args.split,
            "metrics": {"is": metrics_is, "oos": metrics_oos},
            "ci": {
                "expectancy_lower_bound": _expectancy_lower_bound(resolved_net),
                "expectancy_lower_bound_oos": _expectancy_lower_bound(oos_net),
                "method": "bootstrap(seed=11, n_boot=2000, q=0.05)",
            },
            "spread_assumption": {
                "cost_model": "trade_dollars", "spread_mult": args.spread_mult,
                "spread_table": "scripts/poc_sb_stops.SPREADS",
                "commission_per_lot": commission_per_lot,
                "risk_dollars": DEFAULT_RISK_DOLLARS, "max_lots": max_lots,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir / "run.json").write_text(json.dumps(card, indent=2, sort_keys=True))
        with open(run_dir / "signals.jsonl", "w") as f:
            for t in sorted(pooled_trades + pooled_skipped,
                            key=lambda t: (str(t["time"]), t["symbol"])):
                f.write(json.dumps(t, default=str) + "\n")
        _print_pooled_report(card, run_dir)
        return 0
```

with the report printer next to `_print_report`:

```python
def _print_pooled_report(card, run_dir):
    print(f"[RESEARCH_RUN] POOLED strategy={card['strategy']['id']} "
          f"v{card['strategy']['version']} symbols={len(card['symbols'])} "
          f"signals={card['n_signals']} trades={card['n_trades']} "
          f"skipped_busy={card['n_skipped_busy']}")
    for split_name in ("is", "oos"):
        m = card["metrics"][split_name]
        print(f"[RESEARCH_RUN] {split_name.upper():3} n={m['trades']:4d} "
              f"exp={m['expectancy']:+.3f}R totR={m['total_r']:+7.1f} "
              f"PF={m['profit_factor']:.2f} maxDD={m['max_drawdown_r']:.1f}R")
    ci = card["ci"]
    print(f"[RESEARCH_RUN] CI  expectancy_lb={ci['expectancy_lower_bound']:+.4f}R "
          f"(oos {ci['expectancy_lower_bound_oos']:+.4f}R) {ci['method']}")
    nonneg = sum(1 for p in card["per_symbol"].values()
                 if p["metrics"]["total_r"] >= 0)
    print(f"[RESEARCH_RUN] symbols non-negative: {nonneg}/{len(card['symbols'])}")
    print(f"[RESEARCH_RUN] wrote {run_dir}/run.json + signals.jsonl")
```

Also update the single-symbol path's spec_source line to use `args.specs` instead of the hardcoded `"data/specs.json"` string (closes the recorded P06 one-word minor).

- [ ] **Step 4: Run the fast helper tests** — pass. **Step 5:** run the pooled e2e — pass (slow). **Step 6:** re-run the whole `test_research_run` module (regressions: single-symbol path with `--spread-pips` unchanged; existing cards keep their keys).

- [ ] **Step 7: Parity + full suite (foreground)** — ~376 OK (record real count).

- [ ] **Step 8: Commit**

```bash
git add scripts/research_run.py tests/unit/test_research_run.py
git commit -m "feat(research): pooled multi-symbol gate mode (--lake-symbols), --set config overrides, per-symbol FBS spreads with --spread-mult stress, deterministic bootstrap expectancy lower bound; config_hash widened to grading+arbiter

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Pre-registered gate doc (written BEFORE any gate run)

**Files:**
- Create: `docs/research/2026-07-14-gyroscope-gate.md`
- Create: `scripts/run_gyroscope_gate.sh`

**Interfaces:**
- Consumes: Task 8's exact CLI surface; Task 2's PROVENANCE.md.
- Produces: the frozen thresholds Task 10's verdict is judged against. **Committing this doc BEFORE the first pooled run is the pre-registration** — the commit timestamp is the proof.

- [ ] **Step 1: Write `docs/research/2026-07-14-gyroscope-gate.md`** (complete content — copy verbatim, fill nothing in later except the sha256 line from PROVENANCE.md):

```markdown
# Gyroscope Gate — Pre-Registered Study (Plan 07)

Registered BEFORE the first gate run (see this file's git commit vs the
run-cards' timestamps). Strategy: `gyroscope` v1.0.0 (Kalman drift + SPRT,
H1 MARKET), status research. Baseline: `ma_slope_baseline` v1.0.0.

## Dataset (frozen)

- 9 symbols (the validated SilverBullet universe; GBPCAD/XBRUSD stay
  cost-excluded): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD,
  US30, BTCUSD.
- `data/lake/frozen/fbs/<SYM>/H1/*.parquet`, ~3 years (2023-06..2026-06),
  M5→H1 via `load_h1_from_m5`. Provenance + source sha256:
  `data/lake/frozen/PROVENANCE.md` (commit <FILL: short sha of the Task-2 commit>).

## Fixed inputs

- Parameters: the `strategies.gyroscope` block in `config/config.yaml` at
  this commit (α=0.05, β=0.20, δ=0.40, q_atr_frac=0.05, r_frac=1.0,
  warmup 200, nis_window 50, k_sl 3.0, sl_atr_floor 0.8, rr_target 2.0,
  reentry_lockout 5). These ARE the pre-registered values; the headline
  verdict is evaluated at these defaults ONLY.
- Cost model: `trade_dollars` (spread + $7/lot commission, broker tick
  specs), spread per symbol = `scripts/poc_sb_stops.SPREADS` ticks ×
  spread-mult. Baseline stress: spread-mult 1.5.
- Split: chronological pooled 70/30 (IS/OOS) by signal-bar timestamp.
- Grading floor: `--set signal_grading.min_grade=C` for BOTH gyroscope and
  the baseline. Rationale: the SignalGrader scores SMC confluence, which is
  meaningless-and-hostile for non-SMC strategies; C-floor disables that
  selection identically for both arms. Recorded in every run-card
  (overrides + widened config_hash). A live flip would require a
  per-strategy grading policy first (post-GO work item).
- Exit model: the rig's deterministic first-hit SL/TP resolution
  (`resolve_trade` via `simulate_signals`, one open per symbol, MARKET
  fills at next H1 open). Reverse-SPRT/time-stop live exits are built and
  unit-tested but are NOT part of this offline gate's accounting — the gate
  measures entry quality under a fixed exit, exactly like the SB/OTE
  studies.
- Spread-screen honesty: offline replay carries no live spread, so
  Gyroscope's max_spread_atr_frac entry screen passes vacuously (optimistic
  on selection); cost is applied per-symbol via trade_dollars (conservative
  on cost) and the ×1.5 stress (criterion 7) is the binding cost-robustness
  check.

## GO criteria (ALL must hold, evaluated at the defaults)

1. Pooled net expectancy ≥ +0.10 R/trade.
2. ≥ 150 pooled resolved trades.
3. ≥ 6/9 symbols with non-negative net total R.
4. OOS (final 30%) pooled net expectancy > 0.
5. ±30% one-at-a-time sweeps on (α, β, δ, q_atr_frac) — 8 runs — none
   flips the pooled net sign. FALSIFICATION ONLY: a better-looking sweep
   cell is never adopted as the result.
6. Gyroscope pooled net > MaSlopeBaseline pooled net (identical exit model,
   cost, floor, dataset).
7. ×1.5 spread stress keeps pooled net expectancy > 0.
8. Bootstrap lower confidence bound on pooled net expectancy > 0
   (deterministic: seed 11, 2000 resamples, 5% quantile — the run-card's
   ci.expectancy_lower_bound).

Diagnostics (reported, not gating): realized false-entry rate vs α on OOS
(entries stopped within reentry_lockout bars / entries); NIS-suspend
frequency; per-symbol expectancy spread.

## Commands (exactly these, scripts/run_gyroscope_gate.sh)

Defaults, stress, baseline, then the 8 sweeps — 11 pooled runs total.
Run-cards land under data/results/gyro_gate/ (gitignored; the results doc
records their sha256s).

## Advisory C (arbiter timeframe aging)

Gyroscope is H1: the arbiter `_bar_index` single-counter (P05 advisory C —
M5 closes would age H1 theses in ~60 min) is INERT for this offline study
and for any H1-only roster. It is a REQUIRED precondition before ANY live
flip of an M5-timeframe strategy, and per-tf aging must land before
Gyroscope itself flips live alongside any M5 strategy. A GO verdict here
does NOT waive it.

## Outcome

Recorded in docs/research/2026-07-14-gyroscope-gate-results.md after the
runs. GO → recommend demo-forward (the flip is the operator's decision).
NO-GO → gyroscope stays research/disabled; KalmanDrift remains reusable
analysis infra; result stands in the record.
```

- [ ] **Step 2: Write `scripts/run_gyroscope_gate.sh`:**

```bash
#!/usr/bin/env bash
# Plan 07 / Task 10 driver: 11 pooled gate runs (defaults, x1.5 stress,
# baseline, 8 one-at-a-time +-30% sweeps). Each run ~1.5-3h (9 symbols x
# ~20k-bar kernel replay); run under nohup, sequentially.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
SYMS="EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,GBPJPY,XAUUSD,US30,BTCUSD"
OUT=data/results/gyro_gate

run() {
  echo "=== [$(date -u +%H:%M:%S)] research_run $* ==="
  $PY scripts/research_run.py --lake-symbols "$SYMS" --tf H1 \
      --set signal_grading.min_grade=C --out "$OUT" "$@"
}

run --strategy gyroscope --spread-mult 1.0                       # 1 defaults (headline)
run --strategy gyroscope --spread-mult 1.5                       # 2 stress (criterion 7)
run --strategy ma_slope_baseline --spread-mult 1.0               # 3 baseline (criterion 6)
for kv in sprt.alpha=0.035 sprt.alpha=0.065 sprt.beta=0.14 sprt.beta=0.26 \
          sprt.delta=0.28 sprt.delta=0.52 q_atr_frac=0.035 q_atr_frac=0.065; do
  run --strategy gyroscope --spread-mult 1.0 \
      --set "strategies.gyroscope.$kv"                           # 4-11 sweeps (criterion 5)
done
echo "=== GATE RUNS COMPLETE ==="
```

`chmod +x scripts/run_gyroscope_gate.sh`.

- [ ] **Step 3: Fill the one `<FILL>`** in the gate doc (Task-2 commit short sha via `git log --oneline -- data/lake/frozen | tail -1`).

- [ ] **Step 4: Commit — this commit IS the pre-registration; it must precede any gate run:**

```bash
git add docs/research/2026-07-14-gyroscope-gate.md scripts/run_gyroscope_gate.sh
git commit -m "docs(gate): pre-register the Gyroscope gate — 8 GO criteria, frozen dataset, fixed params, sweep-as-falsification, C-floor rationale, advisory-C precondition

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Run the gate; record the verdict

**Files:**
- Create: `docs/research/2026-07-14-gyroscope-gate-results.md`
- Generated (gitignored): `data/results/gyro_gate/*` run-cards, `data/results/gyro_gate.log`

**Interfaces:** consumes Tasks 1-9. Produces the recorded verdict + the ledger close-out.

**Runtime reality (plan for it):** each pooled run replays 9 × ~20k H1 bars through the real kernel — ~1.5-3 h per run, ~20-30 h for all 11, sequential. This does NOT fit a foreground Bash call (10-min cap). Use `nohup` + periodic polling; the suite-green rule applies to the CODE (already satisfied at Task 9) — this task is execution + writeup.

- [ ] **Step 1: Preflight sanity (fast-ish, ~20 min)** — one pooled run over TWO symbols to prove the full path end-to-end before committing 30 h:

```bash
.venv/bin/python scripts/research_run.py --lake-symbols EURUSD,GBPUSD --tf H1 \
  --strategy gyroscope --spread-mult 1.0 --set signal_grading.min_grade=C \
  --out data/results/gyro_preflight
```

Expected: exit 0, a POOLED2 run-card with nonzero `n_signals` (SPRT crossings DO occur on real data) and `mode: pooled`. If `n_signals == 0`, STOP and investigate (most likely the grading floor or the bias exemption is not wired — re-check Task 6/8) — do not start the 11 runs.

- [ ] **Step 2: Launch the full battery in the background:**

```bash
nohup bash scripts/run_gyroscope_gate.sh > data/results/gyro_gate.log 2>&1 &
echo $! > data/results/gyro_gate.pid
```

Poll with `tail -5 data/results/gyro_gate.log` + `ls data/results/gyro_gate | wc -l`; expect 11 run dirs at completion. (Subagent note: this outlives any session — record the pid + expected completion in the ledger and STOP the task here if the session cannot wait; a follow-up dispatch picks up at Step 3 by checking the run-dir count.)

- [ ] **Step 3: Evaluate the 8 criteria** — read each run-card's `run.json`; build the verdict table. Criterion values come ONLY from the cards (no recomputation): 1-4, 8 from the defaults card; 5 from the 8 sweep cards' pooled IS+OOS sign; 6 from defaults-vs-baseline pooled net; 7 from the stress card.

- [ ] **Step 4: Write `docs/research/2026-07-14-gyroscope-gate-results.md`** — structure (all numbers from cards; include each card's sha256 via `sha256sum data/results/gyro_gate/*/run.json`):

```markdown
# Gyroscope Gate — Results (Plan 07)

Gate: docs/research/2026-07-14-gyroscope-gate.md (pre-registered <commit sha>).

## Verdict: GO | NO-GO

| # | Criterion | Threshold | Observed | Pass |
|---|-----------|-----------|----------|------|
| 1 | pooled net exp | >= +0.10R | ... | ... |
| 2 | pooled trades | >= 150 | ... | ... |
| 3 | symbols non-neg | >= 6/9 | ... | ... |
| 4 | OOS pooled exp | > 0 | ... | ... |
| 5 | sweeps flip sign | none of 8 | ... | ... |
| 6 | vs baseline | gyro > baseline | ... vs ... | ... |
| 7 | x1.5 spread | pooled exp > 0 | ... | ... |
| 8 | bootstrap LB | > 0 | ... | ... |

## Run-cards (data/results/gyro_gate/, gitignored — sha256 pins)
<one line per run: dir name, headline numbers, run.json sha256>

## Diagnostics (non-gating)
<realized false-entry rate vs alpha; NIS-suspend frequency; per-symbol table>

## Interpretation & next step
<GO: recommend demo-forward, flip is operator's; advisory-C + per-strategy
grading policy remain preconditions. NO-GO: which criteria failed, what the
failure teaches (cf. SB +0.19R control), gyroscope stays research/disabled.>
```

- [ ] **Step 5: Commit the results doc** (results doc ONLY — run-cards stay gitignored):

```bash
git add docs/research/2026-07-14-gyroscope-gate-results.md
git commit -m "docs(gate): Gyroscope gate verdict — <GO|NO-GO> per pre-registered criteria

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Final ledger entry** — append the Plan-07 close-out to `.superpowers/sdd/progress.md` (span, final suite count, verdict, deviations, carry-forwards: per-strategy grading policy [if GO], advisory C untouched, Antibody = next plan).

---

## Plan self-review (performed at authoring)

1. **Spec coverage:** D1→T1, D2→T2, D3→T3, D4→T4, D5→T5, D6→T6, D7→T7+T8, D8→T9, D9→T10. Hardenings: #1/#2→T7, #3→T8 (helper) + T9 (criterion 8), #4/#5→T9 doc text, #6a→T2 PROVENANCE, #6b→T6 (default-honoring test + parity gate). P06 minors closed: frozen-manifest (T1), spec_source label (T8). Advisory B→T6; advisory C→T9 doc (code untouched, as spec'd).
2. **Placeholders:** the only intentional fill-ins are the two commit-sha references in T9/T10 docs (unknowable at plan time — instructions given for deriving them) and Task 10's results numbers (the point of the run). No TBDs elsewhere.
3. **Type consistency:** `Reading.crossed` is `""|"LONG"|"SHORT"` everywhere (strategy checks truthiness + equality); `_signals_to_trades` returns `(trades, skipped)` in T7 and both T8 call sites; `last_atr(df, period=14)` consistent in T4/T5; `priority_of`/`honors_htf_bias` names identical across manifest/registry/controller/tests; pooled card keys in T8 implementation match the T8 e2e test's assertions; `run()` in the gate script passes `--set` after the common one (argparse `append` collects both).
4. **Known suite-count drift:** counts cited per task are estimates; the ledger records real numbers (standing instruction from Plans 01-06).
