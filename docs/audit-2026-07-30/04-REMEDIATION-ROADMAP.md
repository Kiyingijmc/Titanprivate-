# Titan — Remediation Roadmap & Go-Live Checklist

**Companion to:** `02-AUDIT-REPORT.md` (findings in full) · `03-FINDINGS-REGISTER.xlsx` (tracking)
**Audit date:** 2026-07-30 · **Commits:** `7dd9527`..`cc59155`

---

## 1. Executive summary

**In plain terms:** Titan is a substantially more complete and more carefully-researched system than "unfinished forex bot" suggests. The end-to-end path — tick → feature → signal → grade → arbitration → sizing → two risk gates → order → fill → journal → notify — is fully implemented and functioning.

The research discipline behind the strategy is better than most professional desks: falsified priors, a-priori cost screens, out-of-sample splits with near-zero degradation, per-year and per-symbol slices, 2× spread stress, deterministic bootstrap bounds, honest self-authored integrity caveats, and a GO verdict conditioned on a supervised demo. The single funnel through which every order must pass is the correct architecture and **it holds: no strategy can place an order without passing risk.**

Underneath that, three structural problems:

**1. The layer nearest the money is the least engineered.** `bridge_zmq.py` — 129 lines, the only path an order can take to your broker — has zero tests, no idempotency key, unauthenticated sockets bound to all interfaces, and silently discards both bind failures and truncated messages. Meanwhile ~3,900 lines of tests point at a package (`tradebot/`) that cannot affect a trade.

**2. The component that produces the entire edge has never been run against a simulator.** The stop study is explicit: SilverBullet is **−0.122R** with fixed exits and **+0.194R** with the ratchet+runner. The validated ratchet is an offline reimplementation (`poc_sb_stops.replay_managed`); the live ratchet is `trade_manager.sync_positions`. Every difference between them — unverified fire-and-forget MODIFYs, 5-second-stale volumes, the dust guard, broker stop-level rejections — pushes live *below* the modelled figure, and **none is quantified. Live expectancy is unknown, and the sign is not guaranteed.**

**3. Several safety controls are advisory rather than enforced.** The daily drawdown limit resets on every process restart, with no restart limit. The position-count and per-symbol caps are blind to resting limit orders — the normal state of a limit-entry strategy. The correlation gate fails open during warmup and after any restart. The flatten command reports success it has not verified. Nothing anywhere checks whether the connected account is demo or live.

### Is this safe to run on live money today?

> **No. Not close, and not for strategy reasons.**

Even if the +0.194R edge were fully validated, the risk envelope is unenforced in ways that permit losses far outside the study's stated profile. The study reasons about a 14R (~14%) historical drawdown "within the 3%/day breaker's envelope." In the shipped configuration:

- `max_total_open_risk_pct: 5.0` authorises **5% at risk simultaneously**
- RISK-02 permits all five commitments **on one symbol in one direction**
- RISK-03 means the correlation gate may be **off**
- RISK-01 means each of the numerous crash paths grants a **fresh 3% daily allowance**, with no restart cap

**The breaker is a suggestion, and the concentration limit is not applied to the order type the strategy actually uses.**

### What specifically must change first

Nine things. Nothing else on any list matters until these are done.

| # | Change | ID | Effort |
|---|---|---|---|
| 1 | **Rotate the Telegram token and `deleteWebhook`.** It is public in two places on a public repo | P0-01 | 10 min |
| 2 | **Repo private; untrack ten committed artifacts and 43 `.pyc` files; rewrite history** | P0-01, SEC-03 | 2 h |
| 3 | **Persist `day_start_equity` across restarts; add `StartLimitBurst=3`** | RISK-01, OPS-05 | 2 h |
| 4 | **Pass pending orders into `check_exposure` and `arbiter._apply_caps`** | RISK-02 | 1 h |
| 5 | **Bounds-check `update_symbol_specs`; bind ZMQ to a specific interface; HMAC every message** | SEC-05 | 2 h |
| 6 | **Assert the account mode.** EA reports `ACCOUNT_TRADE_MODE` + login; Python refuses on mismatch | OPS-01 | 2 h |
| 7 | **Extend the journal schema** + a `trade_events` table — *deadline-sensitive* | OBS-01 | 1 d |
| 8 | **Extract the ratchet to one pure function used by both paths; re-run the study** | STRAT-01 | 2 d |
| 9 | **Build `scripts/flatten.py` and write the flatten runbook** | RISK-08, CTRL-02, OPS-04 | 4 h |

**Approximately one working week.** After that, a four-week demo soak with defined pass criteria. Live capital is a decision for after the soak, not before.

---

## 2. Top 10 findings by expected financial impact × likelihood

| # | Finding | Impact | Likelihood | Ref | Fix |
|---|---|---|---|---|---|
| **1** | **Live Telegram token public** in `.env` (6 trees of history) *and* `data/logs/system.log` (HEAD), on a public repo. Enables `setWebhook` — total silent loss of remote control including `/panic` — and perfect impersonation of the bot to you | High | **Certain — already happened** | `7dd9527`; `system.log:147` | Rotate → `deleteWebhook` → private → `filter-repo` |
| **2** | **Daily drawdown anchor resets on every restart.** In-memory only; re-anchors to drawn-down equity on the first heartbeat. `Restart=on-failure`, `RestartSec=10`, **no `StartLimitBurst`.** Crash paths are plentiful | **Very high — 3% × crash count, unbounded, in one day** | High | `risk_manager.py:51`; `titan-live.service:29` | Persist anchor + date to SQLite; `StartLimitBurst=3` |
| **3** | **Live expectancy is unmeasured.** −0.122R with fixed exits, +0.194R with the ratchet; the validated ratchet is offline code, the live ratchet is different code, and every known difference biases live downward | **Very high — you may be running a negative-expectancy system believing it is +2%/week** | **Certain — current state** | `poc_sb_stops.py:215` vs `trade_manager.py:51` | Extract to one pure function; re-run the study |
| **4** | **Count and per-symbol caps blind to resting limit orders.** Both gates receive only filled positions; the only live strategy enters exclusively on LIMIT, and limits rest up to 12 bars | **High — 5% concentrated vs 1% intended** | **High — the book's normal state, weekly** | `exposure.py:92,100`; `arbiter.py:250` | Pass `current_pending_orders` into both |
| **5** | **One ZMQ message re-sizes every trade to `hard_max_lots`.** Sockets bound `tcp://*`, no auth, and `update_symbol_specs` accepts arbitrary floats with zero bounds | **Catastrophic — ~100× intended risk** | Moderate adversarially; the **broker-misquote variant is plausible with no attacker** | `bridge_zmq.py:25`; `risk_manager.py:62` | Bounds-check specs; bind specific interface; HMAC |
| **6** | **Live bars and history bars timestamped in two different timezones, in the same buffer.** On the Kampala host every live bar is 3 h displaced from the history beside it; ATR, FVG and swing detection compute across the discontinuity | High | **Certain on the deployment host** | `candle_maker.py:113`; `data_store.py:79` | `fromtimestamp(ts, tz=utc).replace(tzinfo=None)` |
| **7** | **The flatten commands report success they have not verified.** `count` is *commands enqueued* on a fire-and-forget socket. With the EA detached, ZMQ buffers silently and **the operator is told they are flat while every position runs.** Compounded: `/panic` is unreachable if the loop is wedged, and no out-of-band flatten exists | **Unbounded — you stand down during a crisis** | Moderate | `system_controller.py:1094–1119`; `:336` | Report observed position count after 2 heartbeats; `scripts/flatten.py` |
| **8** | **No idempotency key on any order.** `magic` is a shared constant; the only unique ID is generated broker-side after the fill. On a REQ timeout Python assumes failure while the order may be live | High | Moderate (2.5 s timeout on a single-threaded EA serving 12 symbols) | `bridge_zmq.py:70`; `system_controller.py:449` | UUID in `comment`; EA dedup; **query, never resend** |
| **9** | **The journal cannot validate the ratchet.** No exit reason, no ratchet level at exit, no modification history, no slippage, no submit/fill timestamps. `time_placed` and `ratchet_level` exist in `active_orders` and are explicitly *not* copied by `archive_trade` | High — indirect: keeps #3 open indefinitely | **Certain, and deadline-sensitive** — soak data accruing now is unrecoverable | `state_manager.py:66,200–205` | Add columns + `trade_events` table **before the soak continues** |
| **10** | **No demo/live safeguard of any kind.** Nothing reads `ACCOUNT_TRADE_MODE`; `TITAN_ENV` is read by no code. The only separation is which terminal the EA was hand-attached to | **Catastrophic — full live exposure from an unvalidated demo run** | Low-moderate (one EA misconfiguration) | NOT FOUND | EA reports trade mode + login; Python refuses on mismatch |

**Just outside the ten:** RISK-09 (the bot adopts and force-closes your discretionary trades) · EXIT-01 (ratchet advances before the broker confirms and is never retried — a believed-but-absent breakeven stop) · RISK-06 + RISK-07 (no stop-level validation and the ask price is discarded: silent permanent non-trading on wide-stop symbols, plus a systematic long-side bias) · CTRL-04 + SEC-04 (`PATCH system.mt5_path` → `subprocess.Popen` **as root**).

---

## 3. Severity summary

| Severity | Count | Dominant themes |
|---|---|---|
| **P0** | 1 | Live credential public in git history and in HEAD, on a public repository |
| **Critical** | 8 | Unenforced risk limits · unmeasured edge · unvalidated trust boundary · data-integrity corruption · missing idempotency · unusable journal schema · privilege/config-write chain |
| **High** | 36 | Unverified fire-and-forget commands · fail-open controls · observability blind spots · network exposure · zero test coverage on the order path · no CI, no dependency pinning, no backups, no runbook · weak guards on destructive commands |
| **Medium** | 39 | Backtest realism gaps · unvalidated hyperparameters · resource and lifecycle hygiene · stale artifacts · schema durability |
| **Low** | 17 | Stale docs and entrypoints · misleading status headers · missing metrics · mechanisms built but never called |
| **Total** | **101** | |

### The pattern worth naming

The modal High finding is **not a missing feature.** It is a control that exists, is well-reasoned, is documented in a comment explaining exactly why it is correct — and is **never verified.**

`_dispatch_mgmt_command`'s docstring states the MODIFY outcome "is observable in the next HEARTBEAT's SL/TP." It *is* observable. Nothing observes it. That shape repeats across the ratchet, the partial closes, the TTL cancels, the flatten commands, the correlation matrix, and the `drops` counter.

**The systemic fix is not more controls. It is closing the loop on the ones you have.**

---

## 4. Four-stage roadmap

### Stage A — Stop the bleeding
**Before *any* run, demo included. ~1 week.**

| # | Item | ID | Effort |
|---|---|---|---|
| A1 | Rotate token; `deleteWebhook`; repo → private | P0-01 | 15 m |
| A2 | Untrack 10 runtime artifacts + 43 `.pyc`; `git filter-repo`; force-push | P0-01, SEC-03 | 2 h |
| A3 | Pre-commit: `gitleaks` + reject gitignore-matched files. Remove `git commit` from `.claude/settings.json` | SEC-07 | 1 h |
| A4 | Persist `day_start_equity` + date; `StartLimitBurst=3`, `StartLimitIntervalSec=300` | **RISK-01**, OPS-05 | 2 h |
| A5 | Pass pendings into `check_exposure` + `arbiter._apply_caps` | **RISK-02** | 1 h |
| A6 | Bounds-check `update_symbol_specs`; bind the specific interface; HMAC on every bridge message | **SEC-05** | 3 h |
| A7 | EA reports `ACCOUNT_TRADE_MODE` + login; Python refuses WARMUP→ACTIVE on mismatch | **OPS-01** | 2 h |
| A8 | Fix the timezone seam: `fromtimestamp(ts, tz=utc)` | **RISK-10** | 1 h |
| A9 | `scripts/flatten.py` (out-of-band, verifies against the heartbeat) + the flatten runbook | RISK-08, CTRL-02, OPS-04 | 4 h |
| A10 | Explicit mandatory-stop assertion in `_execute_signal`; log + alert when the daily breaker trips | RISK-06, RISK-14 | 1 h |
| A11 | Magic-filter `sync_positions` and all three EA command handlers | **RISK-09** | 1 h |
| A12 | Port `recovery.acquire_boot_lock` into `main.py`; make ZMQ bind failure fatal | ARCH-06, ARCH-04 | 1 h |
| A13 | `SIGTERM`/`SIGINT` handler: drain, persist, notify, close | ARCH-07 | 2 h |
| A14 | systemd hardening: `User=titan`, `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `ReadWritePaths` | **SEC-04** | 1 h |
| A15 | `SettingsStore.set` rejects keys absent from defaults; deny-list `system.*` | **CTRL-04** | 30 m |
| A16 | Require numeric `TELEGRAM_CHAT_ID` at boot; reject updates lacking `from.id`; check `resp.status_code`; widen the `except` | CTRL-03, EXEC-03, EXEC-04 | 1 h |
| A17 | Move `poll_commands` to its own task | **EXEC-01** | 1 h |
| A18 | Bridge → `127.0.0.1` default; `compare_digest`; add throttle | **SEC-02** | 1 h |
| A19 | Log every Telegram command; install the `logging.Filter` redacting `bot\d+:…` | OBS-09, OBS-06 | 1 h |

### Stage B — Foundations
**Before live capital. ~3 weeks.**

| # | Item | ID | Effort |
|---|---|---|---|
| B1 | **Journal schema + `trade_events` table.** Day one of Stage B — the soak's evidence depends on it | **OBS-01** | 1 d |
| B2 | **Extract the ratchet to one pure function; wire into `research_run.py`; delete `replay_managed`; re-run the study** | **STRAT-01** | 2 d |
| B3 | Idempotency key end to end (UUID in `comment`, EA dedup, query-don't-resend on timeout) | **ARCH-01** | 2 d |
| B4 | `OrderGateway` extraction behind the existing `Broker` protocol | ARCH-05 | 2 d |
| B5 | Heartbeat verification loop for MODIFY/partial/cancel; roll `r_level` back on mismatch | EXIT-01, EXIT-02, EXIT-03 | 2 d |
| B6 | Wire `tradebot/config/schema.py` into `_load_config`; make a corrupt override fatal | ARCH-08, ARCH-09 | 1 d |
| B7 | `ZMQBridge` unit tests against an in-process peer (timeout, concatenation, truncation, bind failure) | **OPS-03** | 1 d |
| B8 | Mock-broker integration harness; full lifecycle scenarios | OPS-03 | 3 d |
| B9 | Runtime invariants (`_assert_invariants` on every heartbeat) + spec sanity | OPS-07 | 1 d |
| B10 | Broker-history reconciliation (`GET_DEALS` + nightly diff) | **OBS-05** | 2 d |
| B11 | Correlation: fail closed, direction-aware, explicit asset-class groups | RISK-03, RISK-04, RISK-05 | 2 d |
| B12 | Separate `last_tick_time` / `last_heartbeat_time` / `last_bar_time`; stale-feed alert; time-delta-based `WATCHDOG=1` | **EXEC-07**, OBS-07, OBS-08 | 1 d |
| B13 | CI: gitleaks, gitignore-collision, unittest, signal-parity, `pip-audit`. Pin deps with a hashed lock | **OPS-02**, SEC-01 | 1 d |
| B14 | Capture the ask; spread gate; ask-side fills in the backtest | **RISK-07**, STRAT-03 | 1 d |
| B15 | Reconcile before ACTIVE; reconcile on heartbeat resumption after a gap | EXEC-08, EXEC-05 | 4 h |
| B16 | Nightly `trade_state.db` backup + `integrity_check` + one **executed** restore drill | OPS-04, OPS-08 | 4 h |
| B17 | Property tests (Hypothesis) on sizing/risk invariants — pointed at `src/`, not `tradebot/` | OPS-06 | 1 d |
| B18 | Runbooks: won't start, bridge down, unexpected position, drawdown hit | OPS-04 | 1 d |
| B19 | Rewrite `verify_integrity.py` as a real preflight (exits non-zero, no `input()`, checks schema + account mode + ports + lock hash) | SEC-06 | 4 h |
| B20 | Chaos tests: kill the EA mid-order, freeze the feed, corrupt the override, SIGKILL mid-runner | OPS-03 | 2 d |
| B21 | Delete the legacy `Backtester`; repoint `CLAUDE.md:21`; archive the `.bat` files; fix `RESUME.md` | STRAT-04, OPS-09, OPS-10 | 2 h |

### Stage C — Feature completion
**During and after the soak. ~3 weeks.**

| # | Item | ID | Effort |
|---|---|---|---|
| C1 | Position-lifecycle state machine (subsumes EXIT-04, completes OBS-01) | EXIT-04, OBS-03 | 3 d |
| C2 | Slippage attribution report — **a stated go-live condition with no tooling today** | — | 2 d |
| C3 | Portfolio-level backtest (count cap, aggregate cap, correlation gate, daily breaker) + Monte Carlo on trade sequence | **STRAT-05** | 3 d |
| C4 | Swap/financing model for XTIUSD, ETHUSD, BTCUSD, US30, US100, XAUUSD | STRAT-06 | 1 d |
| C5 | Stop-level in specs; validate before send; reason taxonomy + retry policy | **RISK-06**, ARCH-05 | 2 d |
| C6 | Consecutive-loss breaker, weekly/monthly caps, peak-equity drawdown, margin headroom | RISK-15 | 2 d |
| C7 | Enable `drawdown_throttle` and validate it in the soak | — | 1 h |
| C8 | Sensitivity sweep on the ratchet levels, partial fractions and trail multiplier | **STRAT-02** | 2 d |
| C9 | Decompose `system_controller.py` (router / reconciler / reporter) | — | 3 d |
| C10 | Remaining Mediums: `round(lots, step)`, M15 CandleMaker, out-of-order tick guard, runner backstop TP, `prune_database`, journal retention | RISK-11, ENTRY-03, EXEC-06, EXIT-05, EXEC-09 | 2 d |
| C11 | Deterministic replay extended past `_execute_signal` | — | 2 d |
| C12 | Walk-forward analysis; Sharpe/Sortino; drawdown duration; MAE/MFE | STRAT-07 | 2 d |

### Stage D — Optimisation and innovation
**Only after 3 months live.**

| # | Item |
|---|---|
| D1 | Shadow/paper instance alongside live; canary deployment discipline |
| D2 | Automated post-mortems on losing streaks |
| D3 | Anomaly detection on the bot's own telemetry (needs 30 days of journal) |
| D4 | Cost/slippage prediction — a lookup table first; a model only if the table underfits |
| D5 | Fill-probability model for resting limits (needs ~6 months of live limits) |
| D6 | Promote Gyroscope through its pre-registered gate — **only** after SilverBullet has a measured live edge |
| D7 | Revisit the `tradebot/` v15 cutover |
| D8 | Portfolio risk parity — only with 2+ genuinely uncorrelated strategies |

**Deliberately on no stage:** Kelly sizing · regime-detection gating · ML direction prediction · RL position management · trade clustering · smart order routing. Each is either inapplicable at this scale or actively harmful given the current evidence base.

---

## 5. Quick wins — under one hour each, highest value first

| # | Action | Time | ID |
|---|---|---|---|
| 1 | **Rotate the token + `deleteWebhook`** | 10 min | P0-01 |
| 2 | **`git rm --cached`** the 10 runtime artifacts and 43 `.pyc` files; flip the repo private | 20 min | P0-01, SEC-03 |
| 3 | **`exposure.py:92,100` + `arbiter.py:250`** — pass `current_pending_orders` | 20 min | RISK-02 |
| 4 | **`risk_manager.py:62`** — bounds-check specs (`1e-6 ≤ ts ≤ 100`, `1e-4 ≤ val ≤ 1e4`, no >10× jump) | 30 min | SEC-05 |
| 5 | **`system_controller.py:690`** — store `msg['a']` as `live_asks[symbol]` | 5 min | RISK-07 |
| 6 | **systemd** — paste `User=titan`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `PrivateTmp=yes`, `StartLimitBurst=3`, `StartLimitIntervalSec=300` | 15 min | SEC-04, OPS-05 |
| 7 | **`bridge/app/settings.py:16`** + its `.env.example` — `127.0.0.1` | 2 min | SEC-02 |
| 8 | **`settings.py:82`** — reject keys absent from defaults | 10 min | CTRL-04 |
| 9 | **`_execute_signal:400`** — `if sl <= 0 or abs(p - sl) <= 0: log + return` | 10 min | RISK-06 |
| 10 | **`telemetry.py:147`** — `log_event("CMD", "TELEGRAM", f"{cmd} {args}")` | 2 min | OBS-09 |
| 11 | **`telemetry.py:126`** — check `status_code == 429`; widen the `except` to include `ValueError` | 15 min | EXEC-03, EXEC-04 |
| 12 | **`Titan_Gateway.mq5`** — `if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;` in the three command handlers | 15 min + recompile | RISK-09 |
| 13 | **`config.yaml:68`** — `drawdown_throttle.enabled: true` | 1 min | — |
| 14 | **Delete every `STATUS: PRODUCTION READY` header** | 10 min | OPS-12 |
| 15 | **`verify_integrity.py`** — remove the `unicorn` entries and the trailing `input()`; add `sys.exit(1)` | 15 min | SEC-06 |
| 16 | **`state_manager.py:36`** — `PRAGMA synchronous=FULL` | 2 min | OBS-10 |
| 17 | **`bridge_zmq.py:26,37,54`** — `raise` instead of `print` on bind failure | 10 min | ARCH-04 |
| 18 | **`state_manager.py:203`** — carry `time_placed` into `archive_trade` (plus the column) | 20 min | OBS-01 |

**Total: roughly 4 hours for all eighteen.** They close one P0, two Criticals, and eight Highs.

---

## 6. Go-live checklist

Require all of these of yourself. Every item is verifiable — no judgement calls.

### Security
- [ ] Telegram token rotated; `getMe` with the old token returns 401
- [ ] `getWebhookInfo` on the new token returns an empty `url`
- [ ] Repository is Private
- [ ] `git ls-files -i -c --exclude-standard` returns **zero** rows
- [ ] `git log --all -p -- .env` returns **nothing**
- [ ] `trufflehog --only-verified` clean across all branches
- [ ] Secrets in an OS keyring or a `chmod 600` `.env`; log redaction verified against a synthetic token
- [ ] ZMQ bound to a specific interface and HMAC-authenticated; `nmap` from another host shows 32768–32770, 8766, 8770, 8787 all closed
- [ ] Service runs as `titan`, not root — `systemctl show titan-live | grep -E 'User|NoNewPrivileges|ProtectSystem'` confirms
- [ ] Pre-commit secret scanning installed; CI blocks on gitleaks and gitignore collisions

### Risk enforcement — each proven by a test, not by reading the code
- [ ] Daily drawdown anchor survives a restart *(test: trip to −2.9%, `systemctl restart`, assert the anchor is unchanged)*
- [ ] `StartLimitBurst` proven *(test: force 4 crashes in 5 min, assert systemd stops restarting)*
- [ ] Count and per-symbol caps hold with resting limits *(test: N limits on one symbol, assert the (N+1)th is blocked)*
- [ ] Aggregate risk cap holds; `aggregate_open_risk` returns `None` and blocks book-wide on a stopless position
- [ ] Correlation gate **fails closed** when the matrix is unavailable
- [ ] No position can exist without a stop — asserted at runtime on every heartbeat, and violation alerts
- [ ] Poisoned specs rejected *(test: inject `ts=1000`, assert rejection and alert)*
- [ ] `drawdown_throttle` enabled and observed firing at least once in the soak

### Correctness
- [ ] `research_run.py` and `TradeManager` call the **same** ratchet function; `replay_managed` deleted
- [ ] The study re-run against the live ratchet, and **the re-run expectancy is positive at 1.5× spread**
- [ ] Timezone seam fixed; `_snapshot_warmup` CSVs show no discontinuity at the warmup→live boundary
- [ ] Every order carries a unique client ID; a forced REQ timeout produces **no** duplicate fill *(chaos test)*
- [ ] `ZMQBridge` unit tests exist and pass; mock-broker lifecycle test passes
- [ ] Signal-parity golden test passes; suite green in CI on every push
- [ ] Dependencies pinned with a hashed lock; the lock hash recorded in every research run-card

### Environment separation
- [ ] EA reports `ACCOUNT_TRADE_MODE` + login; Python **refuses to trade** on mismatch *(test: point demo at live, assert refusal)*
- [ ] Live and demo checkouts have separate ports, DBs, venvs, health ports and `.env` files
- [ ] A deliberate attempt to point a dev run at the live account **fails loudly**

### Observability
- [ ] Journal records exit reason, ratchet level at exit, final SL, requested vs filled price, submit/fill timestamps, filled volume, commission, swap, equity snapshot, config hash, git SHA
- [ ] `trade_events` table records every MODIFY/partial with the heartbeat-observed outcome
- [ ] Journal reconciles against MT5 deal history with **zero unexplained discrepancies** over the full soak
- [ ] Frozen-feed detection proven *(test: stop ticks, keep heartbeats, assert alert within 60 s)*
- [ ] Every Telegram and GUI intervention appears in a durable audit trail
- [ ] At least one alert channel that is **not** Telegram
- [ ] Journal write failures surface to Telegram and `/readyz`

### Operations
- [ ] `scripts/flatten.py` exists, is out-of-band, verifies against the heartbeat, and **has been executed successfully against the demo account**
- [ ] `/panic` reports the *observed* post-flatten position count, not the send count
- [ ] Flatten runbook written, including a tier-3 (manual, bot-independent) path
- [ ] Runbooks for: won't start, bridge down, unexpected position, drawdown hit
- [ ] `SIGTERM` handler drains, persists, notifies; `systemctl stop` produces a shutdown Telegram
- [ ] Nightly DB backup running; **one restore actually performed and verified**
- [ ] `verify_integrity.py` passes and exits 0 on a healthy system

### Soak pass criteria — 4 weeks minimum on FBS demo, at live position sizing
- [ ] ≥ 40 closed trades
- [ ] **Zero** unexplained journal-vs-broker discrepancies
- [ ] **Zero** positions observed without a stop
- [ ] **Zero** duplicate fills
- [ ] **Zero** invariant violations
- [ ] Realised median spread per symbol within **1.5×** the study's indicative table — or the study re-run at measured values and still positive
- [ ] Realised slippage measured and within the cost model's tolerance
- [ ] Observed grade distribution consistent with the study's
- [ ] **Realised R-multiples consistent with the ratchet replay on the same trades** — this is the STRAT-01 closure test and the whole point of the soak
- [ ] No crash-restart events, or every one root-caused and fixed
- [ ] Realised expectancy positive, or the shortfall fully attributed

### First live period — first 4 weeks
- [ ] Start at **0.25%** risk per trade, not 1.0%
- [ ] **3 symbols, not 12** — one per correlation cluster
- [ ] Daily manual reconciliation against the broker statement
- [ ] A pre-agreed hard stop: **−5% cumulative → flatten, halt, review.** Written down before you start
- [ ] Scale toward 1% only after 100 live trades consistent with the study

---

## 7. Closing note from the panel

The four perspectives disagreed about a great deal — whether to rewrite or refactor the controller, whether `tradebot/` is an asset or a distraction, whether `/panic` should have friction, whether the +0.194R edge is real. They agreed on three things.

**First:** the research work here is better than the engineering work, and that is an unusual and **recoverable** position to be in. Most failing trading systems have the opposite problem — solid plumbing wrapped around an edge that was never there. Yours has a plausible edge and plumbing that has not been closed. **The second problem is the one that responds to a checklist.**

**Second:** almost nothing in Stage A is hard. It is one week of unglamorous work — persist a float, pass an extra argument, bound a range, check a return value, rotate a token. **The reason it has not been done is not difficulty; it is that building a Kalman filter and a React cockpit is more interesting than writing a test for a 129-line socket wrapper.** Resist that for one week.

**Third:** do not skip the soak, and do not start it until OBS-01 and the ratchet extraction are done. **The number that decides whether this system is worth running — the live expectancy of the managed exit engine — does not currently exist anywhere: not in any document, not in any test, not in any journal.** Everything else in this audit is in service of being able to measure it honestly.
