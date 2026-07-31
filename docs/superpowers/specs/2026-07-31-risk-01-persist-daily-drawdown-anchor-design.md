# RISK-01 — Persist the daily drawdown anchor across restarts

- **Date:** 2026-07-31
- **Audit finding:** RISK-01 (`docs/audit-2026-07-30/08-BACKLOG-INDEX.md`, severity A, est. 2h)
- **Backlog slug:** `risk-01-daily-drawdown-anchor-resets`
- **Branch:** `feat/risk-01-daily-anchor` (off `main` @ `3679680`)

## 1 · Problem

`RiskManager.day_start_equity` (`src/risk/risk_manager.py:36`) exists only in process
memory. It is set exactly once per process, by the first post-boot heartbeat:

```python
# src/risk/risk_manager.py:51-52
if self.day_start_equity == 0 and equity > 0:
    self.day_start_equity = equity
```

That value is the anchor for the 3 % daily circuit breaker (`check_can_trade`, `:185`)
and for the drawdown throttle (`throttle_factor`, `:290`). Because it is never
persisted, **every process restart re-anchors the breaker to current equity**, silently
issuing a fresh 3 % allowance and discarding the day's realised drawdown.

This is not theoretical. The bot was restarted twice on 2026-07-31 (a host reboot
~13:30, and the S018 deploy at 17:54), so the live demo-forward test has been measuring
drawdown from a mid-day anchor rather than from true session start.

### Confirmed by the audit's own verification pass

`docs/audit-2026-07-30/07-VERIFICATION-AGAINST-LIVE-TREE.md:27` —
`day_start_equity` is in-memory only; `risk_manager.py:36,51-52`; no persistence
anywhere in `src/` → **CONFIRMED**.

### What is *not* in play

The audit frames RISK-01's blast radius partly through systemd auto-restart
(`Restart=on-failure` laundering each crash into a new allowance). The bot currently
runs **outside systemd** (`nohup setsid … main.py`), so that amplifier is dormant —
but the manual-restart re-anchor is live and has already fired twice. The systemd half
is still worth closing statically, because it costs nothing and arms itself the moment
anyone runs the shipped unit files.

## 2 · Design

Three pieces. The guiding constraint is that **`RiskManager` stays a pure, I/O-free
class** — around ten unit-test modules construct it as `RiskManager(config_dict)` with
no database, and that property is worth preserving.

### 2.1 `StateManager` — persistence (`src/core/state_manager.py`)

`StateManager` is already this application's "survives reboots and reconciles" layer
(its own class docstring). It owns `trade_state.db`. Add a single-row table alongside
`active_orders` / `trade_history`:

```sql
CREATE TABLE IF NOT EXISTS risk_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    trading_day_key  TEXT,
    day_start_equity REAL DEFAULT 0.0,
    updated_at       REAL
)
```

The `CHECK (id = 1)` makes "exactly one row" a schema invariant rather than a
convention, so a bug elsewhere cannot accumulate rows and make "which anchor is
current?" ambiguous.

Two methods, following the existing try/except + `self.conn.commit()` convention used
by every other method in the file:

- `save_risk_anchor(trading_day_key: str, day_start_equity: float) -> None`
  `INSERT OR REPLACE` into id 1, stamping `updated_at = time.time()`.
- `get_risk_anchor() -> dict | None`
  Returns `{'trading_day_key', 'day_start_equity', 'updated_at'}` or `None` when the
  table is empty (first-ever boot). Returns `None` on any exception, matching the
  defensive style of `get_ratchet_state` / `get_pending_orders`.

Table creation goes in `_init_db()` next to the others, so existing databases pick it
up on the next boot exactly like the `ALTER TABLE` migration guards already there.

### 2.2 `RiskManager` — one pure setter (`src/risk/risk_manager.py`)

```python
def restore_daily_anchor(self, equity: float) -> None:
    """Prime today's DD anchor from persisted state, before the first heartbeat."""
```

Sets `self.day_start_equity` when `equity > 0`. No I/O, no timezone logic, no new
constructor argument. Every existing `RiskManager` test keeps working untouched.

**Why nothing else in `RiskManager` needs to change:** once the anchor is restored it is
non-zero, so the `if self.day_start_equity == 0` guard at `:51` — the very line that
causes this bug — naturally declines to re-anchor when the first heartbeat lands. The
fix is to *prime that guard before the heartbeat arrives*, not to add a second guard.

### 2.3 `SystemController` — the trading-day boundary and the wiring

The controller already owns the definition of a trading day: it re-anchors at 23:45
Africa/Kampala, tied to the daily report (`src/core/system_controller.py:346-355`).
Restore logic must use that **same** boundary, or a restart just after midnight would
disagree with the reset that had already run.

```python
@staticmethod
def _trading_day_key(now_uganda) -> str:
    """Trading-day label whose boundary is 23:45 EAT, matching reset_daily_metrics."""
    return (now_uganda + timedelta(minutes=15)).strftime('%Y-%m-%d')
```

Shifting the clock forward 15 minutes makes plain `.strftime('%Y-%m-%d')` roll over at
23:45 instead of at midnight. One line, pure, and testable without constructing a
controller.

**Boot restore** — immediately after `self.state_manager` is constructed (`:172`):

- read `get_risk_anchor()`;
- if it exists and its `trading_day_key` equals today's key, call
  `risk_manager.restore_daily_anchor(row['day_start_equity'])` and log it;
- otherwise (absent, or stale because a 23:45 boundary passed while down) do nothing
  and let the existing first-heartbeat path anchor fresh.

This is strictly monotone: it can only ever *keep* an anchor that today's code throws
away. There is no input for which it is more permissive than current behaviour.

**Persist on change, not per heartbeat.** A `self._last_persisted_anchor` cache guards
two call sites so the write happens roughly twice a day rather than every ~5 s:

- after `update_account_info(bal, eq)` in the HEARTBEAT branch (`:713`) — captures the
  boot anchor once it exists;
- after `reset_daily_metrics()` in the 23:45 block (`:355`) — captures the new day's
  anchor immediately, so a restart seconds later restores the *reset* value.

## 3 · Systemd hardening (static, no runtime effect today)

Add to the `[Unit]` section of both `deploy/systemd/titan-live.service` and
`deploy/systemd/titan-demo.service`:

```ini
StartLimitBurst=3
StartLimitIntervalSec=300
```

With `Restart=on-failure` + `RestartSec=10` already present, this caps a crash-loop at
three restarts per five minutes instead of an unbounded loop, each iteration of which
would otherwise mint a fresh drawdown allowance. Zero effect on the running bot, which
is not managed by systemd.

## 4 · Testing

TDD: each test is written first and observed RED against unmodified code.

**`tests/unit/test_state_manager.py`** (extend; reuses the file's existing
`tempfile.TemporaryDirectory()` fixture — never touches the live database):

- `get_risk_anchor()` returns `None` on a fresh database.
- Save then read back returns the same key and equity.
- A second save for a different day **replaces** rather than appends (assert exactly one
  row via `SELECT COUNT(*)`).

**`tests/unit/test_risk_manager_daily_anchor.py`** (extend the existing module):

- **The regression test for the bug itself.** Simulate a restart mid-drawdown:
  `restore_daily_anchor(1000.0)`, then `update_account_info(1000.0, 969.0)` — a first
  heartbeat reporting equity already 3.1 % down on the day. Assert the anchor is still
  1000.0 and `check_can_trade()` is `False`.
  Without the fix, `update_account_info` sees `day_start_equity == 0`, re-anchors to
  969.0, computes a 0 % drawdown and returns `True` — the exact laundering RISK-01
  describes.
- `restore_daily_anchor(0.0)` and a negative value are both no-ops (anchor stays 0, so
  the existing fresh-anchor path still runs and a corrupt persisted row cannot poison
  the breaker).
- `restore_daily_anchor(0.0)` / negative is a no-op (anchor stays 0, existing fresh-anchor
  path still works).

**`tests/unit/test_trading_day_key.py`** (new, pure static method):

- 23:44:59 EAT → today's date.
- 23:45:00 EAT → tomorrow's date (boundary rolls exactly with `reset_daily_metrics`).
- 00:30 EAT → still the previous calendar date's key, i.e. the same trading day the
  23:45 reset opened.

**Not instantiation-tested:** the ~6 lines of controller glue. Nothing in this repo
constructs a full `SystemController` in a unit test, and starting that pattern here
would open the **live bot's real `data/db/trade_state.db`** from the test suite. The
glue is reviewed by inspection; the boundary function and both storage/anchor
primitives it calls are covered directly.

**Mutation check (mandatory before claiming done):** this repo has shipped confirmed
bugs past a green suite. After the suite is green, each of these must be mutated and
observed RED — a green suite alone is not evidence:

- invert the `trading_day_key` comparison at boot;
- change the `timedelta(minutes=15)` shift to `0`;
- make `restore_daily_anchor` a no-op.

**Verification:** `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
Baseline is 716 tests / ~985 s (some suites now differ after the news-source-layer
merge — record the actual figure). Check `uptime` and for concurrent `unittest discover`
processes before believing any failure: this box is shared, and contention manufactures
plausible-looking failures. A contended **OK** is trustworthy; only a contended
**FAILURE** needs a quiet re-run.

## 5 · Out of scope

- `starting_balance` persistence. It has the same in-memory-only shape, but it is only a
  *fallback* used while `day_start_equity == 0` — a window of a few seconds at boot —
  and it is not what RISK-01 names.
- Any change to the 23:45 reset trigger itself, or to the report it is attached to.
- RISK-02 (count caps blind to pendings) and the other audit rows.

## 6 · Risk to the live bot

The demo-forward test is running from the main checkout and is **not** affected by this
work: development happens in a separate worktree, and all tests use temporary
databases. The change only takes effect when the operator next restarts the bot onto
this code — at which point the first restart still anchors fresh (no persisted row for
today yet) and every subsequent one restores correctly.
