---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S020"
date:          "2026-08-08"
slug:          "enable-footgun-registry-enable-ignores-the"
parent_session: "none"
task_domain:   "api"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S020 · 2026-08-08 · "enable-footgun-registry-enable-ignores-the"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Close the /enable footgun: honor config `enabled:false` veto + require a confirmed prior slope before ma_slope_baseline signals

**Why it matters / what it unblocks:** `registry.enable(sid, allow_research=True)` (`src/strategies/registry.py:107-128`) skips the `params.get("enabled", True)` check that `activate_eligible()` enforces (`registry.py:95`), so the Telegram `/enable ma_slope_baseline confirm` path (`src/ops/telemetry.py:198-206`) can force-activate a `status:research` strategy the config explicitly disabled. Combined with `ma_slope_baseline`'s unscoped `pairs` (unscoped = all 12 configured symbols, `base_strategy.py:36`) and its cold-start flip bug (`_prev_sign` defaults to `0`, so the very first nonzero slope reading looks like a "flip" and fires — `ma_slope_baseline.py:34-36`), one operator-confirmed command can currently place 12 immediate market orders from the least-vetted strategy in the repo.

**Exact scope (what "doing this task" means):**
- In `src/strategies/registry.py`, make `enable()` honor the same `enabled:false` veto `activate_eligible()` already enforces: after the research/status gate and before the state-transition check, if `self._params_by_id.get(strategy_id, {}).get("enabled", True) is False`, return a message (no state change, no `StrategyActivated` publish) rather than activating — analogous wording to the existing unknown-id / illegal-transition returns (e.g. `f"Cannot enable '{strategy_id}': disabled via config (enabled: false)."`).
- In `src/strategies/models/ma_slope_baseline.py::on_new_candle`, change the fire condition so a signal requires an *established* previous sign: only signal when `prev != 0 and sign != 0 and sign != prev`; when `prev == 0` (cold start, or previous slope was flat), just record the new sign and return `None` without signaling. Keep the existing `sign == 0` (flat) suppression.
- In `config/config.yaml`, set `ma_slope_baseline.enabled: false` (currently `true` at line 189) so the manifest's `status: research` + the enable-veto fix jointly require an explicit, non-vetoed `/enable ma_slope_baseline confirm` before this strategy can ever go ACTIVE.
- Add/extend unit tests:
  - `tests/unit/test_registry.py` or `tests/unit/test_registry_guards.py`: a `status:research` (or `live`) manifest with `params_by_id[...]["enabled"] = False`; assert `enable(sid, allow_research=True)` leaves state at `LOADED`/unchanged, returns a message (not silently truthy-empty), and publishes nothing.
  - `tests/unit/test_ma_slope_baseline.py`: a new case asserting the *first* candle sequence a symbol ever sees produces no signal even when the initial slope is already nonzero (cold start with `_prev_sign` unset), and that a genuine reversal (established nonzero sign → opposite nonzero sign) still fires. Update the two existing flip tests (`test_uptrend_flip_emits_market_buy_once`, `test_downtrend_flip_emits_sell`) if their flat-then-trending fixture no longer produces a signal under the new semantics — rebuild their `closes` fixtures so they first establish a nonzero prior sign, then flip it, so the "fires exactly once" assertion still targets a genuine reversal.

**Explicitly OUT of scope (do NOT touch this session):**
- No change to `activate_eligible()` — it already honors the veto correctly and is not implicated.
- No change to `_dispatch_mgmt_command`, trade management, or any risk/sizing code.
- No change to the Telegram `/enable` command surface itself (`telemetry.py:198-206`) — the fix belongs in the registry, not the command parser.
- No broader audit or fix of other strategies' cold-start behavior (e.g. other `_prev_*`-style memory patterns) beyond `ma_slope_baseline`.
- No change to `disable()`, manifest schema, or the FSM's state names.

**Relevant project docs / decisions:** Related: audit finding 2026-08-07 (strategies layer); Trading-OS plugin/registry design (docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md).

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `registry.enable(sid, allow_research=True)` on a manifest whose `params_by_id[sid]["enabled"] is False` returns a message, leaves `state_of(sid)` unchanged, and emits no `StrategyActivated` event.
- [ ] `registry.enable()` behavior for `enabled: True`/absent (the default) is unchanged — all existing `TestEnableDisable` cases in `tests/unit/test_registry.py` and `tests/unit/test_registry_guards.py` still pass unmodified.
- [ ] `MaSlopeBaseline.on_new_candle` returns `None` on a symbol's first-ever nonzero-slope reading (no prior established sign), and still fires exactly once on a genuine sign reversal (established nonzero prev → different nonzero sign).
- [ ] `config/config.yaml`'s `ma_slope_baseline.enabled` is `false`.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
