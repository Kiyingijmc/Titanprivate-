# Plan 06: Research Lake + Kernel Replay Runners Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A curated Parquet research lake (manifest, validation-on-ingest, retention) and a research runner that drives the SAME kernel the live bot runs (FeatureBus + grader + arbiter) over lake data — proving live/research parity structurally and unblocking Plan 07's Gyroscope gate study.

**Architecture:** Backend blueprint §7 + B5, right-sized. The lake is `data/lake/` partitioned `broker/symbol/tf/year.parquet` with a JSON manifest (checksum/span/rows/last_used); ingestion validates and quarantines. The replay router generalizes the parity harness's controller fixture into `src/research/kernel_replay.py` — its acceptance test is beautiful and strict: **replaying test_data.csv through the research path must reproduce the frozen golden fixture's signal stream exactly** (blueprint §13.3's one-code-path dividend, made a unit test). Trade resolution and cost math are IMPORTED from the proven `backtest_engine`/rig functions, never duplicated. Deferred + recorded: Optuna (grid sweeps suffice for the ±30% gate checks; new dep unjustified), runs REST API (B2 territory), multi-broker ingest (partition scheme carries `broker` from day one).

**Tech Stack:** Python 3.11, pandas, **pyarrow (NEW dep — pre-approved by the roadmap's global constraints, introduced in T1)**, stdlib unittest.

## Global Constraints

- Suite baseline entering: **298 OK**; green after every task. Parity test untouched and green at every task that imports controller machinery (T3+).
- The parity harness (`scripts/capture_parity_golden.py`) and golden fixture are FROZEN — `kernel_replay.py` is a NEW module that may share technique but not modify them.
- No duplication of validated math: trade resolution/costs come from `tests.backtest.backtest_engine` (`resolve_trade`, `trade_dollars`, `split_trades`, `aggregate_metrics`) via import (the `test_harness.py` sys.path pattern).
- The live bot must be unaffected: nothing under `src/core/`, `src/execution/`, `src/arbiter/`, `src/strategies/` changes in this plan EXCEPT nothing at all — this plan adds `src/data/`, `src/research/`, `scripts/`, `tests/` only. (If a task discovers it needs a kernel change, STOP and escalate.)
- Research runs may activate research-status strategies OFFLINE (that is their purpose); the live promote-gate is untouched.
- Lake writes never touch `data/history/` (the CSV exports stay as the raw source until ingested); `data/lake/` gets a `.gitignore` entry (regenerable) EXCEPT `data/lake/frozen/` (gate datasets, committed).
- Commits end with the Co-Authored-By trailer. Never stage `mql5_bridge/Experts/Titan_Gateway.mq5` or `data/specs.json`.

## File Structure

```
src/data/__init__.py                # T1 (empty)
src/data/lake.py                    # T1: write_partition/load/manifest/validate
tests/unit/test_lake.py             # T1
scripts/lake_import.py              # T2: CSV -> lake (MT5-tab + standard formats)
scripts/lake_prune.py               # T2: retention (dry-run default)
tests/unit/test_lake_import.py      # T2
src/research/__init__.py            # T3 (empty)
src/research/kernel_replay.py       # T3: build_research_controller + replay()
tests/unit/test_kernel_replay.py    # T3 (research-parity acceptance test lives here)
scripts/research_run.py             # T4: CLI -> run dir + IS/OOS report
tests/unit/test_research_run.py     # T4
requirements.txt                    # T1: + pyarrow
.gitignore                          # T1: + data/lake/ (except frozen/)
```

---

### Task 1: Lake core (pyarrow + write/load/manifest/validate)

**Files:** Create `src/data/__init__.py`, `src/data/lake.py`; modify `requirements.txt` (+`pyarrow>=15.0`), `.gitignore` (+`data/lake/` and `!data/lake/frozen/`); test `tests/unit/test_lake.py`.

**Interfaces (Produces):**

```python
class LakeError(ValueError): ...

class Lake:
    def __init__(self, root):                     # root = Path("data/lake") in prod; tmp in tests
    def ingest(self, df, broker, symbol, tf, source="") -> list[str]
        # Validates then writes year-partitioned parquet files
        # (<root>/<broker>/<symbol>/<tf>/<year>.parquet, merged+deduped with any
        # existing partition rows, sorted by time), updates manifest.json
        # (per-partition: rows, first_time, last_time, sha256 of file bytes,
        # source, created, last_used). Returns written partition paths.
        # VALIDATION (all must pass or LakeError + quarantine copy of the
        # offending df to <root>/.rejected/<ts>_<symbol>_<tf>.csv with a
        # reason file): required cols time/open/high/low/close; time parseable,
        # strictly increasing after sort+dedupe; no NaN in OHLC; high>=low,
        # high>=open/close, low<=open/close on every row.
    def load(self, symbol, tf, broker="fbs", start=None, end=None) -> pd.DataFrame
        # Concatenates matching partitions, filters [start, end], touches
        # last_used in the manifest. Missing partition -> LakeError naming
        # what exists for that symbol.
    def manifest(self) -> dict
    def prune(self, active_years=4, unused_days=180, now=None, dry_run=True) -> list[str]
        # Candidates: partitions ENTIRELY older than active_years AND
        # last_used older than unused_days. dry_run returns paths only;
        # real run deletes files + manifest entries. NEVER touches frozen/
        # (any path under <root>/frozen is excluded structurally).
```

**Tests (~8, author them; all against a tmp root):** ingest→load round-trip equality (values + dtypes, sorted); year partitioning (df spanning 2 years → 2 files); merge-dedupe on overlapping re-ingest (no duplicate timestamps, updated manifest rows); each validation failure raises LakeError AND leaves a quarantine file + reason; load start/end filtering; load touches last_used; prune dry-run lists only eligible partitions (old + unused) and never frozen/; prune real-run deletes and updates manifest.

- [ ] Install dep first: `.venv/bin/python -m pip install 'pyarrow>=15.0'` then add to requirements.txt. TDD → module green → full suite (expect ~306 OK; report actual) → commit `feat(lake): parquet research lake — manifest, validation, retention (+pyarrow dep)` (+trailer; 5 files).

---

### Task 2: Import + prune CLIs

**Files:** Create `scripts/lake_import.py`, `scripts/lake_prune.py`; test `tests/unit/test_lake_import.py`.

1. `lake_import.py`: `--csv <path> --symbol X --tf M5 [--broker fbs] [--source note]` — reads BOTH formats present in this repo (sniff): MT5 tab-export (`<DATE>\t<TIME>\t<OPEN>...` like `test_data.csv` — combine date+time cols) and standard comma CSV with a `time` column (like `data/history/*_M5.csv` — READ one first to confirm its exact columns). Normalizes to time/open/high/low/close (+volume if present), calls `Lake.ingest`, prints written partitions + row counts. `--all-history` convenience: globs `data/history/*_{M5,H1,D1}.csv`, infers symbol/tf from filename, ingests each (continue-on-error per file, summary at end).
2. `lake_prune.py`: `[--active-years 4] [--unused-days 180] [--execute]` — dry-run by DEFAULT printing candidates; `--execute` deletes. Prints a one-line summary either way.
3. Tests (~5): tab-format parse equals expected frame; comma-format parse; filename inference (`EURUSD_M5.csv` → EURUSD/M5); continue-on-error aggregation; prune CLI dry-run vs execute against a tmp lake (drive `main(argv)` directly — structure both CLIs with an importable `main(argv=None)`).

- [ ] TDD → module green → full suite (report actual) → commit `feat(lake): import + prune CLIs (MT5-tab & CSV ingestion, dry-run retention)` (+trailer; 3 files).

---

### Task 3: Kernel replay router (the research↔live parity seam)

**Files:** Create `src/research/__init__.py`, `src/research/kernel_replay.py`; test `tests/unit/test_kernel_replay.py`.

**Interfaces (Produces):**

```python
def build_research_controller(strategies, config, ny_time="10:00:00 EST"):
    # A SystemController built via __new__ with EXACTLY the live kernel attached:
    # real FeatureBus + smc pack (validated), real Arbiter(config['arbiter'], publish=collector),
    # real SignalGrader(config), stub logger/time-engine (fixed ny_time), stub store,
    # capturing _execute_signal. Returns (controller, captured, published).
    # Study scripts/capture_parity_golden.py::_make_controller for the pattern —
    # DO NOT MODIFY that file; this module generalizes it (parameterized strategies/config).

def replay(df_h1, symbol, strategies, config, window=300, start=60):
    # Iterates closes exactly like the parity harness (window cap = live rolling
    # semantics), drives controller._run_strategies per close, returns
    # list[SignalRecord] where SignalRecord = dict(i, time, bias, signal, price,
    # sl, tp, grade, strategy) — superset of the golden fixture's element schema.

def load_h1_from_m5(df_m5):  # the SAME resample the parity harness/backtest engine uses —
    # import/reuse, don't re-derive (read how capture_parity_golden gets its H1 frame
    # and reuse that exact mechanism/function).
```

**THE ACCEPTANCE TEST (this plan's centerpiece):** `test_replay_reproduces_golden_fixture` — build SilverBullet from real config, `replay()` over test_data.csv's H1 frame, project each SignalRecord down to the fixture's element schema (`i`, `bias`, `signal`, `price`, `sl`, `tp`, `grade`), assert the projected stream equals `tests/backtest/fixtures/parity_golden_h1.json` element-for-element. If this passes, the research runner IS the live path — every future gate study inherits live-parity for free.

Plus (~3 more tests): a research-status FakeStrat runs through replay (offline activation works — instances injected directly, no promote-gate involvement); arbiter events collected (submit/resolve exercised — assert IntentEmitted count == signal count); window/start parameters respected.

- [ ] TDD → module green (**the acceptance test is the gate**) → parity test itself still green (nothing frozen was touched: `git diff --stat -- scripts/capture_parity_golden.py tests/backtest/fixtures/` empty) → full suite (report actual) → commit `feat(research): kernel replay router — research path reproduces live golden stream` (+trailer; 3 files).

---

### Task 4: Research run CLI (gate-study workhorse)

**Files:** Create `scripts/research_run.py`; test `tests/unit/test_research_run.py`.

1. CLI: `--csv <path>|--lake-symbol X --tf H1 --strategy silver_bullet [--split 0.7] [--spread-pips N] [--out data/results]`. Flow: load data (lake or CSV via the T2 readers) → resample H1 if needed (T3 helper) → build strategy from `config/manifests/<id>.yaml` + `config.yaml` params (research status allowed — this is offline) → `replay()` → resolve each signal to a trade via `backtest_engine.resolve_trade` on the forward bars → net R with a flat spread cost in R terms (reuse the cost approach the SB rig uses — read `poc_sb_stops.cost_r` and use IT if importable cleanly, else `trade_dollars`; state which in the report) → `split_trades` IS/OOS → `aggregate_metrics` per split → print a compact report table.
2. **Run-card** (the one Vibe-Trading borrow-idea): every run writes `<out>/<UTCts>_<strategy>_<symbol>_<tf>/run.json` — {git_sha, strategy_id+version (from manifest), config_hash (sha256 of the strategy's param block), data source+sha256, n_bars, n_signals, n_trades, is/oos metrics, spread assumption, timestamp} + `signals.jsonl`. Reproducibility artifact for every gate study.
3. Tests (~4): end-to-end over test_data.csv with silver_bullet → run dir created, run.json schema complete, n_signals == golden fixture's 13 (consistency pin!), metrics dict has n/exp/totR keys; `--split` respected (IS+OOS trade counts sum); unknown strategy id → clean error; spread parameter flows into net R (two runs, different spreads → different exp).

- [ ] TDD → module green → full suite (report actual) → commit `feat(research): research_run CLI — gate studies through the live kernel with run-cards` (+trailer; 2 files).

---

### Task 5: Final verification + real-data smoke

- [ ] Full suite + parity (record). Real-data smoke (in report, no commit): `lake_import --all-history` dry-ish (ingest 2-3 symbols' M5+D1), then `research_run --lake-symbol EURUSD --tf H1 --strategy silver_bullet` end-to-end — confirm a run dir + plausible report renders (numbers are NOT a gate study; just prove the pipeline). `git log --oneline` span. Working-tree check (lake files must be gitignored — `git status` clean of data/lake/**). No commits except if .gitignore proves wrong (then a one-line fix commit).

## Definition of done

1. The acceptance test holds: research replay reproduces the frozen golden stream element-for-element — one code path, live and research.
2. Lake round-trips validated data with manifest/checksum/retention; bad data quarantines with reasons.
3. `research_run` produces a run-card'd, IS/OOS-split, cost-adjusted report for any manifest strategy over lake or CSV data — Plan 07's Gyroscope gate study is now "write manifest + gate doc, run CLI."
4. Live bot provably untouched: zero diffs under src/core|execution|arbiter|strategies.
5. Deferred + recorded: Optuna, runs REST API, bridge-direct import.
