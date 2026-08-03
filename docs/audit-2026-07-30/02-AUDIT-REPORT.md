# Titan — Complete Technical Audit

**Repository:** `https://github.com/Kiyingijmc/Titanprivate-`
**Commit range:** `7dd9527` → `cc59155` · 356 commits · 22 branches
**Audit date:** 2026-07-30
**Method:** Four-perspective adversarial review. All findings carry file and line references into the audited commit range.

---

## Table of contents

| § | Section | Phase |
|---|---|---|
| 1 | Reconnaissance & Ground Truth | 1 |
| 2 | Structure & Architecture | 1 |
| 3 | Risk Management | 2 |
| 4 | Entries & Exits | 2 |
| 5 | Execution Dynamics & Logistics | 3 |
| 6 | Strategies, Backtesting & Validation | 3 |
| 7 | Journaling & Observability | 4 |
| 8 | Telegram Command & Communications | 4 |
| 9 | Security & Vulnerability Assessment | 5 |
| 10 | Operations, Testing & Deployment | 5 |
| 11 | Innovation & Research | 6 |
| 12 | Synthesis | 6 |

Panel disagreements are preserved at the end of each phase rather than resolved into false consensus.

---

# SECTION 1 — RECONNAISSANCE & GROUND TRUTH

## 1.1 File inventory

| Area | Files | LOC | Responsibility |
|---|---|---|---|
| `src/` | 67 | 7,833 | **The live bot.** v14.4 |
| `tradebot/` | 11 | 2,746 | v15 greenfield rewrite — **dead code at runtime** |
| `tests/` | 79 | 12,074 | unittest suite (682 tests) |
| `frontend/` | 90 | 6,484 | React control GUI |
| `bridge/` | 9 | 1,218 | FastAPI MT5 HTTP bridge (Windows) |
| `mql5_bridge/` | 10 | 1,809 | Expert Advisor + vendored ZMQ bindings |
| `scripts/` | 15 | 2,407 | Research and ops tooling |
| `docs/` | 116 | 34,171 | Plans, specs, session reviews, research |

Inside `src/`: `core/` 2,073 · `ops/` 1,366 · `analysis/` 1,082 · `execution/` 790 · `risk/` 629.

**Largest single file: `src/core/system_controller.py` — 1,119 LOC, 40 methods.** It is simultaneously the main loop, the message router, the risk gate, the reconciler, the strategy runner, the reporter, the Telegram command target, and the GUI's mutation surface. God object; see §2.3.

Second largest: `tradebot/core/event_log.py` — 1,238 LOC, imported by nothing outside tests.

## 1.2 Dependency graph — the headline structural fact

**`src/` and `tradebot/` are not two overlapping packages. They are two disconnected programs.**

```
grep -rn "from tradebot" src/ main.py scripts/ bridge/   → 0 results
grep -rn "from src"     tradebot/                        → 0 results
```

`tradebot/` (2,746 LOC: `event_log`, `projection`, `recovery`, `clock`, `bus`, `sta`, pydantic `config/schema.py`) is imported **only by tests** — and by ~3,900 LOC of them (`test_tradebot_event_log.py` 928, `test_tradebot_properties.py` 880, `test_tradebot_recovery.py` 435). `pyproject.toml:8` states it plainly: *"independent of the src/ Titan v14 bot."*

Consequence: **roughly a third of the test suite tests code that cannot affect a live trade**, while the code that does place trades has thinner coverage. This single fact recurs throughout the audit.

Live import graph (`system_controller.py:24–47`): 22 direct internal imports fanning into `bridge_zmq`, `risk_manager`, `exposure`, `trade_manager`, `state_manager`, `telemetry`, `feature_bus`, `arbiter`, `signal_grader`, `bus`, `event_journal`, `health`, `jsonlog`. Research-only, off the trade path: `src/data/lake.py` (340), `src/research/kernel_replay.py` (212), `src/analysis/kalman_drift.py` (183).

## 1.3 Critical path trace

| Step | Location | Status |
|---|---|---|
| Tick/bar arrival | `bridge_zmq.py:88` `poll_data` (ZMQ PULL, 500-msg drain) | Present |
| Route | `system_controller.py:601` `_process_incoming_data` | Present |
| Feature enrich | `feature_bus.py`, `packs/smc_pack.py` | Present |
| Signal | `strategies/models/silver_bullet.py` `on_new_candle` | Present, one strategy |
| Grade gate | `analysis/signal_grader.py` | Present |
| Arbitration | `arbiter/arbiter.py` | Present |
| Sizing | `risk_manager.py:129` `calculate_lot_size` | Present, fails safe to 0 |
| Exposure gate | `exposure.py` + `risk_manager.py:287` `aggregate_open_risk` | Present, fails closed |
| Order construct | `system_controller.py:449–455` | Present, **no client order ID** |
| Bridge send | `bridge_zmq.py:70` `send_order_reliable` | Present, **not idempotent** |
| MT5 execute | `Titan_Gateway.mq5:152` | Present |
| Fill confirm | `EXECUTION:OPENED` + heartbeat backfill | Present |
| Journal write | `state_manager.register_order`, `ops/event_journal.py` | Present |
| Telegram notify | `telemetry.notify_signal:56` | Present |

**The chain is complete end to end** — considerably more than "unfinished" implies.

## 1.4 State locations and restart survival

| State | Where | Survives restart? |
|---|---|---|
| `active_orders`, `trade_history` | `data/db/trade_state.db` (SQLite WAL) | **Yes** |
| `audit_log` | `data/db/titan_core.db` | Yes |
| Event journal | `data/journal/` (JSONL) | Yes |
| GUI overrides | `config/overrides.yaml` | Yes |
| `market_data` (OHLC buffers) | in-memory `MultiTimeframeStore` | No — rebuilt by `_perform_warmup:915` |
| `symbol_specs` (tick value/size) | in-memory `risk_manager.symbol_specs` | No — **until `HISTORY` arrives, sizing returns 0 and nothing trades** |
| `_reserved_risk`, `pending_signal_meta` | in-memory dicts (`:157`, `:168`) | No |
| `live_prices`, `current_open_positions` | in-memory (`:109–111`) | No |
| **`day_start_equity`** | **in-memory only (`risk_manager.py:51`)** | **No — see RISK-01, a Critical finding** |
| `runner_hwm`, `tightened` | in-memory (`trade_manager.py:48–49`) | No |
| Truth of positions | **the MT5 terminal** | Yes |

Startup reconciliation (`_perform_reconciliation:382`) exists and corroborates DB rows against heartbeat `pos` **and** `orders`. It runs on a 60-second timer (`:322`) and is **not** part of the boot sequence.

## 1.5 Entry points — five, three stale

1. **`main.py`** — the real bootstrap (82 LOC).
2. **`deploy/systemd/titan-live.service`** → `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro`. Directory name ≠ repository name.
3. **`deploy/systemd/titan-demo.service`** → `Titan_demo`, with `:8` warning it is not yet set up.
4. **`RUN_TITAN.bat`** — **stale.** Runs `test_telegram.py` as a preflight, then `python main.py` bare. On non-zero exit it prints `[CRASH]` and `pause`s — no restart.
5. **`AUTO_START.bat`** — **stale and contradictory.** Hardcodes `C:\Program Files\MetaTrader 5\terminal64.exe`, waits a fixed 120 s, calls `RUN_TITAN.bat`. But `CLAUDE.md:7` states the Python core runs in **WSL/Linux** and only MT5 needs Windows. Two mutually exclusive deployment stories.
6. **`frontend/`** — Vite dev server, plus embedded FastAPI on `:8770` (`_start_gui:246`).

Related: `config/config.yaml:21` still carries `mt5_path` for a `taskkill`-based watchdog that `CLAUDE.md:48` admits no-ops on Linux — yet `run:332` calls `_reboot_terminal()` after 60 s of heartbeat silence. **On the documented Linux deployment, the watchdog is a no-op called repeatedly and forever.**

## 1.6 `boot_crash.log` — resolved, but instructive

33 lines, one crash, `2026-01-05 01:51:08`, from `C:\Users\JMC\Desktop\bots\Titan_ICT_Bot_v14_3pro`.

**Root cause** at `risk_manager.py:90` (then): `precision = len(str(float(tick_size)).split('.')[1])` → `IndexError`. For a 5-digit FX symbol, `str(float(0.00001))` is `'1e-05'`, which contains no `.`. **Every 5-decimal pair crashed the process mid-`_execute_signal`.**

**This is fixed.** Current `risk_manager.py:96–104` uses `-Decimal(str(tick_size)).as_tuple().exponent`, with a dedicated branch `harden/normalize-price-crash` and `tests/unit/test_risk_manager_normalize_price.py`.

Two residuals:
- The file is **committed**, leaking a Windows username and desktop path.
- The failure mode was architectural, not arithmetic: an `IndexError` in a pure price-formatting helper propagated through `_run_strategies` → `run()` → `main()` and **killed the process**. Nothing contained it. **That containment gap is still open** (§2.6) and is the engine behind RISK-01.

## 1.7 Documentation vs code

`CLAUDE.md` is unusually accurate — better than most production repositories. Verified correct: ZMQ topology and ports, Python-binds/EA-connects, fail-safe sizing, `Decimal` precision, reconciliation over `pos`+`orders`, one approved strategy.

Disagreements, trusting the code:

| Claim | Reality |
|---|---|
| `CLAUDE.md:49` "TITAN_ENV … purged" | `.env.example:26` still ships `TITAN_ENV=PROD` |
| `CLAUDE.md:39` "Dead code purged 2026-07-12" | `crt`/`ict_ote`/`unicorn` `.pyc` files still tracked |
| `main.py:8` `STATUS: PRODUCTION READY` | This is the file whose crash handler wrote `boot_crash.log`. `CLAUDE.md:50` correctly disowns these headers — **delete them** |
| `config.yaml:36` `max_global_exposure_pct` "treated as INTEGER COUNT" | A field named `_pct` holding a count of positions. Rename it |
| `CLAUDE.md:21` documents `tests/backtest/backtest_engine.py` as the backtest | That harness measures a configuration the repository explicitly rejects (STRAT-04) |
| `docs/RESUME.md:4` "working branch not merged to main" | It was merged. `:23` cites two files that no longer exist |

---

# SECTION 2 — STRUCTURE & ARCHITECTURE

## 2.1 Separation of concerns — the risk gate holds

**Can a strategy place an order without passing risk? NOT FOUND — no such path exists.**

Verified: strategies return a dict from `on_new_candle`; only `_execute_signal:398` constructs an order payload; only `bridge.send_order_reliable` reaches the EA; no other call site of `send_order_reliable` exists on the trade path. The single funnel enforces, in order:

1. sizing (`:416`) — which internally calls `check_can_trade`
2. count/correlation exposure (`:419`)
3. book-wide dollar risk (`:441`)

Both gates `return` on failure. **This is the strongest thing in the codebase and it deserves to be stated plainly.**

Caveat: the funnel is a *1,119-line method container*, not an enforced boundary. Nothing structural prevents a future `send_order_reliable` call elsewhere. It is a convention, not an invariant.

## 2.2 Bridge protocol — Critical

`src/execution/bridge_zmq.py`, 129 LOC. Five findings.

### ARCH-01 [CRITICAL] — No idempotency key. A timeout-then-retry can double-fill.

`bridge_zmq.py:70–83`: on REQ timeout the socket is reset and `False` returned. `_execute_signal:471` logs `"Order handshake FAILED"` and returns. **But the EA may already have filled the order** — the timeout only proves the reply did not arrive within 2500 ms.

There is no client order ID anywhere in the payload (`:449–455`: `symbol`, `cmd`, `side`, `price`, `sl`, `tp`, `volume`, `magic`, `comment`, `strat`). `magic` is the constant `88000` on every order. **Neither side can distinguish a retry from a new order.**

Consequences, all live:
- `_reserve_risk:462` is skipped, so the book-risk cap under-counts a position that exists
- `pending_signal_meta` is skipped, so `EXECUTION:OPENED` arrives without metadata
- `notify_signal` is skipped — the operator is blind to a position that exists
- the strategy can re-fire on the next bar

Partial self-healing exists: SL/TP were in the original payload so the position is protected, and the heartbeat backfills entry/TP within ~5 s. The residual damage is real but bounded.

**Fix:** generate a UUID per intent, place a short hash in `comment` (MT5 comments are ~31 chars), have the EA reject a comment it has already seen, and **on timeout query state — never resend blind.**

### ARCH-02 [CRITICAL] — No schema, no version, no sequence numbers.

Serialization is `json.dumps(..., separators=(',',':'))` (`:57`) with untyped dicts on both sides. `CLAUDE.md:37` documents the message types in prose; nothing validates them. A field rename in Python and a stale EA binary (`CLAUDE.md:37`: "requires a **manual recompile in MetaEditor**") disagree silently.

### ARCH-03 [MEDIUM] — Silent message loss.

`poll_data:110–119`: the sticky-packet splitter `break`s on `JSONDecodeError` and **discards the remainder with no log.** A truncated `HEARTBEAT` means positions vanish from `current_open_positions` for a cycle — and that dict is the input to both reconciliation and the risk cap. `:127` then wraps everything in `except Exception: return batch`, making a ZMQ failure indistinguishable from a quiet market.

### ARCH-04 [HIGH] — Bind failures are non-fatal.

`:26`, `:37`, `:54` catch `ZMQError`, `print`, and continue. `_boot_sequence:781` then `return True` regardless. If a port is held — a stray process, or **a second bot instance** — the bot boots with a dead socket and hangs in `_wait_for_bridge_connection:375` forever. It should crash.

### ARCH-05 [HIGH] — Weak ack, no retry policy.

`:75`: `reply.get('status') == 'OK' or reply.get('ticket', 0) > 0`. No nack taxonomy — requote, rejection, insufficient margin and invalid stops all collapse into `False`. **No retry at all**, so a transient failure is a permanently missed trade and a permanent rejection is indistinguishable from it.

## 2.3 God object, globals, circular imports

- **`system_controller.py`: 1,119 LOC, 40 methods.** Recommended decomposition: `MarketDataRouter`, `OrderGateway`, `Reconciler`, `ReportScheduler`.
- **Circular imports avoided by deferring imports inside functions** — `:202` (`config_layer`), `:253–255` (GUI), `:795` (registry). Works, but papers over a layering problem: `core` importing `ops.web` means the trading kernel depends on its own UI.
- **Global mutable state:** `self.config` is a shared dict object mutated in place. `_apply_runtime_setting:53–68` walks and assigns; its docstring states *"RiskManager/TradeManager hold the SAME config dict object."* See §3.1 RISK-13 for why this is only half true.
- **Defensive `getattr` in the risk path** — `:414`, `:433`, `:392` — with comments explaining that unit-test fixtures build controllers via `object.__new__(SystemController)`, bypassing `__init__`. **The production risk path has been softened to accommodate test fixtures.** `:414–415`: a missing `throttle_factor` yields `risk_mult = 1.0` — silently unthrottled. This is backwards; fix the fixtures, not the gate.

## 2.4 Configuration — no schema validation on the live path

`_load_config:198` → `config_layer.load_layered_config` (35 LOC): YAML defaults, deep-merged with `overrides.yaml`, returned as a **raw dict.** No schema, no type checking, no range checking, no required-key check.

Precedence is **defaults → overrides file.** No env layer, no CLI layer. Secrets arrive separately via `python-dotenv` (`:194`) — good separation, but nothing validates that `TELEGRAM_TOKEN` exists.

**Fail-fast is partially inverted.** `config_layer.py:26–34` deliberately swallows a corrupt `overrides.yaml` and falls back to defaults, commented *"a bad override must never wedge startup."* For a GUI-written file that is defensible — but if the operator lowered `risk_per_trade_pct` via the GUI and the file corrupts, **the bot silently resumes at the higher default risk.**

**The bitter part:** `tradebot/config/schema.py` is 490 LOC of pydantic validation with `tests/unit/test_config_schema.py` (230 LOC) proving it works — **and the live bot does not import it.** The fix is already built and wired to the wrong program.

## 2.5 Concurrency model — single event loop, no threads

> **Correction issued during audit.** An earlier finding claimed GUI settings writes could race the trading loop mid-decision. That was wrong. `server.py:169` runs uvicorn as `asyncio.create_task(server.serve(...))` — a coroutine on the controller's **own event loop.** There are no threads anywhere in the live system.

Consequences:

- **Safe:** the risk-decision block in `_execute_signal` (`:416` sizing → `:419` count gate → `:435` aggregate → `:441` total-risk gate) contains **no `await`** and is therefore atomic under cooperative scheduling. Mutations of primitives cannot tear.
- **Not safe (CTRL-06):** command handlers are `create_task`'d (`telemetry.py:131`) and interleave at await boundaries. `/enable` and `/disable` mutate the registry while `strategy_ttls` — built once at `_init_strategies:809` — is not rebuilt, so a runtime-enabled strategy gets the 7200 s default TTL instead of its timeframe-derived one. For an H1 strategy that is 2 h instead of 12 h: **its resting limits are cancelled 10 hours early.**
- **Not safe:** `/panic` can set `EMERGENCY` between the risk gates and the `await send_order_reliable` at `:457`. That send proceeds. **Panic does not cancel an in-flight order submission.**
- **Shared-loop coupling:** a slow GUI request delays trading and vice versa. `/api/history` runs a SQLite query on the loop.

**Fix:** one `asyncio.Lock` held across `_execute_signal` and the capital-affecting command handlers closes both remaining issues.

## 2.6 Error handling philosophy

11 bare `except:` and 51 `except Exception:` across `src/`, `tradebot/` and `bridge/`. The ones that matter:

- **`run():368–371`** — catches everything, Telegrams `☠️ FATAL SYSTEM CRASH`, then `raise`s. A single unhandled exception anywhere in tick handling **kills the loop with positions open.** No shutdown handler, no flatten, **no SIGTERM handling anywhere** (`grep signal` → nothing). systemd `Restart=on-failure` restarts into the 60-second reconciliation gap — and into a reset drawdown anchor (RISK-01).
- **`bridge_zmq.py:67`** `except Exception: return False` — a failed PUSH (`MODIFY`, `CLOSE_POS`, `CANCEL`) returns `False`, and **no call site checks it.**
- **`state_manager.py:289`, `audit_logger.py:121`** — `except: pass` in `__del__`/close. Acceptable there.
- **`_start_gui:263`, `run():303`, `_snapshot_warmup:242`** — broad catches on explicitly advisory subsystems, logged. Correct.

**Net:** the philosophy is not uniformly wrong — advisory paths are correctly non-fatal and the risk path correctly fails closed. What is missing is a **middle tier**: a bounded per-message error handler so a bad tick degrades one symbol instead of terminating the process.

## 2.7 Navigability and type coverage

Better than the codebase's history suggests. Comments explain *why* and cite the session review or ADR that motivated the change (`:159–167`, `:424–432`, `:383–389` referencing RS013). `docs/session-reviews/` (RS001–RS014) and `docs/decisions/0001-*.md` form a real decision record. **Six months from now, intent will be reconstructable.**

Weaknesses:
- **Type coverage near zero on the live path.** `calculate_lot_size(self, entry, sl, symbol, htf_bias="NEUTRAL", risk_mult=1.0) -> float` annotates only the return. `_execute_signal(self, symbol, decision, name, htf_bias, grade="")` annotates nothing, and `decision` is an untyped dict crossing four modules. **`tradebot/` is fully typed.** Same split as everything else.
- **No linter, no type checker.** `CLAUDE.md:31`: "There is no linter/build step configured."

---

## Phase 1 panel disagreements

### `tradebot/` — finish it, or delete it?

- **Systems architect:** *Delete or freeze.* 2,746 LOC plus ~3,900 test LOC is a second system to keep correct while `src/` has an idempotency hole that can double-fill. Every hour on v15 is an hour the live path stays unsafe.
- **Python engineer:** *It is the right architecture* — event-sourced, typed, `flock` boot lock (`recovery.py:147` — the thing `src/` lacks entirely), property-tested. Porting `src/`'s bridge onto it may be cheaper than retrofitting `src/`.
- **Risk officer:** Break the tie on capital, not design. **You cannot run either today.** The cheapest path to *safe* wins: `src/` plus idempotency plus the pydantic schema — days. A v15 cutover is months and starts unvalidated.
- **Synthesis:** freeze `tradebot/` at HEAD. Port exactly two things: `config/schema.py` into `_load_config`, and `recovery.acquire_boot_lock` into `main.py`. Revisit v15 only after `src/` survives a demo soak.

### The 1,119-line controller — rewrite or refactor?

- **Architect:** Rewrite. Correctness under failure is impossible to reason about at this size.
- **Engineer:** Incremental extraction. Controller coverage is real (`test_controller_routing`, `test_controller_arbiter`, `test_controller_events` ≈ 640 LOC); a rewrite discards it.
- **Security auditor:** Neither, yet. The exploitable surface is the GUI/Telegram mutation methods at `:1051–1113`, reachable from `:8770`. Fix reachability first, size second.
- **Synthesis:** do not rewrite. Extract `OrderGateway` — `_execute_signal` + `_reserve_risk` + `send_order_reliable` — as one unit, because the idempotency fix lands there anyway and it creates a testable seam. Leave the rest.

### Is `config_layer`'s swallow-and-continue right?

- **Engineer / architect:** No — config errors must crash at startup.
- **Risk officer:** Also no, for a sharper reason: silently reverting to a *higher* default risk is worse than not booting.
- **Security auditor:** It is also a denial-of-*safety* primitive — anything that can corrupt `overrides.yaml` resets your risk limits to defaults.
- **Unanimous:** validate on load; make an unparseable override **fatal**.

---

# SECTION 3 — RISK MANAGEMENT

*Treated as the highest-stakes section. For each control: does it exist, is the math right, can it be bypassed?*

## 3.1 Position sizing — the strongest component in the repository

`risk_manager.py:129–203`. Formula: `lots = risk_money / ((|entry − sl| / tick_size) × tick_value)`, then a commission-adjusted second pass, then floor-to-step.

| Requirement | Verdict |
|---|---|
| Pip value per instrument | **Correct** — uses broker `SYMBOL_TRADE_TICK_VALUE`, not pips |
| JPY / metal / index quoting | **Correct, structurally.** Tick-value sizing is quote-convention-agnostic. **The classic JPY 100× bug is not present** |
| Contract size | Implicit in `tick_value` — correct |
| Account vs quote currency | **Correct** — MT5 `tick_value` is already in account currency |
| Broker min lot | Enforced, `:198` |
| Broker step | Enforced, `:202`, **floors** — correct direction |
| Broker **max** lot | **NOT FOUND.** `SYMBOL_VOLUME_MAX` never requested (EA `:285–290` sends only `tv/ts/vm/vs`). Mitigated by `hard_max_lots: 5.0` |
| Leverage / margin headroom | **NOT FOUND.** No `ACCOUNT_MARGIN_FREE` check on the ZMQ path. `margin_free` exists only in `broker/types.py:52`, unused by the live loop |
| Fail-safe without specs | **Correct** — `:158` returns 0 and logs |

**Below broker minimum → the trade is skipped** (`:198–199` returns `0.0`; `_execute_signal:417` returns on `lot <= 0`). This is the correct behaviour.

### RISK-11 [MEDIUM] — `round(lots, 2)` destroys sub-0.01 lot steps

`:203`. If a broker reports `vol_step = 0.001` (common on crypto CFDs — you trade BTCUSD and ETHUSD), a correct size of `0.004` floors to `0.004` then rounds to `0.0` → `lot <= 0` → **the trade is silently skipped forever on that instrument**, with no log distinguishing it from "no signal."
**Fix:** `round(lots, max(2, step_decimals))`.

### RISK-13 [LOW — downgraded] — Cached scalars vs live config

`__init__:28–31` caches `max_dd`, `risk_pct`, `hard_max_lots`, `comm_per_lot` as scalars, while `throttle_factor:217` re-reads live. Half-live is normally worse than fully-stale.

> **Correction issued during audit.** `settings.py:16–26` documents this precisely and **moves those keys to restart-tier**, so the GUI does not falsely report them as effective. The allowlist is exactly five keys, all verified live-readable. **Contained. Downgraded Medium → Low.** The residual defect is the now-false docstring at `system_controller.py:56–58`.

### RISK-12 [LOW] — Commission solver skipped when commission dominates

`:183`: the `estimated_comm < raw_risk_money × 0.5` branch reverts to gross sizing, i.e. **under-charges commission exactly when commission matters most.** Backwards.

## 3.2 Loss limits

| Control | Exists? | Reference |
|---|---|---|
| Per-trade risk % | **Yes**, 1.0% | `config.yaml:57` |
| Daily loss cap | **Yes**, 3.0% | `risk_manager.py:109` |
| Weekly cap | **NOT FOUND** | — |
| Monthly cap | **NOT FOUND** | — |
| Max drawdown from peak equity | **NOT FOUND.** `equity_max` tracked at `:59`, **never read by any limit** — reporting only | — |
| Consecutive-loss halt | **NOT FOUND** | — |
| Drawdown-scaled sizing | Exists, **ships disabled** | `config.yaml:68` |

Evaluated against **unrealized** equity — correct (`check_can_trade:120` uses heartbeat equity, which includes floating P&L). Checked **before every order** — correct: `check_can_trade` is the first statement of `calculate_lot_size:141`.

**When the limit trips: new entries halt, nothing else.** No flatten, no cancellation of resting limits, **no Telegram alert, and nothing is logged at all** — the `logger.log_event` at `:159` fires only for the missing-specs branch. From the operator's view, a tripped daily loss cap is indistinguishable from a quiet market. Open positions keep running against it.

### RISK-01 [CRITICAL] — The daily drawdown limit resets on every process restart

`day_start_equity` lives only in memory. `update_account_info:51` sets it from the first heartbeat with `equity > 0` — **whatever equity happens to be at boot.** `reset_daily_metrics` is called once a day at 23:45 Kampala (`system_controller.py:355`).

**Chain:** any unhandled exception in tick handling → `run():371` re-raises → process dies → `titan-live.service:29` `Restart=on-failure`, `RestartSec=10`, **no `StartLimitBurst`** → new process → new anchor at drawn-down equity → **a fresh 3% is authorised.** Repeatable without bound.

Expected loss is not 3%/day; it is **3% × number of crashes.** Crash paths are plentiful: an unhandled `json.JSONDecodeError` in `poll_commands` (EXEC-04), a Telegram stall causing a missed watchdog and a systemd kill (OBS-08), or any tick-handler exception.

**Fix (~2 h):** persist `day_start_equity` and its date to `trade_state.db`; restore on boot; add `StartLimitBurst=3`, `StartLimitIntervalSec=300`.

## 3.3 Exposure limits

| Control | Exists? | Reference |
|---|---|---|
| Max concurrent positions | Yes, 6 | `exposure.py:92`, `arbiter.py:269` |
| Max per instrument | Yes, 1 | `exposure.py:100`, `arbiter.py:261` |
| Max per direction | **NOT FOUND** | — |
| Currency saturation | Yes, **hardcoded 2**, not configurable | `exposure.py:33` |
| Correlation-aware | Yes, ρ > 0.8 on H1 returns | `correlation.py:29` |
| Aggregate notional | **NOT FOUND** | — |
| Aggregate dollar risk-to-stop | **Yes — well built** | `risk_manager.py:287`, `exposure.py:44` |
| Margin utilisation headroom | **NOT FOUND** | — |

### RISK-02 [CRITICAL] — Every count-based cap is blind to resting pending orders

`check_exposure(proposed_symbol, active_positions_list)` receives `self.current_open_positions` — the heartbeat's **filled** positions (`_execute_signal:419`). `arbiter._apply_caps:250–269` counts the same list. **`current_pending_orders` is never passed to either.**

The only approved strategy enters on **LIMIT** (`silver_bullet.py:118,128`), and limits rest up to 12 H1 bars before TTL cleanup. Therefore:

> SilverBullet places a BUY LIMIT on EURUSD at 09:00. It rests unfilled. At 10:00 another FVG → another BUY LIMIT on EURUSD. `check_exposure` sees zero positions. The arbiter sees zero positions. Both pass. Repeat. All fill on the same move.

**The per-symbol cap of 1 and the total cap of 6 are both unenforced during the normal state of this book.** The only backstop is `max_total_open_risk_pct: 5.0`, which *does* count resting orders (`risk_manager.py:346`) — so the practical bound is ~5 concurrent commitments **which may all be on one symbol in one direction.**

**Fix (~1 h):** pass `current_pending_orders` into both count gates.

### RISK-03 [HIGH] — The correlation filter fails OPEN

`correlation.py:105`: `if self.matrix is None: return True, "Safe (No Matrix)"`. The matrix requires >50 H1 bars per symbol (`:54`) and ≥2 valid symbols (`:69`), rebuilds hourly, and `_update_matrix` swallows every exception into a `print` (`:92`).

**During warmup, after any restart, and after any pandas error, correlation checking is silently disabled** — precisely when the book is being rebuilt. This is the only fail-open control in an otherwise rigorously fail-closed codebase.

### RISK-04 [MEDIUM] — Correlation is direction-blind

`check_correlation:112–131` never inspects position or proposed direction, blocking on `abs(ρ) > 0.8`. EURUSD-long + GBPUSD-**short** (a spread, genuinely two bets) is blocked; the case you actually want caught is blocked by accident. Correct behaviour needs signed exposure: block same-direction on ρ>0.8 **and** opposite-direction on ρ<−0.8.

### RISK-05 [MEDIUM] — Currency saturation uses substring matching and a hardcoded threshold

`exposure.py:107–120`: `if base in sym or quote in sym`, applied only when `len(symbol) == 6`. **US30, US100, BTCUSD, ETHUSD and XTIUSD are exempt outright**; `XAUUSD` participates with `base="XAU"`, which matches nothing, so it is effectively exempt too. That is 6 of 12 symbols, including the three most correlated risk assets in the universe.

## 3.4 Stop-loss integrity

**Is the stop attached atomically with entry? YES.** `Titan_Gateway.mq5:120–121` sets `req.sl`/`req.tp` in the same `MqlTradeRequest` as the entry, before a single `OrderSend` at `:152`. **There is no window in which the position exists without its stop.** This is the control most systems get wrong, and it is correct here.

**Is there a path that opens a position without one? Not in practice — but by accident rather than design.** There is **no explicit `if sl <= 0: reject`.** A `sl=0` decision produces `diff = |entry − 0| = entry`, an enormous notional stop, a sub-minimum lot, and `return 0.0` at `:199`. It fails safe through three layers of arithmetic coincidence. **Add the assertion.**

### RISK-06 [HIGH] — No broker stop-level or freeze-level validation anywhere

`grep SYMBOL_TRADE_STOPS_LEVEL` → **NOT FOUND** in both trees. If the SL sits inside the broker's minimum stop distance, MT5 returns `TRADE_RETCODE_INVALID_STOPS` and rejects the **entire order** (safe: no naked position). But:

- the EA `Print`s to the Experts tab (`:165`) — a Windows GUI log nobody reads
- the REQ reply is a bare `{"status":"ERROR"}` (`:67`) with no reason
- Python logs `"Order handshake FAILED"` (`:472`) and **sends no Telegram**
- there is **no retry and no reason taxonomy**

Net: a symbol whose stop-level exceeds `1.0 × ATR(H1)` will **never trade, silently, forever.** The answer to "retry, close, or naked?" is: **none of those — a silently missed trade.**

### RISK-07 [HIGH] — Spread is measured, transmitted, then discarded

The EA sends both bid and ask (`:88–90`: `"b"` and `"a"`). `_process_incoming_data:690` reads **only `'b'`**.

- **No spread ceiling exists on the live path.** `gyroscope.py:113` reads `context.get('spread')`, but `_run_strategies` builds `ctx` at `:838–844` with no `spread` key. The filter is dead code returning `None`.
- **All candles are bid-only** (`candle_maker.py:108`). A BUY LIMIT priced from a bid-based FVG edge fills at the **ask**, so every long's effective entry is worse by the spread, its stop distance larger, its target further. **A systematic long-side bias absent from the backtest.** At a 1.0-ATR H1 stop on EURUSD (ATR ≈ 12 pips), a 1.0-pip spread is ~8% of R, one-sided.

**Fix (~1 h):** store `msg['a']`, add `max_spread_atr_frac` to `_execute_signal`, model ask-side fills for longs.

**SL derivation** is done properly: `sl = entry ± stop_atr × ATR(14)` (`silver_bullet.py:113,123`), ATR-based, `stop_atr: 1.0`, with a research citation and an explicit "do not lower" warning (`:31–34`). Spread is **not** added to the SL distance — see RISK-07.

## 3.5 Circuit breakers

| Breaker | Status |
|---|---|
| N consecutive losses | **NOT FOUND** |
| Abnormal spread | **NOT FOUND** (spread unavailable — RISK-07) |
| Volatility spike | **NOT FOUND** |
| Stale market data | **Partial** — 60 s heartbeat watchdog calls `_reboot_terminal`, which **no-ops on Linux**. On the documented deployment: no stale-data breaker |
| Repeated bridge errors | **NOT FOUND.** Failures logged and forgotten; no counter, no threshold |
| Equity floor | **Partial** — daily 3% only, and RISK-01 resets it |
| Per-position emergency stop | **Yes** — `trade_manager.py:80`, closes at −1.5× per-trade risk. See RISK-09 |
| News blackout | **Yes** — `_check_news_status:937`. USD high-impact only (`news_manager.py:149`), while you trade GBPJPY, XAUUSD, XTIUSD |

### RISK-08 [HIGH] — The kill switch is not reachable if the main loop is wedged

`/panic` → `trigger_panic:1087` and `/closeall` → `close_all_market_orders:1094` are **reachable only through `telemetry.poll_commands()`, called from inside the main loop at `:336`.** The kill switch shares the loop it is meant to rescue.

If `run()` blocks — a hung `send_order_reliable`, a wedged REQ socket (the EA itself warns about this at `:68`: *"REP socket may be wedged, reattach EA"*), or a `_reboot_terminal` subprocess call — `/panic` is never polled. **There is no out-of-band flatten.** Neither `verify_integrity.py` nor the GUI provides one (the GUI mutates through the same controller).

**Minimum viable fix:** a standalone `scripts/flatten.py` talking to the EA on a separate port, runnable from any shell.

## 3.6 Failure-mode walkthrough

| Scenario | What it does today | What it should do |
|---|---|---|
| **Broker disconnect, position open** | Heartbeats stop; after 60 s `_reboot_terminal` (Linux no-op) fires **every loop iteration forever.** Bot keeps running on stale equity. No alert, no halt | Halt new entries after N missed heartbeats; alert; restart MT5 with backoff on Windows |
| **Crash + restart with positions open** | Reconciles well: unknown heartbeat tickets registered as `"Adopted"` (`:728`), known rows get `backfill_position_state` (`:737`). **No double-count.** But the first reconciliation can be 60 s away, `symbol_specs` are empty so nothing sizes, and **RISK-01 resets the DD anchor** | Reconcile before the loop starts; persist the anchor |
| **Partial fill** | **Not modelled.** `type_filling` is FOK→IOC→RETURN (`:350–355`), so IOC brokers can partial-fill. `EXECUTION:OPENED` carries no volume; Python stores the *requested* `lots`. **The DB's `lots` can permanently exceed the real position**, overstating book risk and mis-sizing partial closes | Read filled volume from the heartbeat and correct the row |
| **Requote / rejection** | Collapsed into `{"status":"ERROR"}` → `False` → one log line, no alert, no retry | Reason codes; retry requotes only; alert on rejects |
| **Timeout-then-retry** | **No client order ID (ARCH-01).** Python assumes failure. Partly self-healing — SL/TP were in the payload, heartbeat backfills within ~5 s. Residual: `_reserve_risk` skipped, no `notify_signal`, LIMIT recorded as `ACTIVE` so TTL cleanup cannot expire it | Idempotency key; on timeout **query, never resend** |
| **Clock skew / stale ticks** | **Actively broken — see RISK-10** | — |
| **Weekend gap** | Watchdog is weekend-aware (`:328–330`). Sizing is not: a Friday H1 stop is applied to a Monday gap with no re-check | Re-validate stops on session open |
| **Broker stop-out / margin call** | **No margin monitoring at all.** The bot would learn via `EXECUTION:CLOSED` and keep trading | Track `margin_level`; halt below a floor |
| **Two instances running** | **No lockfile in `src/`.** ZMQ bind failures caught and printed; `_boot_sequence` returns `True` anyway (ARCH-04). Instance 2 cannot trade but **does open the same SQLite DBs and can write.** `tradebot/core/recovery.py:147` has the correct `flock`; `src/` does not use it | Port `acquire_boot_lock` into `main.py` |

### RISK-10 [CRITICAL] — Live and historical bars are timestamped in two different timezones, in the same buffer

- **History:** `data_store.py:79` → `pd.to_datetime(df['time'], unit='s')` → **UTC-naive** (raw broker server time)
- **Live:** `candle_maker.py:113,115` → `datetime.fromtimestamp(raw_time)` → **local machine time**

Both land in the same `history_deque`. On the Kampala host (UTC+3) every live bar is stamped **3 hours ahead** of the history bars beside it.

Effects: a 3-hour discontinuity at the warmup→live seam that ATR and all SMC swing/FVG detection compute across; arbiter bar keys that cannot match backtest keys; `_snapshot_warmup` CSVs that cannot be replayed against live.

**On a UTC host the bug is invisible — which is exactly why it has survived.**

Related: `time_math.py:57` `convert_broker_to_ny` makes the same error *and* subtracts `broker_offset` — doubly wrong, but **called by nothing** (verified), so latent. `get_current_ny_string:98–101` is correct and DST-aware.

## 3.7 Adversarial exercise — the three most plausible large losses

### A. Restart-laundered drawdown — *Prevented? No.*

Unhandled exception → `run():371` re-raises → systemd restarts in 10 s with no burst limit → `day_start_equity` re-anchors to drawn-down equity → another 3% authorised. **Nothing in the codebase caps daily loss across process lifetimes.**
**Plausible loss: 3% × crash count, in one day.** No control prevents any step.

### B. Stacked limits on one symbol — *Prevented? Partially, by the wrong control.*

Consecutive H1 bars produce repeated BUY LIMITs on one symbol. `check_exposure` (positions only) passes. `arbiter._apply_caps` (positions only) passes. `_reserve_risk` clears once the DB row exists, so it does not accumulate across bars. Only `max_total_open_risk_pct: 5.0` bites — permitting ~5 concurrent 1% commitments, **all potentially same-symbol, same-direction, filling on one move.** Add RISK-03 (correlation off during warmup) and the shape extends across EURUSD/GBPUSD/AUDUSD.
**Plausible loss: 5% in one adverse move, against an intended 1%.**

### C. Titan hijacks your discretionary trades — *Prevented? No.*

### RISK-09 [HIGH] — The EA reports every position on the terminal, with no magic filter

`SendHeartbeat` (`Titan_Gateway.mq5:180–207`) iterates `PositionsTotal()` with **no `POSITION_MAGIC` filter.** Every position — including ones you place by hand — is reported. Python registers unknown tickets as `"Adopted"` (`:728–732`), and `TradeManager.sync_positions` then applies to them:

- **The Risk Guard closes any position whose floating loss exceeds `1.5 × (equity × risk_per_trade_pct)`** (`trade_manager.py:60–82`). Your hand-placed swing trade with a 3%-of-equity plan gets **market-closed by the bot at −1.5%**, with only a Telegram note.
- The Fibonacci ratchet moves your stop and partial-closes 30% and 50% of your position.
- Conversely, one hand-placed **stopless** position makes `_row_risk` return `None` → `aggregate_open_risk` returns `None` → **every symbol blocked account-wide.** That halt is deliberate and correct (and alerted at `:522`) — but the adoption causing it is not.

CLOSE_POS, CANCEL and MODIFY in the EA also carry **no magic filter** (`:317–344`).
**Fix (~15 min + recompile):** filter by `InpMagic` in `sync_positions`' consumers and all three EA command handlers.

---

# SECTION 4 — ENTRIES & EXITS

## 4.1 Lookahead bias — clean, and verified

`CandleMaker.process_tick:127–137`: on bucket rollover the *completed* candle is appended to `history_deque`, a new one started, and `self.candles` returned. `candles` (`:60–78`) is built **only from `history_deque`** — `current_candle` is never included.

Therefore `df.iloc[-1]` inside `SilverBullet.on_new_candle:90` is the **last fully closed bar. No lookahead on the live path.** Indicators (ATR, FVG, swings) are computed by `SMCAnalyzer` over the same closed-bar frame. No repainting: ATR/FVG on closed bars are definitionally stable.

### ENTRY-04 [MEDIUM] — Warmup history includes the forming bar

`CopyRates(sym, tf, 0, bars_count, rates)` with `ArraySetAsSeries(rates, true)` (`:256,267`) copies **from index 0, which includes the currently forming bar.** It lands at the end of `history_deque` and is immediately followed by live bars.
**Fix:** copy from index 1, or drop the last row in `ingest_history`.

## 4.2 Signal debouncing — present and correct

`data_store.py:121`: `last_processed_candle[tf]` per timeframe, compared by candle timestamp, so a duplicated or replayed tick cannot re-fire the strategy. Combined with arbiter thesis aging (`:907`) and `max_positions_per_symbol: 1`, **within-bar stacking is prevented.** Across bars, see RISK-02.

## 4.3 Entry filters

| Filter | Status |
|---|---|
| Session / time-of-day | **Implemented but disabled.** `windows: [[0, 24]]` — `_in_window:60` is always true. A deliberate, research-cited decision, but `silver_bullet.py:18–21` still documents a 10–11 AM NY window and the class is named for it |
| Spread ceiling | **NOT FOUND** — RISK-07 |
| News blackout | **Yes** — `_check_news_status:937`. USD high-impact only |
| Minimum volatility | **Yes** — `body_size >= 0.8 × ATR` (`:103`) |
| Trend regime gating | **Yes** — H1 HTF bias filter (`:859–862`), manifest-gated |
| Signal quality floor | **Yes** — grade ≥ B (`:872`) |

### ENTRY-02 [MEDIUM] — The session gate is keyed to wall-clock, not bar time

`ctx['ny_time'] = self.time_engine.get_current_ny_string()` (`:842`) — the time the *tick arrived*, not the closed bar's timestamp. Inert today, but the moment a window is re-enabled, live and backtest diverge systematically, and a bar processed late is evaluated against the wrong session.

### ENTRY-03 [MEDIUM] — An M15 strategy would never fire, silently

`MultiTimeframeStore.__init__:25–28` creates CandleMakers for **M5 and H1 only.** But `_init_strategies:808` maps `{"M5","M15","H1"}` and `_snapshot_warmup:225` iterates `("M5","M15","H1")`. A manifest with `timeframe: M15` passes registry validation, is filtered against a `tf` that never arrives, and produces **zero signals with zero errors.**

Also latent: `CandleMaker` bucketing (`:118`) is `(minute // tf_min) * tf_min` — correct for 5 and 60, **broken for any tf ≥ 120** (H4 would bucket every tick to the top of the hour).

## 4.4 Exit logic and races

Mechanisms: broker SL/TP set at entry · the Fibonacci ratchet (BE at 0.382 / bank 30% at 0.618 / bank 50% at 0.886) · a runner trail with give-back tightening · the emergency Risk Guard · TTL cancellation of unfilled limits · `/close`, `/closeall`, `/panic`.

**`sync_positions` is well-guarded internally:** a per-ticket 2.0 s cooldown (`:75`), monotonic `r_level` gating, `continue` after a stage advance (`:140`) so ratchet and trail cannot both fire in one pass, and a dust guard (`_partial_volume:186–213`) correctly preventing an illegal remainder. **This is careful work.** The races that remain are *across* mechanisms.

### EXIT-01 [HIGH] — Ratchet state advances before the broker confirms anything

`:136–137` writes `update_ratchet_level` / `update_trade_phase` **immediately**, then dispatches on the **fire-and-forget PUSH socket** (`:563`, `:589`). `send_command` returns `False` on failure (`bridge_zmq.py:67`) and **the return value is never checked at any of the three call sites.**

If the MODIFY is rejected — invalid stops, position already closed, EA busy — **Titan permanently believes the stop moved to breakeven and will never retry**, because `r_level` has advanced past the gate. The EA's only record is a `Print` to the Experts tab.

The docstring at `:557` claims the outcome *"is observable in the next HEARTBEAT's SL/TP."* **Observable, but never observed.** No code compares the heartbeat's `sl` against the expected ratchet level.

### EXIT-02 [HIGH] — The partial close is a bank-then-hope sequence

At L2, `actions` contains a MODIFY *and* a CLOSE_PARTIAL (`:120–122`), both fire-and-forget, both unverified, dispatched in a loop. If MODIFY lands and the partial does not, you hold full size with a tightened stop; if the reverse, reduced size at the original stop. Neither is detected.

**And `current_vol` comes from a heartbeat up to 5 s stale**, so a partial computed from pre-partial volume can be re-sent against a reduced position — **the staleness window (5 s) exceeds the debounce window (2 s).**

### EXIT-03 [MEDIUM] — TTL cancellation deletes the DB row before confirmation

`_cleanup_ghost_orders:748–749`: `send_command("CANCEL", ...)` (fire-and-forget, return ignored) then `state_manager.delete_order(...)` unconditionally. If the cancel fails, or the limit fills in the same instant, the order is gone from Titan's book but alive at the broker. Partly self-healing (re-adopted next heartbeat) — but it re-enters as `"Adopted"` with no strategy attribution and no `initial_sl`.

### EXIT-04 [MEDIUM] — Runner high-water marks are in-memory only

`runner_hwm` and `tightened` (`:48–49`) are plain dicts. A restart mid-runner resets the HWM to current price and clears the one-way tighten flag — the trail loosens back to `0.268 × range` and re-arms. `r_level` survives (SQLite); the runner state does not. **Inconsistent durability within one mechanism.**

## 4.5 Local vs broker-side exits — correct, and the best design decision in the system

Both exist, in the right order:

- **Broker-side:** `req.sl`/`req.tp` attached atomically at entry. **If the Python process dies, the position still has its stop and target.** This is the single most important survivability property and it is present.
- **Local:** the ratchet/trail/Risk Guard run in Python and *modify the broker-side stop*, so improvements survive the bot dying too.

**The one gap:** runner mode removes the TP entirely at L3 (`:129`: `l3_tp = 0.0 if self.runner_enabled else curr_tp`), and `runner.enabled: true` ships. From L3 onward, that position's only broker-side exit is the trailing SL — maintained **exclusively by the Python trail loop.** Combined with RISK-08 (no out-of-band kill switch) and EXIT-01 (unverified MODIFYs), this is the exposure most worth covering before live.
**Fix:** keep a far-away backstop TP rather than setting `tp = 0`.

## 4.6 Order types and pending-order lifecycle

LIMIT for entries — correct for an FVG-edge thesis. A near-touch conversion to MARKET exists at `:405–408` when the limit is within 2 bp of the live bid — sensible, though `0.0002` is a hardcoded magic number applied uniformly to EURUSD and BTCUSD. STOP entries are supported end to end (`:640`, EA `:139–144`) and **currently unused by any strategy.** Expiry is GTC at the broker with a Python-side TTL of 12 bars — reasonable, but see EXIT-03.

## 4.7 A protocol bug that belongs here

### ENTRY-01 [HIGH] — The EA dispatches commands by substring search over raw JSON

`HandleCommand:252,299,317,326` uses `StringFind(json, "CANCEL") >= 0` etc., and the CANCEL and CLOSE_POS blocks are **sequential `if`s, not `else if`** (only MODIFY returns early). Combined with `GetJSONLong` returning the **first** `"ticket":` in the buffer (`:389–396`), two concatenated frames —

```
{"action":"CANCEL","ticket":5}{"action":"CLOSE_POS","ticket":9}
```

— cancel order 5 **and close position 5**. Your own Python side has a "Sticky Packet Splitter" for the reverse direction (`bridge_zmq.py:107`), which is direct evidence that frame concatenation occurs on this link. **This can close the wrong position.**

Same class: `OnTimer:56` treats any REQ frame containing the substring `"PING"` as a ping and **replies `{"status":"OK"}` without executing the trade** — Python then records a phantom order. No current strategy name triggers it; the parser is one config edit away from doing so.

---

## Phase 2 panel disagreements

### Is the risk engine good enough to run?

- **Risk officer:** *No, and not close* — for one reason. RISK-01 means the daily loss limit is not a limit; it is a per-process suggestion. Everything else in Section 3 is tolerable on a small demo. That one is disqualifying.
- **Systems architect:** Disagrees on emphasis. **RISK-02 is worse**, because it is silent and routine: stacking limits is the *normal* operating state of a LIMIT-entry strategy, whereas RISK-01 needs a crash. Expected cost is higher for the thing that happens every week.
- **Python engineer:** Both are ~10-line fixes with existing test scaffolding (`test_risk_manager_exposure_cap.py` is 638 lines and already tests `check_total_risk`). **This is an afternoon, not a project.**
- **Synthesis:** they are the same afternoon. Do both before any run — demo included, because a demo that laundered its drawdown teaches you nothing about the live one.

### The fire-and-forget management path

- **Architect:** The design is defensible — `CLAUDE.md:37` is right that a slow REQ round-trip wedges the EA's REP socket, and the EA itself warns about this. Moving MODIFY off REQ was correct.
- **Engineer:** Correct to move it off REQ; **wrong to stop there.** Fire-and-forget without heartbeat verification is not asynchronous, it is unverified. The heartbeat already carries `sl` and `tp` per position — the confirmation loop is ~20 lines.
- **Risk officer:** Sharper: a believed-but-absent breakeven stop is worse than no ratchet at all, because position sizing and the book-risk cap both assume the stop is where the DB says it is.
- **Synthesis:** keep PUSH, add verification. Compare each position's broker `sl` against the expected ratchet level on the next heartbeat; roll `r_level` back on mismatch; alert after two failures.

### Should Titan manage positions it did not open?

- **Risk officer:** **Absolutely not.** A bot that closes my discretionary trade at −1.5% because it assumed my risk budget is a bot I cannot trust alongside my own trading.
- **Architect:** Magic filtering is the obvious fix, but the fail-closed halt on a *stopless* adopted position is **desirable** — you want the bot to stop when it sees risk it cannot measure.
- **Security auditor:** Then decouple them. **Report** all positions for the risk aggregate; **act on** only your own magic. Two different questions currently answered by one unfiltered loop.
- **Synthesis:** keep `SendHeartbeat` unfiltered (full visibility for the risk cap); filter `TradeManager.sync_positions` and all three EA command handlers by `InpMagic`. Preserves the safety property, removes the hijack.

---

# SECTION 5 — EXECUTION DYNAMICS & LOGISTICS

## 5.1 Latency budget and blocking calls in the hot path

Signal→order path: FeatureBus SMC evaluation (memoised per bar token) → `signal_grader.grade` → `logger.log_event` **with a JSON payload** → arbiter resolve → `normalize_price` ×3 → `calculate_lot_size` → two exposure gates → `send_order_reliable` (2500 ms ceiling).

Typical latency is fine — single-digit milliseconds plus the ZMQ round trip. The problem is what is synchronous inside it.

### EXEC-01 [HIGH] — A network call to api.telegram.org sits in the trading loop, ahead of tick ingestion

`system_controller.py:336` awaits `telemetry.poll_commands()` **before** `bridge.poll_data()` at `:341`. Inside (`telemetry.py:114–124`): throttled to once per 2.0 s, then `asyncio.to_thread(session.post, ..., timeout=3)` against `getUpdates`. `to_thread` releases the event loop, but the loop body is strictly sequential — **the next `poll_data()` cannot run until the Telegram POST returns.**

During an outage that is up to 3 s of stalled tick ingestion every 2 s: the loop spends ~60% of its time waiting on Telegram.

**This is not hypothetical.** `data/logs/system.log:147–177` is a wall of `ConnectTimeoutError` and `NameResolutionError` against `api.telegram.org` — the exact failure, already observed, repeatedly, over ~20 minutes.

Downstream: ticks queue in the ZMQ receive buffer (`RCVHWM 10000`) and drain 500 at a time; candle closes process late; because the session gate reads wall-clock (ENTRY-02), a late-processed bar is evaluated against the wrong hour.
**Fix:** move Telegram polling to its own `asyncio.Task`.

### EXEC-02 [MEDIUM] — Synchronous SQLite commit and file write on the signal path

`audit_logger.log_event:95,101–105` writes a `RotatingFileHandler` record **and** does `conn.execute` + `conn.commit()`, synchronously, in the event loop. `_run_strategies:867` calls it for every signal with a JSON payload, before the order goes out. Separately, `_publish` → `bus.publish` → `EventJournal.record` → `_Writer.write` does `f.write()` + `flush()` synchronously (`jsonlog.py:30–31`) on **every bus event**, and `TickReceived` is published for every tick.

`PRAGMA synchronous=NORMAL` in WAL means no fsync per commit, so this is cheap in the normal case — and **unbounded if the disk stalls.** A stalled disk would stall order submission.

**Correctly off the hot path:** all Telegram sends. `send_message:84` is `asyncio.create_task(...)` fire-and-forget over `to_thread`. The right pattern, used consistently across all six `notify_*` methods.

## 5.2 Rate limits, throttling, backoff

| Surface | Handling |
|---|---|
| Telegram **inbound** | Throttled to 1 poll / 2.0 s (`telemetry.py:114`) |
| Telegram **outbound** | **NOT FOUND.** No queue, no per-chat throttle, no global limit |
| Broker (ZMQ) | No rate limit; EA `OnTimer` at 10 ms |
| Data feed | EA sends only on bid change — effective source-side throttle |

### EXEC-03 [HIGH] — HTTP status codes are never checked, so rate-limited alerts are silently dropped

`_async_send_retry:92–105` catches only `requests.RequestException`. A `429 Too Many Requests` returns a normal response object — `session.post` succeeds, the function `return`s at `:100`, and the message vanishes with no log and no retry. Telegram's per-chat limit is ~1 message/second, and `sync_positions` can emit several notifications in one pass.

**Under exactly the conditions where you most need alerts — a burst, a cascade, an error loop — the alerts are the thing that fails, invisibly.**

### EXEC-04 [MEDIUM] — An unhandled exception class in `poll_commands` is a crash path

`:126–131`: `resp.json()` on a non-JSON body (a proxy error page, a Cloudflare interstitial) raises `json.JSONDecodeError`, which is **not** a `requests.RequestException`, so the `except` at `:133` misses it. It propagates to `run():368`, which re-raises, killing the process. **Combined with RISK-01, every such crash launders a fresh 3% daily loss allowance.** A plausible, network-triggered, unbounded-loss chain.

**Backoff quality:** `0.5 × 2**attempt` — exponential, 3 attempts, **no jitter.** The ZMQ REQ path has **no backoff and no retry at all.**

## 5.3 Reconnection logic

| Link | Behaviour on loss |
|---|---|
| ZMQ (all three sockets) | Python **binds**, so it never reconnects — the EA reconnects to it. Sockets survive an EA restart |
| REQ socket | Reset on timeout (`:78,82`). The pending reply is discarded |
| Telegram | `requests.Session` keep-alive with implicit urllib3 reconnect |
| MT5 terminal | `_reboot_terminal` — **no-op on Linux** |

### EXEC-05 [HIGH] — Nothing re-verifies positions after a reconnect

The reconciliation loop is purely time-based (`:322`, every 60 s) and is **not triggered by a reconnect event.** There is no reconnect event at all: the EA reattaching is invisible to Python except that heartbeats resume. After an EA restart — which the EA explicitly tells the operator to do when the REP socket wedges — **Titan resumes on a snapshot up to 60 s stale. It resumes blind.**

Related: `_wait_for_bridge_connection:375` loops forever with no timeout and no alert. (systemd's `Type=notify` does catch this case, since `READY=1` is never sent.)

## 5.4 Idempotency

**NOT FOUND.** Covered fully as ARCH-01. Restating because Section 5 asks directly: `magic` is the constant `88000` for every order, `comment` carries only the strategy name, and the EA generates the only unique identifier (`res.order`) *after* the fill. **A retry cannot be distinguished from a new order by either side.** This is the single most important missing primitive in the execution layer.

## 5.5 Data integrity

| Check | Status |
|---|---|
| Duplicate ticks | Filtered at source (EA `:84`, sends only on bid change) |
| Duplicate candle-close triggers | **Handled** — `last_processed_candle` per TF |
| Gap detection in bars | **NOT FOUND.** Nothing verifies consecutive bars are `tf_min` apart |
| Out-of-order timestamps | **NOT HANDLED — EXEC-06** |
| Stale-feed detection | **NOT HANDLED — EXEC-07** |

### EXEC-06 [MEDIUM] — An out-of-order tick silently corrupts the forming candle

`candle_maker.py:127`: `if bucket_time > self.current_candle['time']` → close and roll. An **earlier** `bucket_time` falls through to `:139–143` and updates `high`/`low`/`close`/`tick_volume` **using a stale price.** No guard, no counter, no log. Given RISK-10, the first live tick after warmup is already 3 hours displaced, so the discontinuity this would detect is *guaranteed* to exist and *guaranteed* to go unnoticed.

### EXEC-07 [HIGH] — A frozen price feed is completely undetected. It looks exactly like a flat market.

The EA transmits a TICK only when the bid changes (`:84`), but `SendHeartbeat` is unconditional every 5 s (`:98`). If the broker feed freezes while the terminal stays connected:

- no TICK messages → `process_tick` never called → **no candles close, no strategies run**
- heartbeats keep arriving → `last_heartbeat_time` keeps refreshing → **the 60 s watchdog never fires**
- `HealthProbe`/`_readiness` and `sd_notify("WATCHDOG=1")` keep reporting healthy
- open positions are still managed off `live_prices`, which is now a **frozen price** — so the ratchet and Risk Guard evaluate against a stale market

**This is the "alive but not trading" failure in its purest form.**
**Fix:** track `last_tick_time` per symbol; alert/halt when it exceeds a threshold during expected session hours.

## 5.6 Timezone and DST

Core finding is RISK-10 (Critical). Additions:

- **Mixed naive/aware datetimes throughout.** `datetime.now()` (naive) at `:319`, `:605`, `:743`; `datetime.now(self.uganda_tz)` (aware) at `:350`; `datetime.utcnow()` (naive, deprecated) at `:222`; `pd.to_datetime(unit='s')` (naive UTC) at `data_store.py:79`.
- **Three timezones govern one daily cycle.** The daily reset boundary is Africa/Kampala 23:45 (`:351`); the drawdown anchor it resets is compared against broker-time equity; strategy session logic uses US/Eastern.
- **The reset is fragile to a stall.** `:351` requires `hour == 23 and minute == 45` to be *observed*. A >60 s stall at 23:45 (see EXEC-01) means the report is skipped **and `reset_daily_metrics` never runs** — the DD anchor stays on yesterday's equity for the entire next day.
- Backtest `shift_hours=-7` (`:221`) is coincidentally correct year-round for an EET/EEST broker into EST/EDT, because both zones shift together — but wrong during the ~3 weeks each spring/autumn when US and EU transitions do not align.

## 5.7 Resource behaviour

| Concern | Status |
|---|---|
| Bar buffers | **Bounded** — `deque(maxlen=500)` |
| DataFrame accumulation | **Bounded** — cache rebuilt from the deque, not appended |
| `daily_closed_trades` | **Cleared** daily at `:770`. Correct |
| Log rotation | Text: 5 MB × 3. JSONL: date-partitioned, **never pruned** |
| `audit_log` table | Unbounded. `prune_database` exists (`state_manager.py:228`) — **never called** |
| `command_cooldowns`, `runner_hwm`, `tightened` | **Never cleaned.** Negligible in bytes, but they are the ratchet's memory and are not tied to position lifetime |
| File handles | `_Writer` rotates on UTC date change and closes the old handle. Correct |

Nothing here is dangerous. The real gap: `prune_database` is dead code and `data/journal/` grows forever.

## 5.8 Graceful shutdown — NOT FOUND

`grep -rn "SIGTERM\|SIGINT\|add_signal_handler\|atexit" src/ main.py` → **nothing.**

- `systemctl stop titan-live` sends SIGTERM → Python's default handler terminates immediately. No `KeyboardInterrupt`, no `finally`, no cleanup.
- `state_manager.close()`, `event_journal.close()`, `jlog.close()`, `audit_logger.close()` are **never called** except via `__del__`, which is not guaranteed to run.
- In-flight orders are not awaited. `pending_signal_meta`, `_reserved_risk`, `runner_hwm`, `tightened` are lost.
- **No shutdown notification.** The bot goes silent; the operator cannot distinguish a deliberate stop from a crash from a network partition.
- `main.py:68` catches `KeyboardInterrupt` for interactive Ctrl-C but only prints.

**What survives:** SQLite WAL (durable) — positions and ratchet levels are safe. **What is lost:** everything in memory, and the operator's ability to know what happened.

## 5.9 Startup reconciliation

**Exists and is good — but runs too late.** `_perform_reconciliation:382` corroborates DB rows against both heartbeat `pos` **and** `orders` (a fix explicitly earned from incident RS013, per the comment at `:383–389`).

### EXEC-08 [MEDIUM] — Reconciliation is not part of the boot sequence

`run()` calls `_boot_sequence` → `_wait_for_bridge_connection` → `_init_strategies` → `_perform_warmup` → **ACTIVE**, and only then enters the loop where reconciliation is time-gated at 60 s (with `last_recon_time` set in `__init__:179`, so the first run is a full interval away). There is a window — warmup completion plus up to 60 s — in which the bot is ACTIVE, can size and send orders, and has not reconciled. The `symbol_specs` gate narrows it; it is not closed by design.

---

# SECTION 6 — STRATEGIES, BACKTESTING & VALIDATION

## 6.1 Strategy inventory

| Strategy | Status | TF | Thesis | Instruments |
|---|---|---|---|---|
| **SilverBullet** v14.4.2 | `live` | H1 | Limit at the FVG edge of a displacement candle (body ≥ 0.8×ATR), HTF-bias filtered, SL = entry ± 1.0×ATR, RR 2.0, managed by the Fibonacci ratchet + runner | 12 symbols |
| Gyroscope | `research` | H1 | Kalman drift estimate + SPRT sequential test; pre-registered gate params | 9 symbols |
| MA-slope baseline | `research` | H1 | Reference only — Gyroscope gate criterion 6. "Never a live candidate" | — |

Registry gating is real: `status: research` in the manifest prevents auto-activation regardless of `enabled: true` in `config.yaml`. **One live strategy.** Config comments, manifest `status`, and code all agree.

**Universe (`config.yaml:128`):** `EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, BTCUSD, US100, ETHUSD, XTIUSD`.

## 6.2 The research operation — genuine credit where due

**The research discipline substantially exceeds the engineering discipline.** That inversion is unusual and changes what "unfinished" means for this project.

`docs/research/2026-07-11-silverbullet-h1-stop-study.md` contains, verified against the code that produced it:

- A **falsified prior**: the earlier +0.33R London-open edge killed as a cost artifact, stated in its own opening paragraph
- An **a-priori economic screen** (median round-trip cost ≤ 0.25R) used for symbol selection instead of expectancy ranking — the correct discipline, applied consistently in the 07-28 expansion
- 70/30 chronological OOS: **+0.198R train / +0.185R test.** Essentially no degradation
- Every calendar year positive: +0.27 / +0.17 / +0.18 / +0.20R
- **Spread stress at 1.5× and 2×**, still positive (+0.160R / +0.125R)
- Wilson CIs, an `n < 30` insufficiency flag, and a deterministic fixed-seed bootstrap lower confidence bound
- A candid **"Integrity caveats"** section naming its own selection bias (4×3 grid), the intrabar ordering ambiguity, the DST wobble, and partial-2026 coverage
- A verdict of **"GO (supervised demo first)"** conditioned on a ≥2-week demo-forward test with explicit comparison back to the study

And `src/research/kernel_replay.py` is a real parity seam: it constructs a `SystemController` via `__new__` with the **actual live** FeatureBus, smc pack, Arbiter and SignalGrader attached, runs the **actual** `_run_strategies`, and stubs only the logger, time engine, market-data store and `_execute_signal`. `test_signal_parity.py` locks the resulting signal stream against a committed golden fixture (`parity_golden_h1.json`, 6,688 lines). `research_run.py:9–11` states the discipline explicitly: resolution math is *imported* from `backtest_engine.py`, "never reimplemented."

**Universe expansion (07-28/07-29)** ran US100, ETHUSD and XTIUSD through the identical pipeline with OOS, per-year slices, 2× spread stress, and a reproduction check that reproduced EURUSD to +0.195R vs the study's +0.19R. All three are per-symbol stronger than most incumbents.

## 6.3 One implementation, or two? — three, and the important one drifts

**Signal generation: one implementation, and it is locked.** `kernel_replay` drives the live `_run_strategies` with the live components, guarded by `test_signal_parity`. Correct.

**Trade resolution: one implementation.** `resolve_trade` / `trade_dollars` / `split_trades` / `aggregate_metrics` live in `backtest_engine.py` and are imported by `research_run.py`. Correct.

### STRAT-01 [CRITICAL] — Exit management: two implementations, and it produces the entire edge

| H1 · ATR10 stop, pooled net | Expectancy |
|---|---|
| FIXED 2R exits | **−0.122R** |
| RATCHET | +0.087R |
| RATCHET + RUNNER | **+0.109R** (→ +0.194R after the cost screen) |

**The strategy is a losing strategy without the management layer.** The validated ratchet is `scripts/poc_sb_stops.py:215 replay_managed` / `:264 replay_overlay` — an **offline reimplementation**. The study header says so: *"Rig: `scripts/poc_sb_stops.py` (+ offline managed-exit replay)."* The live implementation is `src/execution/trade_manager.py:51 sync_positions`.

Worse: `grep -n "ratchet\|runner\|TradeManager" scripts/research_run.py` → **zero hits.** The good, kernel-parity harness resolves signals with `resolve_trade`, i.e. **fixed TP/SL only — the −0.122R variant.** So the one harness with live-code parity validates the losing configuration, and the one harness that validates the winning configuration has no live-code parity.

The two implementations already differ, all in the pessimistic direction for live:

| Live behaviour | In `replay_managed`? |
|---|---|
| 2.0 s per-ticket command cooldown | No |
| Volume from a heartbeat up to 5 s stale (EXIT-02) | No — exact bar volume |
| MODIFY/partial fire-and-forget, unverified, never retried (EXIT-01) | No — every action assumed to land |
| Dust guard converting a partial to a full close | No |
| Broker stop-level rejection of a BE stop (RISK-06) | No |
| Ratchet state advanced before confirmation | No |

**The correct read is not "the edge is fake."** The gross signal edge is real, stable and OOS-consistent. The correct read is: **the live system's expectancy is unmeasured, because the component responsible for the sign of the result has never been run against a simulator.**

**Fix:** (1) extract the ratchet into a pure function `(bars, entry, sl, tp, r_level, config) -> actions`; (2) have `TradeManager.sync_positions` call it; (3) have `research_run.py` call it; (4) delete `replay_managed`/`replay_overlay`; (5) re-run the study. **Until step 5, treat +0.194R as an upper bound, not an estimate.**

## 6.4 Magic numbers and overfitting risk

The tested grid was 4 stop models × 3 exit variants = 12 combinations on n ≈ 2,280 H1 trades. The study names this and mitigates it credibly (monotone across neighbouring stops, train≈test, every year positive, 10/11 symbols, survives 2× spread).

But the **live config has more free parameters than the grid tested:**

| Parameter | Value | Where | Validated? |
|---|---|---|---|
| `stop_atr` | 1.0 | `config.yaml:126` | **Yes** — 4-point grid |
| Exit variant | ratchet+runner | `config.yaml:100` | **Yes** — 3-point grid |
| `min_grade` | B | `config.yaml:93` | **Yes** — B vs A tested |
| Universe | 12 symbols | `config.yaml:128` | **Yes** — a-priori cost screen |
| `risk_reward` | 2.0 | — | Held fixed, never varied |
| Displacement threshold | **0.8 × ATR, hardcoded** | `silver_bullet.py:103` | No |
| Fib levels | **0.382 / 0.618 / 0.886, hardcoded** | `trade_manager.py:37–39` | No |
| Partial fractions | **30% / 50%, hardcoded** | `:122`, `:132` | No |
| Trail multiplier | **0.268 (= L3−L2), implicit** | `:144` | No |
| BE buffer | **3 pips, hardcoded** | `:112` | No |
| `giveback_frac` | 0.75 | `config.yaml:106` | Partially — arm-C study |
| `thesis_ttl_bars` | 12 | `config.yaml:85` | Inherited from harness |
| Correlation threshold | **0.8, hardcoded** | `correlation.py:29` | No |
| `max_currency_saturation` | **2, hardcoded** | `exposure.py:33` | No |
| Near-touch LIMIT→MARKET | **0.0002, hardcoded** | `system_controller.py:406` | No |

### STRAT-02 [MEDIUM] — The load-bearing parameters are the least-evidenced

The Fibonacci ratchet parameters are simultaneously the ones producing the edge (STRAT-01) **and** the ones chosen with the least evidence. 0.382/0.618/0.886/0.268 are not empirical results; they are Fibonacci ratios adopted because they are Fibonacci ratios.

That they flip a −0.122R strategy to +0.109R on n=2,280 is either a genuine structural effect (banking partials at fixed fractions of a fixed-R target does convert a binary payoff into a positively-skewed one — real theoretical grounding) **or** a fortunate parameterisation. **The study cannot distinguish these, because it never varied them.** A sensitivity sweep is the highest-value research task remaining, and the rig already exists.

## 6.5 Backtest realism

| Dimension | Treatment |
|---|---|
| Data | **Bar (H1, resampled from M5)**, not tick |
| Intrabar SL/TP both hit | **SL first** (`:74–79`) — pessimistic, documented, correct |
| Spread | Modelled, but as a **post-hoc dollar cost**, not a fill adjustment — STRAT-03 |
| Commission | $7/lot round turn (`:425`), matches `config.yaml:57` |
| Swap / financing | **NOT FOUND.** Zero swap modelling. Runner positions are held overnight; on XTIUSD and ETHUSD carry is material |
| Slippage beyond spread | **NOT FOUND.** The study names this caveat itself |
| Partial fills | Not modelled |
| LIMIT fill | Touch-fill: `low <= entry <= high` within TTL (`:58`). No queue position, no requirement the bar traded *through* — **optimistic, and every SilverBullet entry is a limit** |
| Sizing | Real broker specs with the same floor-to-step logic as `RiskManager` — consistent |

### STRAT-03 [HIGH] — Spread is charged as a cost but never applied to the fill

`trade_dollars:168` subtracts `spread_points × tick_value × lots` from gross P&L. But `resolve_trade:68–73` tests `b["low"] <= sl` and `b["high"] >= tp` against **raw bid-based OHLC.** In live trading a long fills at the ask and its stop triggers on the bid — **the spread shifts hit probability, not just P&L.**

This compounds RISK-07: live candles are bid-only even though the EA transmits the ask. So live entry prices are bid-derived, live fills are ask-executed, and the backtest models neither. **Both sides share the same blind spot, which is why parity tests pass and live may still underperform.**

### STRAT-04 [MEDIUM] — The legacy `Backtester` measures a rejected configuration, and `CLAUDE.md` points at it

`CLAUDE.md:21` documents `.venv/bin/python tests/backtest/backtest_engine.py` as *the* offline backtest. That entry point uses `TEST_CONFIG = {'silver_bullet': {'enabled': True, 'session_ny': ["10:00", "11:00"]}}` (`:209–211`) — **hardcoded, ignoring `config/config.yaml` entirely.** No `timeframe` key → `BaseStrategy:30` defaults to `'M5'`; it feeds M5 bars.

So the documented command backtests **SilverBullet on M5 with a 10–11 NY window**, while live runs **H1 all-hours.** Per the study's own table, the M5 configuration nets **−1.318R** at best and **−4.271R** at the legacy stop.

Also missing from that path: FeatureBus, SignalGrader, Arbiter, RiskManager, ExposureManager, TradeManager. And its `SPREADS` table (`:410–413`) **omits US100, ETHUSD and XTIUSD**, which silently fall back to `20` points via `.get(sym, 20)` — off by orders of magnitude for ETHUSD (BTCUSD is listed at 1000).

## 6.6 Validation methodology

| Method | Status |
|---|---|
| In-sample / out-of-sample split | **Yes** — 70/30 chronological, pooled |
| Per-year slices | **Yes** — all four positive |
| Per-symbol slices | **Yes** — 10/11 positive |
| Cost stress (1.5× / 2×) | **Yes** |
| Wilson CI + n<30 flag | **Yes** |
| Bootstrap lower confidence bound | **Yes**, deterministic fixed seed |
| Reproduction check | **Yes** — EURUSD re-run matched |
| Run-cards with git SHA + config hash | **Yes** (`research_run.py:75,189`) |
| **Walk-forward analysis** | **NOT FOUND** |
| **Monte Carlo on trade sequence** | **NOT FOUND** |
| **Parameter sensitivity surfaces** | **NOT FOUND** |
| **Portfolio-level simulation** | **NOT FOUND — STRAT-05** |

### STRAT-05 [HIGH] — No portfolio simulation, so the reported drawdown is not the drawdown you would experience

Both rigs enforce "one open trade per symbol" and then **pool R across symbols.** Nothing simulates the 6-position count cap, the 5% aggregate risk cap, the correlation gate, the currency-saturation gate, the daily 3% breaker, or margin. **The pooled +0.194R is the expectancy of a system that does not exist.**

Concretely, the study's headline safety claim does not survive contact with the risk config. It states: *"historical maxDD ≈ 14R ≈ −14% (within the 3%/day breaker's envelope; ~12 trades/wk means most days trade 1–3 times)."* But:

- `max_total_open_risk_pct: 5.0` **explicitly authorises 5% at risk simultaneously**
- RISK-02 means those 5 commitments can all be on **one symbol in one direction**
- RISK-03 means the correlation gate is off during warmup and after any restart
- the universe now contains **US100 alongside US30** (~0.9 correlated) and **ETHUSD alongside BTCUSD** (~0.8)

A −5% single-day loss is permitted by configuration; the 3% breaker trips *after* it rather than before; and per RISK-01 a restart re-authorises. **The serial-trade assumption underpinning "within the envelope" is an observed average, not an enforced constraint.**

A single-path 14R maxDD from n=1,837 also badly understates the tail. Monte Carlo resampling of the trade sequence is ~30 lines against the existing per-trade CSVs and would give the 95th-percentile drawdown you should actually size for.

## 6.7 Metrics computed

**Present:** expectancy (R), profit factor, win rate + Wilson CI, max drawdown (R), max losing streak, IS/OOS split, per-year, per-symbol, per-hour blocks, net dollars and cost breakdown, bootstrap expectancy lower bound.

**Missing:** Sharpe/Sortino (no time-series equity curve exists — only a trade-sequence one), drawdown **duration**, MAE/MFE distributions, per-session breakdown, and **any live-vs-backtest reconciliation.** That last gap matters most: the study's own rollout plan requires *"compare realized spreads/slippage and the journal's grade distribution against this study before any live-capital decision"* — **and the tooling to satisfy that condition does not exist.**

## 6.8 Diversification vs correlation

12 symbols, **one strategy, one signal type.** Every position is the same bet expressed on 12 instruments. Correlated clusters make it worse: US30/US100, BTCUSD/ETHUSD, EURUSD/GBPUSD/AUDUSD (dollar-side), USDJPY/GBPJPY (yen-side), XAUUSD/XTIUSD.

**These are not independent bets.** That is fine as a design — it is how the study measured it — *provided the risk layer treats them as one bet.* Per RISK-03/04/05, it does not reliably.

Gyroscope (Kalman drift + SPRT) would be genuinely orthogonal — different family (`family: stat` vs `family: smc`), different mechanism. It is correctly held at `status: research` with pre-registered parameters the config forbids tuning. **That is the right way to hold a second strategy. Do not promote it until STRAT-01 is closed.**

---

## Phase 3 panel disagreements

### Does STRAT-01 invalidate the +0.194R result?

- **Systems architect:** *It invalidates the number, not the thesis.* A validated result whose decisive component runs different code in production is an unvalidated result. Treat live expectancy as unknown.
- **Risk officer / trader:** Softer. The *direction* is well established — three independent stop models all improve monotonically with management, every year positive, 2× spread survives. The mechanism has real theoretical grounding. What is uncertain is the **magnitude**, and every unmodelled live effect pushes it **down**. So: real edge, unknown size, biased optimistic.
- **Python engineer:** Both are academic until the ratchet is one function. Extraction is ~100 lines and mostly mechanical — `sync_positions` already separates decision from dispatch. **A day resolves this empirically.**
- **Synthesis:** extract, wire into `research_run.py`, re-run. Until then quote +0.194R only as an upper bound, and do not size live capital off it.

### Is the M5-config legacy backtester worth deleting or just documenting?

- **Engineer:** Delete the class, keep the functions. Divergent harnesses drift, and this one has drifted to measuring a rejected configuration.
- **Architect:** Agrees, plus: `CLAUDE.md:21` is the actual hazard. A stale command in the onboarding doc is how a future session concludes the strategy loses money and "fixes" something that is not broken.
- **Risk officer:** One caveat — that harness is the only thing running with no dependencies and no data lake. Keep a minimal smoke path.
- **Synthesis:** delete `Backtester`; keep the pure functions; make `__main__` a thin wrapper loading the real `config/config.yaml`; update `CLAUDE.md:21`.

### Is the missing swap model material?

- **Trader:** **Yes, for XTIUSD and ETHUSD specifically.** Runner positions with the TP dropped are designed to be held; H1 signals held across rollover on oil and crypto CFDs pay financing that can exceed the +0.42R edge XTIUSD showed. And XTIUSD's spread was measured once, in a quiet session, at a suspiciously tight 2 points — the study says so itself.
- **Architect:** Marginal for FX majors, where sub-24h swap is noise.
- **Synthesis:** add swap for XTIUSD, ETHUSD, BTCUSD, US30, US100, XAUUSD before those six carry live capital. FX majors can wait.

---

# SECTION 7 — JOURNALING & OBSERVABILITY

## 7.1 Trade record completeness — the largest gap in this phase

`trade_history` schema (`state_manager.py:66–78`) has eleven columns: `ticket_id, symbol, strategy, close_time, pnl, entry, sl, tp, lots, grade, comment`.

| Required field | Captured? |
|---|---|
| Unique ID | Yes — broker ticket. No Titan-side ID (ARCH-01) |
| Signal timestamp | **NO** |
| Submit timestamp | **NO** — `time_placed` exists in `active_orders:51` and is **not carried into `trade_history`** by `archive_trade:203`. Destroyed on close |
| Fill timestamp | **NO** |
| Exit timestamp | Yes — `close_time` |
| Instrument | Yes |
| Direction | **NO.** Inferable from `sign(tp − entry)`, never stored |
| Requested vs filled price | **NO** — one `entry` column, which is the *requested* price when meta exists and the *broker's* price otherwise. The two cases are indistinguishable afterwards |
| **Slippage** | **NO.** Not stored, not computed, not computable from the journal |
| Size | Yes — but the *requested* volume (partial fills undetected) |
| SL/TP **and every modification** | **NO.** Only `initial_sl`/`initial_tp`. `ratchet_level` exists in `active_orders:54` and is **dropped by `archive_trade`** |
| **Exit reason** | **NO COLUMN.** TP hit, SL hit, runner trail-out, Risk Guard kill, `/close`, and manual MT5 close are all identical rows |
| Commission | **NO** |
| Swap | **NO** |
| Gross vs net P&L | **NO** — one `pnl` from MT5 `DEAL_PROFIT`, which excludes commission and swap |
| Equity/balance snapshot | **NO** |
| Signal rationale | **Partial** — `grade` (a letter). The scoring `factors` go to `audit_log` in a *different database*, written *before* the ticket exists, with **no ticket linkage** |
| Parameter set | **NO** |
| Code version | **NO** — research runs capture a git SHA; the live journal captures none |

### OBS-01 [CRITICAL] — The journal cannot validate the live ratchet, which is what the project most needs it to do

STRAT-01 established that the entire edge lives in the exit engine and that the validated engine is not the live engine. Closing that gap requires comparing live managed outcomes against modelled ones.

That comparison needs, per trade: **where the stop actually was at each ratchet stage, whether each MODIFY landed, what volume each partial actually closed, and why the position finally exited.** The journal records **none** of these. `ratchet_level` — the one field showing how far the ratchet got — is written to `active_orders` and then explicitly not copied by `archive_trade:200–205`.

`config.yaml:106–108` records the give-back tighten arm as enabled 2026-07-28 "for the FBS demo-forward-test." **A soak is presumably running now, generating the most valuable data this project will produce — into a schema that cannot answer the question the soak exists to answer.**

**This is the highest-leverage fix in the audit, and it is deadline-sensitive:** every day the soak runs without it is a day of unrecoverable evidence.

**Fix:** add `time_placed`, `direction`, `exit_reason`, `ratchet_level_at_exit`, `final_sl`, `filled_volume`, `commission`, `swap`, `equity_at_open`, `config_hash`, `git_sha` to `trade_history`, plus a `trade_events` table appending one row per MODIFY/partial with the outcome observed on the next heartbeat.

Note `_process_incoming_data:674–680` already computes `hold_seconds` and `r_multiple` live, sends them to Telegram, and **discards them.** The derivations exist; only the persistence is missing.

## 7.2 Storage durability

| Property | Status |
|---|---|
| Format | SQLite (two DBs) + JSONL event journal |
| Atomic writes | **Yes** — SQLite transactions; `archive_trade` is INSERT+DELETE+commit as one unit |
| Append-only / transactional | **Transactional.** `trade_history` append-only; `active_orders` mutable working state. Correct split |
| flush / fsync | **`PRAGMA synchronous=NORMAL`.** Survives process crash; **can lose recent commits on power loss or VM reset.** JSONL flushes but never `fsync`s |
| Corruption recovery | **NOT FOUND** |
| Backup | **NOT FOUND** |

### OBS-02 [HIGH] — Every journal write path swallows its own failures

- `register_order:140`, `backfill_position_state:166`, `archive_trade:208`, `reconcile_state:190` all `except Exception: print(...)`. **A disk-full condition silently stops journaling while trading continues.**
- `audit_logger.log_event:106–109` is `except sqlite3.Error: pass` — with the diagnostic `print` **commented out** at `:108`. Fully silent.
- `jsonlog._Writer.write:32–33` increments `self.drops`, exposed as a property (`:49`) and **never read by anything.** A silent-loss counter nobody reads.
- `get_day_stats:225` is `except Exception: pass`, returning zeroed stats. **The nightly performance report can report a flat day because the query failed.**

### OBS-03 [MEDIUM] — `INSERT OR REPLACE` preserves ratchet state but not the trade record

`:129–138` COALESCEs only `phase` and `ratchet_level`. Every other column is overwritten with whatever the caller passed. Currently unreachable due to an `exists()` guard, but the pattern means a future second registration silently zeroes the risk fields `aggregate_open_risk` depends on.

### OBS-04 [MEDIUM] — `INSERT OR IGNORE` + unconditional DELETE can destroy a record

`archive_trade:200,206`: if `trade_history` already holds that ticket, the INSERT is ignored and the `active_orders` row deleted anyway. Note `_perform_reconciliation:395` archives ghosts with `pnl=0.0` — so **a ghost swept 120 s before its real close notification arrives permanently records that trade's P&L as zero.**

## 7.3 Queryability and broker reconciliation

**Queryable:** yes. SQLite plus `scripts/export_journal.py` (58 LOC) dumping to CSV, tested. Its `COLUMNS` list exports everything there is — which is the problem, not the script's fault.

### OBS-05 [HIGH] — No reconciliation of the journal against the broker's own trade history

`reconcile_state:169` compares **open** ticket sets only. `scripts/export_history.py` pulls *bars*, not deals. **Nothing ever compares Titan's `trade_history` P&L, fill prices, or trade count against MT5's `HistoryDealSelect` record.**

This is the mechanism that would have surfaced EXIT-01, EXIT-02 and the partial-fill gap on its own. It needs an EA-side `GET_DEALS` command and a nightly comparison script.

## 7.4 Logging discipline

| Property | Status |
|---|---|
| Structured | **Both** — `jsonlog.JsonLogger` writes JSONL with `bind()` context support; `audit_logger` writes free-text + a SQLite row with a JSON payload |
| Levels used correctly | Loosely. `log_event(type, module, msg)` mixes severity (`ERROR`, `WARN`) with domain (`RISK`, `EXEC`, `SIGNAL`). Everything lands at `logging.INFO` regardless, so **file-log severity filtering is impossible** |
| Correlation IDs | **NOT FOUND.** `JsonLogger.bind()` exists — the mechanism is built — and `grep -rn "\.bind("` shows **no caller.** The signal log at `:867` and the execution log at `:470` share no key; grading `factors` can never be joined to the resulting ticket |
| Secrets redacted | **Partially — OBS-06** |
| Rotation | Text: 5 MB × 3. JSONL: date-partitioned, **never pruned.** `audit_log` table: **unbounded** |
| Retention policy | **NOT FOUND** |

### OBS-06 [HIGH] — The token has already leaked into logs by this mechanism, and the mechanism is still live

`telemetry.py:37` builds `self.base_url = f"https://api.telegram.org/bot{self.token}"`. **The token is embedded in every request URL**, so any library logging a URL logs the credential. Nothing redacts it. See `01-SECURITY-INCIDENT-P0.md`. One dependency upgrade or one `logging.basicConfig()` reinstates it.

Additionally, `test_telegram.py:48,53` prints `token[:5]` and the full chat ID to stdout, and `RUN_TITAN.bat:36` runs it on every startup.

## 7.5 Monitoring and alerting

| Mechanism | Status |
|---|---|
| Heartbeat / liveness | **Two layers, one genuinely good.** `HealthProbe` serves `/healthz` + `/readyz` on 127.0.0.1:8787, and `sd_notify("WATCHDOG=1")` with `WatchdogSec=90` means **a wedged loop gets killed and restarted by systemd.** Credit due — a real liveness net most retail bots lack |
| Alert on error rate | **NOT FOUND** |
| Alert on drawdown | **NOT FOUND.** The daily breaker trips silently; `drawdown_throttle` firing is silent too |
| Alert on bridge disconnect | **NOT FOUND** |
| Alert on alive-but-not-trading | **NOT FOUND — OBS-07** |
| Alert on un-computable book | **Yes** — `_alert_uncomputable_book:522`, with a re-arm guard and the offending row named. Well done |
| Startup / crash notification | Startup yes; crash yes (if the loop survives long enough to schedule a task). **Clean shutdown: no notification at all** |

### OBS-07 [HIGH] — `_readiness` cannot detect "alive but not trading", and its field is misnamed

`_readiness:1041` computes `age = now − self.last_heartbeat_time` and flags staleness above 30 s. But `_process_incoming_data:605` sets `last_heartbeat_time = datetime.now()` **at the top of the function, for every message type — including `TICK`.** It is a *last-message* timestamp.

- A frozen feed with live heartbeats (EXEC-07) → fresh → `/readyz` returns 200, `WATCHDOG=1` keeps firing, systemd is happy, **and the bot processes zero candles indefinitely.**
- The inverse — ticks flowing but heartbeats stopped, so no equity updates and no position visibility — is equally invisible.

None of the three readiness conditions is "did a bar close in the last hour" or "did a heartbeat arrive in the last 15 s."

### OBS-08 [MEDIUM] — A missed watchdog window feeds the unbounded-drawdown chain

`sd_notify("WATCHDOG=1")` sits inside `if (now_dt.second % 10 == 0) and (now_dt.microsecond < 50000)` (`:361–363`) — a 50 ms window per 10 s, hit only if a loop iteration lands inside it. Normally the loop iterates sub-millisecond so it always hits.

But under EXEC-01 (Telegram stalling the loop ~3 s at a time), the effective loop period becomes ~3 s and the chance of landing in a 50 ms window is ~1.7% per iteration — roughly a 40% chance of missing **every** window across the 90 s `WatchdogSec`.

**A Telegram outage can therefore cause systemd to kill and restart a perfectly healthy bot, and each restart re-anchors `day_start_equity` (RISK-01), authorising another 3% daily loss.** Three independently-minor findings compose into an unbounded-loss chain triggered by DNS failure — which the committed log shows has already happened repeatedly.

## 7.6 Audit trail for manual interventions

**Asymmetric, and the weaker side is the one you will actually use.**

**GUI: audited properly.** `server.py:22–28` `_audit()` publishes a `GuiActionExecuted` event with action, truncated args, outcome and client IP on every `/api/command`, `/api/settings` and `/api/registry` mutation, wrapped so audit failure cannot break the request. Good design.

### OBS-09 [HIGH] — Telegram interventions have no durable audit trail

`telemetry.py:147` is `print(f"[CMD] {cmd} {args}")`. That is all. No `_publish`, no `log_event`, no event. **`/panic`, `/closeall` + `/confirm`, `/close 12345`, `/cancel all`, `/pause`, and `/enable gyroscope confirm` produce no record in either database or the event journal.** `log_event` is called only on failure branches.

After an incident you could reconstruct every GUI action and no Telegram action — while Telegram is the interface reachable from a phone and therefore the one used under pressure.

---

# SECTION 8 — TELEGRAM COMMAND & COMMUNICATIONS LAYER

## 8.1 Command inventory and blast radius

| Command | Args | Class | Confirmation |
|---|---|---|---|
| `/status`, `/balance`, `/pending`, `/strategies` | — | read-only | — |
| `/pause` | — | config | none |
| `/resume` | — | config | none — **also clears EMERGENCY** |
| `/disable <id>` | id | config | none |
| `/enable <id>` | id | config | none |
| `/enable <id> confirm` | id | **capital** — activates a `research`-status strategy | literal word `confirm` |
| `/cancel <id\|all>` | ticket | **capital** | none |
| `/close <id>` | ticket | **capital** | none |
| `/closeall` | — | **capital** | `/confirm` within 30 s |
| `/confirm` | — | executes pending | capture-and-clear |
| `/panic` | — | **capital, maximal** | **none** |

### CTRL-01 [HIGH] — The two most destructive commands have the weakest guards

- **`/panic` (`:193–195`) executes immediately.** No confirmation. Meanwhile `/closeall` — a strict subset of what panic does — requires `/confirm` within 30 s. **The confirmation is on the lesser action.** The GUI gets this right: `commands.py:3,8` puts both in `_DESTRUCTIVE` and requires `confirm: true`. **The Telegram layer is less safe than the GUI for the same operation.**
- **`/resume` → `set_system_pause(False)` → `self.state = BotState.ACTIVE` (`:1051–1053`), unconditionally, from any state including EMERGENCY.** A single unconfirmed keystroke reverses a panic. (Panic *is* a real halt — `:692` requires `ACTIVE` to process ticks — but it has no latch.)
- **`/enable <id> confirm` (`:201–204`) passes `allow_research=True`**, promoting a `status: research` strategy to live. `/enable gyroscope confirm` puts an unvalidated Kalman/SPRT strategy on live capital from a phone, guarded by the literal string `"confirm"` as `args[1]`. The GUI equivalent requires typing the strategy id back (`registry_view.py:16`).

### CTRL-02 [HIGH] — `/panic`, `/closeall` and `/cancel all` report success they have not verified

`close_all_market_orders:1094–1101` iterates `current_open_positions`, calls `send_command("CLOSE_POS", ...)` — **fire-and-forget on PUSH, return value discarded** — and increments `count` regardless. The Telegram reply is `☠️ *Flattened* {count} positions`. **`count` is commands enqueued, not positions closed.**

If the EA is detached, the PUSH socket buffers silently (`SNDHWM 1000`) and **the bot tells the operator they are flat while every position remains open.** This is the worst false-confidence failure in the system: it fails in the direction of the operator standing down during an emergency.

Compounding: `cancel_pending_orders:1111` iterates a heartbeat snapshot up to 5 s stale, so a limit placed 2 s ago is never cancelled and remains live after a "successful" panic.

**Fix:** after dispatch, wait 1–2 heartbeats and report the *observed* position count. Escalate if positions remain.

## 8.2 Authorization

`_process:142–144`: `sender_id = str(msg["from"]["id"])` compared against `str(self.allowed_chat_id)`, **checked on every command**, before any dispatch. Using `from.id` rather than `chat.id` is the correct choice — `chat.id` would authorise anyone in a group the bot joins. Tested (`test_wrong_sender_is_ignored`).

**Does authorization hold if the token leaks? Yes — with one exception.**

### CTRL-03 [HIGH] — Authorization fails OPEN if `TELEGRAM_CHAT_ID` is unset

If the env var is absent, `self.allowed_chat_id = None` (`:36`) and `str(None)` is `"None"`. An update lacking a `message` object (a `channel_post`, `edited_channel_post`, or `my_chat_member` event) yields `msg = {}`, so `msg.get("from", {}).get("id")` is `None` and `sender_id` is `"None"`.

**`"None" == "None"` → authorized.**

The dangerous property is not the specific exploit path; it is that **a missing configuration value converts a strict allowlist into an open one.** `is_active` (`:47`) validates only the token, never the chat ID, so the bot starts and runs happily in this state.

## 8.3 Input validation

| Command | Validation |
|---|---|
| `/close <id>` | **`int(args[0])` with `ValueError` handling** (`:179–182`), then `close_specific_market_order:1105` verifies membership in the open-position list. **Belt and braces** |
| `/cancel <id>` | **Not validated at the Telegram layer.** Passed through as a string; `int()` inside the `try` raises into an error reply. Works by exception rather than by check — and **no membership check**, so any integer ticket is sent to an EA that applies no magic filter (RISK-09) |
| `/enable`, `/disable` | Arbitrary string; the registry validates the id |
| Lot sizes | **N/A — no command accepts a volume** |
| Instrument whitelist | N/A — no command takes a symbol |

**There is no order-entry command at all.** A fat-fingered `/buy EURUSD 1000` **cannot occur.** The Telegram surface is close/cancel/pause/enable only. **This is a genuinely good design decision that eliminates the entire fat-finger class, and it deserves to be stated.**

## 8.4 Injection surface — clean

Traced every path from message text:

- `parse_command:17–27` is pure tokenisation. No regex, no format-string evaluation.
- **No `eval`, `exec`, `os.system`, `pickle`, or `yaml.load` anywhere in `src/`.**
- `subprocess` appears twice on the live path: `:774` is `shell=True` but with a **hardcoded literal** (no interpolation, not injectable); `:778` is `subprocess.Popen([mt5_path_str])` — a list, no shell. **Neither is reachable from message text.**
- Outbound HTML escaped via `telegram_format.esc` on the two paths interpolating exception text.
- No file-fetching command exists, so no path traversal via Telegram.

### CTRL-04 [HIGH] — There *is* an authenticated code-execution path, via the GUI settings store

`SettingsStore.set:82–91` calls `validate(key, value)`, which for any unrecognised key **returns `None` (accept)** at `settings.py:69`, then `_set_key:112` creates arbitrary nested keys and writes `overrides.yaml`. So:

```
PATCH /api/settings  {"key": "system.mt5_path", "value": "/tmp/payload.sh"}
```

is accepted and persisted. On the next restart it merges into the live config, and when the heartbeat watchdog fires, `_reboot_terminal:778` executes `subprocess.Popen([mt5_path_str])`.

Less dramatic, more likely: `{"key": "risk.trade.hard_max_lots", "value": 9999}` — accepted unvalidated, effective on restart.

**The docstring at `settings.py:4` calls the allowlist "the safety boundary." It is not — it is a live-vs-restart tier selector.** Anything can be *written*; the allowlist only decides *when* it applies. Combined with the service running as root (SEC-04), this is a root code-execution chain.

## 8.5 Rate limiting and flood protection

| Surface | Status |
|---|---|
| Telegram inbound commands | **NOT FOUND.** Only the 2.0 s poll interval bounds throughput; an unbounded number of commands *within* a batch are `create_task`'d concurrently |
| Telegram outbound | **NOT FOUND** (EXEC-03) |
| GUI REST auth failures | **Yes** — `AuthThrottle`, 5 failures / 60 s per IP |
| GUI WebSocket auth | **NOT THROTTLED — CTRL-05** |
| GUI request rate | **NOT FOUND** — only auth failures are throttled |

### CTRL-05 [MEDIUM] — The WebSocket bypasses the brute-force throttle

`server.py:85–97`: `websocket.accept()` is called **before** authentication, then the token is read from `sec-websocket-protocol` or the first message within 3 s and checked with `auth.token_ok`. **`THROTTLE` is never consulted and `record_failure` is never called.** `/ws` offers unlimited, unrecorded token guesses while `/api/*` allows five per minute.

## 8.6 Concurrency safety

Single event loop, no threads (§2.5). Consequences are bounded but real — see CTRL-06 (registry mutation leaves `strategy_ttls` stale) and the in-flight-order gap in §2.5.

## 8.7 Degradation

**If Telegram is unreachable:** the engine continues — sends are fire-and-forget tasks and poll failures are swallowed. **But it does not continue *safely*, and it does not queue.**

- **Blocking:** yes (EXEC-01) — up to 3 s of stalled tick ingestion every 2 s
- **Queueing:** none. Three attempts over ~1.5 s, then the message is dropped
- **Composed failure:** EXEC-01 → missed `WATCHDOG=1` (OBS-08) → systemd restart → `day_start_equity` re-anchored (RISK-01). **A Telegram outage can cost real money through a chain in which no individual link is severe.**

### CTRL-07 [HIGH] — Telegram is the only alert channel, with no fallback

`/healthz` and `/readyz` are *pull* endpoints on 127.0.0.1 — nobody polls them from off-box. No email, no SMS, no webhook, no second chat. **When Telegram fails, the operator's entire view goes dark, and that failure is one of the conditions most likely to cause a restart loop.**

## 8.8 Message hygiene

- **Secrets in messages: none.** Tickets, symbols, P&L, equity only. No token, no login, no account number. Correct.
- **Formatting:** `telegram_format` is a dedicated 175-LOC module tested by 213 LOC. But `esc()` is HTML-escaping applied to strings sent with `parse_mode="Markdown"` (`:173`, `:188`) — an exception message containing `*` or `_` breaks Markdown parsing, Telegram returns 400, and per EXEC-03 that is silently swallowed. **Error notifications are therefore the ones most likely to fail to deliver.**
- **Unbounded spam:** partially guarded (`_alert_uncomputable_book` re-arm, `report_sent_today`, `command_cooldowns`). **Unguarded:** `_cleanup_ghost_orders:750` and `_perform_reconciliation:396` send one message per item per cycle, and `run():369` sends a crash message on every crash — one every 10 s in a crash loop.

## 8.9 `test_telegram.py` — what it covers

**It is a diagnostic script, not a test.** No `unittest`, no `pytest`, no assertions. `RUN_TITAN.bat:36` runs it as a startup preflight.

**Covers:** `.env` presence, token presence, chat-ID presence, live reachability of `api.telegram.org`, and semantic diagnosis of 401 (bad token) vs 400 (bad chat ID). Genuinely useful as a preflight.

**Does not cover:** anything in the control surface. And **it sends a real message to the real chat and prints the token prefix and full chat ID to stdout.**

**The real coverage is elsewhere and is better than the filename suggests.** `tests/unit/test_telegram_commands.py` (216 LOC, 17 tests) covers `/status` routing, **wrong sender ignored**, non-command → help, pause/resume, `/cancel` and `/close` failure paths, `/closeall` prompting without executing, **`/confirm` exactly-once semantics**, confirm-without-pending, **expired confirm does not execute**, closeall with no positions, `/strategies`, and `/enable` with and without args. Plus `test_telegram_strategy_cmds.py` (90) and two format modules (213). **Real, thoughtful coverage of the confirmation state machine.**

**Untested, each corresponding to a finding:** `/panic` (no test at all — the most destructive command), CTRL-03's auth-fail-open case, `/enable <id> confirm` promotion, `/close` happy path, the absent rate limiting, and whether CTRL-02's reported count reflects reality.

**Recommendation:** rename to `scripts/check_telegram.py` so `unittest discover` and CI cannot mistake it for a test; strip the credential prints.

---

## Phase 4 panel disagreements

### Is the journal gap (OBS-01) more urgent than the risk fixes?

- **Risk officer:** *No.* RISK-01 and RISK-02 can lose money this week. A schema gap loses information.
- **Systems architect:** *Yes.* RISK-01 and RISK-02 are known and one afternoon of work. OBS-01 is a *data* problem: every day the soak runs against the current schema is a day of evidence you cannot recover retroactively. You can fix RISK-01 tomorrow and still fix it correctly. **You cannot go back and record the ratchet levels of trades that already closed. Schema fixes have a deadline that code fixes do not.**
- **Python engineer:** Both are small and non-conflicting. The schema change follows an existing migration-guard pattern (`state_manager.py:99–113`) and is ~40 lines.
- **Synthesis:** the architect wins on sequencing, the risk officer on emphasis. **Do OBS-01 first because it is time-sensitive, then RISK-01/02 the same day, then let the soak run.**

### Bring Telegram up to the GUI's standard, or the reverse?

- **Security auditor:** Up to the GUI's. It is measurably better on the same operations — destructive-command confirmation, typed-id promotion, constant-time compare, per-IP throttle, full audit trail. **Copy the GUI's patterns; do not invent new ones.**
- **Risk officer:** Partly disagree on one point. Telegram is the emergency interface — the one you reach for from a phone with a position running against you. **Adding friction to `/panic` could cost more than it saves.** Fix CTRL-02 so it tells the truth instead.
- **Architect:** Both are satisfiable: keep `/panic` unconfirmed but **verified**, and require a typed confirmation for `/resume` from EMERGENCY. **Confirmation belongs on the un-doing, not the doing.**
- **Synthesis:** leave `/panic` frictionless; fix CTRL-02 as the priority; latch EMERGENCY; bring `/enable ... confirm` up to the GUI's typed-id standard.

### Is `synchronous=NORMAL` acceptable for a trade journal?

- **Engineer:** Yes. It survives process crashes, which is the failure mode that actually happens, and `FULL` costs an fsync on a path already synchronous in the event loop.
- **Risk officer:** For `active_orders` — the live position state the risk cap reads — I want `FULL`. Losing the last few writes there means booting with a wrong view of committed risk.
- **Synthesis:** split it. `trade_state.db` → `synchronous=FULL`; `titan_core.db` and the JSONL stay. Write volume on `active_orders` is ~12 trades/week; the fsync cost is irrelevant.

---

# SECTION 9 — SECURITY & VULNERABILITY ASSESSMENT

*Approached as a red team, assuming the repository is or will become public. It is.*

> **The P0 credential exposure is documented in full in `01-SECURITY-INCIDENT-P0.md`, including exact remediation commands. This section covers everything else.**

## 9.1 Committed artifacts

| Artifact | In HEAD? | Leaks |
|---|---|---|
| `.env` | No (history only, 6 trees) | **Live Telegram token + chat ID** |
| `data/logs/system.log` | **Yes** | Same token, ~30 occurrences |
| `data/db/trade_state.db` | **Yes** | 5 live `active_orders`, 24 `trade_history` rows |
| `data/db/titan_core.db` | **Yes** | 63 `audit_log` rows |
| `boot_crash.log` | **Yes** | Windows username, full desktop path |
| **43 `.pyc` files** | **Yes** | **Bytecode of three "deleted" strategies**, recoverable with `uncompyle6` |
| `test_data.csv` | Yes | **Benign** — OHLC only, no account identifiers |
| `data/lake/frozen/**` | Yes | Benign, deliberately retained |
| `.mig/config`, `.claude/settings.json`, systemd units | Yes | Username, paths, layout |

`.gitignore` (40 lines) is well-constructed and correctly negates `data/lake/frozen/`. **The problem is that ten of those files were committed before the rules existed, and gitignore does not untrack.** `git ls-files -i -c --exclude-standard` returns all of them.

## 9.2 Dependency audit

| | Root `requirements.txt` | `bridge/requirements.txt` |
|---|---|---|
| Pins | **0 exact, 15 `>=`** | **7 exact `==`** |
| Lockfile | **NOT FOUND** | NOT FOUND |

### SEC-01 [HIGH] — The live trading process has zero reproducible dependency state

`pandas>=2.1.4`, `numpy>=1.26`, `pyzmq>=25.1.2`, `requests>=2.31.0`, `pyyaml>=6.0`, `pyarrow>=15.0` all float to latest. **Two installs a month apart produce different systems**, and a `pandas` minor bump can silently change `resample`/`pct_change`/`corr` semantics — which sit directly under `CorrelationManager._update_matrix` and the backtest H1 resampler. **A dependency upgrade can change your backtest results with no code change and no record of it.**

The bridge, ironically the less critical component, is the one that is pinned.

**Fix:** `pip-compile` `requirements.in` → hashed `requirements.txt`; commit the lock; run `pip-audit` in CI; record the lock hash in every research run-card.

## 9.3 Input trust boundaries

| External input | Validated at the boundary? |
|---|---|
| Telegram message text | **Yes** (§8.3) |
| **ZMQ bridge messages (EA→Py)** | **NO — SEC-05, the most serious finding here** |
| `config/config.yaml` | **NO** — raw `yaml.safe_load`, no schema (§2.4) |
| `config/overrides.yaml` | **Partially** — five key shapes (CTRL-04) |
| CSV / parquet research data | Coerced with `errors='coerce'` + `dropna`. Adequate |
| Frontend requests | **Yes** — bearer token, pydantic bodies, int checks |
| HTTP bridge requests | **Yes** — pydantic models, auth on every route except `/health` |

**Deserialization: clean.** `yaml.safe_load` everywhere (verified — no `yaml.load`, no `Loader=`). **No `pickle` anywhere.** No `eval`, no `exec`, no `__import__`. **This is the most common critical finding in Python trading systems and it is absent here.**

### SEC-05 [CRITICAL] — The ZMQ bridge is unauthenticated, bound to all interfaces, and inbound messages are never validated

Three facts compose:

1. **`bridge_zmq.py:25,36,53` bind `tcp://*:{port}`** — all interfaces, ports 32768/32769/32770. `config.yaml:27` declares `host: "127.0.0.1"` and **the code never reads it.**
2. **`TitanZmq.mqh` (84 lines) implements `Init`, `Connect`, `Send`, `Recv`, `Shutdown` and nothing else.** No CURVE, no PLAIN, no ZAP. **Zero authentication, zero encryption.**
3. **`_process_incoming_data:601` validates only `isinstance(msg, dict)`.** No schema, no sender check, no bounds.

**The attack that costs the most money: connect a PUSH socket to port 32769 and send one message.**

```json
{"type":"HISTORY","symbol":"EURUSD","tf":"H1","tv":0.000001,"ts":1000,"vm":0.01,"vs":0.01,"data":[]}
```

`update_symbol_specs:62–76` accepts it — `float()` coercion only, **no sanity bounds whatsoever.** `calculate_lot_size:168–170` then computes `ticks_at_risk ≈ 0`, `money_loss_per_lot ≈ 0`, `lots_gross` → enormous, and `:195` caps at `hard_max_lots = 5.0`. **Every subsequent trade opens at 5.00 lots** — on EURUSD, $500,000 notional against an intended 1% risk. `risk_to_stop` uses the same poisoned specs, so the 5% aggregate cap validates it as safe.

Other one-message attacks on the same port:

- `{"type":"HEARTBEAT","bal":1e9,"eq":1e9,"pos":[],"orders":[]}` → equity fabricated, no drawdown detected, sizing off a billion. **Also wipes `current_open_positions`**, so the count gate and risk aggregate read an empty book.
- `{"type":"TICK","s":"XAUUSD","b":<spike>}` → `live_prices` poisoned → Risk Guard fires or stops ratchet on a fabricated price.
- `{"type":"EXECUTION","status":"CLOSED","ticket":<real>,"pn":0}` → `archive_trade` deletes the live row and records P&L as zero. **The position keeps running with no Titan-side record.**

**And on port 32768** (Python binds PUSH): an attacker connecting a PULL socket becomes a peer, and **ZMQ PUSH round-robins across peers** — so roughly half of every `MODIFY`, `CANCEL`, `CLOSE_POS` and `PING` goes to the attacker instead of the EA. Since all are fire-and-forget and unverified (EXIT-01, CTRL-02), **half your stop-loss updates and half your panic-flatten commands would silently vanish while the bot reports success.**

**Who can reach it:** any process on the Windows host, any other WSL distribution, and — depending on Windows Firewall and WSL networking mode — anything on the LAN.

**Crucially, this is not only an attack.** A broker misquoting `tick_value` after a symbol-spec change produces *identical* damage with no attacker at all. **That makes the bounds check a risk control, not merely a security control.**

**Fix, in order of value per hour:**
1. Bind the specific WSL interface, not `*`. Read `config.yaml`'s existing `host`. **15 min.**
2. Bounds-check `update_symbol_specs`: reject `ts ∉ [1e-6, 100]`, `val ∉ [1e-4, 1e4]`, or any >10× change from the last accepted value. **30 min — blocks the highest-cost single failure.**
3. Add a shared secret: a `k` field on every message, `hmac.compare_digest`-checked, with `InpToken` on the EA side. **~1 h, closes the entire injection class.**
4. Long term: ZMQ CURVE (`Z85.mqh` and `SocketOptions.mqh` are already vendored).

## 9.4 Frontend security — clean

| Property | Status |
|---|---|
| Authentication | Bearer token, `hmac.compare_digest` (`auth.py:41`), fail-closed on missing expected value |
| Authorization | Read/write dependency split; `TITAN_GUI_READONLY=1` mode |
| Brute-force | 5 failures / 60 s per IP on REST. **Not on `/ws`** (CTRL-05) |
| CORS | **No middleware — correct.** Same-origin (`base: "./"`, SPA served by FastAPI) |
| CSRF | **Structurally N/A** — bearer header, no cookies |
| Network exposure | Default `127.0.0.1`; `.env.example:34` reinforces it |
| Can it trigger trades? | **It can close and cancel, not open.** No order-entry endpoint |
| Credential handling | Token in header; **stored in React `useState` only — no `localStorage`.** Correct |
| Path traversal | Handled — `resolve()` + `relative_to()` (`:117–121`) |

The one real defect is CTRL-04.

### SEC-02 [HIGH] — The HTTP bridge binds `0.0.0.0` by default and by documented example

- `bridge/app/settings.py:16`: `bridge_host: str = "0.0.0.0"` — **the default**
- `bridge/config/.env.example:1`: `BRIDGE_HOST=0.0.0.0` — **the documented example**

**An order-entry REST API on every interface of the machine holding your live MT5 terminal.** Write endpoints: `POST /order/market`, `POST /order/pending`, `PUT /position/{ticket}`, `POST /position/{ticket}/close`, `POST /position/{ticket}/partial`, `DELETE /order/{ticket}`.

**Mitigations genuinely present, credit due:**
- `bridge_auth_token: str` has **no default**, so pydantic raises at startup if unset. **Fail-closed.**
- Every mutating route carries `AuthDep` (`main.py:266–307`). Verified — no unauthenticated write path.
- `/health` is deliberately unauthenticated and returns only status.

**Residual defects:**
- `verify_token:116` uses `authorization != expected` — **plain string comparison, not `hmac.compare_digest`.** The GUI gets this right; the bridge does not.
- **No throttle** on auth failures.
- The example token is the literal `CHANGE_ME_generate_a_long_random_token`.

## 9.5 Filesystem, process and privilege

### SEC-04 [HIGH] — The bot runs as root; no hardening directives in either unit

```
$ grep -cE "User=|Group=|NoNewPrivileges|ProtectSystem|PrivateTmp|ReadWritePaths|StartLimit" deploy/systemd/*.service
titan-demo.service:0
titan-live.service:0
```

The runbook says `sudo cp` into `/etc/systemd/system/` then `systemctl enable --now`. **A system unit with no `User=` runs as root.** So the trading process runs as root while:

- serving FastAPI on a configurable bind address (one env var from `0.0.0.0`)
- listening on three unauthenticated ZMQ sockets bound to `*` (SEC-05)
- calling `subprocess.Popen([mt5_path_str])` on a path writable via `PATCH /api/settings` (CTRL-04)

**Chained: GUI token → `PATCH system.mt5_path` → wait for a heartbeat gap → root code execution.** Individually HIGH; **as a chain, CRITICAL.**

Also missing: **`StartLimitBurst`/`StartLimitIntervalSec`.** With `Restart=on-failure` and `RestartSec=10`, a crash loop restarts forever — the mechanism behind RISK-01 and OBS-08.

**Other findings:**
- `subprocess.run("taskkill /F /IM terminal64.exe", shell=True)` — `shell=True` but a hardcoded literal. **Not injectable.** Style issue only.
- `scripts/check_bridge.py:45` and `broker/mt5_http.py:56` use list arguments and hardcoded commands. Safe.
- **No unsafe temp files, no world-writable paths.**
- `.bat` files: no credentials, dynamic `%~dp0` paths, no `curl | sh`. Their defect is being stale — except `RUN_TITAN.bat:36` running `test_telegram.py`, which prints credentials.

### SEC-07 [MEDIUM] — `.claude/settings.json` auto-approves `git commit`

The allowlist includes `Bash(git add *)` and `Bash(git commit *)`, permitting an agent to commit without prompting. **This is plausibly the root cause of the P0.** Not a runtime vulnerability; a process one. Remove both.

## 9.6 `verify_integrity.py` — it always fails, so it is not a control

### SEC-06 [MEDIUM]

`check_structure:32–42` requires `src/strategies/models/unicorn.py`, and `check_imports:62` imports `src.strategies.models.unicorn:UnicornModel`. **Both were deleted on 2026-07-12.** So on a healthy system it prints **"SYSTEM INTEGRITY: UNSTABLE"** and a `CRITICAL Import Error`.

A check that cries wolf on every healthy run is a check nobody runs. It also:
- **exits 0 regardless** — no `sys.exit(1)`, so it cannot gate anything
- ends with `input("Press Enter to Exit...")` — **blocks forever in CI or a preflight**
- requires `RUN_TITAN.bat` and `.env`

**What it misses:** config **schema** validation (the pydantic schema exists and is unwired), file checksums, dependency versions, state consistency vs broker, secret scanning, `.env` completeness (including `TELEGRAM_CHAT_ID`, which is CTRL-03), and port availability.

## 9.7 Threat model

| Attacker | What they can achieve **today** | Control that would stop them |
|---|---|---|
| **Repo read access** (public — anyone) | Recover the live token from `.env` in history *and* `system.log` in HEAD. Set a webhook to seize the command channel and impersonate the bot. Read the 24-trade history, entries, stops, P&L. Decompile three "deleted" strategies. Learn username, paths, ports, universe, full risk config | Rotate + private + `filter-repo` + untrack. Pre-commit secret scanning |
| **Telegram token holder** | `setWebhook` → total, silent loss of remote control including `/panic`. `sendMessage` → perfect impersonation. `getUpdates` → read your commands. **Cannot** issue commands (`from.id` is server-asserted) — **unless `TELEGRAM_CHAT_ID` is unset** (CTRL-03) | Rotate. Require a numeric chat ID. A second alert channel. Webhook monitoring |
| **Local process / malware** (Windows or WSL host) | **Full control of position sizing** via one poisoned `HISTORY` message → every trade at 5.00 lots. Fabricate equity to defeat the breaker. Poison ticks. Steal half of all `MODIFY`/`CLOSE`/`CANCEL` by peering on :32768. Place orders directly via the bridge if it can read `bridge/config/.env` | Specific-interface bind + HMAC + bounds-check specs. Bridge → loopback. OS keyring |
| **LAN attacker** | Everything above **if Windows Firewall permits** — both `tcp://*:3276x` and `BRIDGE_HOST=0.0.0.0` are reachable by default configuration. Plus unlimited GUI token guesses via `/ws` and the bridge | Same fixes. Explicit firewall rules. Throttle `/ws` and the bridge |
| **GUI token holder** | `PATCH system.mt5_path` → **root code execution** on the next watchdog fire. Flatten the book, cancel everything, promote a research strategy to live | Reject keys absent from defaults. Deny-list `system.*`. `User=titan` + `NoNewPrivileges` + `ProtectSystem=strict` |
| **Malicious/compromised broker feed** | Bad specs or bad ticks — **identical impact to the local-process attack, with no defence at all**, because specs are trusted absolutely by design | Bounds + change-rate limits on all broker-supplied specs. Cross-check against `data/specs.json` |
| **Insider / you under pressure** | `/panic` with no confirmation; `/resume` silently clears EMERGENCY; `/enable gyroscope confirm` from a phone; **no audit trail for any Telegram action** | Latch EMERGENCY. Typed-id promotion. Log every command |

**The two rows that should change behaviour this week:** repo read access (rotate now) and local process (one message re-sizes every trade to 5 lots).

## 9.8 Recommended hardening

1. **Secrets** — OS keyring (`keyring` on Linux/WSL, DPAPI/Credential Manager on Windows). If `.env` remains, `chmod 600` plus the redaction filter.
2. **Least privilege** — `titan` user; `User=`, `Group=`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `ReadWritePaths=`, `RestrictAddressFamilies=AF_INET AF_UNIX`, `StartLimitBurst=3`, `StartLimitIntervalSec=300`.
3. **Pre-commit** — `gitleaks` + `detect-secrets` + a hook rejecting gitignore-matched files. Remove `git commit` from `.claude/settings.json`.
4. **Dependencies** — `requirements.in` → hashed lock; `pip-audit` in CI; record the lock hash in run-cards.
5. **CI security scanning** — §10.4.
6. **Network** — ZMQ to the specific WSL interface; bridge to loopback; explicit Windows Firewall rules for 8766/8770/8787/32768–70.

---

# SECTION 10 — OPERATIONS, TESTING & DEPLOYMENT

## 10.1 Test coverage reality check

**The suite was executed: 682 tests, 222 seconds, all green**, on a clean clone with no configuration. That is more than most trading repositories manage.

The distribution is the problem:

| Area | Coverage | Assessment |
|---|---|---|
| `tradebot/` (**dead at runtime**) | ~3,900 LOC incl. 880 LOC property tests | **The best-tested code in the repo cannot affect a trade** |
| GUI / web layer | ~1,100 LOC, 13 files | Thorough |
| Exposure / total-risk cap | **47 tests** (638 LOC) | **Excellent. Genuinely rigorous** |
| Arbiter | 508 + 343 LOC | Strong |
| Registry / manifests | 246 + 150 + 136 | Strong |
| Telegram | 519 LOC, 4 files | Good — confirmation state machine well covered |
| `TradeManager` (the ratchet) | **22 tests** | Moderate — for the component producing the entire edge |
| **`calculate_lot_size`** | **4 tests** | **Thin.** The single most consequential function |
| `normalize_price` | 3 | Thin, but the crash case is regression-locked |
| Daily DD anchor | 4 | **RISK-01 cannot be caught by these** — it is a persistence question the tests do not reach |
| `StateManager` | 6 | Thin for the durability substrate |
| **`ZMQBridge`** | **ZERO.** `grep -rln "ZMQBridge" tests/` returns nothing | **The idempotency hole, the sticky-packet splitter, the swallowed bind failure, the REQ reset: all untested** |
| **`Titan_Gateway.mq5`** (399 LOC) | **ZERO. No MQL5 test framework exists** | ENTRY-01, RISK-09, RISK-06 all unverifiable |
| Startup reconciliation | Incidental only | EXEC-08 untested |

**Critical functions with zero tests:** `ZMQBridge.send_order_reliable`, `ZMQBridge.poll_data`, `_perform_reconciliation`, `_cleanup_ghost_orders`, `_dispatch_mgmt_command`, everything in the EA.

**The asymmetry is stark: 47 tests on the aggregate risk cap, 0 on the socket that submits orders.**

### OPS-03 [HIGH] — Zero test coverage on the order path

## 10.2 Recommended test strategy

| Tier | What to add | Effort |
|---|---|---|
| **Unit — sizing** | Table-driven cases per asset class using real `data/specs.json`: EURUSD (5-dp), USDJPY (3-dp), XAUUSD, US30, BTCUSD, ETHUSD, XTIUSD. Assert realised risk within 1% of intended and **rounding always down.** Would catch RISK-11 immediately | 3 h |
| **Property (Hypothesis)** | You own the dependency and have 880 LOC of precedent — **point it at `src/`.** Invariants: `realised_risk ≤ risk_pct × equity` for all (entry, sl, spec) triples; `lots` always a multiple of `vol_step`; `lots == 0 or lots ≥ vol_min`; `aggregate_open_risk` monotone in book size; `normalize_price` idempotent | 1 day |
| **Unit — bridge** | `ZMQBridge` against an in-process peer: timeout→reset, concatenated frames, truncated JSON, bind failure. **Highest value per hour** | 1 day |
| **Integration — mock broker** | Fake EA speaking the JSON protocol over real ZMQ. Full scenarios: warmup → specs → signal → order → fill → ratchet → close. **The harness that makes STRAT-01 testable** | 2–3 days |
| **Replay** | The tape exists: `data/journal/events-*.jsonl`, `parity_golden_h1.json`, `_snapshot_warmup` CSVs with sha256. `kernel_replay.py` is the driver. **Extend past `_execute_signal`** | 2 days |
| **Chaos** | Kill the mock EA mid-order; freeze ticks while heartbeats continue (EXEC-07); truncate a frame; corrupt `overrides.yaml`; SIGKILL with a runner live | 2 days |
| **MQL5** | No unit framework exists. Use MT5's Strategy Tester with a scripted command sequence, asserting against the heartbeat stream. Cover magic filtering, stop-level rejection, concatenated frames, the `PING` substring collision | 2 days |
| **Demo soak** | See the go-live checklist in `04-REMEDIATION-ROADMAP.md` | 4 weeks calendar |

## 10.3 Runtime invariants — recommended, currently absent

### OPS-07 [MEDIUM] — No runtime invariant assertions exist

| Invariant | Implementation | Catches |
|---|---|---|
| **No position without a stop** | On every heartbeat: `all(float(p['sl']) != 0 for p in pos)`. Alert + halt new entries on violation | RISK-06 rejections, adopted manual trades (RISK-09) |
| **Σ position risk ≤ configured max** | Already computed by `aggregate_open_risk`. Assert every heartbeat, not just pre-trade | RISK-02, poisoned specs (SEC-05) |
| **Internal state matches broker state** | `set(DB active_orders) == set(heartbeat pos ∪ orders)` after the grace window | EXEC-05, OBS-04, partial fills |
| **No duplicate order IDs** | Once idempotency keys exist, assert in-flight uniqueness | Timeout-retry double-fill |
| **Specs sanity** | `1e-6 ≤ ts ≤ 100`, `1e-4 ≤ val ≤ 1e4`, no >10× change | **The highest-cost failure in the threat model** |

Wire into one `_assert_invariants()` called from the HEARTBEAT branch, publishing an `InvariantViolated` event surfaced on `/readyz` and Telegram (once per occurrence).

## 10.4 CI/CD

### OPS-02 [HIGH] — There is no CI

`ls .github` → **NO .github DIRECTORY.**

`scripts/run_pr_checks.sh` (85 LOC) is a manual, tiered check runner — and it is honest about itself (`:8`): *"There is NO hosted CI: this repo has no git remote, so nothing runs on push."*

**That statement is now false.** The repository has a public GitHub remote with 356 commits and 22 branches. The condition it cites no longer holds.

Recommended minimal pipeline, every push and PR:

```yaml
# .github/workflows/ci.yml
- gitleaks + detect-secrets           # BLOCKING — a live P0 came from exactly this
- reject files matched by .gitignore  # BLOCKING — how .env got committed
- ruff check + ruff format --check    # no linter exists today
- mypy src/ tradebot/                 # tradebot/ is fully typed
- python -m unittest discover -s tests/unit -p 'test_*.py'   # 682 tests, 222s
- python tests/unit/test_signal_parity.py                    # golden-tape lock
- pip-audit --requirement requirements.txt
- verify_integrity.py --ci            # once it exits non-zero and drops input()
```

222 s of tests is well within any free tier. **The two blocking items at the top are worth more than everything else combined.**

## 10.5 Deployment review

| Item | `titan-live.service` | `.bat` files |
|---|---|---|
| Restart policy | `on-failure`, `RestartSec=10` | **None.** `pause` on crash |
| Crash-loop protection | **NOT FOUND** — no `StartLimitBurst` (**OPS-05**) | N/A |
| Resource limits | `MemoryMax=2G` only | None |
| Log handling | `StandardOutput=journal` — correct | Console only |
| Run-as user | **root** (SEC-04) | Interactive user |
| Environment loading | **None.** No `EnvironmentFile=`; relies on `load_dotenv` | `.env` presence checked |
| Watchdog | `Type=notify` + `WatchdogSec=90` — **a genuine liveness net.** Credit due | None |
| Hardening | **Zero directives** | N/A |

**Two divergent deployment paths, only one maintained.** The `.bat` files launch `python main.py` on Windows; `CLAUDE.md:7` says the core runs in WSL. Neither has been touched by the WSL/systemd work. **They document a superseded architecture and leak credentials on every run.**

### OPS-09 [MEDIUM] — `docs/RESUME.md` is stale and is the designated first-read file

`:4` says the working branch is *"NOT merged to main"* — it was merged. `:23` cites `scripts/poc_mtf_pb.py` and `tests/unit/test_mtf_pb.py`; **both are missing from the tree.**

## 10.6 Environment parity — there is no safeguard at all

### OPS-01 [HIGH] — Nothing anywhere checks whether the connected account is demo or live

```
$ grep -rni "TITAN_ENV|is_demo|is_live|demo_mode|account_type" --include=*.py src/ main.py
main.py:17:# 1. Environment Guard: Ensure Python 3.10+      ← only match, unrelated
$ grep -rn "ACCOUNT_TRADE_MODE" mql5_bridge/ bridge/
(nothing)
```

- **`TITAN_ENV` is shipped in `.env.example:26` and read by nothing.** `CLAUDE.md:49` says it was purged. The variable survives as documentation of a control that does not exist.
- **MQL5 exposes `AccountInfoInteger(ACCOUNT_TRADE_MODE)`** returning `DEMO`/`REAL`/`CONTEST`. The EA never reads it; the heartbeat never reports it; Python never asserts on it.

**The only thing separating a demo run from a live run is which MT5 terminal the EA happens to be attached to** — determined by a hand-typed `InpIP` in an MQL5 dialog on a Windows GUI. The demo unit's separation (separate checkout, ports, DB) is real but **entirely convention.** Point the demo checkout's EA at the live terminal and the demo bot trades live money, with no error, no warning, and no record.

**Fix (~2 h):**
1. EA adds `ACCOUNT_TRADE_MODE` and the login number to `SendHeartbeat` — 3 lines of MQL5
2. `config.yaml` gains `system.expected_account_mode: DEMO` and `system.expected_login: <n>`
3. Python refuses to leave WARMUP on mismatch — ~10 lines

**This converts the strongest guarantee in the system from "I remembered correctly" to "the software refuses."** Given that everything is to be validated on demo before live capital, **this is the control that makes the entire soak trustworthy.**

## 10.7 Runbook gaps

`docs/runbooks/deploy-systemd.md` (59 lines) is genuinely good for what it covers: WSL systemd prerequisite, install/enable, correct watchdog semantics, health checks, emphatic demo-stage caveats, `journalctl` invocations, rollback.

### OPS-04 [HIGH] — The most important runbook does not exist

| Procedure | Documented? |
|---|---|
| Bot won't start | **NO.** `boot_crash.log` is not mentioned anywhere |
| Bridge down / EA detached | **NO.** `check_bridge.py` exists, documented in `CLAUDE.md` but not the runbook. The EA's own "reattach EA" warning has no procedure behind it |
| Unexpected open position | **NO.** The "Adopted" path (RISK-09) and the book-wide halt — the two conditions most likely to page you |
| Drawdown limit hit | **NO.** And it is not even alerted, so you would learn by noticing the bot stopped trading |
| **Flatten everything immediately** | **NO. The most important runbook page in any trading system.** Worse, per CTRL-02 `/panic` reports unverified success, and per RISK-08 it is unreachable if the loop is wedged |
| Rollback | **YES** — but `git checkout <sha> -- .` does not restore deleted files; add `git clean -fd` |

**Priority: write the flatten runbook first, and make it not depend on the bot.** Three tiers: (1) `/panic`, then *verify* against MT5's own position list; (2) `scripts/flatten.py` talking directly to the EA on its own port; (3) close manually in the terminal and `systemctl stop titan-live`. **Tier 3 always works and should be written down before tier 1 is trusted.**

## 10.8 Backup and recovery

| | Status |
|---|---|
| Journal backup | **NOT FOUND** |
| State DB backup | **NOT FOUND** |
| Config backup | Git — but `config/overrides.yaml` is gitignored, so **GUI-set risk settings are backed up nowhere** (OPS-08) |
| Tested restore path | **NOT FOUND** |
| Corruption detection | **NOT FOUND** — no `PRAGMA integrity_check` |

`prune_database` exists and is never called. **There is no backup of `trade_state.db`** — the file holding ratchet state, position record, and (once OBS-01 lands) the evidence base for validating the strategy.

**Minimum viable:** nightly `sqlite3 trade_state.db ".backup 'backups/trade_state-$(date +%F).db'"` from a systemd timer, keep 30, plus weekly `PRAGMA integrity_check`, plus **one documented and actually executed restore drill.**

---

## Phase 5 panel disagreements

### Root privilege vs. ZMQ exposure — which is more urgent?

- **Security auditor:** **ZMQ, decisively.** Root escalation requires the GUI token, which lives on a loopback service. The ZMQ injection requires nothing but the ability to open a socket, and one message re-sizes every trade to 5.00 lots.
- **Systems architect:** Agrees on ranking, disagrees on framing. **The ZMQ hole is not fundamentally an auth problem — it is the absence of input validation on the most-trusted input in the system.** `update_symbol_specs` accepting arbitrary floats is a correctness bug that a hostile broker feed or a buggy EA build triggers just as easily. **Fix the bounds check first (30 min), then the HMAC.**
- **Risk officer:** Both describe the same control I want for a non-security reason: **spec sanity bounds.** A broker misquoting `tick_value` produces identical damage with no attacker. That makes it a risk control, and it belongs in `risk_manager.py` where the risk officer can see it.
- **Synthesis (unanimous on sequencing):** bounds check (30 min) → specific-interface bind (15 min) → HMAC (1 h) → `User=titan` + hardening (1 h). **All four in one morning.**

### Is the absence of CI acceptable for a one-person project?

- **Python engineer:** Normally yes — `run_pr_checks.sh` plus discipline is defensible for a solo repo, and 682 passing tests prove the discipline is real.
- **Security auditor:** **No, and the evidence is in front of us.** `.env` was committed and lived through six trees. A pre-commit secret scan is ~10 lines of YAML and would have made the P0 impossible. **The argument "I'm careful" was already tested and it failed.**
- **Architect:** And `.claude/settings.json` auto-approves `git commit`. An agent with commit rights and no secret scanner will eventually commit a secret; this one did.
- **Synthesis:** the security tier of CI is non-negotiable and is an hour's work. The lint/type tier is optional.

### Is the demo soak worth running before these fixes land?

- **Risk officer:** **No.** Per RISK-01 a soak with a resetting drawdown anchor teaches you nothing about the live breaker. Per OBS-01 the journal cannot record what the soak exists to measure. Per OPS-01 nothing guarantees it is even pointed at the demo account. **You would spend four weeks of calendar time producing unusable evidence.**
- **Architect:** Partly disagree. The soak also tests things the fixes do not touch — EA stability over weeks, realised spreads vs the study's indicative table, memory behaviour, WSL networking, heartbeat cadence. Some of that is only learnable by running.
- **Trader:** The study's own verdict conditions GO on comparing *"realized spreads/slippage and the journal's grade distribution."* Slippage is not captured. Grade is. So the soak as configured can satisfy one of the two stated conditions.
- **Synthesis:** land OBS-01, RISK-01, RISK-02 and OPS-01 first — roughly two days — **then** start the clock. Anything already collected is an infrastructure shakedown, not strategy evidence.

---

# SECTION 11 — INNOVATION & RESEARCH

*Full treatment, including seven candidate strategies and one control experiment, is in `05-STRATEGY-ARSENAL.md`. This section covers the architectural and risk-sophistication assessment.*

## 11.1 The over-engineering flag you asked for

| | Lines |
|---|---|
| `docs/` | **34,171** |
| Live trading code (`src/`) | 7,833 |
| Tests of code that **cannot affect a trade** | ~3,900 |
| The v15 rewrite, imported by nothing | 2,746 |
| React control GUI | 6,484 |
| **Tests of the socket that submits every order** | **0** |

**4.4 lines of documentation per line of live trading code.** A complete event-sourced kernel that nothing imports. A 90-file React cockpit. A Kalman-filter + SPRT strategy. A research lake with frozen Parquet provenance. Meanwhile `bridge_zmq.py` has never been unit-tested.

**This is not a criticism of the work's quality.** `kernel_replay.py`, the 47-test exposure suite, the ADR record, the session reviews, and the stop study are all genuinely good — better than most professional desks produce. **The problem is allocation, not competence.** The sophistication is concentrated in the layers furthest from the money.

**Stop extending, until Stage A and B are done:** `tradebot/` (freeze; port only `config/schema.py` and `recovery.acquire_boot_lock`) · Gyroscope (keep at `research`) · the GUI (harden what exists) · the research lake and universe (stop expanding until the correlation gate and count caps hold) · documentation (three overlapping planning systems; consolidate).

**The single highest-value engineering hour available is a unit test for `ZMQBridge.send_order_reliable`. It is also the least interesting hour available. That gap is the whole story of this repository.**

## 11.2 Architectural upgrades

**Worth doing, sequenced:**

| ID | Upgrade | Benefit | Effort | Notes |
|---|---|---|---|---|
| **A1** | **Extract the ratchet into a pure function** | Enormous | 1 day | The STRAT-01 fix as architecture. `sync_positions` already separates decision from dispatch. **Do before anything else** |
| **A2** | **`OrderGateway` seam** | High | 2 days | `src/execution/broker/base.py` (31 LOC) already defines a protocol and is **unused by the live path.** Finish it. Idempotency, retry taxonomy and the mock harness all land here |
| **A3** | **Position-lifecycle state machine** | High | 3 days | Fixes EXIT-01, EXIT-04, OBS-01 and OBS-04 in one design. Currently lifecycle is scattered across `status`, `phase`, `ratchet_level`, `runner_hwm`, `tightened`, `pending_signal_meta` in three storage tiers |
| **A4** | **Dependency injection** | Moderate | 1–2 days | The tell is already in the code: `getattr` guards at `:414`, `:433` and `object.__new__` fixtures. **The production risk path has been softened to accommodate untestable construction.** Do it *as* you extract A2/A3 |

**Speculative:**

- **A5 — Event sourcing / full replayability.** This is what `tradebot/` already is. **Do not attempt the v15 cutover before you have a live system with a measured edge** — you would migrate an unvalidated strategy onto an unproven kernel. A1–A3 are all steps toward it, so nothing is wasted. Revisit after 3 months live.
- **A6 — Strategy plugin interface.** Already ~80% built (`manifest.py` + `registry.py` + manifests), with working promote-gating, serving one strategy. **Ahead of demand. Do not extend.**

## 11.3 Risk sophistication

**Framing first:** every item below adds a parameter to a system whose existing risk parameters are partly unenforced (RISK-02), partly reset by restarts (RISK-01), and partly fail-open (RISK-03). **Sophistication applied to an unenforced baseline makes the system harder to reason about without making it safer.**

| ID | Item | Verdict |
|---|---|---|
| **B1** | Volatility-scaled sizing | **You already have this.** `sl = entry ± 1.0 × ATR(14)` fixes risk in dollars while stop distance scales with volatility. **Nothing to build** |
| **B2** | Drawdown-responsive scaling | **Exists and ships disabled.** `throttle_factor:205` is implemented, config-gated, reads live. **Turn it on for the soak — the cheapest genuine risk improvement available, one boolean** |
| **B3** | Correlation-aware exposure | Not a new feature — the RISK-03/04/05 fix. Fail closed, direction-aware, explicit asset-class groups. 2 days |
| **B4** | Regime detection gating | **Explicitly flagged as over-engineering.** And you effectively built one already — Gyroscope's Kalman drift + SPRT *is* a regime detector. Note SilverBullet's per-year expectancy is notably *stable* (+0.27/+0.17/+0.18/+0.20R), which is weak evidence that regime gating has little to add |
| **B5** | Kelly-fraction sizing | **Do not implement.** Kelly requires a trustworthy edge estimate; yours is unmeasured and, once measured, will rest on n=1,837 with acknowledged selection bias. **The optimal fraction is hypersensitive to the win-rate input. Fixed fractional at 1% is correct for this maturity, and probably for the next two years** |
| **B6** | Portfolio risk parity / dynamic correlation | Risk parity across 12 expressions of one signal is re-weighting a single bet. Meaningful only with 2–3 genuinely uncorrelated strategies — which is gated behind STRAT-01 |

## 11.4 Execution improvements

| ID | Item | Verdict |
|---|---|---|
| **C1** | **Capture the ask; add a spread gate** | **Highest value per hour in the audit — 1 hour.** The EA already sends `"a"`; `:690` discards it. Fixes RISK-07 and STRAT-03 together |
| **C2** | Execution-quality / slippage attribution | High. 2 days, mostly OBS-01. **A stated go-live condition with no tooling today** |
| **C3** | Spread-aware entry timing | Moderate, 1 day, depends on C1. Gyroscope already has the parameter and it is inert |
| **C4** | Smart order placement (iceberg, TWAP) | **Not applicable. Skip permanently.** At 0.01–5.00 lots on retail CFDs you have no market impact and no order-book access |

## 11.5 Analytics and tooling

| ID | Item | Verdict |
|---|---|---|
| **D1** | **Broker-history reconciliation** | **Very high. 2 days.** The OBS-05 fix. **Rank above everything else here — it is a bug-detector, not a dashboard.** Would have surfaced EXIT-01, EXIT-02 and the partial-fill gap on its own |
| **D2** | Shadow / paper mode alongside live | High, 3 days. **Requires OPS-01 first** — two instances with no environment guard is how you accidentally trade live twice |
| **D3** | Automated post-mortems on losing streaks | Moderate, 1 day, depends on OBS-01. Partly substitutes for the missing consecutive-loss breaker |
| **D4** | Performance dashboard | Low — 6,484 lines of React already exist. Point it at the journal once OBS-01 lands |
| **D5** | Trade clustering | **Argue against.** The study already did the defensible version (per-symbol, per-year, per-hour, per-grade with an a-priori screen). Unsupervised clustering on n=1,837 finds structure whether or not it exists, and every cluster you act on is a fresh selection-bias decision on the same data |

## 11.6 Where ML genuinely helps vs. is a trap

**Traps — do not do these:**

- **Predicting price direction from OHLC features.** Signal-to-noise on H1 FX bars is such that any model with enough capacity to find an edge has enough capacity to fit noise, and n=1,837 trades is three orders of magnitude short. **Your own research already demonstrates the discipline that makes this obviously wrong** — you falsified a frictionless +0.33R edge because costs killed it.
- **Reinforcement learning for position management.** Superficially attractive because management *is* the edge. But your simulator cannot order intrabar events (the study says so), does not model spread at the fill (STRAT-03), and does not model swap. **You would train a policy against a simulator whose known errors are the same order of magnitude as the effect you are optimising.**
- **"AI-optimised" parameter search over the ratchet.** Grid search with better marketing, on the same 3 years, converting one honest selection-bias caveat into an unmeasurable one.

**Plausible — each with a precondition:**

- **Cost/slippage prediction.** Genuinely tractable: dense labels (every fill produces one), stationary-ish structure, directly usable output. **Precondition: OBS-01 + C2 capturing realised slippage.** Start with a lookup table by symbol × hour; you likely never need a model.
- **Fill-probability modelling for resting limits.** Your backtest fills any limit whose price is touched — optimistic, and every entry is a limit. A model of P(fill | depth, volatility, time) corrects a known bias in the *simulator* rather than predicting the market. **Precondition: several hundred live limit outcomes (~6 months).** Note `docs/superpowers/plans/2026-07-30-passive-entry-s1-fill-model.md` is your most recent commit, suggesting you reached this conclusion independently. **It is the right target.**
- **Anomaly detection on the bot's own telemetry.** Not market prediction — operational monitoring. "Is today's signal rate, grade distribution, spread and slippage consistent with the last 30 days?" **Highest genuine ML value in the system, and it is arguably just statistics.** Would catch EXEC-07, SEC-05 and RISK-03 as anomalies rather than as audit findings.

**The honest answer to "where does ML help": nowhere yet — and the reason is data infrastructure, not modelling.** All three preconditions (a journal recording the label, a simulator whose biases are smaller than the effect, a measured baseline expectancy) are currently unmet.

## 11.7 Robustness

| ID | Item | Verdict |
|---|---|---|
| **E1** | Deterministic replay from the journal | Very high, 2 days, **mostly built.** Extend `kernel_replay` past `_execute_signal` |
| **E2** | Canary deployment | Moderate, 1 day. `titan-demo.service` already models the pattern. Formalise: 48 h on demo before the live unit updates |
| **E3** | Two-instance shadow | As D2. Depends on OPS-01 |
| **E4** | **Out-of-band flatten** | **Very high, half a day. The most important robustness item that does not already partly exist.** `scripts/flatten.py`: own ZMQ socket, own port, sends `CLOSE_POS` for every reported position, **then polls the heartbeat until the list is empty and prints the observed count.** Runnable from any shell, independent of the main loop, tells the truth. Fixes RISK-08, CTRL-02 and OPS-04 as one item |

---

# SECTION 12 — SYNTHESIS

*The executive summary, top-10 ranking, severity table, four-stage roadmap, quick wins and go-live checklist are in `04-REMEDIATION-ROADMAP.md`, and the complete finding list is in `03-FINDINGS-REGISTER.xlsx`.*

## Closing note from the panel

The four perspectives disagreed across every phase — whether to rewrite or refactor the controller, whether `tradebot/` is an asset or a distraction, whether `/panic` should have friction, whether the +0.194R edge is real. They agreed on three things.

**First:** the research work here is better than the engineering work, and that is an unusual and **recoverable** position to be in. Most failing trading systems have the opposite problem — solid plumbing wrapped around an edge that was never there. This one has a plausible edge and plumbing that has not been closed. **The second problem is the one that responds to a checklist.**

**Second:** almost nothing in Stage A is hard. It is one week of unglamorous work — persist a float, pass an extra argument, bound a range, check a return value, rotate a token. **The reason it has not been done is not difficulty; it is that building a Kalman filter and a React cockpit is more interesting than writing a test for a 129-line socket wrapper.** Resist that for one week.

**Third:** do not skip the soak, and do not start it until OBS-01 and the ratchet extraction are done. **The number that decides whether this system is worth running — the live expectancy of the managed exit engine — does not currently exist anywhere: not in any document, not in any test, not in any journal.** Everything else in this audit is in service of being able to measure it honestly.
