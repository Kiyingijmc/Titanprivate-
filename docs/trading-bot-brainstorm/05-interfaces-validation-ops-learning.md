# 05 — Interfaces, Validation Pipeline, Operations & Learning Loop

## PART A — GUI & Telegram (Topic 8)

### A1. GUI (web app served by the interface process)

Pages:
1. **Dashboard:** equity curve + open risk gauge vs limits, positions table (child, instrument, R multiple, mode badge), live signal feed with state chips, regime map (instrument × regime heat strip), breaker status bar.
2. **Confirmations:** pending cards — direction, instrument, level, computed size, stop/TP in R and price, the frozen 'why' snapshot rendered as human sentences ("RSI2 = 4.1, price at lower BB, regime RANGING 0.81, spread normal"), validity countdown, Approve / Reject / Snooze.
3. **Children:** per-child page — live vs backtest overlay, per-instrument viability badges, params (editable within validated ranges), mode switch, pause.
4. **Instruments:** discovery results, tags, resolution confidence, spread profile per session, enable/propose queue.
5. **Config:** form-based editor over the schema (invalid states unclickable), config history + revert.
6. **Backtests:** run/queue from the GUI, walk-forward reports, gate checklist per child version.
7. **Journal:** every closed trade with snapshot, execution telemetry, human-vs-bot close attribution.

Websocket-pushed state; the GUI is a *projection of the event log* — it can replay any day.

### A2. Telegram

Commands: `/status` (equity, open R, breakers), `/positions`, `/signals`, `/mode <child> <mode>`, `/pause <child|family|all>`, `/resume`, `/flatten <instrument|all>` (double-confirm), `/killswitch` (double-confirm), `/report daily|weekly`, `/config get|set` (live-class keys only).
- Signal cards: compact snapshot + inline **Approve / Reject** buttons (callback = atomic CAS on the confirmation store — GUI resolves live).
- Security: user-ID allowlist; destructive commands require confirmation tap + rate limiting; secrets never in messages; quiet hours (urgent breaker alerts pierce them).
- Notifications: fills, exits (with R result), breaker trips, spec-change diffs, viability disables, anomaly alerts.

## PART B — Validation pipeline (Topic 9)

### B1. Data
- Source: broker's own M1 history via MT5 (matches live feed) + a second source cross-check for gaps/bad ticks; resample upward to all needed timeframes; store Parquet.
- Quality gates: gap scan, duplicate scan, weekend/holiday map, outlier ticks flagged.

### B2. Cost model (the honesty layer)
- Spread: per-session sampled distribution (from live sampling once running; conservative published values before that) — *not* a single average.
- Slippage: from execution profiles once live; before that, mechanism-dependent conservative defaults (stops slip, limits don't, market = ½ spread extra).
- Commission + swap (incl. triple-swap day) always included. Backtests without this model are not admissible evidence.

### B3. Methodology
- **In-sample / out-of-sample split** (e.g. 2015–2021 / 2022–now), parameters touched only on IS.
- **Walk-forward:** optimize on rolling 2y, test on next 6m, roll; efficiency = OOS performance / IS performance, require ≥ 0.5.
- **Overfitting defenses:** max 3–4 free params per child; parameter-neighborhood stability (performance plateau, not spike); Monte-Carlo trade reshuffling for drawdown distribution; multiple-testing discipline (log every variant tried; discount accordingly).
- **Regime-sliced results:** performance by regime label must match the child's thesis (a meanrev child profitable mainly in TRENDING regimes is a red flag even if net-positive).

### B4. Promotion gates (per child version)

| Gate | Requirement (defaults, tune later) |
|---|---|
| G1 Backtest | OOS profit factor ≥ 1.3 after costs; max DD ≤ 2× target; ≥ 100 trades; WF efficiency ≥ 0.5; param plateau |
| G2 Demo forward | ≥ 8 weeks or ≥ 30 trades on demo; results within Monte-Carlo cone of backtest; execution telemetry sane |
| G3 Live probation | 25% of normal risk for ≥ 4 weeks; no anomaly flags; then full risk |

Demotion is automatic: live performance exits the expectation cone → child back to demo/paused (see Part D).

## PART C — Operations & safety (Topic 10)

- **Deployment:** small VPS near broker server (latency matters little for H1+ but connection stability does); Dockerized processes; systemd/watchdog restarts; NTP time sync (session logic depends on it).
- **Recovery drill (tested, not assumed):** kill -9 the core mid-position → replay event log → reconcile with broker → positions adopted, stops verified present, diff report. This drill is part of CI.
- **Monitoring:** heartbeat to a dead-man's-switch (healthchecks.io-style) — silence itself alerts; feed-staleness detector; disk/memory watch; daily self-report to Telegram.
- **Alert taxonomy:** INFO (fills) → WARN (viability disable, spec change) → CRITICAL (breaker, reconcile diff, dead feed) — CRITICAL pierces quiet hours.
- **Security:** MT5 credentials in env/secret store, never in config files; Telegram allowlist; GUI behind auth + TLS; no inbound ports beyond the GUI.
- **The two red buttons** (Telegram + GUI, always available, bypass everything except sanity double-confirm): PAUSE-ALL (no new risk) and FLATTEN-ALL (close everything, cancel everything).

## PART D — Learning loop (Topic 11)

The feedback flows that make "fully automatic adjustment" real:

1. **Execution profiles → execution defaults** (file 03 A1/A4): measured slippage per mechanism shifts stop-vs-synthetic and limit-offset choices per broker/instrument/session. Cadence: rolling, with minimum-sample thresholds before any switch.
2. **Spread sampling → viability gates** (file 03 B4): continuous; auto-disable/enable with hysteresis so children don't flap.
3. **Live-vs-backtest drift:** each child's live trades scored against its Monte-Carlo expectation cone (win rate, avg R, DD). Outside the 95% cone → WARN + risk auto-halved; outside 99% → paused + review flag. This is the edge-decay alarm — the most valuable automation in the entire system, because all edges decay eventually.
4. **Regime attribution:** P&L sliced by regime label, live vs backtest; divergence = the regime engine or the thesis drifted — both visible.
5. **Human-decision analytics:** hybrid/manual approve-vs-reject outcomes ("your rejections would have made +14R this quarter") — data on whether the human filter adds value per child.
6. **Periodic re-validation:** every child re-runs the walk-forward on schedule (quarterly) with data since its last validation appended; failing children demoted automatically.
7. **Anti-goal (explicit):** no online self-modification of strategy parameters. The loop adjusts *execution, costs, risk throttles, and on/off states* — it never silently re-optimizes entry logic. Parameter changes go through the validation pipeline like any new version. Self-tuning entry logic on live data is how bots overfit themselves to death in production.
