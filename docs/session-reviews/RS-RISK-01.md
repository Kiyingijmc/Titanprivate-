# RS-RISK-01 — Independent adversarial review

**Change under review:** `3679680..c16e537` on `main` (merge `39a0e33`, branch
`feat/risk-01-daily-anchor`) — persist the daily drawdown anchor across restarts.
**Audit finding:** RISK-01 (`docs/audit-2026-07-30/`, severity A).
**Reviewer:** independent; did not build this.
**Date:** 2026-08-01.

**Verdict: CHANGES.** The implementation is careful, well-documented and its unit
tests genuinely bite. But the spec's load-bearing safety claim —

> "This is strictly monotone: it can only ever *keep* an anchor that today's code
> throws away. **There is no input for which it is more permissive than current
> behaviour.**"
> — `docs/superpowers/specs/2026-07-31-risk-01-persist-daily-drawdown-anchor-design.md:122-123`

— is **false**, and I have a worked, reproducible scenario in which the merged code
grants **1.94×** the intended daily loss allowance where the pre-change code granted
the correct one. The trigger is not exotic: it is a bot restart during an MT5/EA
outage, a condition this repo's own operational history records (the ~9 h outage of
2026-07-29).

---

## Method

- Read via `git show`/`git diff` against `main`; the repo root checkout
  (`feat/swap-survey`, which does **not** contain `c16e537`) was never touched and the
  live bot was never run.
- All execution in a throwaway detached worktree at `c16e537` under `/tmp`, using the
  root interpreter `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python`.
- Box was quiet throughout (`load average: 0.27 … 2.44`, single `unittest discover`).
- Targeted suite: `test_trading_day_key` + `test_risk_manager_daily_anchor` +
  `test_state_manager` → **Ran 34 tests, OK** (13.2 s).
- Full-suite wiring mutation: see MINOR-8.
- Three adversarial harnesses driving the **real** `RiskManager` and **real**
  `StateManager` against a verbatim transcription of the `__init__` restore block.

---

## What I verified as CORRECT

These were attacked and held. Recording them so the next reviewer does not re-spend
the effort.

| Claim | Result |
|---|---|
| `restore_daily_anchor` is a pure setter, no I/O, no new ctor args | ✅ holds; ~10 test modules still build `RiskManager` from a bare dict |
| The `if self.day_start_equity == 0` guard reasoning, "including for a restored anchor that is later reset" | ✅ **sound.** `day_start_equity` is assigned in exactly three places (`__init__`→0, `update_account_info`, `reset_daily_metrics`) and **nothing can ever return it to 0** after boot. Once restored it is never re-anchored by a heartbeat. *(This is also precisely the mechanism that makes MAJOR-1 possible — see below.)* |
| `_trading_day_key` rolls at exactly 23:45:00 EAT | ✅ 23:44:59→today, 23:45:00→tomorrow; agrees instant-for-instant with the `hour==23 and minute==45` trigger |
| Month / year boundary | ✅ `2026-12-31 23:50` → `2027-01-01` |
| Host `TZ` changes | ✅ immune — `datetime.now(self.uganda_tz)` is computed from UTC, not local wall clock |
| DST | ✅ non-issue **today**. Verified `pytz.timezone('Africa/Kampala')` has **no** transitions after 2000, so the naive `aware + timedelta` (no `pytz.normalize()`) cannot skew. *Latent only*: if `uganda_tz` were ever pointed at a DST zone, the un-normalised add would drift from the `hour==23 and minute==45` trigger twice a year. `uganda_tz` is hardcoded at `system_controller.py:101`, so this is informational. |
| `now_uganda.hour == 0` report-flag reset | ✅ no interaction with the key |
| Genuinely stale row (bot down for days) is rejected | ✅ key mismatch → "anchoring fresh", identical to old code |
| Corrupt / non-numeric / NaN / Inf / negative persisted value cannot wipe a live anchor | ✅ well covered, and `test_a_bad_value_never_wipes_an_anchor_that_already_exists` is a genuinely good test — it distinguishes "rejected" from "assigned 0.0", which the weaker sibling test cannot |
| Concurrency / WAL | ✅ no new risk. Single-row table, `INSERT OR REPLACE`, two real writes per day, same serialized event-loop connection as every other write. `CREATE TABLE IF NOT EXISTS` correctly back-fills a pre-existing DB (tested). |
| Test quality generally | ✅ the new tests bite. `test_never_raises_into_the_main_loop` in particular is defending a real hazard (the loop's only handler Telegrams FATAL and re-raises). |

---

## Findings by severity

| # | Severity | Finding |
|---|---|---|
| MAJOR-1 | **MAJOR** | Monotonicity claim falsified — a stale anchor is written under the **new** trading-day key and restored on every restart that day. 1.94× the intended daily loss allowance in a worked scenario. |
| MEDIUM-2 | MEDIUM | A positive-but-implausible persisted anchor disables the DD breaker and throttle entirely (fail-open). Only a `> 0` check gates a disk value that now controls a safety limit. |
| MEDIUM-3 | MEDIUM | A failed write still poisons the self-suppression cache → persistence permanently and silently off for that day. |
| MEDIUM-4 | MEDIUM | `get_risk_anchor()` returning `None` from an exception is unlogged and indistinguishable from "never saved" → the whole fix can be silently disabled. |
| MEDIUM-5 | MEDIUM | `StartLimitBurst=3` with no `OnFailure=` can leave the **live** engine dead holding open positions, unalerted. |
| MINOR-6 | MINOR | `_persist_daily_anchor` should be called *after* the 23:45 block, not before. |
| MINOR-7 | MINOR | Boot log can claim `"Restored daily DD anchor 0.00 … (survived restart)"` when the restore was rejected. |
| MEDIUM-8 | MEDIUM | Boot-restore block is structurally untestable; the spec's own mandatory boot-comparison mutation is unsatisfiable. Mutation-proven: both wiring points can be deleted with the full suite still green. |
| INFO-9 | INFO | `updated_at` written, never read — the natural place for a staleness guard. |
| INFO-10 | INFO | `synchronous=NORMAL` under WAL: survives process death (the target case), not host power loss. |

---

## Findings, in detail

### MAJOR-1 — The monotonicity claim is false: a stale anchor is written under the **new** day's key and then restored forever

**Root cause.** The persisted key is stamped at *write* time from `now`, not from the
anchor's own provenance. `_persist_daily_anchor` writes
`(_trading_day_key(now), self.risk_manager.day_start_equity)` and simply *assumes* that
whatever is in `day_start_equity` belongs to `now`'s trading day. That is only true
after `reset_daily_metrics()` has actually run for that boundary. A stale anchor
re-labelled with a fresh key is then indistinguishable from a genuine one at boot, and
the "otherwise (absent, or **stale**) do nothing" branch the spec relies on never fires.

**Why `reset_daily_metrics` can fail to run for a boundary.** The reset is
level-triggered on a *one-minute wall-clock window* (`now_uganda.hour == 23 and
now_uganda.minute == 45`) evaluated inside the main loop. The loop is not running
during boot, and the gap between `__init__` (where `today_key` is computed and the
anchor restored) and the loop's first iteration is **unbounded**:

```
src/core/system_controller.py:343   await self._wait_for_bridge_connection()
    async def _wait_for_bridge_connection(self):
        while True:
            connected = await self.bridge.ping()
            if connected: return
            await asyncio.sleep(2.0)          # <-- no timeout, no ceiling
```

So a restart while MT5/the EA is down parks the process here for minutes or hours,
holding an anchor restored under day D's key, and resumes on day D+1 or later.
`reset_daily_metrics` is never called; `update_account_info`'s `== 0` guard (correct,
per the table above) refuses to re-anchor; and the loop then *persists* the day-D
anchor under key D+1.

**Reproduction** (`attack2.py`, real `RiskManager` + real `StateManager`):

```
Day D: anchor 10000, account grows to 10300. P1 stopped 23:30. P2 constructed
23:35 (key still day D) -> RESTORES 10000. EA not attached; handshake spins;
P2's loop first runs 00:20 on D+1, so the 23:45 window is never observed.

[D 23:35 __init__] RESTORED 10000.0 (key 2026-07-31)
[D+1 00:20 loop] persisted -> {'trading_day_key': '2026-08-01', 'day_start_equity': 10000.0, ...}

  NEW anchor  10000.00 -> halts below   9700.00
  OLD anchor  10300.00 -> halts below   9991.00
  allowed loss on D+1: NEW 600.00 vs OLD 309.00  ->  MORE PERMISSIVE (1.94x)

  ...and the wrong anchor is now on DISK under key 2026-08-01, so every
  further restart during D+1 restores it too:
  [D+1 09:00 restart] RESTORED 10000.0 (key 2026-08-01)
```

The multiplier scales with the size of the preceding winning day and is unbounded in
principle; after a multi-day outage the anchor can be arbitrarily far from the true
day-start equity.

**Second, narrower path to the same state** (`attack.py`): `_persist_daily_anchor` is
called *before* the 23:45 block, so on the first 23:45:00 iteration the key has already
rolled to D+1 while `day_start_equity` is still day D's. The row `(D+1, A_D)` is
genuinely written to disk. In a healthy process it is overwritten microseconds later
(`telemetry.send_message` is fire-and-forget via `asyncio.create_task`, so the report
does not widen the window), which is why I rate this variant low on its own — but it
is a real wrong-day write, and it also lands whenever `reset_daily_metrics` no-ops
because `current_equity == 0` (a process that has not yet seen a heartbeat).

**Severity rationale.** This is the exact failure class RISK-01 exists to kill — a
restart laundering a stale anchor into a larger drawdown allowance — reintroduced in a
narrower window, and made *worse* than before in one respect: previously a missed
23:45 reset self-healed on the next restart (the anchor was re-taken from live equity);
now it is written to disk and survives every subsequent restart that day.

**Suggested fix (primary).** Make the day roll-over **edge-triggered on the key the
change already introduced**, instead of on a missable one-minute window. This uses only
code this commit added and makes the key and the reset provably the same boundary,
which is what the spec claimed but did not achieve:

```python
key = self._trading_day_key(now_uganda)
if key != self._current_day_key:          # seeded in __init__
    self.risk_manager.reset_daily_metrics()
    self._current_day_key = key
self._persist_daily_anchor(now_uganda)     # note: AFTER, see MINOR-6
```

Leave the 23:45 Telegram report on its existing minute-window trigger — only the
*anchor* reset needs to move.

**Suggested fix (belt).** Give the anchor its own provenance: record the trading-day
key at the moment `day_start_equity` is established, and have `_persist_daily_anchor`
write *that* key, refusing to write when it disagrees with `now`'s key. Then a stale
anchor is detectable at boot and the "do nothing" branch works as designed.

---

### MEDIUM-2 — A positive-but-implausible persisted anchor disables the breaker entirely (fail-open)

*Hardening / defence-in-depth, not a demonstrated live bug: `_persist_daily_anchor`
only ever writes values sourced from a broker heartbeat, so reaching this state needs
DB corruption, a hand-edit, or a genuinely tiny reported equity. Rated MEDIUM for the
severity of the consequence, not its likelihood.*


`restore_daily_anchor` validates only `math.isfinite(value) and value > 0`. A tiny
positive anchor makes `pnl_pct` enormously positive, so `check_can_trade()` returns
`True` forever and `throttle_factor()` returns `1.0` — the 3% daily circuit breaker and
the drawdown throttle are both **switched off for the whole trading day**, and the
value now survives restarts:

```
anchor=0.01        day_start_equity=0.01       can_trade=True  throttle=1.0
anchor=1e-09       day_start_equity=1e-09      can_trade=True  throttle=1.0
anchor=1e12        day_start_equity=1e12       can_trade=False throttle=0.5   (fails CLOSED - fine)
reference: correct anchor 10000 with equity 5000 -> can_trade=False
```

(all with `current_equity` **halved** on the day — the breaker should be hard-blocking.)

Before this change `day_start_equity` could only ever originate from a live heartbeat.
This commit makes a **file on disk** a control input to a safety limit, gated by a
single `> 0` check. That is out of step with the discipline `risk_manager.py` applies
to the other externally-sourced numbers it divides by, in the same file, with an
explicit rationale:

```python
SPEC_BOUNDS = {'val': (1e-4, 1e4), 'ts': (1e-6, 100.0)}
MAX_SPEC_JUMP = 10.0
# ... "Never coerce a bad value into the store -- half-good specs size real trades."
```

**Suggested fix.** Bound the restored anchor for plausibility rather than mere
positivity — e.g. defer the restore decision to the first heartbeat and reject an
anchor that is not within a sane ratio of the reported equity/balance, and log +
Telegram the rejection. Fail closed, never open.

---

### MEDIUM-3 — A failed write silently and permanently disables persistence

`save_risk_anchor` swallows every exception into a `print`, so the caller cannot tell
success from failure — yet the caller updates the self-suppression cache
unconditionally:

```python
self.state_manager.save_risk_anchor(key, equity)
self._last_persisted_anchor = (key, equity)      # set even if the write failed
```

Measured: one simulated `database is locked` and the anchor is **never retried** for
that `(key, equity)` pair — 1 write attempt across 100 000 main-loop iterations. A
single transient DB error at the wrong moment leaves RISK-01 off for the rest of the
day, with one line on stdout and nothing in the audit log or Telegram.

**Suggested fix.** Have `save_risk_anchor` return a bool; set `_last_persisted_anchor`
only on success; route the failure through `self.logger.log_event` (and Telegram, as
the exposure cap already does for its own un-computable case).

---

### MEDIUM-4 — `get_risk_anchor() -> None` from an exception is silent and indistinguishable from "never saved"

`get_risk_anchor` returns `None` on **any** exception with no logging. The boot block
then logs nothing at all, because the "anchoring fresh" message sits under
`elif saved:`:

```python
saved = self.state_manager.get_risk_anchor()      # None on read failure
if saved and saved.get('trading_day_key') == today_key:   ... log "Restored"
elif saved:                                                ... log "anchoring fresh"
# saved is None -> NO LOG AT ALL
```

A permanently unreadable `risk_state` (corruption, a schema conflict, a locked DB)
leaves the fix off forever with **zero operator signal**, and the audit log looks
identical to a clean first-ever boot. For a safety control this is the failure mode
that matters most.

**Suggested fix.** Distinguish the two: log at INFO when there is genuinely no row, and
at ERROR (plus Telegram) when the read *failed*. The boot-restore `except Exception` is
also broader than needed — it wraps the key computation and the logging as well as the
DB read.

---

### MEDIUM-5 — `StartLimitBurst=3` can leave the LIVE engine dead with open positions and no alert

Both units gain `StartLimitBurst=3` / `StartLimitIntervalSec=300` in `[Unit]` (correct
section for modern systemd). With `RestartSec=10` a crash-loop exhausts the budget in
~30 s and the unit enters `failed`. There is **no `OnFailure=`**, no
`StartLimitAction=`, and no notifier unit anywhere in `deploy/`. The in-file comment
says systemd "leaves it failed for an operator to look at" — but nothing tells the
operator. For the **live** unit that means the engine can be down indefinitely holding
open positions with no BE/partial/trail management and no daily-DD breaker. Note
`WatchdogSec=90` also consumes this budget, so three watchdog trips during an MT5 flap
produce the same outcome.

Separately, the comment's stated rationale — *"each boot re-anchors the daily drawdown
breaker, laundering one bad day into an unlimited number of fresh 3% allowances"* — is
obsoleted by the very commit that adds it. Not a defect, but the deployed comment now
misdescribes why the cap is there, and the cap's real cost (unattended downtime) is
weighed nowhere.

**Suggested fix.** Add an `OnFailure=` notifier (or at minimum document the required
external monitoring), and re-word the rationale.

---

### MINOR-6 — Move `_persist_daily_anchor` to *after* the 23:45 block

The comment justifies the current position as *"so the post-reset anchor is picked up
on the very next iteration (~1 ms later)"*. Placing the call **after** the block picks
it up on the **same** iteration and eliminates the wrong-day write described in
MAJOR-1's second path. There is no advantage to the current ordering.

### MINOR-7 — The boot log can claim a restore that did not happen

If `restore_daily_anchor` rejects the persisted value (e.g. the column is `NULL`, so
`float(None)` raises and the call is a no-op), the very next line still logs
`"Restored daily DD anchor 0.00 for trading day … (survived restart)"` and seeds
`_last_persisted_anchor = (key, 0.0)`. Functionally harmless, but it puts a false
positive in the audit log for exactly the corruption case an operator would be reading
the log to diagnose. Check the return value, or re-read `day_start_equity` and log the
rejection instead.

### MEDIUM-8 — The boot-restore block is structurally untestable, so one of the spec's own MANDATORY mutations cannot be satisfied

**Confirmed:** no test constructs `SystemController` through `__init__`. Every fixture
uses `SystemController.__new__` / `object.__new__` and hand-sets attributes
(`test_tape_fidelity`, `test_mgmt_dispatch_notify`, `test_bridge_zmq_bind_host`,
`test_controller_routing`, `test_controller_arbiter`, `test_strategy_timeframe`,
`test_controller_news_gate`, …). The two AST-based structural tests in the suite assert
only on `_check_news_status`'s try/except placement.

**Mutation evidence.** I removed *both* wiring points at once — the
`self._persist_daily_anchor(now_uganda)` call in `run()` **and** the entire `__init__`
boot-restore block — and ran the full suite:

> `MUTANT_RESULT`

So the loop call site and the restore block can both be deleted without any test
noticing. Consequently the spec's own mandatory gate —

> "**Mutation check (mandatory before claiming done)** … invert the `trading_day_key`
> comparison at boot"

— is **unsatisfiable as written**: nothing executes that comparison. The plan and spec
are commendably honest about this ("What remains genuinely uncovered is the boot-restore
block in `__init__`"), and the stated reason (constructing a controller would open the
live bot's DB and bind its ports) is real — but it is also **self-imposed and already
solved elsewhere in this same commit**: `_persist_daily_anchor` was extracted into a
method driven by a stub `self`, precisely so it could be tested without a controller.
The same 15 lines can be extracted as `_restore_daily_anchor_at_boot(now_uganda)` and
tested identically. Given that MAJOR-1 lives inside that block, "known coverage
boundary" is not an acceptable resting place.

### INFO-9 — `updated_at` is written but never read

The column exists and is asserted in a test, but no code consumes it. It is the natural
place for a wall-clock staleness guard (a second, independent check that would have
caught MAJOR-1's row: an anchor whose `updated_at` predates the last 23:45 boundary is
by definition not today's anchor). Currently dead weight.

### INFO-10 — `PRAGMA synchronous=NORMAL` under WAL

Commits survive process death (SIGKILL, the FATAL re-raise, systemd restart) — which is
the case RISK-01 targets — but not a host power loss or kernel panic, where the last
commit can be lost. Pre-existing and shared with the hot trade path, so not a demand;
noted because the anchor's entire purpose is surviving ungraceful termination.

---

## Definition-of-Done assessment

| DoD item | Status |
|---|---|
| Single-row `risk_state` table with `CHECK (id = 1)` | ✅ delivered and tested (including back-fill into a pre-existing DB) |
| `restore_daily_anchor` is a pure setter, no I/O, no ctor change | ✅ |
| The `== 0` guard reasoning is sound, incl. a restored-then-reset anchor | ✅ verified |
| `_trading_day_key` rolls at 23:45 EAT, matching `reset_daily_metrics` | ✅ for the key; ❌ the *reset* itself is still on a missable minute window, so the two only agree when the loop happens to observe that minute (MAJOR-1) |
| Boot restore is STRICTLY MONOTONE | ❌ **falsified** — two concrete inputs, 1.94× the intended allowance |
| `_persist_daily_anchor` called once from the main loop, `(key, equity)`-cached | ✅ mechanically, but see MINOR-6 (ordering) and MEDIUM-3 (cache poisoned by failed writes) |
| Mandatory mutation sweep | ⚠️ two of three satisfiable and confirmed; the boot-comparison mutation is unsatisfiable (MINOR-8) |
| Suite green | ✅ targeted modules 34/34 OK |

---

## Required before this can be called done

1. **MAJOR-1** — make the anchor reset edge-triggered on `_trading_day_key`, or give the
   anchor its own provenance key. This is the finding that blocks.
2. **MEDIUM-2** — bound the restored anchor for plausibility; fail closed.
3. **MEDIUM-3 / MEDIUM-4** — make write failures and read failures visible and
   retryable; never leave a safety control silently off.
4. **MEDIUM-8** — extract the boot-restore block into a testable method (the same
   treatment `_persist_daily_anchor` already received) and add a test that reproduces
   MAJOR-1: anchor persisted on day D, loop's first iteration on day D+1, assert the
   anchor is **not** carried forward.
5. **MEDIUM-5 / MINOR-6 / MINOR-7** — cheap, do them in the same pass.

---

## Artifacts

- Throwaway worktree (removed after review):
  `/tmp/claude-1000/-home-kiyingijmc-projects-Titan-ICT-Bot-v14-3pro/57c48a24-4ac2-4480-927a-243b7732f6e9/scratchpad/risk01-wt`
- Harnesses: `…/scratchpad/attack.py` (23:45 ordering write),
  `…/scratchpad/attack2.py` (boot-overshoot monotonicity break + failed-write cache).

MIG-VERDICT CHANGES
