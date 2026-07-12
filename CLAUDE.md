# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Titan is a Python ICT/SMC trading engine that trades through **MetaTrader 5 over a ZeroMQ bridge** — it does **not** use the `MetaTrader5` Python package. The Python side is the strategy/risk brain; an MQL5 Expert Advisor (`Titan_Gateway.mq5`) running inside MT5 on Windows is the execution venue. They talk over three ZMQ sockets. Because of this, the Python side is cross-platform and runs in WSL/Linux; only MT5 + the EA require Windows.

## Commands

The virtualenv is at `.venv` (it ships without `pip`; if pip is missing, bootstrap with `curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python -`).

```bash
.venv/bin/python -m pip install -r requirements.txt   # deps (pandas/numpy/pyzmq/...)

# Tests (stdlib unittest — there is no pytest)
.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'   # all unit tests
.venv/bin/python -m unittest tests.unit.test_risk_manager_sizing -v  # a single test module

# Offline backtest (reads test_data.csv; needs no MT5)
.venv/bin/python tests/backtest/backtest_engine.py

# Live MT5 bridge tooling (run ONLY when main.py is NOT running — same ports)
.venv/bin/python scripts/check_bridge.py                              # prove EA<->Python link, prints WSL IP
.venv/bin/python scripts/export_history.py --symbol EURUSD --tf M5 --count 5000 --out data/history/EURUSD_M5.csv

# Run the live bot
.venv/bin/python main.py
```

There is no linter/build step configured.

## Architecture (the big picture)

- **`main.py`** is only a bootstrap (Python ≥3.10 guard, `sys.path`, fatal logging to `boot_crash.log`). The real system is **`src/core/system_controller.py`**: a single `async while True` loop that polls the bridge, routes messages, runs strategies on M5 candle close, manages open trades, reconciles state, and sends Telegram reports.
- **ZMQ bridge** (`src/execution/bridge_zmq.py` ⇄ `mql5_bridge/Experts/Titan_Gateway.mq5`): **Python BINDS, the EA CONNECTS.** Three sockets: `32768` PUSH (Py→MT5 commands), `32769` PULL (MT5→Py data, drained in batches), `32770` REQ/REP (reliable order handshake + PING). Only one process can bind these ports — never run the bot and the `scripts/` tools simultaneously.
- **Message flow** (EA→Py JSON `type`s): `TICK`, `HEARTBEAT` (balance/equity + open positions + pending orders), `HISTORY` (bars **plus broker specs** `tv`/`ts`/`vm`/`vs`), `EXECUTION` (OPENED/CLOSED). Commands Py→EA: `TRADE` (cmd `MARKET`/`LIMIT`/`STOP`) over REQ for order entry only; `MODIFY` (SL/TP), `CLOSE_POS` (optional `volume` = partial close), `CANCEL`, `GET_HISTORY`, `PING` are fire-and-forget on PUSH. Never put slow trade calls on the REQ path — a reply the EA can't deliver in time wedges its REP socket until the EA is reattached; management outcomes are verified from HEARTBEAT state instead. Trade-management commands are routed by `SystemController._dispatch_mgmt_command`; any EA change requires a **manual recompile in MetaEditor on Windows**.
- **Signal grading + trade management** (v14.4): every signal is confluence-graded (A++…C) by `src/analysis/signal_grader.py` and journaled; only grades ≥ `signal_grading.min_grade` execute. In-trade management (BE at 38.2%, partials at 61.8%/88.6%, opt-in runner trail) lives in `src/execution/trade_manager.py` and only engages when `active_orders.initial_entry/initial_tp` are non-zero — send-time metadata + heartbeat backfill guarantee that; don't reintroduce `tp=0` registrations. See `docs/TRADE_MANAGEMENT.md`.
- **Strategy contract**: `src/strategies/models/silver_bullet.py` (the only approved strategy; Unicorn/ICT_OTE/CRT were removed 2026-07-12 — unapproved, all NO-GO'd or unvalidated) extends `base_strategy.py` and returns a decision dict `{signal, type, price, sl, tp}` from `on_new_candle()`. Only `on_new_candle` is used by the controller and backtester. The controller enriches data via `SMCAnalyzer` + `BiasEngine` and filters all signals against HTF bias. New strategies enter as Trading-OS plugins per `docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md`.
- **Risk/sizing** (`src/risk/risk_manager.py`): position sizing is **broker-spec driven** — it uses MT5 `tick_value`/`tick_size` (asset-agnostic and correct for forex/metals/indices/crypto/oil). Specs arrive via the `HISTORY` message and are stored per-symbol by `update_symbol_specs`. **If specs have not loaded for a symbol, `calculate_lot_size` fails safe (returns 0 + logs) rather than guessing** — do not reintroduce a hardcoded per-asset fallback. `normalize_price` snaps to the broker tick grid; precision is counted via `Decimal` to survive scientific-notation ticks like `1e-05`.
- **State** (`src/core/state_manager.py`): a persistent SQLite connection (WAL) tracking `active_orders`/`trade_history`; survives reboots and reconciles "ghost" trades closed externally.
- **Telemetry** (`src/ops/telemetry.py`): Telegram notifications **and remote control** (`/panic`, `/closeall`, `/close`, `/pause`…), authorized by a single chat ID.

## Critical conventions & gotchas

- **Trading only happens for symbols in `config/config.yaml` strategy `pairs`** (they seed `active_symbols`, get `GET_HISTORY` at warmup, and thus get broker specs). To trade a new FBS asset, add it there with the **exact** broker symbol name; a "cold" symbol may return no history on the first request and simply won't trade until specs+data load.
- **WSL↔Windows networking**: the EA's `InpIP` input must point at the WSL IP (it changes on WSL reboot — re-read with `ip -4 addr show eth0`). The live MT5 is **FBS MetaTrader 5**; its data folder is `…/Terminal/776D2ACDFA4F66FAF3C8985F75FA9FF6`. `libzmq.dll` + `libsodium.dll` (x64) must sit in that terminal's `MQL5/Libraries`.
- **Secrets**: `.env` holds the live Telegram token and is git-ignored (use `.env.example` as the template). `config.yaml`'s `mt5_path` and the `_reboot_terminal` watchdog are Windows-only (`taskkill`/`terminal64.exe`) and no-op on Linux.
- **Dead code was purged 2026-07-12** (event_bus, reconciliation, dev_override.yaml, Zmq_Wrapper.mqh, TITAN_ENV, sqlalchemy). The v15 event bus is `src/core/bus.py` (new design, Phase III blueprint §5) — do not resurrect the old patterns.
- The files carry verbose `AUDIT:`/`STATUS: PRODUCTION READY` headers from the previous owner; treat them as historical commentary, not ground truth.

## Working style for this repo

Use TDD for fixes (a failing `tests/unit` case first, then the minimal change), keep changes small and anchored to existing patterns, and verify by running the unit suite before claiming done. Ask before adding new dependencies, layers, or frameworks. Work on a feature branch (`main` holds the inherited baseline).

## HTTP bridge (Phase 1 — data + execution-in-isolation; live loop still on ZMQ)

Titan has a Windows-side FastAPI MT5 bridge in `bridge/` (copied from MOS, port 8766) and a
Linux-side `Broker` client in `src/execution/broker/`. To pull data / use the broker:

1. Windows: MT5 running + logged into FBS-Demo.
2. Windows PowerShell, in the bridge dir (via `\\wsl.localhost\...\bridge` PSDrive): `py -3.11 run_bridge.py` (binds :8766).
3. WSL: set `TITAN_BRIDGE_TOKEN` (match `bridge/config/.env`'s `BRIDGE_AUTH_TOKEN`). URL auto-resolves (mirrored→127.0.0.1, NAT→gateway); override with `TITAN_BRIDGE_URL`.
4. Verify: `.venv/bin/python scripts/check_bridge_http.py` → "✅ Bridge is UP".
5. Pull data: `scripts/export_history.py --symbol XAUUSD --tf M5 --out data/history/XAUUSD_M5.csv`; `scripts/cache_specs.py`.

The ZMQ bridge + EA remain the live execution path until Phases 2–3. Don't run live writes from
the Titan bridge and the MOS bridge against the same terminal simultaneously.
