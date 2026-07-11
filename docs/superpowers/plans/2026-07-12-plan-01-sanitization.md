# Plan 01: System Sanitization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the codebase to the approved arsenal (SilverBullet only) by deleting unapproved SMC/ICT strategy models, NO-GO'd research rigs, and dead code — with the full unit suite green after every task.

**Architecture:** Pure-subtraction refactor. SilverBullet keeps its entire dependency chain (SMCAnalyzer → market_structure/liquidity, BiasEngine, signal_grader, ATR/FVG columns, `poc_sb_stops.py` rig). Everything below is verified-then-deleted: grep for references first, delete, re-run the suite, commit per task so any step is independently revertible.

**Tech Stack:** Python 3.11, stdlib unittest, git. No new dependencies; one dependency removed (`sqlalchemy`).

## Global Constraints

- Test command (run after every task): `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
- Baseline: record the pass count in Task 0; every subsequent task must show the same count minus exactly the tests deleted in this plan.
- KEEP list (never touch): `silver_bullet.py`, `smc_analyzer.py`, `market_structure.py`, `liquidity.py`, `bias_engine.py`, `signal_grader.py`, `time_math.py`, `news_manager.py`, `scripts/poc_sb_stops.py`, `scripts/sweep_silverbullet.py`, `tests/unit/test_silverbullet_timing.py`, `tests/unit/test_sb_overlay.py`, everything in `docs/research/` (results history is permanent).
- Do NOT touch the pre-existing uncommitted change to `mql5_bridge/Experts/Titan_Gateway.mq5` or the untracked `data/specs.json` — they belong to other work in flight.
- SilverBullet live behavior must be bit-identical: it is not CRT, so making the HTF-bias filter unconditional (Task 2) does not change its filtering.

---

### Task 0: Commit session documents and record the test baseline

**Files:**
- Commit (already written): `docs/research/2026-07-12-novel-arsenal-brainstorm.md`, `docs/research/2026-07-12-trading-os-blueprint.md`, `docs/research/2026-07-12-backend-infrastructure-blueprint.md`, `docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md`, `docs/superpowers/plans/2026-07-12-plan-01-sanitization.md`

**Interfaces:**
- Produces: git baseline commit; recorded test count `N_baseline` used by every later task's verification.

- [ ] **Step 1: Verify starting state**

Run: `git status --short`
Expected: ` M mql5_bridge/Experts/Titan_Gateway.mq5`, `?? data/specs.json`, plus the five docs above as untracked/new. Nothing else.

- [ ] **Step 2: Commit the docs only**

```bash
git add docs/research/2026-07-12-novel-arsenal-brainstorm.md \
        docs/research/2026-07-12-trading-os-blueprint.md \
        docs/research/2026-07-12-backend-infrastructure-blueprint.md \
        docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md \
        docs/superpowers/plans/2026-07-12-plan-01-sanitization.md
git commit -m "docs: v15 blueprints (novel arsenal, trading OS, backend) + program roadmap

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Run the full suite and record the baseline**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK` (possibly with skips). Record the `Ran N tests` number as **N_baseline** in the task notes.

---

> **EXECUTION ORDER NOTE:** Run Task 2 BEFORE Task 1. `tests/backtest/backtest_engine.py`
> imports the strategy models; deleting the model files (Task 1) before making the engine
> SilverBullet-only (Task 2) would break `test_harness`/`test_perf_equivalence` mid-plan.
> Task 2 is safe first because the engine can go SB-only while the model files still exist.
> Effective order: 0 → 2 → 1 → 3 → 4 → 5 → 6 → 7.

### Task 1: Delete unapproved strategy models and rewire the controller

**Files:**
- Delete: `src/strategies/models/unicorn.py`, `src/strategies/models/ict_ote.py`, `src/strategies/models/crt.py`
- Modify: `src/core/system_controller.py` (imports; `_init_strategies` at ~line 494; CRT special-case in `_run_strategies` at ~line 535)
- Test: existing suite (`tests/unit/test_controller_routing.py`, `test_strategy_timeframe.py` already cover routing and do not reference the deleted models)

**Interfaces:**
- Produces: `SystemController._init_strategies()` builds `self.strategies = [SilverBullet(...)]` only. `_run_strategies` applies the HTF-bias filter unconditionally (no `strat.name != "CRT"` guard).

- [ ] **Step 1: Confirm the only references live in the controller**

Run: `grep -rn "UnicornModel\|ICT_OTE\|CandleRangeTheory\|unicorn\|ict_ote\b" src/ --include="*.py" | grep -v "strategies/models/"`
Expected: hits only in `src/core/system_controller.py` (import lines + `_init_strategies`).

- [ ] **Step 2: Edit `_init_strategies` to SilverBullet only**

Replace (current code at `src/core/system_controller.py:494-501`):

```python
    def _init_strategies(self):
        s = self.config.get('strategies', {})
        self.strategies = [
            SilverBullet(s.get('silver_bullet',{}), self.logger),
            UnicornModel(s.get('unicorn_model',{}), self.logger),
            ICT_OTE(s.get('ict_ote',{}), self.logger),
            CandleRangeTheory(s.get('crt',{}), self.logger)
        ]
```

with:

```python
    def _init_strategies(self):
        s = self.config.get('strategies', {})
        self.strategies = [
            SilverBullet(s.get('silver_bullet',{}), self.logger),
        ]
```

Then delete the three import lines for `UnicornModel`, `ICT_OTE`, `CandleRangeTheory` at the top of the file (find them with `grep -n "unicorn\|ict_ote\|crt" src/core/system_controller.py`). Keep the `SilverBullet` import.

- [ ] **Step 3: Remove the CRT bias-filter exemption**

Replace (current code at `src/core/system_controller.py:535-538`):

```python
                if strat.name != "CRT":
                    if (bias_str == "BULLISH" and decision['signal'] == "SELL") or \
                       (bias_str == "BEARISH" and decision['signal'] == "BUY"):
                           continue
```

with:

```python
                if (bias_str == "BULLISH" and decision['signal'] == "SELL") or \
                   (bias_str == "BEARISH" and decision['signal'] == "BUY"):
                    continue
```

- [ ] **Step 4: Delete the model files**

```bash
git rm src/strategies/models/unicorn.py src/strategies/models/ict_ote.py src/strategies/models/crt.py
```

- [ ] **Step 5: Verify import health and run the suite**

Run: `.venv/bin/python -c "from src.core.system_controller import SystemController; print('imports OK')"`
Expected: `imports OK`
Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `Ran N_baseline tests ... OK`

- [ ] **Step 6: Commit**

```bash
git add -A src/core/system_controller.py src/strategies/models/
git commit -m "refactor: remove unapproved strategies (Unicorn, ICT_OTE, CRT); SilverBullet-only arsenal

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Reduce the offline backtester to the approved arsenal

**Files:**
- Modify: `tests/backtest/backtest_engine.py` (imports and strategy construction — locate with the grep in Step 1)
- Test: `tests/unit/test_harness.py`, `tests/unit/test_perf_equivalence.py` (both `import backtest_engine`)

**Interfaces:**
- Produces: `backtest_engine` constructs only `SilverBullet`; its module-level API (whatever `test_harness.py` imports) is unchanged.

- [ ] **Step 1: Locate references**

Run: `grep -n "UnicornModel\|ICT_OTE\|CandleRangeTheory\|unicorn\|ict_ote\|crt" tests/backtest/backtest_engine.py`
Expected: import lines and entries in a strategy list/dict mirroring the controller's old `_init_strategies` pattern.

- [ ] **Step 2: Edit to SilverBullet-only**

Delete the three imports and the three constructor entries found in Step 1, preserving the list/dict structure with the `SilverBullet` entry — the same subtraction as Task 1 Step 2 (final shape: a one-element collection containing the `SilverBullet` construction, config-keyed by `silver_bullet`).

- [ ] **Step 3: Run the backtester-dependent tests, then the suite**

Run: `.venv/bin/python -m unittest tests.unit.test_harness tests.unit.test_perf_equivalence -v 2>&1 | tail -5`
Expected: OK.
Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `Ran N_baseline tests ... OK`

- [ ] **Step 4: Commit**

```bash
git add tests/backtest/backtest_engine.py
git commit -m "refactor: backtest engine runs approved arsenal only (SilverBullet)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Delete the OTE research chain

**Files:**
- Delete: `src/analysis/ote_structure.py`, `scripts/poc_ote_canonical.py`, `tests/unit/test_ote_rig.py`, `tests/unit/test_ote_structure.py`

**Interfaces:**
- Consumes: nothing. `test_ote_rig.py` imports `replay_managed`/`cost_r` from `scripts/poc_sb_stops.py` — that module STAYS (SilverBullet's validated rig); only the OTE test file goes.
- Produces: no `ote` references outside `docs/`.

- [ ] **Step 1: Verify the closure is exactly these four files**

Run: `grep -rln "ote_structure\|poc_ote_canonical" src/ tests/ scripts/ --include="*.py"`
Expected: exactly `src/analysis/ote_structure.py`, `scripts/poc_ote_canonical.py`, `tests/unit/test_ote_rig.py`, `tests/unit/test_ote_structure.py`. (If anything else appears, STOP and report before deleting.)

- [ ] **Step 2: Delete**

```bash
git rm src/analysis/ote_structure.py scripts/poc_ote_canonical.py \
       tests/unit/test_ote_rig.py tests/unit/test_ote_structure.py
```

- [ ] **Step 3: Run the suite; compute the new expected count**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: OK, with `Ran (N_baseline − tests_in_deleted_files)` — record the delta from the two deleted test files' case counts (visible in the Task 0 verbose run or via `git show HEAD~1 --stat`).

- [ ] **Step 4: Commit**

```bash
git commit -am "chore: delete OTE research chain (canonical NO-GO 2026-07-11; results retained in docs/research)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Delete the MTF-pullback and trend-H4 research rigs

**Files:**
- Delete: `scripts/poc_mtf_pb.py`, `scripts/poc_mtf_pb2.py`, `scripts/poc_trend_h4.py`, `tests/unit/test_mtf_pb.py`, `tests/unit/test_mtf_pb2.py`, `tests/unit/test_mtf_pb2_perf.py`, `tests/unit/test_trend_poc.py`

**Interfaces:**
- Produces: `scripts/` contains only live tooling (`check_bridge*`, `export_history`, `cache_specs`, `export_journal`, `smoke_test_execution`) + SilverBullet research (`poc_sb_stops`, `sweep_silverbullet`).

- [ ] **Step 1: Verify closure**

Run: `grep -rln "poc_mtf_pb\|poc_trend_h4" src/ tests/ scripts/ --include="*.py" | grep -v "^scripts/poc_mtf_pb\|^scripts/poc_trend_h4\|^tests/unit/test_mtf_pb\|^tests/unit/test_trend_poc"`
Expected: no output. Also check `test_perf_equivalence.py` imports only `backtest_engine` (it does — verified during planning), not the MTF rigs.

- [ ] **Step 2: Delete**

```bash
git rm scripts/poc_mtf_pb.py scripts/poc_mtf_pb2.py scripts/poc_trend_h4.py \
       tests/unit/test_mtf_pb.py tests/unit/test_mtf_pb2.py \
       tests/unit/test_mtf_pb2_perf.py tests/unit/test_trend_poc.py
```

- [ ] **Step 3: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: OK; count drops by exactly the deleted files' case counts.

- [ ] **Step 4: Commit**

```bash
git commit -am "chore: delete MTF-PB v1/v2 + trend-H4 research rigs (NO-GO; results retained in docs/research)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Purge the dead-code list

**Files:**
- Delete: `src/core/event_bus.py`, `src/execution/reconciliation.py`, `config/dev_override.yaml`, `mql5_bridge/Include/Zmq_Wrapper.mqh`
- Modify: `requirements.txt` (remove line 17: `sqlalchemy>=2.0.0`)

**Interfaces:**
- Produces: CLAUDE.md's dead-code list becomes empty (updated in Task 6). Note for Plan 02: the new typed bus is a NEW module (`src/core/bus.py`), not a revival of `event_bus.py`.

- [ ] **Step 1: Verify nothing imports the dead modules**

Run: `grep -rn "event_bus\|reconciliation\|dev_override\|TITAN_ENV" src/ tests/ scripts/ main.py --include="*.py"`
Expected: no output beyond the dead files themselves. (`TITAN_ENV` was verified during planning to have zero code references — if a hit appears, STOP and report.)

- [ ] **Step 2: Delete files and the dependency line**

```bash
git rm src/core/event_bus.py src/execution/reconciliation.py \
       config/dev_override.yaml mql5_bridge/Include/Zmq_Wrapper.mqh
```

Then in `requirements.txt`, delete the line `sqlalchemy>=2.0.0`.

- [ ] **Step 3: Verify the venv still satisfies requirements and run the suite**

Run: `.venv/bin/python -m pip check && .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: no broken requirements; suite OK with the Task-4 count.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: purge dead code (event_bus, reconciliation, dev_override, Zmq_Wrapper.mqh, sqlalchemy dep)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Config and CLAUDE.md alignment

**Files:**
- Modify: `config/config.yaml` (delete the `unicorn_model:` block at ~lines 89–96, `ict_ote:` at ~97–104, `crt:` at ~105+ under `strategies:`)
- Modify: `CLAUDE.md` (strategy contract paragraph; dead-code paragraph)

**Interfaces:**
- Produces: config parses with only `silver_bullet` under `strategies:`; CLAUDE.md describes the sanitized reality.

- [ ] **Step 1: Delete the three config blocks**

In `config/config.yaml`, remove the `unicorn_model:`, `ict_ote:`, and `crt:` mappings entirely (all are `enabled: false`). Keep `silver_bullet:` and `signal_grading:` untouched.

- [ ] **Step 2: Verify config parses and the controller boots to config-load**

Run: `.venv/bin/python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); assert list(c['strategies'].keys())==['silver_bullet'], c['strategies'].keys(); print('config OK')"`
Expected: `config OK`

- [ ] **Step 3: Update CLAUDE.md**

In the **Architecture** section, replace the strategy-contract sentence:

> **Strategy contract**: `src/strategies/models/{silver_bullet,unicorn,ict_ote,crt}.py` extend `base_strategy.py` …

with:

> **Strategy contract**: `src/strategies/models/silver_bullet.py` (the only approved strategy; Unicorn/ICT_OTE/CRT were removed 2026-07-12 — unapproved, all NO-GO'd or unvalidated) extends `base_strategy.py` and returns a decision dict `{signal, type, price, sl, tp}` from `on_new_candle()`. Only `on_new_candle` is used by the controller and backtester. The controller enriches data via `SMCAnalyzer` + `BiasEngine` and filters all signals against HTF bias. New strategies enter as Trading-OS plugins per `docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md`.

In **Critical conventions & gotchas**, replace the dead-code bullet with:

> - **Dead code was purged 2026-07-12** (event_bus, reconciliation, dev_override.yaml, Zmq_Wrapper.mqh, TITAN_ENV, sqlalchemy). The v15 event bus is `src/core/bus.py` (new design, Phase III blueprint §5) — do not resurrect the old patterns.

- [ ] **Step 4: Run the suite one more time**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add config/config.yaml CLAUDE.md
git commit -m "chore: align config and CLAUDE.md with sanitized SilverBullet-only arsenal

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Final verification sweep

**Files:**
- None created/modified — verification only.

**Interfaces:**
- Produces: the sanitization done-signal for Plan 02 to start.

- [ ] **Step 1: Global reference sweep**

Run: `grep -rn "UnicornModel\|ICT_OTE\|CandleRangeTheory\|ote_structure\|poc_ote\|poc_mtf\|poc_trend\|event_bus\|dev_override\|sqlalchemy\|TITAN_ENV" src/ tests/ scripts/ config/ main.py requirements.txt --include="*.py" --include="*.yaml" --include="*.txt" 2>/dev/null`
Expected: no output. (docs/ is intentionally excluded — history is retained.)

- [ ] **Step 2: Offline backtest smoke run**

Run: `.venv/bin/python tests/backtest/backtest_engine.py 2>&1 | tail -5`
Expected: completes without ImportError/KeyError (reads `test_data.csv`, needs no MT5). Signal output may legitimately be empty — the check is that the engine runs end-to-end.

- [ ] **Step 3: Full suite, final count**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK`; count = N_baseline − (cases from the 6 deleted test files). Record the new baseline for Plan 02.

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/trade-mgmt-pipeline
```

(Or a dedicated `feat/v15-sanitize` branch if the operator prefers to keep the in-flight EA change separate — ask before creating new branches.)
