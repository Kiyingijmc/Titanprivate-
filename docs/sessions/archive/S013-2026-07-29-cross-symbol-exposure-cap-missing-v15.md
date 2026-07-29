---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S013"
date:          "2026-07-29"
slug:          "cross-symbol-exposure-cap-missing-v15"
parent_session: "none"
task_domain:   "risk_management"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S013 · 2026-07-29 · "cross-symbol-exposure-cap-missing-v15"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Add portfolio-wide aggregate open-risk cap to the execution-time exposure gate

**Why it matters / what it unblocks:** Closes v15 Plan 10 "Advisory A": ExposureManager (src/risk/exposure.py) already blocks new trades on position count and pairwise correlation, but nothing sums $ risk across all currently open positions before allowing a new one — so total portfolio risk can silently exceed intended limits even when every individual trade passes its own gates.

**Exact scope (what "doing this task" means):**
- Add config key `risk.account.max_total_open_risk_pct` under the existing `risk:account:` block (config/config.yaml:32-38), with a conservative documented default, alongside the existing `max_daily_drawdown_pct`/`max_global_exposure_pct` keys.
- Add a method that sums risk-in-$ across all currently open positions by calling the existing `RiskManager.money_for_move(symbol, abs(entry-sl), lots)` (src/risk/risk_manager.py:232-245) once per open position.
- Extend `ExposureManager.check_exposure` (src/risk/exposure.py) — or add a sibling method on the same class — to accept the proposed trade's risk-in-$ (computed by the caller via `money_for_move`) plus the aggregate open risk-in-$, and return `allowed=False` with a distinguishable reason string when `(aggregate_open_risk + proposed_risk) / current_equity * 100 > max_total_open_risk_pct`.
- Wire the new check into `SystemController._execute_signal` (src/core/system_controller.py:379-385), alongside the existing `exposure_manager.check_exposure(...)` call, computing proposed risk via `risk_manager.money_for_move(symbol, abs(p-sl), lot)` and aggregate open risk from `self.current_open_positions` (heartbeat list per position: `s` symbol, `p` open price, `sl`, `vol` — see `Titan_Gateway.mq5:194`; per-position risk = `money_for_move(s, abs(p - sl), vol)`). A blocked trade must log via the existing `RISK`/`EXPOSURE` event pattern (system_controller.py:381-384).
- Fail-safe edge handling (repo convention — never guess): (a) an open position with `sl == 0` (no stop, e.g. externally opened) has undefined risk-to-stop → the gate must treat the aggregate as un-computable and BLOCK the new trade with a distinguishable reason (do not skip the position or invent a proxy); (b) `current_equity <= 0` (no heartbeat yet) → BLOCK with a distinguishable reason, never divide by zero.
- TDD: write failing unit tests first for the new aggregate-risk method and the new gate path, then implement.
- Add regression tests (new file `tests/unit/test_risk_manager_exposure_cap.py`, or extend an existing `test_risk_manager_*`/exposure test module) covering: aggregate risk under cap → allowed; aggregate + proposed risk over cap → blocked with reason; empty open-positions list (first trade) never blocked by this check; a boundary-value case at exactly the cap; an open position with `sl == 0` → blocked (fail-safe); `current_equity <= 0` → blocked (fail-safe).

**Explicitly OUT of scope (do NOT touch this session):**
- The blueprint's correlation-bucket / `net.risk_clusters` cap (blueprint §9.1 item 4, second half) — requires FeatureBus `net.*` pack work not yet built; stays deferred per docs/superpowers/plans/2026-07-13-plan-05-arbiter-v15_2.md:7.
- Any change to `Arbiter._apply_caps` (src/arbiter/arbiter.py:248-278) or its `max_positions_per_symbol`/`max_total_positions` counters — this session extends only the ExposureManager/system_controller execution-time gate; the two-layer duplication between Arbiter caps and ExposureManager caps is not reconciled here.
- `CorrelationManager` (src/risk/correlation.py) pairwise threshold/logic — untouched.
- The currency-substring "saturation" heuristic in `ExposureManager` — untouched.
- Ratifying the final production value of `max_total_open_risk_pct` — ship a conservative documented default; final tuning is an operator decision post-deploy.
- Any FeatureBus schema or `net.*` additions.

**Relevant project docs / decisions:** docs/research/2026-07-12-trading-os-blueprint.md §9.1 item 4; docs/superpowers/plans/2026-07-13-plan-05-arbiter-v15_2.md:7 (Plan 10 deferral); docs/superpowers/specs/2026-07-14-plan-07-gyroscope-gate-design.md:36 (Advisory A origin); S012 archive note (Advisory A fenced off)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `risk.account.max_total_open_risk_pct` present in config/config.yaml with a documented default.
- [ ] Aggregate-open-risk computation added (RiskManager or ExposureManager), reusing `money_for_move`, covered by a red-first unit test.
- [ ] New gate blocks a proposed trade when aggregate open risk + proposed risk exceeds the cap and allows it when under, including a boundary-value test at the cap.
- [ ] Fail-safe edges pinned by red-first tests: `sl == 0` open position → blocked; `current_equity <= 0` → blocked; neither path divides by zero or guesses a risk value.
- [ ] Gate wired into `SystemController._execute_signal` alongside the existing `exposure_manager.check_exposure` call; blocked trades log a distinguishable RISK/EXPOSURE reason string.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path, touching only the files named above; no changes to Arbiter, CorrelationManager, or FeatureBus.
