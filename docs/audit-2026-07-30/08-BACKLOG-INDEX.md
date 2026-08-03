# Audit findings → mig backlog index

Every one of the **101 findings** in `03-FINDINGS-REGISTER.xlsx` is loaded as a row in the mig
backlog (`docs/sessions/_BACKLOG.md`), track **S**, source **audit**, status **inbox** — mig's
queue of work accepted and waiting to be built.

> **On `promoted`.** In mig, `promoted` does not mean "approved and queued" — it means a session
> has been *minted*: an ID is allocated, a prompt file is written to `docs/sessions/archive/`, and
> the track pointer `docs/sessions/NEXT.md` is overwritten to point at it. Only one session can hold
> the pointer at a time, so promoting all 101 would mint S017…S117 and leave a single usable pointer
> with 100 orphaned prompts. **`inbox` is the waiting-for-implementation state**; a row moves to
> `promoted` when it is actually picked up, one at a time, via `mig backlog promote <slug> S`.

## Working the queue

```bash
mig triage S                      # ranked ready board
mig backlog ls --status inbox     # everything waiting
mig backlog show <slug>           # full finding: severity, location, fix, stage
mig backlog promote <slug> S      # take one — mints the session
mig spec <ID> && mig approve <ID> # spec gate
mig run S                         # build -> verify -> review -> gate
```

Each row's description carries the register's own fields, in this order:

```
<ID> <finding> · sev <severity> · stage <A|B|C> · effort <est> · loc <file:line> · fix <recommended fix> · audit-2026-07-30 §<section>
```

**Loaded:** 101 / 101 findings — complete.

| Severity | Count | Stage A | Stage B | Stage C |
|---|---|---|---|---|
| **P0** | 1 | 1 | 0 | 0 |
| **Critical** | 8 | 4 | 4 | 0 |
| **High** | 36 | 17 | 15 | 4 |
| **Medium** | 39 | 11 | 19 | 9 |
| **Low** | 17 | 3 | 3 | 11 |
| **Total** | **101** | 36 | 41 | 24 |

---


## P0 — act today  (1)

| ID | Stage | Effort | Finding | Location | Backlog slug |
|---|---|---|---|---|---|
| **P0-01** | A | 2 h | Live Telegram token public in git history (.env, 6 trees) and in HEAD (data/logs/system.log) | `7dd9527 .env; data/logs/system.log:147` | `p0-01-live-telegram-token-public` |

## Critical — blocks live capital  (8)

| ID | Stage | Effort | Finding | Location | Backlog slug |
|---|---|---|---|---|---|
| **RISK-01** | A | 2 h — **DONE 2026-07-31** (`feat/risk-01-daily-anchor`, unmerged) | Daily drawdown anchor resets on every process restart; no restart cap | `risk_manager.py:51; titan-live.service:29` | `risk-01-daily-drawdown-anchor-resets` |
| **RISK-02** | A | 1 h | Position-count and per-symbol caps are blind to resting pending orders | `exposure.py:92,100; arbiter.py:250` | `risk-02-position-count-and-per` |
| **RISK-10** | A | 1 h | Live bars and history bars are timestamped in two different timezones, in the same buffer | `candle_maker.py:113; data_store.py:79` | `risk-10-live-bars-and-history` |
| **SEC-05** | A | 2 h | ZMQ unauthenticated, bound tcp://*, inbound messages never validated | `bridge_zmq.py:25,36,53; risk_manager.py:62; TitanZmq.mqh` | `sec-05-zmq-unauthenticated-bound-tcp` |
| **ARCH-01** | B | 2 d | No idempotency key on any order; timeout-then-retry can double-fill | `bridge_zmq.py:70; system_controller.py:449` | `arch-01-no-idempotency-key-on` |
| **ARCH-02** | B | 2 d | Bridge protocol has no schema, no version, no sequence numbers | `bridge_zmq.py:57; CLAUDE.md:37` | `arch-02-bridge-protocol-has-no` |
| **OBS-01** | B | 1 d | Journal schema cannot validate the live ratchet; soak data accruing now is unusable | `state_manager.py:66,200-205` | `obs-01-journal-schema-cannot-validate` |
| **STRAT-01** | B | 2 d | Validated exit engine is not the live exit engine; the edge lives entirely in exits | `poc_sb_stops.py:215 vs trade_manager.py:51` | `strat-01-validated-exit-engine-is` |

## High — blocks live capital  (36)

| ID | Stage | Effort | Finding | Location | Backlog slug |
|---|---|---|---|---|---|
| **ARCH-04** | A | 15 m | ZMQ bind failures are non-fatal; bot boots with a dead socket | `bridge_zmq.py:26,37,54; :781` | `arch-04-zmq-bind-failures-are` |
| **ARCH-06** | A | 30 m | No single-instance lock; two bots can write the same databases | `NOT FOUND in src/; tradebot/core/recovery.py:147` | `arch-06-no-single-instance-lock` |
| **ARCH-07** | A | 2 h | No SIGTERM/SIGINT handler; no graceful shutdown anywhere | `src/, main.py (grep: nothing)` | `arch-07-no-sigterm-sigint-handler` |
| **CTRL-02** | A | 4 h | /panic, /closeall and /cancel all report success they have not verified | `system_controller.py:1094-1119` | `ctrl-02-panic-closeall-and-cancel` |
| **CTRL-03** | A | 15 m | Telegram authorization fails OPEN when TELEGRAM_CHAT_ID is unset | `telemetry.py:36,142-144` | `ctrl-03-telegram-authorization-fails-open` |
| **CTRL-04** | A | 30 m | SettingsStore.set accepts any key -> PATCH system.mt5_path -> subprocess.Popen on restart | `settings.py:69,82; system_controller.py:778` | `ctrl-04-settingsstore-set-accepts-any` |
| **EXEC-01** | A | 1 h | A network call to api.telegram.org sits in the trading loop, ahead of tick ingestion | `system_controller.py:336; telemetry.py:119` | `exec-01-a-network-call-to` |
| **EXEC-03** | A | 15 m | HTTP status codes never checked; 429s silently drop alerts | `telemetry.py:94-100` | `exec-03-http-status-codes-never` |
| **OBS-06** | A | 30 m | Token embedded in every request URL; no log redaction anywhere | `telemetry.py:37` | `obs-06-token-embedded-in-every` |
| **OBS-09** | A | 2 m | No durable audit trail for any Telegram intervention | `telemetry.py:147` | `obs-09-no-durable-audit-trail` |
| **OPS-01** | A | 2 h | No demo/live safeguard of any kind | `NOT FOUND` | `ops-01-no-demo-live-safeguard` |
| **OPS-05** | A | 5 m | No StartLimitBurst; unbounded restart loop | `titan-live.service:29` | `ops-05-no-startlimitburst-unbounded-restart` |
| **RISK-07** | A | 1 h | Ask price is transmitted by the EA and discarded; no spread ceiling exists | `system_controller.py:690; EA:88-90` | `risk-07-ask-price-is-transmitted` |
| **RISK-08** | A | 4 h | Kill switch shares the event loop it is meant to rescue | `system_controller.py:336` | `risk-08-kill-switch-shares-the` |
| **RISK-09** | A | 15 m | EA reports all positions with no magic filter; bot adopts and force-closes manual trades | `EA:180-207; trade_manager.py:82` | `risk-09-ea-reports-all-positions` |
| **SEC-02** | A | 1 h | HTTP bridge (full order entry) defaults to 0.0.0.0, by default and by documented example | `bridge/app/settings.py:16; .env.example:1; main.py:116` | `sec-02-http-bridge-full-order` |
| **SEC-04** | A | 1 h | Service runs as root; zero hardening directives in either systemd unit | `deploy/systemd/*.service` | `sec-04-service-runs-as-root` |
| **CTRL-01** | B | 4 h | The two most destructive commands have the weakest guards | `telemetry.py:193,201; :1051` | `ctrl-01-the-two-most-destructive` |
| **CTRL-07** | B | 4 h | Telegram is the only alert channel; no fallback exists | `telemetry.py; health.py` | `ctrl-07-telegram-is-the-only` |
| **ENTRY-01** | B | 1 d | EA routes commands by substring search over raw JSON; concatenated frames close the wrong ticket | `EA:252,299,317,326,389` | `entry-01-ea-routes-commands-by` |
| **EXEC-05** | B | 4 h | No reconnect-triggered reconciliation; resumes blind for up to 60s | `system_controller.py:322,373` | `exec-05-no-reconnect-triggered-reconciliation` |
| **EXEC-07** | B | 4 h | A frozen price feed with live heartbeats is completely undetected | `EA:84,98; system_controller.py:332` | `exec-07-a-frozen-price-feed` |
| **EXIT-01** | B | 2 d | Ratchet state advances before the broker confirms; never verified, never retried | `trade_manager.py:136; system_controller.py:563` | `exit-01-ratchet-state-advances-before` |
| **EXIT-02** | B | (with EXIT-01) | MODIFY + partial dispatched unverified; volume read from a 5s-stale heartbeat | `trade_manager.py:120-122` | `exit-02-modify-partial-dispatched-unverified` |
| **OBS-02** | B | 4 h | Every journal write path swallows its own failures; drops counter never read | `state_manager.py:140,166,208; jsonlog.py:33` | `obs-02-every-journal-write-path` |
| **OBS-05** | B | 2 d | No reconciliation of the journal against broker deal history | `NOT FOUND` | `obs-05-no-reconciliation-of-the` |
| **OBS-07** | B | 4 h | _readiness uses last-message time, not last-heartbeat; cannot detect alive-but-not-trading | `system_controller.py:605,1041` | `obs-07-readiness-uses-last-message` |
| **OPS-02** | B | 1 d | There is no CI; run_pr_checks.sh cites a condition that no longer holds | `NO .github; scripts/run_pr_checks.sh:8` | `ops-02-there-is-no-ci` |
| **OPS-03** | B | 1 d | ZMQBridge has zero tests; the EA has zero tests and no framework | `grep ZMQBridge tests/ -> nothing` | `ops-03-zmqbridge-has-zero-tests` |
| **OPS-04** | B | 1 d | No flatten runbook; no backup of trade_state.db; no tested restore | `docs/runbooks/` | `ops-04-no-flatten-runbook-no` |
| **RISK-03** | B | 2 d | Correlation filter fails OPEN during warmup, after restart, and on any error | `correlation.py:105,92` | `risk-03-correlation-filter-fails-open` |
| **SEC-01** | B | 4 h | Zero dependency pinning on the live path; no lockfile | `requirements.txt (0 exact, 15 >=)` | `sec-01-zero-dependency-pinning-on` |
| **ARCH-05** | C | 1 d | Weak ack; no nack taxonomy; no retry policy at all | `bridge_zmq.py:75; system_controller.py:472` | `arch-05-weak-ack-no-nack` |
| **RISK-06** | C | 2 d | No broker stop-level or freeze-level validation; rejections are silent and unretried | `EA:152; system_controller.py:472` | `risk-06-no-broker-stop-level` |
| **STRAT-03** | C | 1 d | Spread is charged as a post-hoc cost but never applied to the fill | `backtest_engine.py:68-73,168` | `strat-03-spread-is-charged-as` |
| **STRAT-05** | C | 3 d | No portfolio simulation; the reported 14R maxDD ignores the 5% concurrent cap | `simulate_signals:137; research_run.py:237` | `strat-05-no-portfolio-simulation-the` |

## Medium — fix before scaling  (39)

| ID | Stage | Effort | Finding | Location | Backlog slug |
|---|---|---|---|---|---|
| **ARCH-03** | A | 15 m | Truncated ZMQ messages silently discarded | `bridge_zmq.py:118` | `arch-03-truncated-zmq-messages-silently` |
| **CTRL-05** | A | 30 m | WebSocket auth bypasses AuthThrottle; unlimited unrecorded token guesses | `server.py:85-97` | `ctrl-05-websocket-auth-bypasses-auththrottle` |
| **ENTRY-03** | A | 4 h | M15 strategies silently never fire; H4 bucketing broken | `data_store.py:25; candle_maker.py:118` | `entry-03-m15-strategies-silently-never` |
| **EXEC-04** | A | 5 m | json.JSONDecodeError in poll_commands escapes and crashes the process | `telemetry.py:127,133` | `exec-04-json-jsondecodeerror-in-poll` |
| **OBS-08** | A | 30 m | WATCHDOG=1 fires in a 50ms/10s window; loop stalls cause spurious systemd restarts | `system_controller.py:361` | `obs-08-watchdog-1-fires-in` |
| **OBS-10** | A | 2 m | synchronous=NORMAL on the live position-state database | `state_manager.py:36` | `obs-10-synchronous-normal-on-the` |
| **OPS-09** | A | 30 m | docs/RESUME.md - the designated first-read file - is stale | `RESUME.md:4,23` | `ops-09-docs-resume-md-the` |
| **RISK-14** | A | 30 m | Daily limit trip is completely unlogged and unalerted | `risk_manager.py:141` | `risk-14-daily-limit-trip-is` |
| **SEC-03** | A | 5 m | 43 .pyc files tracked, including bytecode of three deleted strategies | `git ls-files` | `sec-03-43-pyc-files-tracked` |
| **SEC-07** | A | 2 m | .claude/settings.json auto-approves git add and git commit | `.claude/settings.json:6-7` | `sec-07-claude-settings-json-auto` |
| **STRAT-04** | A | 2 h | Legacy Backtester measures the rejected M5 config; CLAUDE.md points the operator at it | `backtest_engine.py:209; CLAUDE.md:21` | `strat-04-legacy-backtester-measures-the` |
| **ARCH-08** | B | 1 d | No config schema validation on the live path (a validated schema exists, unwired) | `config_layer.py:20; tradebot/config/schema.py` | `arch-08-no-config-schema-validation` |
| **ARCH-09** | B | 30 m | Corrupt overrides.yaml silently reverts to defaults (higher risk) | `config_layer.py:29-34` | `arch-09-corrupt-overrides-yaml-silently` |
| **CTRL-06** | B | 1 h | Runtime-enabled strategies get no strategy_ttls entry | `system_controller.py:809,1060,746` | `ctrl-06-runtime-enabled-strategies-get` |
| **CTRL-08** | B | 2 h | /panic cannot cancel an in-flight order submission | `system_controller.py:457,1087` | `ctrl-08-panic-cannot-cancel-an` |
| **ENTRY-02** | B | 4 h | Session gate keyed to wall-clock, not bar time | `system_controller.py:842` | `entry-02-session-gate-keyed-to` |
| **ENTRY-04** | B | 15 m | Warmup history includes the currently forming bar | `EA:256,267` | `entry-04-warmup-history-includes-the` |
| **EXEC-06** | B | 30 m | Out-of-order tick silently corrupts the forming candle | `candle_maker.py:127,139` | `exec-06-out-of-order-tick` |
| **EXEC-08** | B | 2 h | Reconciliation is not part of the boot sequence | `system_controller.py:267-292,322` | `exec-08-reconciliation-is-not-part` |
| **EXIT-03** | B | 2 h | TTL cancellation deletes the DB row before the cancel is confirmed | `system_controller.py:748` | `exit-03-ttl-cancellation-deletes-the` |
| **EXIT-04** | B | 2 h | Runner high-water marks and tighten flag are in-memory only | `trade_manager.py:48-49` | `exit-04-runner-high-water-marks` |
| **EXIT-05** | B | 30 m | Runner sets tp = 0; no broker-side target survives the bot dying | `trade_manager.py:129` | `exit-05-runner-sets-tp-0` |
| **OBS-03** | B | 30 m | INSERT OR REPLACE preserves ratchet state but not the trade record | `state_manager.py:129` | `obs-03-insert-or-replace-preserves` |
| **OBS-04** | B | 1 h | INSERT OR IGNORE + unconditional DELETE; ghost sweep records P&L as 0 permanently | `state_manager.py:200,206; :395` | `obs-04-insert-or-ignore-unconditional` |
| **OPS-06** | B | 1 d | Only 4 tests on calculate_lot_size; property tests point at the dead package | `test_risk_manager_sizing.py; test_tradebot_properties.py` | `ops-06-only-4-tests-on` |
| **OPS-07** | B | 1 d | No runtime invariant assertions | `NOT FOUND` | `ops-07-no-runtime-invariant-assertions` |
| **OPS-08** | B | 30 m | config/overrides.yaml is gitignored, so GUI-set risk settings are backed up nowhere | `.gitignore:37` | `ops-08-config-overrides-yaml-is` |
| **RISK-04** | B | (with RISK-03) | Correlation check is direction-blind | `correlation.py:128` | `risk-04-correlation-check-is-direction` |
| **RISK-05** | B | (with RISK-03) | Currency saturation uses substring matching and a hardcoded threshold | `exposure.py:33,107` | `risk-05-currency-saturation-uses-substring` |
| **SEC-06** | B | 4 h | verify_integrity.py always fails, exits 0, and blocks on input() | `verify_integrity.py:41,62,137` | `sec-06-verify-integrity-py-always` |
| **ARCH-10** | C | 1 d | Production risk path softened with getattr to accommodate test fixtures | `system_controller.py:414,433` | `arch-10-production-risk-path-softened` |
| **ARCH-11** | C | 2 h | _reboot_terminal is a no-op on the documented Linux deployment, called forever | `system_controller.py:772,332` | `arch-11-reboot-terminal-is-a` |
| **CTRL-10** | C | 2 h | No rate limiting on inbound Telegram commands, per-user or global | `telemetry.py` | `ctrl-10-no-rate-limiting-on` |
| **EXEC-02** | C | 1 d | Synchronous SQLite commit and file flush on the signal path | `audit_logger.py:101; jsonlog.py:31` | `exec-02-synchronous-sqlite-commit-and` |
| **EXEC-09** | C | 1 h | prune_database is dead code; audit_log and data/journal/ grow without bound | `state_manager.py:228; jsonlog.py:27` | `exec-09-prune-database-is-dead` |
| **RISK-11** | C | 15 m | round(lots, 2) destroys sub-0.01 lot steps | `risk_manager.py:203` | `risk-11-round-lots-2-destroys` |
| **RISK-15** | C | 2 d | No weekly cap, monthly cap, peak-equity drawdown, consecutive-loss halt or margin headroom | `risk_manager.py; NOT FOUND` | `risk-15-no-weekly-cap-monthly` |
| **STRAT-02** | C | 2 d | The load-bearing ratchet parameters were never varied | `trade_manager.py:37-39,122,132,144` | `strat-02-the-load-bearing-ratchet` |
| **STRAT-06** | C | 1 d | No swap/financing model anywhere | `trade_dollars:148` | `strat-06-no-swap-financing-model` |

## Low — hygiene  (17)

| ID | Stage | Effort | Finding | Location | Backlog slug |
|---|---|---|---|---|---|
| **OPS-10** | A | 15 m | .bat files document a superseded architecture and leak the token prefix on every run | `AUTO_START.bat:13; RUN_TITAN.bat:36` | `ops-10-bat-files-document-a` |
| **OPS-12** | A | 10 m | Misleading STATUS: PRODUCTION READY headers throughout | `main.py:8 and elsewhere` | `ops-12-misleading-status-production-ready` |
| **OPS-17** | A | 10 m | test_telegram.py is a diagnostic script named like a test | `test_telegram.py` | `ops-17-test-telegram-py-is` |
| **OPS-11** | B | 5 m | Rollback procedure does not restore deleted files | `deploy-systemd.md:57` | `ops-11-rollback-procedure-does-not` |
| **OPS-14** | B | 10 m | _web_task is never awaited; GUI death is silent | `system_controller.py:260` | `ops-14-web-task-is-never` |
| **SEC-09** | B | 15 m | Bridge .env.example ships a memorable placeholder token | `bridge/config/.env.example:3` | `sec-09-bridge-env-example-ships` |
| **CTRL-09** | C | 30 m | esc() HTML-escapes strings sent with parse_mode=Markdown | `telemetry.py:173,188` | `ctrl-09-esc-html-escapes-strings` |
| **OBS-11** | C | 4 h | JsonLogger.bind() exists with zero callers; no correlation IDs anywhere | `jsonlog.py:52` | `obs-11-jsonlogger-bind-exists-with` |
| **OBS-12** | C | 2 h | Log levels mix severity with domain; everything lands at INFO | `audit_logger.py:95` | `obs-12-log-levels-mix-severity` |
| **OPS-13** | C | 30 m | command_cooldowns, runner_hwm and tightened are never pruned | `trade_manager.py:34,48,49` | `ops-13-command-cooldowns-runner-hwm` |
| **OPS-15** | C | 15 m | max_global_exposure_pct is a position count, not a percentage | `config.yaml:36` | `ops-15-max-global-exposure-pct` |
| **OPS-16** | C | 5 m | Backoff has no jitter | `telemetry.py:105` | `ops-16-backoff-has-no-jitter` |
| **RISK-12** | C | 15 m | Commission solver skipped when commission dominates | `risk_manager.py:183` | `risk-12-commission-solver-skipped-when` |
| **RISK-13** | C | 5 m | Cached risk scalars vs live config (DOWNGRADED - contained) | `risk_manager.py:28-31; settings.py:16-26` | `risk-13-cached-risk-scalars-vs` |
| **SEC-08** | C | 5 m | subprocess with shell=True (hardcoded literal, not injectable) | `system_controller.py:774` | `sec-08-subprocess-with-shell-true` |
| **STRAT-07** | C | 2 d | Missing walk-forward, Sharpe/Sortino, drawdown duration, MAE/MFE | `aggregate_metrics:110` | `strat-07-missing-walk-forward-sharpe` |
| **STRAT-08** | C | 1 h | Backtest shift_hours=-7 is fragile across misaligned DST transitions | `backtest_engine.py:221` | `strat-08-backtest-shift-hours-7` |

---

*Generated from `03-FINDINGS-REGISTER.xlsx` after loading it into the mig backlog. Slugs are read
back out of `docs/sessions/_BACKLOG.md`, which mig owns — do not hand-edit either file.*
