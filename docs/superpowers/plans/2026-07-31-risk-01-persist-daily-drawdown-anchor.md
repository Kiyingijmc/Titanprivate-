# RISK-01 Persist Daily Drawdown Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 3 % daily drawdown circuit breaker survive a process restart, so restarting the bot mid-day no longer discards the day's realised drawdown and mints a fresh allowance.

**Architecture:** Three seams. `StateManager` (already the "survives reboots" layer, owns `trade_state.db`) gains a single-row `risk_state` table plus save/get methods. `RiskManager` gains exactly one pure setter — no I/O, no new constructor argument — so the ~10 test modules that build it from a bare config dict keep working. `SystemController` owns the trading-day boundary (23:45 Africa/Kampala, matching the `reset_daily_metrics` call it already makes there), restores the anchor at boot, and persists it on change.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, stdlib `unittest` (there is **no pytest** in this repo), `pytz` (already a dependency, already imported by the controller).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-31-risk-01-persist-daily-drawdown-anchor-design.md`.
- Tests run with `.venv/bin/python -m unittest`, never `pytest`. The venv is at `.venv` in the worktree root.
- Work happens in the worktree `…/scratchpad/risk01-wt` on branch `feat/risk-01-daily-anchor`, based on `main` @ `3679680`. **Never run anything against the repo root checkout** — a live demo-forward bot is running from it.
- Every test must use `tempfile.TemporaryDirectory()` for databases. **Never** let a test open `data/db/trade_state.db`; that is the live bot's database.
- `RiskManager` must remain I/O-free: no `db_path`, no sqlite import, no new required constructor arguments.
- Restore must be **strictly monotone** — it may only ever keep an anchor that current code discards. There must be no input for which the new code is more permissive than today's.
- Follow the surrounding style: `StateManager` methods wrap bodies in `try/except` and call `self.conn.commit()` after writes; failures `print(f"[DB ERROR] …")` and return a safe default rather than raising.
- Baseline suite before any change: record the actual `Ran N tests … OK` figure. Before believing any FAILURE, check `uptime` and `ps -eo args | grep '[u]nittest discover'` — this box is shared and contention manufactures plausible failures. A contended **OK** is trustworthy; only a contended **FAILURE** needs a quiet re-run.

---

### Task 1: `risk_state` table and accessors in `StateManager`

**Files:**
- Modify: `src/core/state_manager.py` (add table to `_init_db`, add two methods near `get_ratchet_state`)
- Test: `tests/unit/test_state_manager.py` (extend — the file already has a `tempfile` fixture pattern)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `StateManager.save_risk_anchor(trading_day_key: str, day_start_equity: float) -> None`
  - `StateManager.get_risk_anchor() -> dict | None` returning
    `{'trading_day_key': str, 'day_start_equity': float, 'updated_at': float}`, or `None`
    when no row exists or on any error.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_state_manager.py`, before the `if __name__ == "__main__":` block:

```python
class RiskAnchorPersistence(unittest.TestCase):
    """RISK-01: the daily DD anchor must survive a process restart."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state.db")
        self.sm = StateManager(self.path)

    def tearDown(self):
        self.sm.close()
        self.tmp.cleanup()

    def test_no_anchor_on_fresh_db(self):
        self.assertIsNone(self.sm.get_risk_anchor())

    def test_save_then_read_round_trip(self):
        self.sm.save_risk_anchor("2026-07-31", 1234.56)
        row = self.sm.get_risk_anchor()
        self.assertEqual(row["trading_day_key"], "2026-07-31")
        self.assertAlmostEqual(row["day_start_equity"], 1234.56)
        self.assertGreater(row["updated_at"], 0)

    def test_second_save_replaces_and_never_appends(self):
        self.sm.save_risk_anchor("2026-07-31", 1000.0)
        self.sm.save_risk_anchor("2026-08-01", 1100.0)
        n = self.sm.conn.execute("SELECT COUNT(*) FROM risk_state").fetchone()[0]
        self.assertEqual(n, 1)  # single-row table, not an append log
        row = self.sm.get_risk_anchor()
        self.assertEqual(row["trading_day_key"], "2026-08-01")
        self.assertAlmostEqual(row["day_start_equity"], 1100.0)

    def test_anchor_survives_reopening_the_database(self):
        """The actual restart scenario: new StateManager, same file."""
        self.sm.save_risk_anchor("2026-07-31", 987.65)
        self.sm.close()
        reopened = StateManager(self.path)
        try:
            row = reopened.get_risk_anchor()
            self.assertEqual(row["trading_day_key"], "2026-07-31")
            self.assertAlmostEqual(row["day_start_equity"], 987.65)
        finally:
            reopened.close()
            self.sm = StateManager(self.path)  # so tearDown's close() is valid

    def test_table_is_added_to_a_preexisting_database(self):
        """An existing trade_state.db must gain risk_state on next boot."""
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE active_orders (
            ticket_id INTEGER PRIMARY KEY, symbol TEXT, strategy TEXT, order_type TEXT,
            time_placed REAL, status TEXT, phase INTEGER DEFAULT 0)""")
        conn.commit(); conn.close()

        sm = StateManager(path)
        sm.save_risk_anchor("2026-07-31", 500.0)
        self.assertAlmostEqual(sm.get_risk_anchor()["day_start_equity"], 500.0)
        sm.close(); tmp.cleanup()
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
cd "$WT" && .venv/bin/python -m unittest tests.unit.test_state_manager -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: 'StateManager' object has no attribute 'save_risk_anchor'`
(and `no such table: risk_state`). If any of these **passes**, stop: the test is not
testing what it claims.

- [ ] **Step 3: Add the table to `_init_db`**

In `src/core/state_manager.py`, inside `_init_db()`'s `try:` block, immediately after the
`CREATE TABLE IF NOT EXISTS trade_history (…)` statement and **before** the
`# --- MIGRATION GUARD (Retained) ---` comment:

```python
            # RISK-01: the daily drawdown anchor, so a restart cannot re-anchor
            # the circuit breaker to mid-day equity and mint a fresh allowance.
            # CHECK (id = 1) makes "exactly one row" a schema invariant, so a bug
            # elsewhere can never make "which anchor is current?" ambiguous.
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS risk_state (
                    id               INTEGER PRIMARY KEY CHECK (id = 1),
                    trading_day_key  TEXT,
                    day_start_equity REAL DEFAULT 0.0,
                    updated_at       REAL
                )
            ''')
```

- [ ] **Step 4: Add the two accessors**

In `src/core/state_manager.py`, in the `# --- Standard Helpers ---` section, immediately
before `def get_ratchet_state(self, t):`:

```python
    def save_risk_anchor(self, trading_day_key, day_start_equity):
        """Persist today's drawdown anchor (RISK-01).

        Called on change, not per heartbeat: once when the boot anchor is first
        established and once at the 23:45 daily reset.
        """
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO risk_state
                (id, trading_day_key, day_start_equity, updated_at)
                VALUES (1, ?, ?, ?)
            """, (str(trading_day_key), float(day_start_equity), time.time()))
            self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] SaveRiskAnchor: {e}")

    def get_risk_anchor(self):
        """The persisted drawdown anchor, or None if never saved / unreadable.

        None means "no usable anchor" and the caller must fall back to the
        existing first-heartbeat behaviour -- never to a guessed number.
        """
        try:
            r = self.conn.execute(
                "SELECT trading_day_key, day_start_equity, updated_at "
                "FROM risk_state WHERE id=1").fetchone()
            return dict(r) if r else None
        except Exception:
            return None
```

- [ ] **Step 5: Run the tests and verify they pass**

```bash
cd "$WT" && .venv/bin/python -m unittest tests.unit.test_state_manager -v 2>&1 | tail -20
```

Expected: `OK`, with all five new tests listed.

- [ ] **Step 6: Mutation-check the tests actually bite**

A green suite is not evidence in this repo. Apply each mutation, confirm RED, revert:

1. Change `WHERE id=1` in `get_risk_anchor` to `WHERE id=2` → expect round-trip failures.
2. Change `INSERT OR REPLACE` to `INSERT OR IGNORE` → expect
   `test_second_save_replaces_and_never_appends` to fail on the stale value.
3. Delete the `CREATE TABLE … risk_state` block → expect
   `test_table_is_added_to_a_preexisting_database` to fail.

If any mutation leaves the suite green, the corresponding test is decorative — fix it
before continuing.

- [ ] **Step 7: Commit**

```bash
cd "$WT"
git add src/core/state_manager.py tests/unit/test_state_manager.py
git commit -m "feat(risk-01): persist the daily drawdown anchor in trade_state.db

Single-row risk_state table plus save_risk_anchor/get_risk_anchor. The
CHECK (id = 1) constraint makes 'exactly one anchor' a schema invariant.
get_risk_anchor returns None rather than a guess when unreadable, matching
the fail-safe discipline the risk layer already uses."
```

---

### Task 2: `RiskManager.restore_daily_anchor`

**Files:**
- Modify: `src/risk/risk_manager.py` (one method, after `update_account_info` at `:47-55`)
- Test: `tests/unit/test_risk_manager_daily_anchor.py` (extend — already has the `CFG` fixture)

**Interfaces:**
- Consumes: nothing from Task 1 (deliberately — `RiskManager` must not know about storage).
- Produces: `RiskManager.restore_daily_anchor(equity: float) -> None`. Sets
  `self.day_start_equity` when `equity` is a positive number; otherwise a no-op.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_risk_manager_daily_anchor.py`, before `if __name__ == "__main__":`:

```python
class RestoredAnchorSurvivesRestart(unittest.TestCase):
    """RISK-01: a restart must not re-anchor the breaker to mid-day equity."""

    def test_restored_anchor_survives_the_first_heartbeat(self):
        # The bug, reproduced: bot restarts already 3.1% down on the day.
        rm = RiskManager(CFG)
        rm.restore_daily_anchor(1000.0)
        rm.update_account_info(1000.0, 969.0)   # first post-boot heartbeat
        self.assertAlmostEqual(rm.day_start_equity, 1000.0)
        # Without the fix update_account_info re-anchors to 969.0, computes a
        # 0% drawdown, and hands back a fresh 3% allowance.
        self.assertFalse(rm.check_can_trade())

    def test_restored_anchor_still_allows_inside_the_limit(self):
        rm = RiskManager(CFG)
        rm.restore_daily_anchor(1000.0)
        rm.update_account_info(1000.0, 980.0)   # -2% on the day
        self.assertTrue(rm.check_can_trade())

    def test_restore_is_a_noop_for_zero_and_negative(self):
        """A corrupt persisted row must not poison the breaker."""
        for bad in (0.0, -1.0, -1000.0):
            rm = RiskManager(CFG)
            rm.restore_daily_anchor(bad)
            self.assertEqual(rm.day_start_equity, 0.0)
            # The normal fresh-anchor path must still work afterwards.
            rm.update_account_info(1000.0, 1000.0)
            self.assertAlmostEqual(rm.day_start_equity, 1000.0)

    def test_restore_is_a_noop_for_unusable_types(self):
        for bad in (None, "", "abc"):
            rm = RiskManager(CFG)
            rm.restore_daily_anchor(bad)
            self.assertEqual(rm.day_start_equity, 0.0)

    def test_restored_anchor_also_drives_the_throttle(self):
        """throttle_factor shares the anchor; it must see the restored one."""
        cfg = {"risk": {"account": {"max_daily_drawdown_pct": 3.0,
                                    "max_global_exposure_pct": 6.0},
                        "trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0,
                                  "static_commission_usd": 7.0},
                        "drawdown_throttle": {"enabled": True,
                                              "trigger_dd_pct": 2.0, "factor": 0.5}}}
        rm = RiskManager(cfg)
        rm.restore_daily_anchor(1000.0)
        rm.update_account_info(1000.0, 975.0)   # -2.5% vs the restored anchor
        self.assertEqual(rm.throttle_factor(), 0.5)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
cd "$WT" && .venv/bin/python -m unittest tests.unit.test_risk_manager_daily_anchor -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: 'RiskManager' object has no attribute 'restore_daily_anchor'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/risk/risk_manager.py`, immediately after `update_account_info` (i.e. after line 55,
before `def track_equity`):

```python
    def restore_daily_anchor(self, equity):
        """Prime today's DD anchor from persisted state, before any heartbeat.

        RISK-01: day_start_equity was in-memory only, so every restart re-set it
        to whatever equity the first post-boot heartbeat reported -- discarding
        the day's realised drawdown and granting a fresh allowance. The caller
        (SystemController, at boot) supplies the anchor persisted earlier today.

        No I/O here on purpose: RiskManager stays a pure class that ~10 test
        modules construct from a bare config dict. Storage is StateManager's job.

        A non-positive or unusable value is a NO-OP, not a coercion: a corrupt
        persisted row must leave the existing first-heartbeat path intact rather
        than anchor the breaker to nonsense.
        """
        try:
            value = float(equity)
        except (TypeError, ValueError):
            return
        if math.isfinite(value) and value > 0:
            self.day_start_equity = value
```

`math` is already imported at the top of this file (line 11).

- [ ] **Step 4: Run the tests and verify they pass**

```bash
cd "$WT" && .venv/bin/python -m unittest tests.unit.test_risk_manager_daily_anchor -v 2>&1 | tail -20
```

Expected: `OK`.

- [ ] **Step 5: Mutation-check**

1. Make the method body just `pass` → `test_restored_anchor_survives_the_first_heartbeat`
   must FAIL. **This is the single most important mutation in the plan** — it proves the
   test actually reproduces RISK-01 rather than passing incidentally.
2. Change `value > 0` to `value >= 0` → `test_restore_is_a_noop_for_zero_and_negative`
   must FAIL.
3. Remove the `try/except` → `test_restore_is_a_noop_for_unusable_types` must ERROR.

Revert each mutation after confirming RED.

- [ ] **Step 6: Commit**

```bash
cd "$WT"
git add src/risk/risk_manager.py tests/unit/test_risk_manager_daily_anchor.py
git commit -m "feat(risk-01): RiskManager.restore_daily_anchor

One pure setter, no I/O and no new ctor args, so every existing test that
builds RiskManager from a bare config dict is untouched. Once restored the
anchor is non-zero, so update_account_info's existing 'if day_start_equity
== 0' guard declines to re-anchor -- the fix primes that guard before the
first heartbeat rather than adding a second one."
```

---

### Task 3: Trading-day boundary at 23:45 EAT

**Files:**
- Modify: `src/core/system_controller.py` (add one `@staticmethod` near the top of `SystemController`)
- Test: `tests/unit/test_trading_day_key.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `SystemController._trading_day_key(now_uganda: datetime) -> str`, a
  `'%Y-%m-%d'` label whose boundary falls at 23:45 rather than midnight.

**Why 23:45:** the controller already re-anchors there (`system_controller.py:346-355`,
inside the Uganda report block). If restore used a midnight boundary the two would
disagree for 15 minutes each night, and a restart in that window would either resurrect
a superseded anchor or discard a valid one.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_trading_day_key.py`:

```python
"""RISK-01: the trading-day label must roll over at 23:45 Africa/Kampala,
the same boundary at which SystemController already calls
RiskManager.reset_daily_metrics() (system_controller.py:346-355). A midnight
boundary would disagree with that reset for 15 minutes every night."""
import os
import sys
import unittest
from datetime import datetime

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pytz  # noqa: E402

from src.core.system_controller import SystemController  # noqa: E402

EAT = pytz.timezone("Africa/Kampala")


def at(y, m, d, hh, mm, ss=0):
    return EAT.localize(datetime(y, m, d, hh, mm, ss))


class TradingDayKey(unittest.TestCase):
    def test_midday_is_todays_date(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 12, 0)),
                         "2026-07-31")

    def test_just_before_2345_is_still_today(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 23, 44, 59)),
                         "2026-07-31")

    def test_2345_starts_the_next_trading_day(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 23, 45, 0)),
                         "2026-08-01")

    def test_after_midnight_stays_in_the_day_2345_opened(self):
        """00:30 belongs to the trading day the 23:45 reset just started."""
        self.assertEqual(SystemController._trading_day_key(at(2026, 8, 1, 0, 30)),
                         "2026-08-01")

    def test_month_boundary(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 7, 31, 23, 50)),
                         "2026-08-01")

    def test_year_boundary(self):
        self.assertEqual(SystemController._trading_day_key(at(2026, 12, 31, 23, 50)),
                         "2027-01-01")

    def test_is_a_staticmethod_needing_no_controller(self):
        """Must be callable without constructing SystemController, which would
        open the live bot's real databases and bind its ports."""
        self.assertIsInstance(
            SystemController.__dict__["_trading_day_key"], staticmethod)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd "$WT" && .venv/bin/python -m unittest tests.unit.test_trading_day_key -v 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: type object 'SystemController' has no attribute '_trading_day_key'`.

- [ ] **Step 3: Write the minimal implementation**

In `src/core/system_controller.py`, add as the first method of `class SystemController`,
immediately before `def _load_env(self):`:

```python
    # RISK-01. The daily DD anchor is keyed by TRADING day, not calendar day.
    # The bot already re-anchors at 23:45 Africa/Kampala (the Uganda report block
    # in the main loop), so a restore that used a midnight boundary would
    # disagree with that reset for 15 minutes every night -- long enough for a
    # restart to resurrect an anchor the reset had already superseded.
    # Shifting the clock forward 15 minutes makes plain strftime roll over at
    # exactly 23:45.
    @staticmethod
    def _trading_day_key(now_uganda):
        """'%Y-%m-%d' label for the trading day containing `now_uganda`."""
        return (now_uganda + timedelta(minutes=15)).strftime('%Y-%m-%d')
```

`timedelta` is already imported (`system_controller.py:18`).

- [ ] **Step 4: Run the test and verify it passes**

```bash
cd "$WT" && .venv/bin/python -m unittest tests.unit.test_trading_day_key -v 2>&1 | tail -20
```

Expected: `OK`, 7 tests.

- [ ] **Step 5: Mutation-check**

1. Change `timedelta(minutes=15)` to `timedelta(minutes=0)` →
   `test_2345_starts_the_next_trading_day` and `test_month_boundary` must FAIL.
2. Change it to `timedelta(minutes=30)` → `test_just_before_2345_is_still_today` must FAIL.

Both mutations must be caught. Revert after confirming.

- [ ] **Step 6: Commit**

```bash
cd "$WT"
git add src/core/system_controller.py tests/unit/test_trading_day_key.py
git commit -m "feat(risk-01): trading-day key with a 23:45 EAT boundary

Keyed to the same instant at which the main loop already calls
reset_daily_metrics, so a restart just after midnight cannot resurrect an
anchor that the 23:45 reset had superseded."
```

---

### Task 4: Wire restore-at-boot and persist-on-change into `SystemController`

**Files:**
- Modify: `src/core/system_controller.py`
  - `__init__`, just after `self.state_manager = StateManager(...)` (`:172`)
  - the 23:45 report block (`:346-355`)
  - the `HEARTBEAT` branch (`:709-713`)

**Interfaces:**
- Consumes: `StateManager.save_risk_anchor` / `get_risk_anchor` (Task 1),
  `RiskManager.restore_daily_anchor` (Task 2), `SystemController._trading_day_key` (Task 3).
- Produces: no new public API. Adds instance attribute `self._last_persisted_anchor`
  (`tuple[str, float] | None`) used only as a write-suppression cache.

**Why this task has no new unit test:** nothing in this repo constructs a
`SystemController` in a unit test, and doing so would open the **live bot's real**
`data/db/trade_state.db` and bind its ports. All three primitives this glue calls are
covered directly by Tasks 1–3; the glue itself is verified by inspection plus the
scripted end-to-end check in Step 5, which uses a temporary database.

- [ ] **Step 1: Add the boot restore**

In `src/core/system_controller.py`, immediately after:

```python
        state_db_path = self.root_dir / "data/db/trade_state.db"
        self.state_manager = StateManager(str(state_db_path))
```

insert:

```python

        # RISK-01: restore today's drawdown anchor before the first heartbeat.
        # Without this, every restart re-anchored the 3% breaker to whatever
        # equity happened to be live at boot, discarding the day's realised
        # drawdown. Strictly monotone: an absent or stale row changes nothing,
        # so this can only ever KEEP an anchor the old code threw away.
        self._last_persisted_anchor = None
        try:
            saved = self.state_manager.get_risk_anchor()
            today_key = self._trading_day_key(datetime.now(self.uganda_tz))
            if saved and saved.get('trading_day_key') == today_key:
                self.risk_manager.restore_daily_anchor(saved.get('day_start_equity'))
                self._last_persisted_anchor = (today_key,
                                               self.risk_manager.day_start_equity)
                self.logger.log_event(
                    "RISK", "ANCHOR",
                    f"Restored daily DD anchor {self.risk_manager.day_start_equity:.2f} "
                    f"for trading day {today_key} (survived restart).")
            elif saved:
                self.logger.log_event(
                    "RISK", "ANCHOR",
                    f"Persisted anchor is for {saved.get('trading_day_key')}, "
                    f"today is {today_key}; anchoring fresh.")
        except Exception as e:
            # Never let anchor restore stop the bot booting; falling through
            # lands on today's existing first-heartbeat behaviour.
            self.logger.log_event("RISK", "ANCHOR", f"Anchor restore skipped: {e}")
```

- [ ] **Step 2: Add the persist helper**

Add as a method of `SystemController`, immediately after `_trading_day_key` from Task 3:

```python
    def _persist_daily_anchor(self):
        """Write the DD anchor when it CHANGES (RISK-01).

        Called from the heartbeat path, so it must not write every ~5s: the
        cache below reduces this to roughly two writes a day -- once when the
        boot anchor first appears, once at the 23:45 reset.
        """
        equity = self.risk_manager.day_start_equity
        if equity <= 0:
            return
        key = self._trading_day_key(datetime.now(self.uganda_tz))
        if self._last_persisted_anchor == (key, equity):
            return
        self.state_manager.save_risk_anchor(key, equity)
        self._last_persisted_anchor = (key, equity)
```

- [ ] **Step 3: Call it from the two sites where the anchor can change**

In the `HEARTBEAT` branch, change:

```python
            if eq > 0: 
                self.risk_manager.update_account_info(bal, eq)
                self.risk_manager.track_equity(eq)
```

to:

```python
            if eq > 0: 
                self.risk_manager.update_account_info(bal, eq)
                self.risk_manager.track_equity(eq)
                self._persist_daily_anchor()  # RISK-01: no-op unless it changed
```

And in the 23:45 report block, change:

```python
                        self.report_sent_today = True
                        self.risk_manager.reset_daily_metrics()
```

to:

```python
                        self.report_sent_today = True
                        self.risk_manager.reset_daily_metrics()
                        self._persist_daily_anchor()  # RISK-01: capture the new day
```

- [ ] **Step 4: Verify the module still imports**

```bash
cd "$WT" && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from src.core.system_controller import SystemController
print('import OK')
print('key:', SystemController._trading_day_key(__import__('pytz').timezone('Africa/Kampala').localize(__import__('datetime').datetime(2026,7,31,23,50))))
"
```

Expected: `import OK` then `key: 2026-08-01`.

- [ ] **Step 5: End-to-end check of the three parts together (temp DB only)**

```bash
cd "$WT" && .venv/bin/python - <<'PY'
import sys, tempfile, os
sys.path.insert(0, '.')
from src.core.state_manager import StateManager
from src.risk.risk_manager import RiskManager

CFG = {"risk": {"account": {"max_daily_drawdown_pct": 3.0},
                "trade": {"risk_per_trade_pct": 1.0}}}
tmp = tempfile.TemporaryDirectory()
db = os.path.join(tmp.name, "s.db")

# --- day 1: bot boots, anchors at 1000, drops to 969 (-3.1%) ---
sm = StateManager(db)
rm = RiskManager(CFG)
rm.update_account_info(1000.0, 1000.0)
sm.save_risk_anchor("2026-07-31", rm.day_start_equity)
rm.update_account_info(1000.0, 969.0)
assert rm.check_can_trade() is False, "breaker should have tripped"
sm.close()

# --- restart, same trading day ---
sm2 = StateManager(db)
rm2 = RiskManager(CFG)
saved = sm2.get_risk_anchor()
assert saved["trading_day_key"] == "2026-07-31"
rm2.restore_daily_anchor(saved["day_start_equity"])
rm2.update_account_info(1000.0, 969.0)          # first post-boot heartbeat
assert rm2.day_start_equity == 1000.0, rm2.day_start_equity
assert rm2.check_can_trade() is False, "RISK-01: breaker must stay tripped"

# --- control: without restore, the bug reappears ---
rm3 = RiskManager(CFG)
rm3.update_account_info(1000.0, 969.0)
assert rm3.check_can_trade() is True, "control case should show the old bug"
sm2.close(); tmp.cleanup()
print("E2E OK — restart keeps the breaker tripped; control reproduces the bug")
PY
```

Expected: `E2E OK — …`. The control assertion is the important one: it proves the
scenario genuinely reproduces RISK-01 on unmodified logic.

- [ ] **Step 6: Commit**

```bash
cd "$WT"
git add src/core/system_controller.py
git commit -m "feat(risk-01): restore the DD anchor at boot, persist it on change

Boot restore is strictly monotone -- an absent or stale row changes nothing,
so this can only keep an anchor the old code discarded. Persist is cached on
(trading_day, equity) so the heartbeat path writes ~twice a day rather than
every 5s, and the 23:45 reset captures the new day immediately."
```

---

### Task 5: Systemd restart cap

**Files:**
- Modify: `deploy/systemd/titan-live.service`
- Modify: `deploy/systemd/titan-demo.service`

**Interfaces:** none — static configuration, not executable Python.

**No runtime effect today:** the bot runs outside systemd (`nohup setsid … main.py`), so
this closes the crash-restart amplifier for whenever the shipped units are actually used.
`StartLimitBurst` / `StartLimitIntervalSec` belong in `[Unit]`, not `[Service]`.

- [ ] **Step 1: Edit both unit files**

In **both** files, change the `[Unit]` section from:

```ini
[Unit]
Description=...
After=network-online.target
```

to:

```ini
[Unit]
Description=...
After=network-online.target
# RISK-01: cap the crash-restart loop. With Restart=on-failure below, an
# unbounded loop would restart the process indefinitely, and each boot
# re-anchors the daily drawdown breaker -- laundering one bad day into an
# unlimited number of fresh 3% allowances. Three starts per five minutes,
# then systemd gives up and leaves it failed for an operator to look at.
StartLimitBurst=3
StartLimitIntervalSec=300
```

Keep each file's own `Description=` line unchanged.

- [ ] **Step 2: Verify the files parse**

```bash
cd "$WT"
for f in deploy/systemd/titan-live.service deploy/systemd/titan-demo.service; do
  echo "== $f"; cat "$f"
  systemd-analyze verify "./$f" 2>&1 | head -5 || echo "(systemd-analyze unavailable — inspect by eye)"
done
```

Expected: both show `StartLimitBurst=3` / `StartLimitIntervalSec=300` under `[Unit]`,
above `[Service]`. `systemd-analyze` may be absent under WSL; visual confirmation of
section placement is sufficient.

- [ ] **Step 3: Commit**

```bash
cd "$WT"
git add deploy/systemd/titan-live.service deploy/systemd/titan-demo.service
git commit -m "fix(risk-01): cap the systemd crash-restart loop

StartLimitBurst=3 / StartLimitIntervalSec=300 in [Unit]. Dormant today (the
bot runs outside systemd) but arms the moment these units are used: with an
unbounded Restart=on-failure loop, every restart re-anchors the daily
drawdown breaker."
```

---

### Task 6: Full suite, mutation sweep, and documentation

**Files:**
- Modify: `docs/audit-2026-07-30/08-BACKLOG-INDEX.md` (mark RISK-01 addressed)

- [ ] **Step 1: Check the box is quiet before trusting any failure**

```bash
uptime
ps -eo args | grep -E '[u]nittest discover|[v]itest' || echo "no concurrent suites"
```

Record the load. A contended **OK** is trustworthy; only a contended **FAILURE** needs a
quiet re-run.

- [ ] **Step 2: Run the full suite**

```bash
cd "$WT" && time .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' 2>&1 | tail -25
```

Expected: `OK`. Record the exact `Ran N tests in Ns` line — N should be the `main`
baseline plus the ~16 tests added here. Budget ~1000 s+; do not interrupt it.

- [ ] **Step 3: Re-run the three headline mutations against the FULL suite**

The per-task mutations proved each test bites its own module. Confirm none is masked
once everything is wired together:

1. `RiskManager.restore_daily_anchor` body → `pass`. Full suite must FAIL.
2. `_trading_day_key` shift → `timedelta(minutes=0)`. Full suite must FAIL.
3. `get_risk_anchor` → `return None` unconditionally. Note which tests fail; if **none**
   do, that is expected (only the controller glue consumes it, which is not
   instantiation-tested) — record that honestly as a known coverage boundary rather than
   claiming coverage the suite does not have.

Revert every mutation and re-run to confirm green before continuing.

- [ ] **Step 4: Update the audit backlog index**

In `docs/audit-2026-07-30/08-BACKLOG-INDEX.md`, change the RISK-01 row's estimate cell
from `2 h` to `2 h — DONE 2026-07-31 (feat/risk-01-daily-anchor)`.

- [ ] **Step 5: Commit**

```bash
cd "$WT"
git add docs/audit-2026-07-30/08-BACKLOG-INDEX.md
git commit -m "docs(risk-01): mark the daily-drawdown-anchor finding addressed"
```

- [ ] **Step 6: Report honestly**

State: the exact suite figure, which mutations were confirmed RED, and the known coverage
boundary (controller glue is not instantiation-tested). Do **not** claim the fix is live —
it takes effect only when the operator restarts the bot onto this branch, and the branch
is not merged.

---

## Self-Review

**Spec coverage:** §2.1 `StateManager` → Task 1. §2.2 `RiskManager` → Task 2. §2.3
boundary → Task 3, wiring → Task 4. §3 systemd → Task 5. §4 testing → Tasks 1–3 tests +
Task 6 full suite and mutation sweep. §5 out-of-scope items appear in no task (correct).
§6 live-bot safety → Global Constraints. No gaps.

**Placeholder scan:** every code step contains literal code; no "TBD", no "similar to
Task N", no "add error handling" hand-waves.

**Type consistency:** `save_risk_anchor(trading_day_key, day_start_equity)` and
`get_risk_anchor() -> dict|None` with keys `trading_day_key` / `day_start_equity` /
`updated_at` are used identically in Tasks 1, 4 and the E2E script.
`restore_daily_anchor(equity)` matches between Tasks 2 and 4.
`_trading_day_key(now_uganda) -> str` matches between Tasks 3 and 4.
`_last_persisted_anchor` is initialised in Task 4 Step 1 and consumed in Task 4 Step 2.

**One deliberate coverage boundary**, stated rather than papered over: the ~15 lines of
controller glue in Task 4 have no unit test, because constructing a `SystemController`
would open the live bot's real database. Task 4 Step 5 substitutes a scripted end-to-end
check on a temporary database, including a control case that reproduces the original bug.
