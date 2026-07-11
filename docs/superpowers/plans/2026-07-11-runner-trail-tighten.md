# Runner-Trail Tighten (Arm C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-way runner-trail tighten to `TradeManager`: once a runner pullback gives back ≥ `giveback_frac` of the trail distance from the leg's high-water mark, permanently switch that ticket's trail from `0.268×range` to `tight_trail_frac×range` — the validated zero-cost drawdown reducer (arm C).

**Architecture:** All logic sits inside the existing runner-trail block of `TradeManager.sync_positions` (reached only at `r_level ≥ 3` with runner enabled). Two in-memory dicts on the instance track per-ticket HWM and a one-way "tightened" set; both are pruned each sync for closed tickets. Config-gated (`trade_management.runner.tighten_on_giveback`), ships **off**, defaults baked in so an old config is unchanged.

**Tech Stack:** Python 3.10+, stdlib `unittest` (no pytest). Change is confined to `src/execution/trade_manager.py`, `config/config.yaml`, and new tests in the existing `tests/unit/test_trade_manager.py`.

## Global Constraints

- **In-memory state only** — no StateManager schema change, no SQLite. Two instance fields: `self.runner_hwm: dict[int,float]`, `self.tightened: set[int]`.
- **No new bridge command type, no EA change.** Reuses the existing `MODIFY` action already emitted by the runner trail.
- **Disabled = byte-identical to today.** When `tighten_on_giveback` is false, the emitted commands must match current behavior (trail = `0.268×range`). A test pins this.
- **Config keys (exact), under `trade_management.runner`, defaults baked into `__init__`:** `tighten_on_giveback: false`, `giveback_frac: 0.75`, `tight_trail_frac: 0.10`.
- **Constants:** normal trail = `range_size × (L3_FIB − L2_FIB)` = `range_size × 0.268`. Tightened trail = `range_size × tight_trail_frac`. Trigger = give-back `≥ giveback_frac × normal_trail`. Tighten is **one-way** (ticket added to `self.tightened`, never removed except by close-pruning).
- **Only acts at `r_level ≥ 3` with runner on** — after both ratchet partials, when the trade is already risk-free. Tests stub `r_level = 3`.
- Tests: stdlib `unittest`, added as a new class in `tests/unit/test_trade_manager.py` (reuse its `make_tm`, `pos`, `FakeState`, `FakeRisk` helpers). Run: `.venv/bin/python -m unittest tests.unit.test_trade_manager -v`.

---

### Task 1: Arm C runner-trail tighten (whole mechanism)

Add config reads + state fields, the HWM-track / give-back-trigger / trail-select logic inside the runner block, and close-pruning — with full unit coverage. This is one cohesive mechanism; it ships as one reviewable task.

**Files:**
- Modify: `src/execution/trade_manager.py` (`__init__` ~lines 30-42; `sync_positions` runner block ~lines 135-146; add prune near ~line 50)
- Modify: `config/config.yaml` (`trade_management.runner` block, ~lines 59-61)
- Test: `tests/unit/test_trade_manager.py` (add `RunnerTightenArmC` class)

**Interfaces:**
- Consumes: existing `TradeManager(logger, state_manager, risk_manager, config)`; `state_manager.get_ratchet_state(ticket) -> (r_level, init_entry, init_tp)`; `risk_manager.normalize_price(p, symbol)`; position dicts with keys `t,s,pf,vol,tp,sl`; prices dict `{symbol: price}`.
- Produces: instance fields `self.tighten_enabled: bool`, `self.giveback_frac: float`, `self.tight_trail_frac: float`, `self.runner_hwm: dict[int,float]`, `self.tightened: set[int]`. `sync_positions` behavior unchanged except the runner trail distance narrows one-way after a give-back trigger when enabled.

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/unit/test_trade_manager.py` (it reuses the module's existing `make_tm`, `pos`, `FakeState`, `FakeRisk`). Trade geometry: long entry 1.1000 / tp 1.1100 → range 0.0100, normal trail 0.00268, tight trail 0.00100, trigger 0.75×0.00268 = 0.00201.

```python
CFG_ON = {"trade_management": {"runner": {"enabled": True, "tighten_on_giveback": True}}}
CFG_OFF = {"trade_management": {"runner": {"enabled": True, "tighten_on_giveback": False}}}


class RunnerTightenArmC(unittest.TestCase):
    """Arm C: one-way runner-trail tighten on a give-back from the HWM.
    Long entry 1.1000 / tp 1.1100 (range 0.0100); r_level=3 (runner phase)."""

    def _tm(self, cfg):
        tm = make_tm(config=cfg)
        tm.state_manager.ratchets[101] = (3, 1.1000, 1.1100)  # r_level=3, entry, tp
        return tm

    def test_disabled_trail_unchanged(self):
        tm = self._tm(CFG_OFF)
        cmds = tm.sync_positions([pos(101, tp=0.0, sl=0.0)], {"EURUSD": 1.1090})
        self.assertEqual(len(cmds), 1)
        # normal trail 0.00268 -> 1.1090 - 0.00268 = 1.10632
        self.assertAlmostEqual(cmds[0]["sl"], 1.10632, places=5)
        self.assertNotIn(101, tm.tightened)

    def test_hwm_seeds_on_first_sight_no_trigger(self):
        tm = self._tm(CFG_ON)
        tm.sync_positions([pos(101, tp=0.0, sl=0.0)], {"EURUSD": 1.1090})
        self.assertAlmostEqual(tm.runner_hwm[101], 1.1090, places=5)
        self.assertNotIn(101, tm.tightened)          # give-back 0 on first sight

    def test_giveback_below_threshold_no_tighten(self):
        tm = self._tm(CFG_ON)
        tm.runner_hwm[101] = 1.1090                   # prior high
        cmds = tm.sync_positions([pos(101, tp=0.0, sl=0.0)], {"EURUSD": 1.1075})
        # give-back 0.0015 < 0.00201 -> not tightened, normal trail 0.00268
        self.assertNotIn(101, tm.tightened)
        self.assertAlmostEqual(cmds[0]["sl"], 1.10482, places=5)

    def test_giveback_triggers_tighten(self):
        tm = self._tm(CFG_ON)
        tm.runner_hwm[101] = 1.1090
        cmds = tm.sync_positions([pos(101, tp=0.0, sl=0.0)], {"EURUSD": 1.1065})
        # give-back 0.0025 >= 0.00201 -> tighten; tight trail 0.00100 -> 1.10550
        self.assertIn(101, tm.tightened)
        self.assertAlmostEqual(cmds[0]["sl"], 1.10550, places=5)

    def test_tighten_is_one_way(self):
        tm = self._tm(CFG_ON)
        tm.tightened.add(101)
        tm.runner_hwm[101] = 1.1090
        cmds = tm.sync_positions([pos(101, tp=0.0, sl=0.0)], {"EURUSD": 1.1200})
        # new high, but already tightened -> trail stays tight 0.00100 -> 1.11900
        self.assertIn(101, tm.tightened)
        self.assertAlmostEqual(cmds[0]["sl"], 1.11900, places=5)

    def test_short_side_symmetry(self):
        tm = make_tm(config=CFG_ON)
        tm.state_manager.ratchets[102] = (3, 1.1000, 1.0900)  # short, range 0.0100
        tm.runner_hwm[102] = 1.0910                            # prior low (HWM for short)
        cmds = tm.sync_positions([pos(102, tp=0.0, sl=0.0)], {"EURUSD": 1.0935})
        # give-back 0.0025 >= 0.00201 -> tighten; short trail adds: 1.0935 + 0.00100 = 1.09450
        self.assertIn(102, tm.tightened)
        self.assertAlmostEqual(cmds[0]["sl"], 1.09450, places=5)

    def test_prune_drops_closed_tickets(self):
        tm = self._tm(CFG_ON)
        tm.runner_hwm[999] = 1.2000
        tm.tightened.add(999)
        tm.sync_positions([pos(101, tp=0.0, sl=0.0)], {"EURUSD": 1.1090})
        self.assertNotIn(999, tm.runner_hwm)          # 999 not in the position list
        self.assertNotIn(999, tm.tightened)
        self.assertIn(101, tm.runner_hwm)             # 101 is live
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_trade_manager.RunnerTightenArmC -v`
Expected: FAIL — `AttributeError: 'TradeManager' object has no attribute 'tightened'` (and `runner_hwm`), because the fields and logic don't exist yet.

- [ ] **Step 3: Add config reads + state fields in `__init__`**

In `src/execution/trade_manager.py`, replace the current config block (lines 41-42):

```python
        mgmt = (config or {}).get('trade_management', {})
        self.runner_enabled = bool(mgmt.get('runner', {}).get('enabled', False))
```

with:

```python
        mgmt = (config or {}).get('trade_management', {})
        runner_cfg = mgmt.get('runner', {})
        self.runner_enabled = bool(runner_cfg.get('enabled', False))
        # Arm C (validated 2026-07-11): one-way runner-trail tighten on a give-back.
        self.tighten_enabled = bool(runner_cfg.get('tighten_on_giveback', False))
        self.giveback_frac = float(runner_cfg.get('giveback_frac', 0.75))
        self.tight_trail_frac = float(runner_cfg.get('tight_trail_frac', 0.10))
        self.runner_hwm = {}      # ticket -> best price in trade direction (in-memory)
        self.tightened = set()    # tickets whose trail has been tightened (one-way)
```

- [ ] **Step 4: Add close-pruning at the top of `sync_positions`**

Immediately after `commands = []` and `now = time.time()` (currently lines 49-50), insert:

```python
        # Prune per-ticket runner state for tickets no longer open (avoids growth).
        live_tickets = {int(p.get('t', 0)) for p in position_list_json}
        self.runner_hwm = {t: v for t, v in self.runner_hwm.items() if t in live_tickets}
        self.tightened = {t for t in self.tightened if t in live_tickets}
```

- [ ] **Step 5: Replace the runner-trail block with the arm-C version**

Replace the current runner-trail block (lines 135-145):

```python
                # --- RUNNER TRAIL (post-L3, runner mode only) ---
                if self.runner_enabled and r_level >= 3:
                    trail_dist = range_size * (self.L3_FIB - self.L2_FIB)
                    candidate = (curr_price - trail_dist) if is_long else (curr_price + trail_dist)
                    candidate = get_sl(candidate)
                    curr_sl = float(pos.get('sl', 0))
                    tighter = (candidate > curr_sl) if is_long else (curr_sl == 0 or candidate < curr_sl)
                    if tighter:
                        commands.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                         "sl": candidate, "tp": curr_tp, "comment": "Runner Trail"})
                        self.command_cooldowns[ticket] = now
```

with:

```python
                # --- RUNNER TRAIL (post-L3, runner mode only) ---
                if self.runner_enabled and r_level >= 3:
                    base_trail = range_size * (self.L3_FIB - self.L2_FIB)

                    # Track the runner-leg high-water mark (seed on first sight).
                    prev_hwm = self.runner_hwm.get(ticket, curr_price)
                    hwm = max(prev_hwm, curr_price) if is_long else min(prev_hwm, curr_price)
                    self.runner_hwm[ticket] = hwm

                    # Arm C: one-way tighten once a pullback gives back
                    # >= giveback_frac of the trail distance from the HWM.
                    if self.tighten_enabled and ticket not in self.tightened:
                        give_back = (hwm - curr_price) if is_long else (curr_price - hwm)
                        if give_back >= self.giveback_frac * base_trail:
                            self.tightened.add(ticket)

                    trail_dist = (range_size * self.tight_trail_frac
                                  if ticket in self.tightened else base_trail)

                    candidate = (curr_price - trail_dist) if is_long else (curr_price + trail_dist)
                    candidate = get_sl(candidate)
                    curr_sl = float(pos.get('sl', 0))
                    tighter = (candidate > curr_sl) if is_long else (curr_sl == 0 or candidate < curr_sl)
                    if tighter:
                        commands.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                         "sl": candidate, "tp": curr_tp, "comment": "Runner Trail"})
                        self.command_cooldowns[ticket] = now
```

- [ ] **Step 6: Run the arm-C tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_trade_manager.RunnerTightenArmC -v`
Expected: PASS (all 7 cases).

- [ ] **Step 7: Add the config keys (ships OFF)**

In `config/config.yaml`, the current runner block is:

```yaml
trade_management:
  runner:
    enabled: true
```

Replace it with:

```yaml
trade_management:
  runner:
    enabled: true
    # Arm C (validated 2026-07-11, docs/research/2026-07-11-pullback-monetizer-overlay-results.md):
    # once a runner pullback gives back >= giveback_frac of the trail distance from its
    # high-water mark, tighten the trail from 0.268x to tight_trail_frac x range (one-way).
    # Ships OFF — enable for the FBS demo-forward-test before going live.
    tighten_on_giveback: false
    giveback_frac: 0.75
    tight_trail_frac: 0.10
```

- [ ] **Step 8: Run the full TradeManager suite (no regressions) + full unit suite**

Run: `.venv/bin/python -m unittest tests.unit.test_trade_manager -v`
Expected: OK — the existing ratchet/trail tests still pass (disabled-path behavior unchanged) plus the 7 new cases.

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: OK.

- [ ] **Step 9: Commit**

```bash
git add src/execution/trade_manager.py config/config.yaml tests/unit/test_trade_manager.py
git commit -m "feat(trade-mgmt): arm C one-way runner-trail tighten on give-back (config-gated, off)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Why one task:** config reads, the two state fields, HWM tracking, the trigger, trail selection, and pruning are a single mechanism — a reviewer can't accept half. Keeping them together also avoids shipping "unused state" in an intermediate commit.
- **The 2s cooldown is why the tests pre-seed `runner_hwm` and call `sync_positions` once** instead of simulating multiple ticks: a second sync within 2s of a command is skipped by `command_cooldowns`. Pre-seeding the HWM reproduces "a prior high, then this pullback" in a single call. The HWM update runs first each call and keeps the higher (long) / lower (short) value, so the seeded high survives the pullback tick.
- **Disabled-path proof:** `test_disabled_trail_unchanged` asserts the exact SL from the `0.268` trail, guaranteeing backward compatibility — that assertion must stay.
- **Live vs rig detection:** the rig measured give-back from intra-bar highs/lows; live uses discrete heartbeat `curr_price`. This is expected and validated separately by the demo-forward-test — do not try to reconstruct intra-bar extremes here.
- **Not in scope:** enabling the flag, the demo-forward-test, and any go-live step. Config ships `false`; the operator flips it on for the demo run per the spec.
