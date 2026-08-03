# EA Command Ack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CANCEL`/`MODIFY`/`CLOSE_POS` failures observable to Python, retried when transient, and escalated when not — so a refused command can never again look identical to a successful one.

**Architecture:** The EA echoes a Python-generated `cid` back as a new `CMD_RESULT` frame on the existing PUSH socket. A pure `CommandTracker` uses that ack to *classify* failures and drive a short retry, while the heartbeat stays the *authority* on whether the book actually changed. Retry and the close-failure halt fire on an explicit reject or a heartbeat-confirmed no-change — never on a dropped frame.

**Tech Stack:** Python 3.12, stdlib `unittest` (there is no pytest), pyzmq, MQL5.

**Spec:** [`docs/superpowers/specs/2026-08-02-ea-command-ack-design.md`](../specs/2026-08-02-ea-command-ack-design.md)

## Global Constraints

- Tests are stdlib `unittest`. Run with `.venv/bin/python -m unittest tests.unit.<module> -v`. **There is no pytest.**
- No new dependencies. Ask before adding any.
- `CommandTracker` is **pure**: no sockets, no DB, no `time.time()` inside it. Every method takes `now` as a float parameter.
- `tracker.tick(...)` is called from the **main loop only, never from the HEARTBEAT branch.** Bookkeeping in the heartbeat handler has caused defects in this codebase before.
- Constants, copied verbatim from the spec:
  - `RETRYABLE_RETCODES = {10004, 10020, 10021, 10024, 10031}`
  - `SUCCESS_RETCODES = {10008, 10009}`  (PLACED, DONE)
  - `BACKOFF_S = (2.0, 8.0, 30.0)`, `MAX_ATTEMPTS = 3`
  - `UNKNOWN_FAIL_AFTER_S = 15.0`
  - `PRICE_TOL = 1e-6`
  - **10018 (MARKET_CLOSED) is terminal, not retryable.** It escalates.
- New snapshot/GUI fields must degrade, never raise, on a controller that lacks the attribute — same defensive style as the existing `dollar` and `risk` blocks.
- Five test modules build `SystemController` via `object.__new__`, so a `grep 'SystemController('` sweep misses them. When changing controller behaviour, check: `test_strategy_timeframe.py`, `test_controller_routing.py`, `test_controller_news_gate.py`, `test_gui_server.py`, `test_risk_manager_exposure_cap.py`.
- Work on branch `feat/gui-risk-and-pending-visibility` (or a branch off it). Do not commit to `main`.

---

### Task 1: CommandTracker — registration and result classification

**Files:**
- Create: `src/execution/command_tracker.py`
- Test: `tests/unit/test_command_tracker.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CommandTracker`, `classify(retcode) -> str`, `InFlight` dataclass, and the module constants listed in Global Constraints. Later tasks call `register(...)`, `on_result(...)`, `tick(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_command_tracker.py
import unittest
from src.execution.command_tracker import CommandTracker, classify


def make_tracker():
    return CommandTracker()


def register_cancel(t, cid="c-1", ticket=555, now=100.0):
    t.register(cid=cid, action="CANCEL", ticket=ticket, symbol="EURUSD",
               expected={}, payload={"ticket": ticket, "cid": cid}, now=now)


class TestClassify(unittest.TestCase):
    def test_success_codes(self):
        self.assertEqual(classify(10009), "success")   # DONE
        self.assertEqual(classify(10008), "success")   # PLACED

    def test_fast_transient_codes_retry(self):
        for code in (10004, 10020, 10021, 10024, 10031):
            self.assertEqual(classify(code), "retry", code)

    def test_market_closed_is_terminal_not_retry(self):
        """10018 implies an hours-long wait. Per the retry-horizon decision it
        escalates to a human rather than occupying a retry slot."""
        self.assertEqual(classify(10018), "terminal")

    def test_unknown_code_is_terminal(self):
        self.assertEqual(classify(10013), "terminal")


class TestRegisterAndResult(unittest.TestCase):
    def test_registered_command_is_in_flight(self):
        t = make_tracker()
        register_cancel(t)
        self.assertEqual(t.in_flight_count(), 1)

    def test_result_for_unknown_cid_is_uncorrelated(self):
        t = make_tracker()
        self.assertFalse(t.on_result("nope", ok=False, retcode=10018, err=0,
                                     comment="", now=101.0))

    def test_retryable_reject_schedules_first_backoff(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        self.assertTrue(t.on_result("c-1", ok=False, retcode=10004, err=0,
                                    comment="requote", now=101.0))
        self.assertEqual(t.peek("c-1").retry_at, 103.0)   # 101 + BACKOFF_S[0]

    def test_terminal_reject_marks_for_escalation(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=False, retcode=10018, err=0,
                    comment="Market closed", now=101.0)
        entry = t.peek("c-1")
        self.assertTrue(entry.escalate_now)
        self.assertEqual(entry.reason, "reject")

    def test_ok_ack_does_not_resolve_on_its_own(self):
        """The heartbeat is the authority. A broker that says DONE while the
        book never changes must still fall through the unchanged-window path."""
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=True, retcode=10009, err=0, comment="", now=101.0)
        self.assertEqual(t.in_flight_count(), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.execution.command_tracker'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/execution/command_tracker.py
"""Tracks fire-and-forget management commands to a confirmed outcome.

CANCEL/MODIFY/CLOSE_POS go out on the PUSH socket with no reply, so before this
existed a refused command and a successful one were indistinguishable above the
wire (2026-08-02: a GUI cancel returned ok while FBS refused it with retcode
10018, evidence only in MT5's Experts log).

Deliberately pure -- no sockets, no DB, no clock. Every entry point takes `now`.
That keeps the whole retry policy unit-testable without a bridge, the same shape
RiskManager already uses.
"""
from dataclasses import dataclass, field
from typing import Optional

# Fast-transient only. Anything slower than "seconds to minutes" escalates to a
# human instead of occupying a retry slot -- notably 10018 MARKET_CLOSED, which
# implies waiting for a session to open.
RETRYABLE_RETCODES = frozenset({10004, 10020, 10021, 10024, 10031})
SUCCESS_RETCODES = frozenset({10008, 10009})     # PLACED, DONE

BACKOFF_S = (2.0, 8.0, 30.0)
MAX_ATTEMPTS = 3
UNKNOWN_FAIL_AFTER_S = 15.0
PRICE_TOL = 1e-6


def classify(retcode) -> str:
    """'success' | 'retry' | 'terminal' for an MT5 trade retcode."""
    try:
        code = int(retcode or 0)
    except (TypeError, ValueError):
        return "terminal"
    if code in SUCCESS_RETCODES:
        return "success"
    if code in RETRYABLE_RETCODES:
        return "retry"
    return "terminal"


@dataclass
class InFlight:
    cid: str
    action: str                 # CANCEL | MODIFY | CLOSE_POS
    ticket: int
    symbol: str
    expected: dict
    payload: dict               # exact dict to re-send on retry
    sent_at: float
    attempts: int = 1
    retry_at: Optional[float] = None
    retcode: Optional[int] = None
    err: int = 0
    comment: str = ""
    reason: str = ""            # "" | "reject" | "no-ack"
    escalate_now: bool = False


class CommandTracker:
    def __init__(self):
        self._inflight: dict[str, InFlight] = {}

    def in_flight_count(self) -> int:
        return len(self._inflight)

    def peek(self, cid) -> Optional[InFlight]:
        """Test/diagnostic accessor. Not part of the controller contract."""
        return self._inflight.get(cid)

    def register(self, cid, action, ticket, symbol, expected, payload, now):
        self._inflight[cid] = InFlight(
            cid=cid, action=action, ticket=int(ticket), symbol=symbol,
            expected=dict(expected or {}), payload=dict(payload or {}), sent_at=float(now))

    def on_result(self, cid, ok, retcode, err, comment, now) -> bool:
        """Feed a CMD_RESULT. Returns False when the cid is unknown (an
        uncorrelated result -- worth logging, but nothing to act on)."""
        entry = self._inflight.get(cid)
        if entry is None:
            return False
        entry.retcode = int(retcode or 0)
        entry.err = int(err or 0)
        entry.comment = comment or ""
        if ok:
            # NOT resolved here. The heartbeat is the authority: a broker that
            # reports DONE while the book never changes must still be caught.
            return True
        entry.reason = "reject"
        if classify(entry.retcode) == "retry" and entry.attempts < MAX_ATTEMPTS:
            entry.retry_at = float(now) + BACKOFF_S[entry.attempts - 1]
        else:
            entry.escalate_now = True
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker -v`
Expected: PASS — 9 tests OK

- [ ] **Step 5: Commit**

```bash
git add src/execution/command_tracker.py tests/unit/test_command_tracker.py
git commit -m "feat(exec): CommandTracker registration and retcode classification"
```

---

### Task 2: CommandTracker — retry scheduling and escalation

**Files:**
- Modify: `src/execution/command_tracker.py`
- Test: `tests/unit/test_command_tracker.py`

**Interfaces:**
- Consumes: `CommandTracker.register/on_result`, `BACKOFF_S`, `MAX_ATTEMPTS` from Task 1.
- Produces: `TickOutcome(retries: list[tuple[str, dict]], escalations: list[dict], resolved: list[str])` and `CommandTracker.tick(now, positions, orders) -> TickOutcome`. `retries` entries are `(action, payload)` ready to hand to `bridge.send_command`. Task 5 consumes both lists.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_command_tracker.py
class TestRetryAndEscalation(unittest.TestCase):
    def test_terminal_reject_escalates_on_next_tick(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=False, retcode=10018, err=0,
                    comment="Market closed", now=101.0)
        out = t.tick(now=101.0, positions=[], orders=[{"t": 555}])
        self.assertEqual(len(out.escalations), 1)
        esc = out.escalations[0]
        self.assertEqual(esc["action"], "CANCEL")
        self.assertEqual(esc["ticket"], 555)
        self.assertEqual(esc["retcode"], 10018)
        self.assertEqual(esc["reason"], "reject")
        self.assertEqual(t.in_flight_count(), 0)

    def test_retryable_reject_waits_for_backoff(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=False, retcode=10004, err=0, comment="", now=101.0)
        out = t.tick(now=102.9, positions=[], orders=[{"t": 555}])
        self.assertEqual(out.retries, [])
        self.assertEqual(t.in_flight_count(), 1)

    def test_retry_fires_at_backoff_and_bumps_attempt(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=False, retcode=10004, err=0, comment="", now=101.0)
        out = t.tick(now=103.0, positions=[], orders=[{"t": 555}])
        self.assertEqual(out.retries, [("CANCEL", {"ticket": 555, "cid": "c-1"})])
        entry = t.peek("c-1")
        self.assertEqual(entry.attempts, 2)
        self.assertIsNone(entry.retry_at)
        self.assertEqual(entry.sent_at, 103.0)   # unknown-window restarts

    def test_backoff_schedule_is_2_8_30(self):
        t = make_tracker()
        register_cancel(t, now=0.0)
        t.on_result("c-1", ok=False, retcode=10004, err=0, comment="", now=0.0)
        self.assertEqual(t.peek("c-1").retry_at, 2.0)
        t.tick(now=2.0, positions=[], orders=[{"t": 555}])
        t.on_result("c-1", ok=False, retcode=10004, err=0, comment="", now=2.0)
        self.assertEqual(t.peek("c-1").retry_at, 10.0)   # 2 + 8

    def test_exhausted_retries_escalate_with_attempt_count(self):
        t = make_tracker()
        register_cancel(t, now=0.0)
        now = 0.0
        for _ in range(MAX_ATTEMPTS):
            t.on_result("c-1", ok=False, retcode=10004, err=0, comment="", now=now)
            entry = t.peek("c-1")
            if entry.escalate_now:
                break
            now = entry.retry_at
            t.tick(now=now, positions=[], orders=[{"t": 555}])
        out = t.tick(now=now, positions=[], orders=[{"t": 555}])
        self.assertEqual(len(out.escalations), 1)
        self.assertEqual(out.escalations[0]["attempts"], 3)
        self.assertEqual(t.in_flight_count(), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker.TestRetryAndEscalation -v`
Expected: FAIL — `AttributeError: 'CommandTracker' object has no attribute 'tick'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/execution/command_tracker.py` — the `TickOutcome` dataclass beside `InFlight`, and `tick` plus `_escalation` as methods on `CommandTracker`:

```python
@dataclass
class TickOutcome:
    retries: list = field(default_factory=list)       # [(action, payload), ...]
    escalations: list = field(default_factory=list)   # [dict, ...]
    resolved: list = field(default_factory=list)      # [cid, ...]
```

```python
    def _escalation(self, entry: InFlight) -> dict:
        return {
            "cid": entry.cid, "action": entry.action, "ticket": entry.ticket,
            "symbol": entry.symbol, "retcode": entry.retcode,
            "reason": entry.reason or "no-ack", "attempts": entry.attempts,
            "comment": entry.comment,
        }

    def tick(self, now, positions, orders) -> TickOutcome:
        out = TickOutcome()
        now = float(now)
        for cid, entry in list(self._inflight.items()):
            if entry.escalate_now:
                out.escalations.append(self._escalation(entry))
                del self._inflight[cid]
                continue
            if entry.retry_at is not None and now >= entry.retry_at:
                entry.attempts += 1
                entry.retry_at = None
                entry.reason = ""
                entry.sent_at = now          # restart the unknown window
                out.retries.append((entry.action, dict(entry.payload)))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker -v`
Expected: PASS — all tests OK

- [ ] **Step 5: Commit**

```bash
git add src/execution/command_tracker.py tests/unit/test_command_tracker.py
git commit -m "feat(exec): CommandTracker retry scheduling and escalation"
```

---

### Task 3: CommandTracker — heartbeat resolution and the unknown path

**Files:**
- Modify: `src/execution/command_tracker.py`
- Test: `tests/unit/test_command_tracker.py`

**Interfaces:**
- Consumes: `TickOutcome`, `tick` from Task 2; `UNKNOWN_FAIL_AFTER_S`, `PRICE_TOL` from Task 1.
- Produces: no new public names. `tick` gains state resolution — this is the safety-critical behaviour Task 5 depends on.

`positions` and `orders` are the raw heartbeat lists. Positions carry `t`/`s`/`p`/`sl`/`tp`/`vol`; orders carry `t`/`s`/`p`/`type`/`vol` and **no** `sl`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_command_tracker.py
class TestStateResolution(unittest.TestCase):
    def test_cancel_resolves_when_order_leaves_the_book(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        out = t.tick(now=101.0, positions=[], orders=[])
        self.assertEqual(out.resolved, ["c-1"])
        self.assertEqual(t.in_flight_count(), 0)

    def test_modify_resolves_when_sl_and_tp_match(self):
        t = make_tracker()
        t.register(cid="m-1", action="MODIFY", ticket=7, symbol="EURUSD",
                   expected={"sl": 1.1, "tp": 1.2},
                   payload={"ticket": 7, "cid": "m-1"}, now=100.0)
        pos = [{"t": 7, "sl": 1.1, "tp": 1.2, "vol": 0.1}]
        self.assertEqual(t.tick(now=101.0, positions=pos, orders=[]).resolved, ["m-1"])

    def test_modify_unresolved_while_sl_still_old(self):
        t = make_tracker()
        t.register(cid="m-1", action="MODIFY", ticket=7, symbol="EURUSD",
                   expected={"sl": 1.1, "tp": 1.2},
                   payload={"ticket": 7, "cid": "m-1"}, now=100.0)
        pos = [{"t": 7, "sl": 1.05, "tp": 1.2, "vol": 0.1}]
        self.assertEqual(t.tick(now=101.0, positions=pos, orders=[]).resolved, [])

    def test_full_close_resolves_when_position_gone(self):
        t = make_tracker()
        t.register(cid="x-1", action="CLOSE_POS", ticket=9, symbol="ETHUSD",
                   expected={"remaining": None}, payload={"ticket": 9, "cid": "x-1"},
                   now=100.0)
        self.assertEqual(t.tick(now=101.0, positions=[], orders=[]).resolved, ["x-1"])

    def test_partial_close_resolves_when_volume_reduced(self):
        t = make_tracker()
        t.register(cid="x-2", action="CLOSE_POS", ticket=9, symbol="ETHUSD",
                   expected={"remaining": 0.10}, payload={"ticket": 9, "cid": "x-2"},
                   now=100.0)
        pos = [{"t": 9, "sl": 0, "tp": 0, "vol": 0.10}]
        self.assertEqual(t.tick(now=101.0, positions=pos, orders=[]).resolved, ["x-2"])

    def test_partial_close_unresolved_while_volume_unchanged(self):
        t = make_tracker()
        t.register(cid="x-2", action="CLOSE_POS", ticket=9, symbol="ETHUSD",
                   expected={"remaining": 0.10}, payload={"ticket": 9, "cid": "x-2"},
                   now=100.0)
        pos = [{"t": 9, "sl": 0, "tp": 0, "vol": 0.15}]
        self.assertEqual(t.tick(now=101.0, positions=pos, orders=[]).resolved, [])

    def test_state_wins_over_a_pending_reject(self):
        """Broker said no, but the book shows the change applied. Trust the book
        and do not retry -- retrying here would double-act."""
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=False, retcode=10004, err=0, comment="", now=100.0)
        out = t.tick(now=103.0, positions=[], orders=[])
        self.assertEqual(out.resolved, ["c-1"])
        self.assertEqual(out.retries, [])


class TestUnknownPath(unittest.TestCase):
    def test_missing_ack_is_not_a_failure_before_the_window(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        out = t.tick(now=114.0, positions=[], orders=[{"t": 555}])
        self.assertEqual(out.escalations, [])
        self.assertEqual(out.retries, [])
        self.assertEqual(t.in_flight_count(), 1)

    def test_missing_ack_past_the_window_retries_as_transient(self):
        """No retcode means no evidence the command is permanently invalid, so
        it is treated as transient rather than escalated straight away."""
        t = make_tracker()
        register_cancel(t, now=100.0)
        out = t.tick(now=115.0, positions=[], orders=[{"t": 555}])
        self.assertEqual(out.retries, [("CANCEL", {"ticket": 555, "cid": "c-1"})])
        self.assertEqual(t.peek("c-1").attempts, 2)

    def test_ok_ack_with_unchanged_book_still_fails(self):
        t = make_tracker()
        register_cancel(t, now=100.0)
        t.on_result("c-1", ok=True, retcode=10009, err=0, comment="", now=100.5)
        out = t.tick(now=115.0, positions=[], orders=[{"t": 555}])
        self.assertEqual(len(out.retries), 1)

    def test_no_ack_escalation_reports_null_retcode_and_reason(self):
        t = make_tracker()
        register_cancel(t, now=0.0)
        now = 0.0
        for _ in range(MAX_ATTEMPTS):
            now += UNKNOWN_FAIL_AFTER_S
            out = t.tick(now=now, positions=[], orders=[{"t": 555}])
            if out.escalations:
                break
        self.assertEqual(len(out.escalations), 1)
        self.assertEqual(out.escalations[0]["reason"], "no-ack")
        self.assertIsNone(out.escalations[0]["retcode"])
```

Add to the imports at the top of the test file:

```python
from src.execution.command_tracker import (
    CommandTracker, classify, MAX_ATTEMPTS, UNKNOWN_FAIL_AFTER_S)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker.TestStateResolution -v`
Expected: FAIL — `AssertionError: [] != ['c-1']` (tick does not yet inspect state)

- [ ] **Step 3: Write minimal implementation**

Add the module-level helpers and extend `tick`:

```python
def _find_position(positions, ticket):
    for p in positions or []:
        try:
            if int(p.get("t", 0) or 0) == ticket:
                return p
        except (TypeError, ValueError):
            continue
    return None


def _price_matches(actual, wanted) -> bool:
    return abs(float(actual or 0.0) - float(wanted or 0.0)) <= PRICE_TOL


def is_applied(entry: InFlight, positions, orders) -> bool:
    """Has the book actually changed the way this command intended?

    This -- not the ack -- is the authority. A missing CMD_RESULT is merely
    unknown; only a book that refuses to change is a failure.
    """
    if entry.action == "CANCEL":
        return _find_position(orders, entry.ticket) is None
    if entry.action == "MODIFY":
        pos = _find_position(positions, entry.ticket)
        if pos is None:
            return True          # position closed; nothing left to modify
        return (_price_matches(pos.get("sl"), entry.expected.get("sl"))
                and _price_matches(pos.get("tp"), entry.expected.get("tp")))
    if entry.action == "CLOSE_POS":
        pos = _find_position(positions, entry.ticket)
        if pos is None:
            return True          # fully closed
        remaining = entry.expected.get("remaining")
        if remaining is None:
            return False         # full close requested, position still open
        return float(pos.get("vol", 0.0)) <= float(remaining) + PRICE_TOL
    return False
```

Then in `tick`, insert the state check as the **first** branch of the loop and add the unknown-window branch at the end:

```python
        for cid, entry in list(self._inflight.items()):
            # State first: the book is the authority, and a change that landed
            # must never be retried even if the broker reported a reject.
            if is_applied(entry, positions, orders):
                out.resolved.append(cid)
                del self._inflight[cid]
                continue
            if entry.escalate_now:
                ...                                  # unchanged from Task 2
            if entry.retry_at is not None and now >= entry.retry_at:
                ...                                  # unchanged from Task 2
                continue
            # No ack, or an "ok" ack the book never honoured. Not a failure
            # until the window closes -- a dropped frame must not look like one.
            if entry.retry_at is None and (now - entry.sent_at) >= UNKNOWN_FAIL_AFTER_S:
                entry.reason = "no-ack"
                entry.retcode = None
                if entry.attempts >= MAX_ATTEMPTS:
                    out.escalations.append(self._escalation(entry))
                    del self._inflight[cid]
                else:
                    entry.attempts += 1
                    entry.sent_at = now
                    out.retries.append((entry.action, dict(entry.payload)))
```

Note the `continue` after the retry branch is required so a retry does not also fall into the unknown-window branch in the same tick.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker -v`
Expected: PASS — all tests OK

- [ ] **Step 5: Commit**

```bash
git add src/execution/command_tracker.py tests/unit/test_command_tracker.py
git commit -m "feat(exec): heartbeat-authoritative resolution and unknown path"
```

---

### Task 4: CommandTracker — the close-failure block

**Files:**
- Modify: `src/execution/command_tracker.py`
- Test: `tests/unit/test_command_tracker.py`

**Interfaces:**
- Consumes: `tick`, `_escalation` from Tasks 2–3.
- Produces: `CommandTracker.blocked_closes() -> dict[int, dict]` and `CommandTracker.is_entry_blocked() -> bool`. Task 7 calls `is_entry_blocked()`; Task 8 renders `blocked_closes()`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_command_tracker.py
class TestCloseFailureBlock(unittest.TestCase):
    def _exhaust_close(self, t, ticket=9, cid="x-1"):
        t.register(cid=cid, action="CLOSE_POS", ticket=ticket, symbol="ETHUSD",
                   expected={"remaining": None},
                   payload={"ticket": ticket, "cid": cid}, now=0.0)
        t.on_result(cid, ok=False, retcode=10018, err=0, comment="Market closed", now=0.0)
        return t.tick(now=0.0, positions=[{"t": ticket, "vol": 0.1}], orders=[])

    def test_failed_close_blocks_new_entries(self):
        t = make_tracker()
        out = self._exhaust_close(t)
        self.assertEqual(len(out.escalations), 1)
        self.assertTrue(t.is_entry_blocked())
        self.assertIn(9, t.blocked_closes())

    def test_failed_modify_does_not_block(self):
        """A failed MODIFY leaves the trade stopped, just not where intended.
        Only believing you are flat when you are not is worth halting for."""
        t = make_tracker()
        t.register(cid="m-1", action="MODIFY", ticket=7, symbol="EURUSD",
                   expected={"sl": 1.1, "tp": 1.2},
                   payload={"ticket": 7, "cid": "m-1"}, now=0.0)
        t.on_result("m-1", ok=False, retcode=10018, err=0, comment="", now=0.0)
        t.tick(now=0.0, positions=[{"t": 7, "sl": 1.0, "tp": 1.2}], orders=[])
        self.assertFalse(t.is_entry_blocked())

    def test_block_auto_clears_when_position_leaves_the_book(self):
        """It did close after all. A guard only a human can clear gets cleared
        reflexively, which is how fail-closed guards rot."""
        t = make_tracker()
        self._exhaust_close(t)
        self.assertTrue(t.is_entry_blocked())
        t.tick(now=60.0, positions=[], orders=[])
        self.assertFalse(t.is_entry_blocked())

    def test_block_persists_while_position_still_open(self):
        t = make_tracker()
        self._exhaust_close(t)
        t.tick(now=60.0, positions=[{"t": 9, "vol": 0.1}], orders=[])
        self.assertTrue(t.is_entry_blocked())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker.TestCloseFailureBlock -v`
Expected: FAIL — `AttributeError: 'CommandTracker' object has no attribute 'is_entry_blocked'`

- [ ] **Step 3: Write minimal implementation**

In `__init__` add `self._blocked_closes: dict[int, dict] = {}`. Add the two accessors:

```python
    def blocked_closes(self) -> dict:
        """ticket -> escalation dict for closes confirmed un-applied."""
        return dict(self._blocked_closes)

    def is_entry_blocked(self) -> bool:
        return bool(self._blocked_closes)
```

In `tick`, record on escalation of a close. Both escalation sites (the
`escalate_now` branch and the unknown-window branch) must call this, so factor it:

```python
    def _on_escalated(self, entry: InFlight, out: TickOutcome):
        esc = self._escalation(entry)
        out.escalations.append(esc)
        if entry.action == "CLOSE_POS":
            self._blocked_closes[entry.ticket] = esc
```

Replace both `out.escalations.append(self._escalation(entry))` calls with
`self._on_escalated(entry, out)`.

Then, at the **top of `tick`**, before the in-flight loop, auto-clear:

```python
        for ticket in list(self._blocked_closes):
            if _find_position(positions, ticket) is None:
                del self._blocked_closes[ticket]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_command_tracker -v`
Expected: PASS — all tests OK

- [ ] **Step 5: Commit**

```bash
git add src/execution/command_tracker.py tests/unit/test_command_tracker.py
git commit -m "feat(exec): close-failure entry block with heartbeat auto-clear"
```

---

### Task 5: Controller wiring — cid on dispatch, CMD_RESULT routing, main-loop tick

**Files:**
- Modify: `src/core/system_controller.py` — `__init__` (near line 110), `_dispatch_mgmt_command` (line 698), `cancel_pending_orders` (line 1276), `_process_incoming_data` (line 748), main loop section C (near line 438)
- Test: `tests/unit/test_controller_command_ack.py` (create)

**Interfaces:**
- Consumes: `CommandTracker`, `TickOutcome` from Tasks 1–4.
- Produces: `SystemController.command_tracker` attribute, `SystemController._next_cid() -> str`, and a `CMD_RESULT` branch in `_process_incoming_data`. Tasks 6–8 read `self.command_tracker`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_controller_command_ack.py
import unittest
from unittest.mock import AsyncMock
import asyncio

from src.core.system_controller import SystemController
from src.execution.command_tracker import CommandTracker


def bare_controller():
    """The five sibling controller test modules build fixtures this way: only
    the attributes the target method touches, bypassing __init__."""
    c = object.__new__(SystemController)
    c.command_tracker = CommandTracker()
    c._cid_seq = 0
    c.bridge = AsyncMock()
    c.logger = type("L", (), {"log_event": lambda *a, **k: None})()
    c.state_manager = type("S", (), {"get_order": lambda self, t: None})()
    c.telemetry = AsyncMock()
    c.current_open_positions = []
    c.current_pending_orders = []
    return c


class TestCidGeneration(unittest.TestCase):
    def test_cids_are_unique(self):
        c = bare_controller()
        self.assertNotEqual(c._next_cid(), c._next_cid())


class TestDispatchRegisters(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_registers_and_carries_cid(self):
        c = bare_controller()
        await c.cancel_pending_orders(555)
        self.assertEqual(c.command_tracker.in_flight_count(), 1)
        action, payload = c.bridge.send_command.call_args[0]
        self.assertEqual(action, "CANCEL")
        self.assertIn("cid", payload)

    async def test_modify_registers_expected_sl_tp(self):
        c = bare_controller()
        await c._dispatch_mgmt_command(
            {"action": "MODIFY", "ticket": 7, "symbol": "EURUSD",
             "sl": 1.1, "tp": 1.2, "comment": "Ratchet L1"})
        entry = c.command_tracker.peek(next(iter(
            c.command_tracker._inflight)))
        self.assertEqual(entry.expected, {"sl": 1.1, "tp": 1.2})

    async def test_partial_close_registers_remaining_volume(self):
        c = bare_controller()
        c.current_open_positions = [{"t": 9, "vol": 0.15}]
        await c._dispatch_mgmt_command(
            {"action": "CLOSE_PARTIAL", "ticket": 9, "volume": 0.05, "comment": ""})
        entry = c.command_tracker.peek(next(iter(c.command_tracker._inflight)))
        self.assertAlmostEqual(entry.expected["remaining"], 0.10)


class TestCmdResultRouting(unittest.IsolatedAsyncioTestCase):
    async def test_cmd_result_reaches_the_tracker(self):
        c = bare_controller()
        c.command_tracker.register(cid="c-1", action="CANCEL", ticket=555,
                                   symbol="EURUSD", expected={},
                                   payload={"ticket": 555}, now=0.0)
        await c._process_incoming_data({
            "type": "CMD_RESULT", "cid": "c-1", "action": "CANCEL",
            "ticket": 555, "ok": False, "retcode": 10018, "err": 0,
            "comment": "Market closed"})
        self.assertTrue(c.command_tracker.peek("c-1").escalate_now)

    async def test_uncorrelated_result_does_not_raise(self):
        c = bare_controller()
        await c._process_incoming_data({
            "type": "CMD_RESULT", "cid": "ghost", "ok": False,
            "retcode": 10018, "err": 0, "comment": ""})   # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_command_ack -v`
Expected: FAIL — `AttributeError: 'SystemController' object has no attribute '_next_cid'`

- [ ] **Step 3: Write minimal implementation**

In `__init__`, beside the other state near line 110:

```python
        from src.execution.command_tracker import CommandTracker
        self.command_tracker = CommandTracker()
        self._cid_seq = 0
```

Add the generator method:

```python
    def _next_cid(self) -> str:
        """Opaque, unique for the process lifetime. Never persisted or parsed;
        (ticket, action) alone is NOT enough -- the trade manager can have two
        ratchet MODIFYs in flight for one ticket."""
        self._cid_seq = getattr(self, '_cid_seq', 0) + 1
        return f"k{self._cid_seq}"
```

In `_dispatch_mgmt_command`, for each of the three branches, build the payload
with a `cid`, register, then send. MODIFY:

```python
        if action == "MODIFY":
            cid = self._next_cid()
            payload = {"cid": cid, "ticket": int(c['ticket']), "symbol": c.get('symbol', ''),
                       "sl": float(c.get('sl', 0.0)), "tp": float(c.get('tp', 0.0))}
            self.command_tracker.register(
                cid=cid, action="MODIFY", ticket=int(c['ticket']),
                symbol=c.get('symbol', ''),
                expected={"sl": payload["sl"], "tp": payload["tp"]},
                payload=payload, now=time.time())
            await self.bridge.send_command("MODIFY", payload)
```

CLOSE_PARTIAL — `remaining` is the live volume minus the amount being closed:

```python
        elif action == "CLOSE_PARTIAL":
            cid = self._next_cid()
            tkt = int(c['ticket'])
            live = next((p for p in self.current_open_positions
                         if int(p.get('t', 0)) == tkt), None)
            remaining = (float(live.get('vol', 0.0)) - float(c['volume'])) if live else None
            payload = {"cid": cid, "ticket": tkt, "volume": float(c['volume'])}
            self.command_tracker.register(
                cid=cid, action="CLOSE_POS", ticket=tkt, symbol=c.get('symbol', ''),
                expected={"remaining": remaining}, payload=payload, now=time.time())
            await self.bridge.send_command("CLOSE_POS", payload)
```

CLOSE_POS (full) registers `expected={"remaining": None}` and otherwise mirrors
the above. `cancel_pending_orders` registers with `action="CANCEL"`,
`expected={}`:

```python
    async def cancel_pending_orders(self, target_id='all'):
        pending = getattr(self, 'current_pending_orders', [])
        tickets = [int(o.get('t')) for o in pending] if target_id == 'all' else (
            [int(target_id)] if target_id else [])
        for tkt in tickets:
            cid = self._next_cid()
            payload = {"cid": cid, "ticket": tkt}
            self.command_tracker.register(
                cid=cid, action="CANCEL", ticket=tkt, symbol="",
                expected={}, payload=payload, now=time.time())
            await self.bridge.send_command("CANCEL", payload)
        return len(tickets)
```

> The return value still counts commands **sent**, not applied. That is now
> honest rather than misleading, because the tracker owns the real outcome.

In `_process_incoming_data`, add a branch beside the existing `msg_type` tests:

```python
        elif msg_type == 'CMD_RESULT':
            matched = self.command_tracker.on_result(
                msg.get('cid', ''), ok=bool(msg.get('ok', False)),
                retcode=msg.get('retcode', 0), err=msg.get('err', 0),
                comment=msg.get('comment', ''), now=time.time())
            if not matched:
                self.logger.log_event(
                    "WARN", "BRIDGE",
                    f"Uncorrelated CMD_RESULT cid={msg.get('cid','')!r} "
                    f"ticket={msg.get('ticket')} retcode={msg.get('retcode')}")
```

In the main loop, in **section C (Control & Telemetry)** — not the HEARTBEAT
branch — add after `await self.telemetry.poll_commands()`:

```python
                outcome = self.command_tracker.tick(
                    now_ts, self.current_open_positions,
                    getattr(self, 'current_pending_orders', []) or [])
                for retry_action, retry_payload in outcome.retries:
                    await self.bridge.send_command(retry_action, retry_payload)
                for esc in outcome.escalations:
                    await self._escalate_command_failure(esc)
```

`_escalate_command_failure` arrives in Task 6. For this task, add a temporary
stub so the loop runs:

```python
    async def _escalate_command_failure(self, esc):
        self.logger.log_event("MGMT", "CMD_ACK", f"command failed: {esc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_command_ack -v`
Expected: PASS

Then check nothing regressed in the five sibling fixtures:

Run: `.venv/bin/python -m unittest tests.unit.test_controller_routing tests.unit.test_strategy_timeframe tests.unit.test_controller_news_gate tests.unit.test_gui_server tests.unit.test_risk_manager_exposure_cap -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/system_controller.py tests/unit/test_controller_command_ack.py
git commit -m "feat(core): correlate management commands and route CMD_RESULT"
```

---

### Task 6: Escalation — CommandFailed event and Telegram

**Files:**
- Modify: `src/core/events.py` (append, following the `@_register` pattern)
- Modify: `src/core/system_controller.py` — replace the Task 5 stub
- Test: `tests/unit/test_controller_command_ack.py`

**Interfaces:**
- Consumes: escalation dicts from Task 2 (`cid`, `action`, `ticket`, `symbol`, `retcode`, `reason`, `attempts`, `comment`).
- Produces: `CommandFailed` event class; `SystemController._escalate_command_failure(esc)` in final form.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_controller_command_ack.py
from src.core.events import CommandFailed


class TestEscalation(unittest.IsolatedAsyncioTestCase):
    def _controller(self):
        c = bare_controller()
        c.published = []
        c._publish = c.published.append
        return c

    async def test_publishes_a_command_failed_event(self):
        c = self._controller()
        await c._escalate_command_failure({
            "cid": "c-1", "action": "CANCEL", "ticket": 555, "symbol": "EURUSD",
            "retcode": 10018, "reason": "reject", "attempts": 1,
            "comment": "Market closed"})
        self.assertEqual(len(c.published), 1)
        evt = c.published[0]
        self.assertIsInstance(evt, CommandFailed)
        self.assertEqual(evt.ticket, 555)
        self.assertEqual(evt.retcode, 10018)

    async def test_telegrams_the_operator_naming_the_reason(self):
        c = self._controller()
        await c._escalate_command_failure({
            "cid": "c-1", "action": "CANCEL", "ticket": 555, "symbol": "EURUSD",
            "retcode": 10018, "reason": "reject", "attempts": 1,
            "comment": "Market closed"})
        text = c.telemetry.send_message.call_args[0][0]
        self.assertIn("CANCEL", text)
        self.assertIn("555", text)
        self.assertIn("10018", text)

    async def test_no_ack_failure_reads_differently_from_a_broker_reject(self):
        c = self._controller()
        await c._escalate_command_failure({
            "cid": "c-1", "action": "CANCEL", "ticket": 555, "symbol": "EURUSD",
            "retcode": None, "reason": "no-ack", "attempts": 3, "comment": ""})
        text = c.telemetry.send_message.call_args[0][0]
        self.assertIn("no reply", text.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_command_ack.TestEscalation -v`
Expected: FAIL — `ImportError: cannot import name 'CommandFailed'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/core/events.py`:

```python
@_register
@dataclass(frozen=True)
class CommandFailed(Event):
    """A management command confirmed un-applied after retries (CMD-ACK)."""
    name: ClassVar[str] = "CommandFailed"
    action: str = ""       # CANCEL | MODIFY | CLOSE_POS
    ticket: int = 0
    symbol: str = ""
    retcode: Optional[int] = None   # None when the EA never replied
    reason: str = ""       # "reject" | "no-ack"
    attempts: int = 0
    detail: str = ""       # the EA's comment
```

Replace the Task 5 stub in `system_controller.py`:

```python
    async def _escalate_command_failure(self, esc):
        """A management command is confirmed un-applied. Tell the operator.

        Silence here is what made the 2026-08-02 cancel invisible: the API said
        ok, the order stayed resting, and nothing recorded a failure anywhere.
        """
        self._publish(CommandFailed(
            action=esc["action"], ticket=esc["ticket"], symbol=esc.get("symbol", ""),
            retcode=esc.get("retcode"), reason=esc.get("reason", ""),
            attempts=esc.get("attempts", 0), detail=esc.get("comment", "")))
        self.logger.log_event("MGMT", "CMD_ACK",
                              f"{esc['action']} #{esc['ticket']} failed: {esc}")
        if esc.get("reason") == "no-ack":
            why = ("the EA sent **no reply** and the book never changed "
                   "(retcode unavailable)")
        else:
            why = f"broker rejected it with retcode `{esc.get('retcode')}`"
        detail = f"\n`{esc['comment']}`" if esc.get("comment") else ""
        blocked = ("\n\n🛑 **New entries are blocked** until this position "
                   "closes or clears." if esc["action"] == "CLOSE_POS" else "")
        await self.telemetry.send_message(
            f"⚠️ **Command not applied**\n`{esc['action']}` on ticket "
            f"`#{esc['ticket']}` {esc.get('symbol','')} did not take effect after "
            f"{esc.get('attempts', 0)} attempt(s) — {why}.{detail}{blocked}",
            parse_mode="Markdown")
```

Add `CommandFailed` to the existing events import at the top of
`system_controller.py`, and `Optional` to the `typing` import in `events.py` if
it is not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_command_ack -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/events.py src/core/system_controller.py tests/unit/test_controller_command_ack.py
git commit -m "feat(core): escalate un-applied commands to Telegram and the bus"
```

---

### Task 7: Block new entries on a failed close

**Files:**
- Modify: `src/core/system_controller.py` — `_execute_signal`, immediately after the `check_total_risk` block (near line 591)
- Test: `tests/unit/test_controller_command_ack.py`

**Interfaces:**
- Consumes: `CommandTracker.is_entry_blocked()`, `blocked_closes()` from Task 4.
- Produces: no new names.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_controller_command_ack.py
class TestEntryBlock(unittest.IsolatedAsyncioTestCase):
    async def test_failed_close_stops_new_entries(self):
        """Believing you are flat when you are not is the dangerous case, so
        this fails closed the same way the portfolio risk cap does."""
        c = bare_controller()
        c.command_tracker._blocked_closes = {
            9: {"action": "CLOSE_POS", "ticket": 9, "symbol": "ETHUSD",
                "retcode": 10018, "reason": "reject", "attempts": 1, "comment": ""}}
        self.assertTrue(c.command_tracker.is_entry_blocked())
        self.assertTrue(c._entry_blocked_by_close_failure())

    async def test_clean_tracker_does_not_block(self):
        c = bare_controller()
        self.assertFalse(c._entry_blocked_by_close_failure())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_command_ack.TestEntryBlock -v`
Expected: FAIL — `AttributeError: ... has no attribute '_entry_blocked_by_close_failure'`

- [ ] **Step 3: Write minimal implementation**

```python
    def _entry_blocked_by_close_failure(self) -> bool:
        tracker = getattr(self, 'command_tracker', None)
        return bool(tracker is not None and tracker.is_entry_blocked())
```

In `_execute_signal`, directly after the `if not allowed:` exposure-cap block
and before the `payload = {...}` construction:

```python
        if self._entry_blocked_by_close_failure():
            stuck = ", ".join(f"#{t}" for t in self.command_tracker.blocked_closes())
            self.logger.log_event("RISK", "CMD_ACK",
                                  f"Block {symbol}: close never applied ({stuck})")
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_command_ack -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/system_controller.py tests/unit/test_controller_command_ack.py
git commit -m "feat(risk): block new entries while a close is confirmed un-applied"
```

---

### Task 8: Expose command state in the GUI snapshot

**Files:**
- Modify: `src/ops/web/state_view.py` — `build_snapshot`, plus a `_commands_block` helper
- Modify: `frontend/src/lib/types.ts`
- Test: `tests/unit/test_gui_pending_and_risk.py`

**Interfaces:**
- Consumes: `CommandTracker.in_flight_count()`, `blocked_closes()`.
- Produces: snapshot key `commands: {"in_flight": int, "blocked_closes": [...]}`; TypeScript `CommandsBlock`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_gui_pending_and_risk.py
class TestCommandsBlock(unittest.TestCase):
    def test_reports_in_flight_and_blocked_closes(self):
        from src.execution.command_tracker import CommandTracker
        c = FakeController()
        c.command_tracker = CommandTracker()
        c.command_tracker.register(cid="c-1", action="CANCEL", ticket=555,
                                   symbol="EURUSD", expected={},
                                   payload={"ticket": 555}, now=0.0)
        c.command_tracker._blocked_closes = {
            9: {"action": "CLOSE_POS", "ticket": 9, "symbol": "ETHUSD",
                "retcode": 10018, "reason": "reject", "attempts": 1, "comment": ""}}
        block = build_snapshot(c)["commands"]
        self.assertEqual(block["in_flight"], 1)
        self.assertEqual(len(block["blocked_closes"]), 1)
        self.assertEqual(block["blocked_closes"][0]["ticket"], 9)

    def test_controller_without_a_tracker_degrades(self):
        block = build_snapshot(FakeController())["commands"]   # must not raise
        self.assertEqual(block["in_flight"], 0)
        self.assertEqual(block["blocked_closes"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_pending_and_risk.TestCommandsBlock -v`
Expected: FAIL — `KeyError: 'commands'`

- [ ] **Step 3: Write minimal implementation**

In `state_view.py`, add `"commands": _commands_block(controller),` to the
`build_snapshot` return dict, and:

```python
def _commands_block(controller) -> dict:
    """In-flight management commands and any close confirmed un-applied.

    A blocked close halts new entries, so it must be visible here for the same
    reason the risk blocker is: an unexplained trading stop is indistinguishable
    from a quiet market.
    """
    try:
        tracker = getattr(controller, "command_tracker", None)
        if tracker is None:
            return {"in_flight": 0, "blocked_closes": []}
        return {"in_flight": tracker.in_flight_count(),
                "blocked_closes": list(tracker.blocked_closes().values())}
    except Exception:
        return {"in_flight": 0, "blocked_closes": []}
```

In `frontend/src/lib/types.ts`, add and wire into `Snapshot` as optional:

```typescript
export interface BlockedClose {
  action: string; ticket: number; symbol: string;
  retcode: number | null; reason: string; attempts: number; comment: string;
}
export interface CommandsBlock {
  in_flight: number;
  /** Non-empty means new entries are halted until these clear. */
  blocked_closes: BlockedClose[];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_pending_and_risk -v`
Expected: PASS

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/state_view.py frontend/src/lib/types.ts tests/unit/test_gui_pending_and_risk.py
git commit -m "feat(gui): expose in-flight commands and blocked closes in the snapshot"
```

---

### Task 9: EA — report every management-command outcome

**Files:**
- Modify: `mql5_bridge/Experts/Titan_Gateway.mq5` — add `ReportCmdResult` near the other helpers; rewrite the MODIFY (line ~299), CANCEL (line ~317) and CLOSE_POS (line ~326) branches of `HandleCommand`
- Test: none automated — MQL5 is not unit-testable here. Verification is the live smoke test in Step 4.

**Interfaces:**
- Consumes: the `cid` field added to outbound payloads in Task 5.
- Produces: `CMD_RESULT` frames matching §4.2 of the spec.

- [ ] **Step 1: Add the shared reporter**

Place immediately above `HandleCommand`. One helper on purpose: these three
branches have already drifted apart once, and per-branch reporting code would
let them drift again.

```mql5
void ReportCmdResult(string cid, string action, long ticket, bool ok,
                     int retcode, int err, string comment) {
   StringReplace(comment, "\"", "'");   // keep the JSON parseable
   string json = StringFormat(
      "{\"type\":\"CMD_RESULT\",\"cid\":\"%s\",\"action\":\"%s\",\"ticket\":%I64d,"
      "\"ok\":%s,\"retcode\":%d,\"err\":%d,\"comment\":\"%s\"}",
      cid, action, ticket, ok ? "true" : "false", retcode, err, comment);
   socket_push.Send(json);
}
```

- [ ] **Step 2: Rewrite the three branches**

```mql5
   if(StringFind(json, "\"action\":\"MODIFY\"") >= 0) {
      string cid = GetJSONString(json, "cid");
      MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
      req.action   = TRADE_ACTION_SLTP;
      req.position = (ulong)GetJSONLong(json, "ticket");
      req.symbol   = GetJSONString(json, "symbol");
      req.sl       = GetJSONDouble(json, "sl");
      req.tp       = GetJSONDouble(json, "tp");
      bool sent = OrderSend(req, res);
      int  err  = sent ? 0 : GetLastError();
      bool ok   = sent && (res.retcode == TRADE_RETCODE_DONE ||
                           res.retcode == TRADE_RETCODE_PLACED);
      if(!ok) Print("TITAN | Modify Failed: retcode=", res.retcode, " err=", err,
                    " ", res.comment);
      ReportCmdResult(cid, "MODIFY", (long)req.position, ok, (int)res.retcode,
                      err, res.comment);
      return;
   }

   if(StringFind(json, "\"action\":\"CANCEL\"") >= 0) {
      string cid = GetJSONString(json, "cid");
      ulong t_id = (ulong)GetJSONLong(json, "ticket");
      MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
      req.action = TRADE_ACTION_REMOVE;
      req.order  = t_id;
      bool sent = OrderSend(req, res);
      int  err  = sent ? 0 : GetLastError();
      bool ok   = sent && (res.retcode == TRADE_RETCODE_DONE ||
                           res.retcode == TRADE_RETCODE_PLACED);
      if(!ok) Print("TITAN | Cancel Failed: retcode=", res.retcode, " err=", err,
                    " ", res.comment);
      ReportCmdResult(cid, "CANCEL", (long)t_id, ok, (int)res.retcode, err,
                      res.comment);
      return;
   }

   if(StringFind(json, "\"action\":\"CLOSE_POS\"") >= 0) {
      string cid = GetJSONString(json, "cid");
      long t_id = GetJSONLong(json, "ticket");
      if(!PositionSelectByTicket((ulong)t_id)) {
         // Already gone. Report success: Python's heartbeat check agrees, and
         // reporting failure here would halt entries for a closed position.
         ReportCmdResult(cid, "CLOSE_POS", t_id, true, 0, 0, "position not found");
         return;
      }
      MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
      string sym = PositionGetString(POSITION_SYMBOL);
      req.action   = TRADE_ACTION_DEAL;
      req.position = (ulong)t_id;
      req.symbol   = sym;
      req.volume   = PositionGetDouble(POSITION_VOLUME);
      double vol_req = GetJSONDouble(json, "volume");
      if(vol_req > 0 && vol_req < req.volume) req.volume = vol_req;
      req.type  = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY) ?
                  ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.price = (req.type==ORDER_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_ASK)
                                             : SymbolInfoDouble(sym, SYMBOL_BID);
      req.type_filling = GetFillingMode(sym);
      bool sent = OrderSend(req, res);
      int  err  = sent ? 0 : GetLastError();
      bool ok   = sent && (res.retcode == TRADE_RETCODE_DONE ||
                           res.retcode == TRADE_RETCODE_PLACED);
      if(!ok) Print("TITAN | Close Failed: retcode=", res.retcode, " err=", err,
                    " ", res.comment);
      ReportCmdResult(cid, "CLOSE_POS", t_id, ok, (int)res.retcode, err, res.comment);
      return;
   }
```

- [ ] **Step 3: Recompile on Windows**

Open `Titan_Gateway.mq5` in MetaEditor on the Windows side and press F7.
Expected: `0 errors, 0 warnings`. Then remove and re-attach the EA to its chart.

> Do this with **no orders in flight**. Reattaching drops the ZMQ connection,
> and this codebase has prior form with a wedged REP socket on reattach.

- [ ] **Step 4: Live smoke test**

With `main.py` running, send a cancel for a ticket that does not exist. It is
non-destructive and exercises the whole path.

```bash
T=$(grep '^TITAN_GUI_TOKEN' .env | cut -d= -f2- | tr -d '"'"'"' \r')
curl -s -X POST -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"command":"cancel","ticket":999999999}' http://127.0.0.1:8770/api/command
sleep 20
grep CMD_ACK data/logs/titan_system.log | tail -3
```

Expected: a `CMD_ACK` line naming a terminal retcode, and a Telegram message.
Expected NOT to see: silence, or an entry block (this is a CANCEL, not a close).

- [ ] **Step 5: Commit**

```bash
git add mql5_bridge/Experts/Titan_Gateway.mq5
git commit -m "feat(ea): report every management-command outcome as CMD_RESULT"
```

---

### Task 10: Full-suite verification

**Files:** none modified.

- [ ] **Step 1: Check for competing load first**

```bash
ps -eo pid,cmd | grep 'unittest discover' | grep -v grep
uptime
```

A concurrent suite from another session roughly doubles wall-clock and can make
a passing test time out. If one is running, wait for it — a timeout here is an
artifact, not a failure.

- [ ] **Step 2: Run the Python suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: `OK`, with the baseline count plus roughly 35 new tests.

- [ ] **Step 3: Run the frontend suite and typecheck**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc exit 0; vitest all pass.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test: full-suite green for the EA command-ack work"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §4.1 outbound `cid` | 5 |
| §4.2 `CMD_RESULT` frame | 9 (EA), 5 (routing) |
| §5 EA helper, retcode capture, `"action":"..."` match, `return` | 9 |
| §6.1 pure tracker | 1–4 |
| §6.2 classification, backoff, 3 attempts | 1, 2 |
| §6.3 unknown path, `ok`-ack-still-verified | 3 |
| §6.4 dispatch/routing/main-loop tick | 5 |
| §6.5 Telegram, bus event, snapshot block | 6, 8 |
| §6.6 close-failure block + auto-clear | 4, 7 |
| §7 testing incl. the five `object.__new__` modules | 5 (Step 4), 10 |
| §8 rollout ordering (Python first, EA last) | task order 1–8 then 9 |

No gaps.

**Placeholder scan:** none — every code step contains runnable code.

**Type consistency:** `register(cid, action, ticket, symbol, expected, payload, now)` is used identically in Tasks 1, 3, 4, 5, 8. `TickOutcome.retries` is `[(action, payload)]` in Tasks 2, 3 and consumed as a 2-tuple in Task 5. `expected` keys are `{"sl","tp"}` for MODIFY and `{"remaining"}` for CLOSE_POS throughout; CANCEL uses `{}`. `blocked_closes()` returns `dict[int, dict]` in Task 4 and is consumed as `.values()` in Task 8 and as keys in Task 7 — consistent.
