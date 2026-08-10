---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S024"
date:          "2026-08-09"
slug:          "one-strategy-exception-is-bot-fatal"
parent_session: "none"
task_domain:   "execution"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S024 · 2026-08-09 · "one-strategy-exception-is-bot-fatal"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Contain per-strategy exceptions in `_run_strategies` and stop swallowing bias/liquidity faults silently

**Why it matters / what it unblocks:** One malformed candle in any single symbol/strategy currently propagates out of `_run_strategies` to the main loop's top-level handler, which Telegrams FATAL SYSTEM CRASH and re-raises — killing the whole async loop, including in-trade management for every *other* open position across all symbols. Meanwhile a persistent H1 data fault in `BiasEngine`/`LiquidityEngine` is swallowed to `('NEUTRAL', {})` with logging commented out, so the bias filter silently degrades (NEUTRAL trades both directions) with zero operator visibility. The fragility is inverted: code faults are bot-fatal, data faults are invisible.

**Exact scope (what "doing this task" means):**
- In `src/core/system_controller.py::_run_strategies`, wrap the `decision = await strat.on_new_candle(enriched_df, context=ctx)` call (currently line 1696, inside `for strat in active:`) in a local `try/except Exception`, so one strategy's exception for one symbol/bar cannot propagate to the loop's outer `except Exception` (line 630) and kill the process.
- On catch: journal the failure via `self.logger.log_event("ERROR", strat.name, ...)` including the symbol and the exception message/type, then `continue` to the next strategy in `active` — do not `return`/abort the rest of the loop, and do not silently pass with no trace.
- Send an operator-visible WARN (not FATAL) via the existing Telegram path (`self.telemetry`) for a strategy exception, throttled per-strategy-per-symbol the same way `_alert_uncomputable_book` throttles (reuse that interval-gating pattern; do not spam a Telegram per bar if a strategy is broken for an extended period).
- In `src/analysis/bias_engine.py::get_bias_context`'s `except Exception as e:` (lines 66-69) and `src/analysis/liquidity.py::get_pd_arrays`'s `except Exception as e:` (lines 67-70): uncomment/replace the dead `print` with a real WARN-level log call via a module-level `logging.getLogger(__name__)` (the pattern already used in `src/ops/web/server.py`) so a persistent H1 data fault is visible in the log stream instead of silently degrading to `NEUTRAL`/`{}` with zero trace.
- Add/extend unit tests: (a) a strategy whose `on_new_candle` raises does not propagate past `_run_strategies` and other active strategies/symbols still run afterward; (b) `BiasEngine.get_bias_context` and `LiquidityEngine.get_pd_arrays` emit a log record on the exception path (assert via `assertLogs`).

**Explicitly OUT of scope (do NOT touch this session):**
- Redesigning the bias/liquidity NEUTRAL fallback behavior itself (still returns `NEUTRAL`/`{}` on fault — only the *visibility* of the fault changes, not the trading behavior).
- Adding a strategy-health circuit breaker, auto-disable, or retry/backoff logic for a repeatedly-failing strategy.
- Touching the outer main-loop `except Exception` at line 630 (`FATAL SYSTEM CRASH`) — it stays as the last-resort net for genuinely unexpected top-level errors.
- Any change to `_dispatch_mgmt_command`, trade management, or the EA/MQL5 side.
- Threading a real logger object through `FeatureBus`/`ResourceSpec` — the bias/liquidity fix uses a plain module logger, not an architectural change to the feature bus.

**Relevant project docs / decisions:** audit 2026-08-07 signals D6+D7 (full-system-audit); no ADR — bug fix within existing error-handling conventions (cf. `_alert_uncomputable_book` throttle pattern, `src/ops/web/server.py` module logger pattern)

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `_run_strategies` catches an exception raised by one strategy's `on_new_candle` for one symbol without raising past the function; a journaled ERROR log entry is written naming the strategy and symbol.
- [ ] Other strategies in the same `active` list (and subsequent symbols/bars) continue to run normally after one strategy raises — verified by a new/updated unit test in `tests/unit/`.
- [ ] A strategy exception sends a throttled Telegram WARN via `self.telemetry`, not the FATAL SYSTEM CRASH message, and does not re-raise to the outer loop.
- [ ] `BiasEngine.get_bias_context`'s except-path logs a WARNING (visible via `assertLogs` in a new/updated unit test) instead of a commented-out `print`.
- [ ] `LiquidityEngine.get_pd_arrays`'s except-path logs a WARNING (visible via `assertLogs` in a new/updated unit test) instead of a commented-out `print`.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
