# Titan Control GUI — Backend API Implementation Plan, v15 Edition (Phase 1a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embedded FastAPI + WebSocket control API inside the running controller — live cockpit snapshot, EventBus-fed event feed, registry lifecycle actions with the promote-gate intact, tiered settings edits, and the four hardening features (tape-journaled GUI actions, WS first-frame auth, auth-failure throttling, read-only mode).

**Architecture:** A second asyncio task in `SystemController` serves FastAPI on `:8770` (ops health probe stays on `:8787`). The feed is a `BusBridge`: one `bus.subscribe_all()` subscriber projecting events into a ring buffer + per-client WS queues — the GUI sees exactly what the golden tape journals. Registry/commands/settings routes call ONLY existing controller methods; every accepted mutation publishes a new `GuiActionExecuted` event to the bus.

**Tech Stack:** Python 3.10+, FastAPI + uvicorn (NEW deps — installed in Task 3), PyYAML (present), stdlib `unittest`, `fastapi.testclient.TestClient` (uses installed httpx).

**Spec:** `docs/superpowers/specs/2026-07-14-control-gui-phase1-v15-design.md`

## Global Constraints

- Work on a NEW branch `feat/control-gui-backend` created from `feat/trade-mgmt-pipeline` HEAD. Never merge to `main`; no git remote — never push.
- Tests: stdlib `unittest` only. Full-suite command: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` (baseline **337 OK**, ~8–13 min — run once at Task 10, not per task; per-task runs use the module test). Use `asyncio.run(...)` in tests, never `get_event_loop()`.
- The GUI is optional infrastructure: web-layer failure → log warning, keep trading. No new ZMQ socket. No new trade-path logic — command/registry routes call existing controller methods only.
- All web modules live in `src/ops/web/`, unit-tested against fakes; they must never import or start the bridge.
- FROZEN, never modify: `scripts/capture_parity_golden.py`, `tests/backtest/fixtures/*`, `tests/unit/test_signal_parity.py`.
- NEVER stage (user's parallel in-flight work): `mql5_bridge/Experts/Titan_Gateway.mq5`, `data/specs.json`, `scripts/check_bridge.py`, `tests/unit/test_check_bridge_ip.py`.
- Env vars: `TITAN_GUI_TOKEN` (auth, fail-closed), `TITAN_GUI_BIND` (default `127.0.0.1`), `TITAN_GUI_READONLY` (`"1"` → mutating routes 403). Port: **8770** (constant).
- Safe-subset live-apply allowlist (exact dotted keys — note throttle keys live under `risk.`):
  `signal_grading.enabled`, `signal_grading.min_grade`, `risk.trade.risk_per_trade_pct`,
  `risk.account.max_daily_drawdown_pct`, `risk.account.max_global_exposure_pct`,
  `risk.drawdown_throttle.enabled`, `risk.drawdown_throttle.trigger_dd_pct`,
  `risk.drawdown_throttle.factor`, `trade_management.runner.enabled`,
  `trade_management.runner.tighten_on_giveback`, `trade_management.runner.giveback_frac`,
  `trade_management.runner.tight_trail_frac`.
  There is NO `strategies.<name>.enabled` key — the registry owns lifecycle.
- The `arbiter.*` and `ops.*` blocks are restart-tier, always.
- Verbatim interfaces this plan builds against (verified 2026-07-14):
  - `EventBus.subscribe_all(handler, name=None)` (`src/core/bus.py:47`); sync-handler exceptions circuit-break after 5 consecutive failures; `publish(event)` is sync.
  - `Event.to_dict()` returns `{...fields, "evt": <name>}` (`src/core/events.py:21`); new event types = `@_register` + `@dataclass(frozen=True)` + `name: ClassVar[str]` in `src/core/events.py`.
  - Controller: `enable_strategy(sid, allow_research=False)` (:873), `disable_strategy(sid)` (:878), `set_system_pause(p)` (:859), `async close_specific_market_order(ticket_id)` (:908), `async close_all_market_orders()` (:899), `async trigger_panic()` (:892), `async cancel_pending_orders(target_id='all')` (:915), `_publish(event)` guard (:165), `_load_config` (:158), attrs `current_open_positions` / `last_heartbeat_time` / `is_manual_pause` / `registry` / `arbiter` / `signal_grader` / `risk_manager` / `state_manager`.
  - `StrategyRegistry.report() -> list[dict]` with keys `id, version, family, tf, status, state, priority` (:158); promote-gate = `enable(sid, allow_research=True)`.
  - `Arbiter.stats() -> {"submitted", "approved", "blocked_by"}` (:125).
  - `RiskManager.throttle_factor() -> float` reads `self.config['risk']['drawdown_throttle']` fresh per call (`src/risk/risk_manager.py:201`); `RiskManager` holds the SAME config dict object the controller loads, so in-place nested updates are live.
  - `StateManager.get_order(ticket) -> dict|None` incl. `grade`, `strategy` (:143); `conn` has a dict-capable row factory.
  - HEARTBEAT position keys: `t, s, p, sl, tp, pf, vol, type (0=BUY else SELL), comment`.
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## File Structure

- `src/ops/web/__init__.py` — package marker (Task 1).
- `src/ops/web/config_layer.py` — `deep_merge` + `load_layered_config` (Task 1).
- `src/ops/web/settings.py` — `SettingsStore` (Task 2).
- `src/ops/web/auth.py` — token check, `AuthThrottle`, read-only guard (Task 3).
- `src/core/events.py` — MODIFY: add `GuiActionExecuted` (Task 4).
- `src/ops/web/bus_bridge.py` — `project()` + `BusBridge` (Task 4).
- `src/ops/web/state_view.py` — `build_snapshot` + `history_rows` (Task 5).
- `src/ops/web/commands.py` — `execute_command` confirm-gated (Task 6).
- `src/ops/web/registry_view.py` — `registry_report` + `execute_registry_action` (Task 7).
- `src/ops/web/server.py` — `create_app` + `start` (Task 8).
- `src/core/system_controller.py` — MODIFY: layered config, `apply_runtime_setting`, web-task start (Task 9).
- Housekeeping: `requirements.txt`, `.env.example`, `.gitignore` (Tasks 3, 9).
- `tests/unit/test_gui_<module>.py` — one per module.

---

### Task 0: Branch

- [ ] `git checkout -b feat/control-gui-backend` from `feat/trade-mgmt-pipeline` HEAD. No commit.

---

### Task 1: Layered config loading

**Files:**
- Create: `src/ops/web/__init__.py` (empty), `src/ops/web/config_layer.py`
- Test: `tests/unit/test_gui_config_layer.py`

**Interfaces:**
- Produces: `deep_merge(base: dict, override: dict) -> dict` (new dict; nested dicts merge recursively; scalars/lists replace; `base` never mutated). `load_layered_config(defaults_path, overrides_path) -> dict` (missing/empty overrides file → defaults unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_config_layer.py
import unittest
import tempfile
from pathlib import Path
from src.ops.web.config_layer import deep_merge, load_layered_config


class TestDeepMerge(unittest.TestCase):
    def test_nested_override_wins_and_defaults_survive(self):
        base = {"risk": {"trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0}},
                "signal_grading": {"min_grade": "B"}}
        override = {"risk": {"trade": {"risk_per_trade_pct": 0.5}}}
        merged = deep_merge(base, override)
        self.assertEqual(merged["risk"]["trade"]["risk_per_trade_pct"], 0.5)
        self.assertEqual(merged["risk"]["trade"]["hard_max_lots"], 5.0)
        self.assertEqual(merged["signal_grading"]["min_grade"], "B")
        self.assertEqual(base["risk"]["trade"]["risk_per_trade_pct"], 1.0)  # base unmutated

    def test_list_value_is_replaced_not_merged(self):
        merged = deep_merge({"pairs": ["A", "B"]}, {"pairs": ["C"]})
        self.assertEqual(merged["pairs"], ["C"])


class TestLoadLayered(unittest.TestCase):
    def test_missing_overrides_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            defaults = Path(d) / "config.yaml"
            defaults.write_text("signal_grading:\n  min_grade: B\n")
            cfg = load_layered_config(defaults, Path(d) / "overrides.yaml")
            self.assertEqual(cfg["signal_grading"]["min_grade"], "B")

    def test_overrides_applied_on_top(self):
        with tempfile.TemporaryDirectory() as d:
            defaults = Path(d) / "config.yaml"
            defaults.write_text("signal_grading:\n  min_grade: B\n  enabled: true\n")
            overrides = Path(d) / "overrides.yaml"
            overrides.write_text("signal_grading:\n  min_grade: A\n")
            cfg = load_layered_config(defaults, overrides)
            self.assertEqual(cfg["signal_grading"]["min_grade"], "A")
            self.assertTrue(cfg["signal_grading"]["enabled"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m unittest tests.unit.test_gui_config_layer -v` → `ModuleNotFoundError: No module named 'src.ops.web'`

- [ ] **Step 3: Implement**

```python
# src/ops/web/__init__.py
```

```python
# src/ops/web/config_layer.py
"""Layered config: checked-in defaults deep-merged with GUI-written overrides."""
import copy
from pathlib import Path

import yaml


def deep_merge(base: dict, override: dict) -> dict:
    """New dict: override wins key-by-key; nested dicts merge; lists/scalars replace."""
    result = copy.deepcopy(base)
    for key, ovr_val in override.items():
        base_val = result.get(key)
        if isinstance(base_val, dict) and isinstance(ovr_val, dict):
            result[key] = deep_merge(base_val, ovr_val)
        else:
            result[key] = copy.deepcopy(ovr_val)
    return result


def load_layered_config(defaults_path: Path, overrides_path: Path) -> dict:
    with open(defaults_path, "r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}
    overrides = {}
    if Path(overrides_path).exists():
        with open(overrides_path, "r", encoding="utf-8") as f:
            overrides = yaml.safe_load(f) or {}
    return deep_merge(defaults, overrides)
```

- [ ] **Step 4: Run to verify PASS** (4 tests)
- [ ] **Step 5: Commit** — `feat(gui): layered config loader (defaults + overrides deep-merge)` (+trailer)

---

### Task 2: SettingsStore (v15 allowlist, validation, tiers, persistence)

**Files:**
- Create: `src/ops/web/settings.py`
- Test: `tests/unit/test_gui_settings.py`

**Interfaces:**
- Consumes: `deep_merge` (Task 1).
- Produces: `SettingsStore(defaults: dict, overrides_path: Path)` with `.is_safe(key)->bool`, `.validate(key, value)->str|None`, `.effective()->dict`, `.describe()->list[{"key","value","source","tier"}]`, `.set(key, value)->{"applied","restart_required","value"}` (raises `ValueError` on invalid; writes nothing on failure).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_settings.py
import unittest
import tempfile
from pathlib import Path
import yaml
from src.ops.web.settings import SettingsStore

DEFAULTS = {
    "signal_grading": {"enabled": True, "min_grade": "B"},
    "risk": {"trade": {"risk_per_trade_pct": 1.0},
             "account": {"max_daily_drawdown_pct": 3.0, "max_global_exposure_pct": 6.0},
             "drawdown_throttle": {"enabled": False, "trigger_dd_pct": 2.0, "factor": 0.5}},
    "trade_management": {"runner": {"enabled": False, "tighten_on_giveback": False,
                                    "giveback_frac": 0.75, "tight_trail_frac": 0.10}},
    "arbiter": {"max_total_positions": 6},
    "connection": {"zeromq": {"push_port": 32768}},
}


def _store(tmp):
    return SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")


class TestSafeSubset(unittest.TestCase):
    def test_whitelisted_keys_are_safe(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            for key in ("signal_grading.min_grade", "risk.trade.risk_per_trade_pct",
                        "risk.drawdown_throttle.enabled",
                        "risk.drawdown_throttle.trigger_dd_pct",
                        "risk.drawdown_throttle.factor",
                        "trade_management.runner.tight_trail_frac"):
                self.assertTrue(s.is_safe(key), key)

    def test_restart_tier_keys_are_not_safe(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            for key in ("connection.zeromq.push_port", "arbiter.max_total_positions",
                        "strategies.silver_bullet.enabled"):   # registry owns lifecycle
                self.assertFalse(s.is_safe(key), key)


class TestValidate(unittest.TestCase):
    def test_min_grade_enum(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("signal_grading.min_grade", "A"))
            self.assertIsNotNone(s.validate("signal_grading.min_grade", "Z"))

    def test_throttle_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("risk.drawdown_throttle.trigger_dd_pct", 2.5))
            self.assertIsNotNone(s.validate("risk.drawdown_throttle.trigger_dd_pct", 0))
            self.assertIsNone(s.validate("risk.drawdown_throttle.factor", 0.5))
            self.assertIsNotNone(s.validate("risk.drawdown_throttle.factor", 1.5))
            self.assertIsNotNone(s.validate("risk.drawdown_throttle.enabled", "yes"))

    def test_risk_pct_bounds_and_bools(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("risk.trade.risk_per_trade_pct", 0.5))
            self.assertIsNotNone(s.validate("risk.trade.risk_per_trade_pct", 0))
            self.assertIsNotNone(s.validate("risk.trade.risk_per_trade_pct", 999))
            self.assertIsNotNone(s.validate("signal_grading.enabled", "yes"))


class TestSetAndDescribe(unittest.TestCase):
    def test_set_safe_key_applies_live_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            res = s.set("risk.drawdown_throttle.enabled", True)
            self.assertEqual(res["applied"], "live")
            self.assertFalse(res["restart_required"])
            written = yaml.safe_load((Path(d) / "overrides.yaml").read_text())
            self.assertTrue(written["risk"]["drawdown_throttle"]["enabled"])

    def test_set_restart_key_flags_restart(self):
        with tempfile.TemporaryDirectory() as d:
            res = _store(d).set("connection.zeromq.push_port", 40000)
            self.assertEqual(res["applied"], "on_restart")
            self.assertTrue(res["restart_required"])

    def test_set_invalid_raises_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            with self.assertRaises(ValueError):
                s.set("signal_grading.min_grade", "Z")
            self.assertFalse((Path(d) / "overrides.yaml").exists())

    def test_describe_tags_source_and_tier(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            s.set("signal_grading.min_grade", "A")
            rows = {r["key"]: r for r in s.describe()}
            self.assertEqual(rows["signal_grading.min_grade"]["source"], "override")
            self.assertEqual(rows["signal_grading.min_grade"]["tier"], "live")
            self.assertEqual(rows["signal_grading.enabled"]["source"], "default")
            self.assertEqual(rows["arbiter.max_total_positions"]["tier"], "restart")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/ops/web/settings.py
"""Layered-config store: tagged effective view, validation, override persistence.

The safe-subset allowlist is the safety boundary — only these keys may ever be
applied to a running bot. Everything else is saved and flagged restart-required.
Strategy lifecycle is NOT here: the registry owns enable/disable/promote.
"""
import copy
import re
from pathlib import Path

import yaml

from .config_layer import deep_merge

_SAFE_PATTERNS = [
    r"signal_grading\.enabled",
    r"signal_grading\.min_grade",
    r"risk\.trade\.risk_per_trade_pct",
    r"risk\.account\.max_daily_drawdown_pct",
    r"risk\.account\.max_global_exposure_pct",
    r"risk\.drawdown_throttle\.enabled",
    r"risk\.drawdown_throttle\.trigger_dd_pct",
    r"risk\.drawdown_throttle\.factor",
    r"trade_management\.runner\.enabled",
    r"trade_management\.runner\.tighten_on_giveback",
    r"trade_management\.runner\.giveback_frac",
    r"trade_management\.runner\.tight_trail_frac",
]
_SAFE_RE = [re.compile(f"^{p}$") for p in _SAFE_PATTERNS]

_VALID_GRADES = {"A++", "A+", "A", "B", "C"}
_BOOL_KEYS = (".enabled", ".tighten_on_giveback")
_FRAC_KEYS = (".giveback_frac", ".tight_trail_frac", ".factor")


class SettingsStore:
    def __init__(self, defaults: dict, overrides_path: Path):
        self._defaults = copy.deepcopy(defaults)
        self._overrides_path = Path(overrides_path)
        self._overrides = {}
        if self._overrides_path.exists():
            self._overrides = yaml.safe_load(self._overrides_path.read_text()) or {}

    def is_safe(self, key: str) -> bool:
        return any(rx.match(key) for rx in _SAFE_RE)

    def validate(self, key: str, value):
        if key == "signal_grading.min_grade":
            return None if value in _VALID_GRADES else f"min_grade must be one of {sorted(_VALID_GRADES)}"
        if key.endswith(_BOOL_KEYS):
            return None if isinstance(value, bool) else "must be a boolean"
        if key.endswith(_FRAC_KEYS):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 <= value <= 1 else "must be in [0, 1]"
        if key.endswith("risk_per_trade_pct"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 < value <= 10 else "risk_per_trade_pct must be in (0, 10]"
        if key.endswith("_pct"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 < value <= 100 else "percent must be in (0, 100]"
        return None  # restart-tier keys: saved as-is

    def effective(self) -> dict:
        return deep_merge(self._defaults, self._overrides)

    def describe(self) -> list:
        rows = []
        for key, value in _flatten(self.effective()):
            rows.append({"key": key, "value": value,
                         "source": "override" if _has_key(self._overrides, key) else "default",
                         "tier": "live" if self.is_safe(key) else "restart"})
        return rows

    def set(self, key: str, value) -> dict:
        err = self.validate(key, value)
        if err:
            raise ValueError(err)
        _set_key(self._overrides, key, value)
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self._overrides_path.write_text(yaml.safe_dump(self._overrides, sort_keys=False))
        safe = self.is_safe(key)
        return {"applied": "live" if safe else "on_restart",
                "restart_required": not safe, "value": value}


def _flatten(d: dict, prefix: str = ""):
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _flatten(v, key)
        else:
            yield key, v


def _has_key(d: dict, dotted: str) -> bool:
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _set_key(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
```

- [ ] **Step 4: Run to verify PASS** (9 tests)
- [ ] **Step 5: Commit** — `feat(gui): SettingsStore — v15 safe-subset (throttle live, arbiter restart), validation, overrides` (+trailer)

---

### Task 3: Auth — token, failure throttling, read-only guard (+ install deps)

**Files:**
- Create: `src/ops/web/auth.py`
- Modify: `requirements.txt`
- Test: `tests/unit/test_gui_auth.py`

**Interfaces:**
- Produces: `token_ok(supplied)->bool` (constant-time, fail-closed on unset env); `require_token(request)->None` (FastAPI dependency: 429 if IP throttled, 401 on bad token — and records the failure); `require_writable()->None` (403 when `TITAN_GUI_READONLY=="1"`); `AuthThrottle(limit=5, window_s=60.0)` with `.blocked(ip)->bool` / `.record_failure(ip)` and a module-level instance `THROTTLE`.

- [ ] **Step 0: Install deps + requirements.txt**

```bash
.venv/bin/python -m pip install 'fastapi>=0.115,<1.0' 'uvicorn>=0.30,<1.0'
```

Append to `requirements.txt`:

```
# Control GUI API (embedded FastAPI server)
fastapi>=0.115,<1.0
uvicorn>=0.30,<1.0
```

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_auth.py
import unittest
import os
from fastapi import HTTPException
from src.ops.web import auth


class _Req:
    """Minimal stand-in for fastapi.Request in dependency-level tests."""
    def __init__(self, token=None, ip="1.2.3.4"):
        self.headers = {"authorization": f"Bearer {token}"} if token else {}
        self.client = type("C", (), {"host": ip})()


class TokenEnv(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("TITAN_GUI_TOKEN")
        os.environ["TITAN_GUI_TOKEN"] = "sekret"
        auth.THROTTLE.reset()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("TITAN_GUI_TOKEN", None)
        else:
            os.environ["TITAN_GUI_TOKEN"] = self._prev
        os.environ.pop("TITAN_GUI_READONLY", None)
        auth.THROTTLE.reset()


class TestTokenOk(TokenEnv):
    def test_correct_token_passes(self):
        self.assertTrue(auth.token_ok("sekret"))

    def test_wrong_missing_or_unset_fails(self):
        self.assertFalse(auth.token_ok("nope"))
        self.assertFalse(auth.token_ok(None))
        os.environ.pop("TITAN_GUI_TOKEN", None)
        self.assertFalse(auth.token_ok("sekret"))  # fail closed


class TestRequireToken(TokenEnv):
    def test_valid_header_passes(self):
        auth.require_token(_Req(token="sekret"))  # no raise

    def test_bad_token_401_and_recorded(self):
        with self.assertRaises(HTTPException) as ctx:
            auth.require_token(_Req(token="wrong"))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_throttle_429_after_limit(self):
        for _ in range(5):
            with self.assertRaises(HTTPException):
                auth.require_token(_Req(token="wrong", ip="9.9.9.9"))
        with self.assertRaises(HTTPException) as ctx:
            auth.require_token(_Req(token="sekret", ip="9.9.9.9"))  # even correct token
        self.assertEqual(ctx.exception.status_code, 429)

    def test_other_ip_unaffected_by_throttle(self):
        for _ in range(5):
            with self.assertRaises(HTTPException):
                auth.require_token(_Req(token="wrong", ip="9.9.9.9"))
        auth.require_token(_Req(token="sekret", ip="8.8.8.8"))  # no raise


class TestReadOnly(TokenEnv):
    def test_readonly_env_blocks_writes(self):
        os.environ["TITAN_GUI_READONLY"] = "1"
        with self.assertRaises(HTTPException) as ctx:
            auth.require_writable()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_default_is_writable(self):
        auth.require_writable()  # no raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/ops/web/auth.py
"""Bearer-token auth (fail-closed), per-IP failure throttling, read-only guard."""
import hmac
import os
import time

from fastapi import HTTPException, Request


class AuthThrottle:
    """>limit bad tokens from one IP inside window_s -> blocked until window rolls."""

    def __init__(self, limit: int = 5, window_s: float = 60.0):
        self._limit = limit
        self._window_s = window_s
        self._failures: dict = {}  # ip -> list[timestamps]

    def _prune(self, ip: str, now: float) -> list:
        hits = [t for t in self._failures.get(ip, []) if now - t < self._window_s]
        self._failures[ip] = hits
        return hits

    def blocked(self, ip: str, now: float | None = None) -> bool:
        return len(self._prune(ip, now if now is not None else time.monotonic())) >= self._limit

    def record_failure(self, ip: str, now: float | None = None) -> None:
        self._prune(ip, now if now is not None else time.monotonic())
        self._failures.setdefault(ip, []).append(now if now is not None else time.monotonic())

    def reset(self) -> None:
        self._failures.clear()


THROTTLE = AuthThrottle()


def token_ok(supplied) -> bool:
    expected = os.environ.get("TITAN_GUI_TOKEN", "") or ""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(supplied), expected)


def _client_ip(request) -> str:
    client = getattr(request, "client", None)
    return getattr(client, "host", "?") or "?"


def require_token(request: Request) -> None:
    """FastAPI dependency: 429 when the caller IP is throttled, 401 on bad token."""
    ip = _client_ip(request)
    if THROTTLE.blocked(ip):
        raise HTTPException(status_code=429, detail="too many auth failures; retry later")
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else None
    if not token_ok(supplied):
        THROTTLE.record_failure(ip)
        raise HTTPException(status_code=401, detail="invalid or missing token")


def require_writable() -> None:
    """FastAPI dependency: 403 on all mutating routes in read-only mode."""
    if os.environ.get("TITAN_GUI_READONLY", "") == "1":
        raise HTTPException(status_code=403, detail="read-only mode")
```

- [ ] **Step 4: Run to verify PASS** (8 tests)
- [ ] **Step 5: Commit** — `feat(gui): auth — fail-closed bearer token, per-IP failure throttling, read-only guard (+fastapi/uvicorn deps)` (+trailer; include `requirements.txt`)

---

### Task 4: GuiActionExecuted event + BusBridge (EventBus → ring buffer → WS queues)

**Files:**
- Modify: `src/core/events.py` (append one event type — nothing else in the file changes)
- Create: `src/ops/web/bus_bridge.py`
- Test: `tests/unit/test_gui_bus_bridge.py`

**Interfaces:**
- Consumes: `EventBus.subscribe_all(handler, name)` (`src/core/bus.py:47`), `Event.to_dict()`.
- Produces:
  - Event `GuiActionExecuted(action: str, args: str, outcome: str, client: str)` registered in `EVENT_TYPES` (follow the file's existing decorator pattern exactly).
  - `project(event) -> dict | None` — `None` for `TickReceived` (feed noise); else `{"topic": <evt name>, "ts": <epoch float>, ...event fields}`.
  - `BusBridge(ring_size=200)` with `.handle(event)` (sync; safe to register via `subscribe_all`), `.attach(maxsize=100) -> asyncio.Queue`, `.detach(queue)`, `.recent(limit=200) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_bus_bridge.py
import unittest
import asyncio
from src.core.bus import EventBus
from src.core.events import (EVENT_TYPES, GuiActionExecuted, IntentBlocked,
                             SystemStateChanged, TickReceived)
from src.ops.web.bus_bridge import BusBridge, project


class TestGuiActionEvent(unittest.TestCase):
    def test_registered_and_serializable(self):
        self.assertIn("GuiActionExecuted", EVENT_TYPES)
        e = GuiActionExecuted(action="pause", args="{}", outcome="ok", client="127.0.0.1")
        d = e.to_dict()
        self.assertEqual(d["evt"], "GuiActionExecuted")
        self.assertEqual(d["action"], "pause")


class TestProject(unittest.TestCase):
    def test_projects_topic_ts_and_fields(self):
        msg = project(IntentBlocked(strategy_id="sb", symbol="EURUSD",
                                    direction="BUY", rule="opposition", detail="x"))
        self.assertEqual(msg["topic"], "IntentBlocked")
        self.assertEqual(msg["rule"], "opposition")
        self.assertIn("ts", msg)
        self.assertNotIn("evt", msg)

    def test_ticks_are_dropped(self):
        self.assertIsNone(project(TickReceived(symbol="EURUSD", bid=1.0, ask=1.1)))


class TestBusBridge(unittest.TestCase):
    def test_ring_buffer_and_recent(self):
        bridge = BusBridge(ring_size=2)
        for state in ("ACTIVE", "PAUSED", "ACTIVE"):
            bridge.handle(SystemStateChanged(state=state))
        recent = bridge.recent()
        self.assertEqual(len(recent), 2)                      # ring capped
        self.assertEqual(recent[-1]["state"], "ACTIVE")
        self.assertEqual(bridge.recent(limit=1)[0]["state"], "ACTIVE")

    def test_subscribed_bus_events_reach_client_queue(self):
        bus = EventBus()
        bridge = BusBridge()
        bus.subscribe_all(bridge.handle, name="gui")
        q = bridge.attach()
        bus.publish(SystemStateChanged(state="PAUSED"))
        msg = asyncio.run(q.get())
        self.assertEqual(msg["topic"], "SystemStateChanged")

    def test_full_client_queue_drops_never_raises(self):
        bridge = BusBridge()
        q = bridge.attach(maxsize=1)
        bridge.handle(SystemStateChanged(state="A"))
        bridge.handle(SystemStateChanged(state="B"))          # full -> dropped
        self.assertEqual(asyncio.run(q.get())["state"], "A")
        self.assertTrue(q.empty())

    def test_detach_stops_delivery(self):
        bridge = BusBridge()
        q = bridge.attach()
        bridge.detach(q)
        bridge.handle(SystemStateChanged(state="A"))
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
```

> Note: check `TickReceived`'s actual field names in `src/core/events.py:50` before running;
> if its constructor differs from `(symbol, bid, ask)`, use its real fields in the test —
> the assertion under test is only "ticks project to None".

- [ ] **Step 2: Run to verify it fails** — `ImportError: cannot import name 'GuiActionExecuted'`

- [ ] **Step 3: Implement**

Append to `src/core/events.py` (match the file's existing decorator/style exactly — see `IntentBlocked` at :137 as the template):

```python
@_register
@dataclass(frozen=True)
class GuiActionExecuted(Event):
    """An accepted mutation issued through the control GUI (audit trail)."""
    name: ClassVar[str] = "GuiActionExecuted"
    action: str = ""     # e.g. "command:pause", "settings:risk.drawdown_throttle.enabled"
    args: str = ""       # compact JSON of the request payload
    outcome: str = ""    # "ok" | "error:<detail>"
    client: str = ""     # requester IP
```

```python
# src/ops/web/bus_bridge.py
"""EventBus -> GUI feed: curated projection, ring-buffer backfill, per-client queues.

Registered on the bus via subscribe_all(handle, name="gui"); the bus's own
circuit-breaker (src/core/bus.py) cuts this subscriber off after repeated
failures, so a GUI bug can never wedge the publisher.
"""
import asyncio
import collections
import time

_SKIP_TOPICS = {"TickReceived"}   # tick firehose stays on the tape, not the GUI feed


def project(event):
    """Event -> feed dict {topic, ts, ...fields}; None for skipped topics."""
    d = event.to_dict()
    topic = d.pop("evt", type(event).__name__)
    if topic in _SKIP_TOPICS:
        return None
    return {"topic": topic, "ts": time.time(), **d}


class BusBridge:
    def __init__(self, ring_size: int = 200):
        self._ring = collections.deque(maxlen=ring_size)
        self._clients: list = []

    def handle(self, event) -> None:
        msg = project(event)
        if msg is None:
            return
        self._ring.append(msg)
        for q in self._clients:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # slow/dead client: drop, never block the publisher

    def attach(self, maxsize: int = 100) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._clients.append(q)
        return q

    def detach(self, q) -> None:
        if q in self._clients:
            self._clients.remove(q)

    def recent(self, limit: int = 200) -> list:
        items = list(self._ring)
        return items[-limit:]
```

- [ ] **Step 4: Run to verify PASS** (6 tests)
- [ ] **Step 5: Also run** `.venv/bin/python -m unittest tests.unit.test_controller_events -v` (events.py was touched; existing event tests must stay green — if that module name differs, run the test module that covers `src/core/events.py`).
- [ ] **Step 6: Commit** — `feat(gui): GuiActionExecuted tape event + BusBridge (EventBus->ring buffer->WS queues)` (+trailer)

---

### Task 5: State snapshot + history rows

**Files:**
- Create: `src/ops/web/state_view.py`
- Test: `tests/unit/test_gui_state_view.py`

**Interfaces:**
- Produces:
  - `build_snapshot(controller) -> dict` with keys `health` (`bridge_connected`, `last_heartbeat_age_s`, `paused`, `last_error`), `account` (`balance`, `equity`), `positions` (mapped HEARTBEAT dicts + journal `grade`/`strategy` backfill), `arbiter` (`stats` from `controller.arbiter.stats()`, `throttle: {enabled, current_mult}`), `registry` (list of `{id, version, status, state, tf, priority}` from `controller.registry.report()`).
  - `history_rows(conn, limit=50) -> list[dict]` — `SELECT * FROM trade_history ORDER BY rowid DESC LIMIT ?`.
- Consumes (read-only controller attrs, all verified in Global Constraints): `current_open_positions`, `last_heartbeat_time`, `is_manual_pause`, `risk_manager` (`current_equity`, `starting_balance`, `throttle_factor()`), `state_manager.get_order`, `arbiter.stats()`, `registry.report()`, `config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_state_view.py
import unittest
import sqlite3
from datetime import datetime, timedelta
from src.ops.web.state_view import build_snapshot, history_rows


class FakeRisk:
    current_equity = 10250.0
    starting_balance = 10000.0

    @staticmethod
    def throttle_factor():
        return 0.5


class FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 4, "approved": 3, "blocked_by": {"opposition": 1}}


class FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "silver_bullet", "version": "14.4.2", "family": "smc",
                 "tf": "H1", "status": "live", "state": "ACTIVE", "priority": 50}]


class FakeState:
    def __init__(self, rows):
        self._rows = rows

    def get_order(self, ticket):
        return self._rows.get(ticket)


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now() - timedelta(seconds=2)
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.arbiter = FakeArbiter()
        self.registry = FakeRegistry()
        self.config = {"risk": {"drawdown_throttle": {"enabled": True}}}
        self.current_open_positions = [
            {"t": 123, "s": "EURUSD", "p": 1.10, "sl": 1.095, "tp": 1.11,
             "pf": 12.5, "vol": 0.10, "type": 0, "comment": "SB"}]
        self.state_manager = FakeState({123: {"grade": "A+", "strategy": "silver_bullet"}})


class TestSnapshot(unittest.TestCase):
    def test_positions_mapped_with_journal_backfill(self):
        pos = build_snapshot(FakeController())["positions"][0]
        self.assertEqual(pos["ticket"], 123)
        self.assertEqual(pos["side"], "BUY")
        self.assertEqual(pos["grade"], "A+")
        self.assertEqual(pos["strategy"], "silver_bullet")

    def test_sell_side_and_missing_journal_row(self):
        c = FakeController()
        c.current_open_positions[0]["type"] = 1
        c.state_manager = FakeState({})
        pos = build_snapshot(c)["positions"][0]
        self.assertEqual(pos["side"], "SELL")
        self.assertEqual(pos["grade"], "")

    def test_health_account_arbiter_registry_blocks(self):
        snap = build_snapshot(FakeController())
        self.assertTrue(snap["health"]["bridge_connected"])
        self.assertEqual(snap["account"]["equity"], 10250.0)
        self.assertEqual(snap["arbiter"]["stats"]["approved"], 3)
        self.assertTrue(snap["arbiter"]["throttle"]["enabled"])
        self.assertEqual(snap["arbiter"]["throttle"]["current_mult"], 0.5)
        self.assertEqual(snap["registry"][0]["id"], "silver_bullet")
        self.assertEqual(snap["registry"][0]["state"], "ACTIVE")
        self.assertNotIn("family", snap["registry"][0])   # trimmed view

    def test_stale_heartbeat_marks_disconnected(self):
        c = FakeController()
        c.last_heartbeat_time = datetime.now() - timedelta(seconds=120)
        self.assertFalse(build_snapshot(c)["health"]["bridge_connected"])


class TestHistoryRows(unittest.TestCase):
    def test_reads_newest_first_with_limit(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE trade_history (ticket_id INT, symbol TEXT, pnl REAL)")
        for i in range(5):
            conn.execute("INSERT INTO trade_history VALUES (?, 'EURUSD', ?)", (i, i * 1.0))
        rows = history_rows(conn, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ticket_id"], 4)   # newest first


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/ops/web/state_view.py
"""Read-only assembly of the /api/state snapshot and /api/history rows."""
from datetime import datetime

_HEARTBEAT_STALE_S = 60.0
_REGISTRY_FIELDS = ("id", "version", "status", "state", "tf", "priority")


def build_snapshot(controller) -> dict:
    age = (datetime.now() - controller.last_heartbeat_time).total_seconds()
    rm = controller.risk_manager
    throttle_cfg = (controller.config.get("risk", {}) or {}).get("drawdown_throttle", {}) or {}
    return {
        "health": {
            "bridge_connected": age <= _HEARTBEAT_STALE_S,
            "last_heartbeat_age_s": round(age, 1),
            "paused": bool(getattr(controller, "is_manual_pause", False)),
            "last_error": getattr(controller, "last_error", None),
        },
        "account": {
            "balance": float(getattr(rm, "starting_balance", 0.0) or 0.0),
            "equity": float(getattr(rm, "current_equity", 0.0) or 0.0),
        },
        "positions": [_map_position(controller, p) for p in controller.current_open_positions],
        "arbiter": {
            "stats": controller.arbiter.stats(),
            "throttle": {"enabled": bool(throttle_cfg.get("enabled", False)),
                         "current_mult": float(rm.throttle_factor())},
        },
        "registry": [{k: r.get(k) for k in _REGISTRY_FIELDS} for r in controller.registry.report()],
    }


def _map_position(controller, p: dict) -> dict:
    ticket = int(p.get("t", 0))
    try:
        row = controller.state_manager.get_order(ticket)
    except Exception:
        row = None
    return {
        "ticket": ticket,
        "symbol": p.get("s", "?"),
        "side": "BUY" if int(p.get("type", 0)) == 0 else "SELL",
        "lots": float(p.get("vol", 0.0)),
        "entry": float(p.get("p", 0.0)),
        "sl": float(p.get("sl", 0.0)),
        "tp": float(p.get("tp", 0.0)),
        "pnl": float(p.get("pf", 0.0)),
        "grade": (row or {}).get("grade", "") or "",
        "strategy": (row or {}).get("strategy", "") or "",
    }


def history_rows(conn, limit: int = 50) -> list:
    try:
        cur = conn.execute(
            "SELECT * FROM trade_history ORDER BY rowid DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
```

- [ ] **Step 4: Run to verify PASS** (5 tests)
- [ ] **Step 5: Commit** — `feat(gui): /api/state snapshot (health/account/positions/arbiter/registry) + history rows` (+trailer)

---

### Task 6: Command router (confirm-gate)

**Files:**
- Create: `src/ops/web/commands.py`
- Test: `tests/unit/test_gui_commands.py`

**Interfaces:**
- Produces: `async execute_command(controller, payload: dict) -> dict`. Commands: `pause`, `resume`, `close` (needs int `ticket`), `closeall`, `panic`, `cancel`. Destructive (`closeall`, `panic`) need `confirm is True` else `{"status": "needs_confirm"}` WITHOUT touching the controller. Unknown → `{"status": "error", ...}`. Success → `{"status": "ok", "result": ...}`.
- Consumes: the six controller methods listed in Global Constraints, verbatim.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_commands.py
import unittest
import asyncio
from src.ops.web.commands import execute_command


class FakeController:
    def __init__(self):
        self.calls = []

    def set_system_pause(self, p):
        self.calls.append(("pause", p))
        return "PAUSED" if p else "ACTIVE"

    async def close_specific_market_order(self, ticket_id):
        self.calls.append(("close", ticket_id))
        return f"closed {ticket_id}"

    async def close_all_market_orders(self):
        self.calls.append(("closeall",))
        return 3

    async def trigger_panic(self):
        self.calls.append(("panic",))

    async def cancel_pending_orders(self, target_id="all"):
        self.calls.append(("cancel", target_id))
        return "cancelled"


class TestCommands(unittest.TestCase):
    def test_pause_and_resume(self):
        c = FakeController()
        self.assertEqual(asyncio.run(execute_command(c, {"command": "pause"}))["result"], "PAUSED")
        self.assertEqual(asyncio.run(execute_command(c, {"command": "resume"}))["result"], "ACTIVE")

    def test_close_requires_int_ticket(self):
        c = FakeController()
        self.assertEqual(asyncio.run(execute_command(c, {"command": "close"}))["status"], "error")
        res = asyncio.run(execute_command(c, {"command": "close", "ticket": 42}))
        self.assertEqual(res["result"], "closed 42")

    def test_destructive_need_confirm_and_do_not_touch_controller(self):
        c = FakeController()
        for cmd in ("closeall", "panic"):
            res = asyncio.run(execute_command(c, {"command": cmd}))
            self.assertEqual(res["status"], "needs_confirm")
        self.assertEqual(c.calls, [])
        self.assertEqual(asyncio.run(execute_command(c, {"command": "closeall", "confirm": True}))["result"], 3)
        asyncio.run(execute_command(c, {"command": "panic", "confirm": True}))
        self.assertIn(("panic",), c.calls)

    def test_cancel_and_unknown(self):
        c = FakeController()
        self.assertEqual(asyncio.run(execute_command(c, {"command": "cancel"}))["result"], "cancelled")
        self.assertEqual(asyncio.run(execute_command(c, {"command": "boom"}))["status"], "error")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/ops/web/commands.py
"""Map GUI command payloads onto existing controller methods. No new trade logic."""

_DESTRUCTIVE = {"closeall", "panic"}


async def execute_command(controller, payload: dict) -> dict:
    command = payload.get("command")
    if command in _DESTRUCTIVE and payload.get("confirm") is not True:
        return {"status": "needs_confirm", "command": command}

    if command == "pause":
        return {"status": "ok", "result": controller.set_system_pause(True)}
    if command == "resume":
        return {"status": "ok", "result": controller.set_system_pause(False)}
    if command == "close":
        ticket = payload.get("ticket")
        if not isinstance(ticket, int) or isinstance(ticket, bool):
            return {"status": "error", "detail": "close requires integer 'ticket'"}
        return {"status": "ok", "result": await controller.close_specific_market_order(ticket)}
    if command == "closeall":
        return {"status": "ok", "result": await controller.close_all_market_orders()}
    if command == "panic":
        await controller.trigger_panic()
        return {"status": "ok", "result": "panic_executed"}
    if command == "cancel":
        return {"status": "ok", "result": await controller.cancel_pending_orders(
            payload.get("ticket", "all"))}

    return {"status": "error", "detail": "unknown command"}
```

- [ ] **Step 4: Run to verify PASS** (4 tests)
- [ ] **Step 5: Commit** — `feat(gui): command router with confirm-gate over existing controller methods` (+trailer)

---

### Task 7: Registry actions (lifecycle + promote confirm)

**Files:**
- Create: `src/ops/web/registry_view.py`
- Test: `tests/unit/test_gui_registry_view.py`

**Interfaces:**
- Produces:
  - `registry_report(controller) -> list[dict]` — full `controller.registry.report()` passthrough (the GUI's `/api/registry` detail view).
  - `execute_registry_action(controller, strategy_id: str, action: str, payload: dict) -> dict`:
    - `action == "enable"` → `controller.enable_strategy(strategy_id)` (default `allow_research=False`; the registry itself refuses research-status and returns the guidance message).
    - `action == "disable"` → `controller.disable_strategy(strategy_id)`.
    - `action == "promote"` → requires `payload.get("confirm") == strategy_id` (typed-id echo) else `{"status": "needs_confirm", "expect": strategy_id}` WITHOUT calling the controller; on match → `controller.enable_strategy(strategy_id, allow_research=True)`.
    - unknown action → `{"status": "error", ...}`. Success → `{"status": "ok", "result": <controller msg>}`.
- Consumes: `enable_strategy(sid, allow_research=False)` (:873), `disable_strategy(sid)` (:878).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_registry_view.py
import unittest
from src.ops.web.registry_view import execute_registry_action, registry_report


class FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "gyroscope", "version": "0.1.0", "family": "kalman",
                 "tf": "H1", "status": "research", "state": "LOADED", "priority": 50}]


class FakeController:
    def __init__(self):
        self.calls = []
        self.registry = FakeRegistry()

    def enable_strategy(self, sid, allow_research=False):
        self.calls.append(("enable", sid, allow_research))
        return f"enabled {sid}" if allow_research else f"refused research {sid}"

    def disable_strategy(self, sid):
        self.calls.append(("disable", sid))
        return f"disabled {sid}"


class TestRegistryActions(unittest.TestCase):
    def test_report_passthrough(self):
        rows = registry_report(FakeController())
        self.assertEqual(rows[0]["id"], "gyroscope")
        self.assertEqual(rows[0]["family"], "kalman")   # full detail, untrimmed

    def test_enable_never_passes_allow_research(self):
        c = FakeController()
        res = execute_registry_action(c, "gyroscope", "enable", {})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(c.calls, [("enable", "gyroscope", False)])

    def test_disable(self):
        c = FakeController()
        res = execute_registry_action(c, "silver_bullet", "disable", {})
        self.assertEqual(res["result"], "disabled silver_bullet")

    def test_promote_without_typed_confirm_never_calls_controller(self):
        c = FakeController()
        for payload in ({}, {"confirm": True}, {"confirm": "wrong_id"}):
            res = execute_registry_action(c, "gyroscope", "promote", payload)
            self.assertEqual(res["status"], "needs_confirm", payload)
        self.assertEqual(c.calls, [])

    def test_promote_with_typed_id_uses_allow_research(self):
        c = FakeController()
        res = execute_registry_action(c, "gyroscope", "promote", {"confirm": "gyroscope"})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(c.calls, [("enable", "gyroscope", True)])

    def test_unknown_action(self):
        res = execute_registry_action(FakeController(), "x", "explode", {})
        self.assertEqual(res["status"], "error")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/ops/web/registry_view.py
"""Registry lifecycle for the GUI. The promote-gate stays server-side in the
registry (enable(allow_research=...)); this module only decides whether the
typed-id confirmation was supplied — it can never bypass the gate."""


def registry_report(controller) -> list:
    return controller.registry.report()


def execute_registry_action(controller, strategy_id: str, action: str, payload: dict) -> dict:
    if action == "enable":
        return {"status": "ok", "result": controller.enable_strategy(strategy_id)}
    if action == "disable":
        return {"status": "ok", "result": controller.disable_strategy(strategy_id)}
    if action == "promote":
        if payload.get("confirm") != strategy_id:
            return {"status": "needs_confirm", "expect": strategy_id,
                    "detail": "promote requires body {'confirm': '<strategy_id>'}"}
        return {"status": "ok",
                "result": controller.enable_strategy(strategy_id, allow_research=True)}
    return {"status": "error", "detail": f"unknown registry action '{action}'"}
```

- [ ] **Step 4: Run to verify PASS** (6 tests)
- [ ] **Step 5: Commit** — `feat(gui): registry lifecycle actions — enable/disable + promote with typed-id confirm` (+trailer)

---

### Task 8: FastAPI app (routes, WS first-frame auth, read-only, audit publish)

**Files:**
- Create: `src/ops/web/server.py`
- Test: `tests/unit/test_gui_server.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces:
  - `create_app(controller, settings_store, bridge) -> FastAPI`. Routes (REST all behind `require_token`; mutating ones also behind `require_writable`):
    - `GET /api/state`, `GET /api/events?limit=`, `GET /api/history?limit=`
    - `POST /api/command`, `GET /api/settings`, `PATCH /api/settings`
    - `GET /api/registry`, `POST /api/registry/{sid}/{action}` (`action` ∈ enable/disable/promote)
    - `WS /ws`: accept → wait ≤3s for first text frame == token (fallback: `sec-websocket-protocol` header) → on fail close(1008) → on success send `{type:"state", ...snapshot}` then stream bridge queue messages as `{type:"event", ...}`.
  - Every ACCEPTED mutation (command executed, setting written, registry action performed) publishes `GuiActionExecuted` via `controller._publish(...)`; `needs_confirm`/422/403/401 outcomes do NOT publish.
  - `start(controller, settings_store, bridge) -> asyncio.Task` — uvicorn Server on `TITAN_GUI_BIND`/`:8770`, `log_level="warning"`, `lifespan="off"`; returns `asyncio.create_task(server.serve())`. Not unit-tested.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_server.py
import unittest
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
from fastapi.testclient import TestClient
from src.core.events import GuiActionExecuted
from src.ops.web import auth
from src.ops.web.server import create_app
from src.ops.web.settings import SettingsStore
from src.ops.web.bus_bridge import BusBridge

DEFAULTS = {"signal_grading": {"enabled": True, "min_grade": "B"},
            "risk": {"drawdown_throttle": {"enabled": False, "trigger_dd_pct": 2.0,
                                           "factor": 0.5}},
            "connection": {"zeromq": {"push_port": 32768}}}
AUTH = {"Authorization": "Bearer sekret"}


class FakeRisk:
    current_equity = 10000.0
    starting_balance = 10000.0

    @staticmethod
    def throttle_factor():
        return 1.0


class FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 0, "approved": 0, "blocked_by": {}}


class FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "silver_bullet", "version": "14.4.2", "family": "smc",
                 "tf": "H1", "status": "live", "state": "ACTIVE", "priority": 50}]


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now()
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.arbiter = FakeArbiter()
        self.registry = FakeRegistry()
        self.config = {"risk": {"drawdown_throttle": {"enabled": False}}}
        self.current_open_positions = []
        self.state_manager = type("S", (), {"get_order": staticmethod(lambda t: None)})()
        self.applied = []
        self.published = []

    def set_system_pause(self, p):
        self.is_manual_pause = p
        return "PAUSED" if p else "ACTIVE"

    def enable_strategy(self, sid, allow_research=False):
        return f"enabled {sid} research={allow_research}"

    def disable_strategy(self, sid):
        return f"disabled {sid}"

    def apply_runtime_setting(self, key, value):
        self.applied.append((key, value))

    def _publish(self, event):
        self.published.append(event)


def _make(tmp):
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    os.environ.pop("TITAN_GUI_READONLY", None)
    auth.THROTTLE.reset()
    ctrl = FakeController()
    store = SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")
    bridge = BusBridge()
    app = create_app(ctrl, store, bridge)
    return TestClient(app), ctrl, bridge


class TestAuthAndState(unittest.TestCase):
    def test_state_requires_auth_and_has_v15_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, _ = _make(d)
            self.assertEqual(client.get("/api/state").status_code, 401)
            body = client.get("/api/state", headers=AUTH).json()
            for key in ("health", "account", "positions", "arbiter", "registry"):
                self.assertIn(key, body)

    def test_events_backfill(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, bridge = _make(d)
            from src.core.events import SystemStateChanged
            bridge.handle(SystemStateChanged(state="PAUSED"))
            rows = client.get("/api/events?limit=10", headers=AUTH).json()["events"]
            self.assertEqual(rows[-1]["topic"], "SystemStateChanged")


class TestMutationsAndAudit(unittest.TestCase):
    def test_command_pause_publishes_audit(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.post("/api/command", json={"command": "pause"}, headers=AUTH)
            self.assertEqual(r.json()["result"], "PAUSED")
            audits = [e for e in ctrl.published if isinstance(e, GuiActionExecuted)]
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].action, "command:pause")
            self.assertEqual(audits[0].outcome, "ok")

    def test_needs_confirm_does_not_publish_audit(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.post("/api/command", json={"command": "panic"}, headers=AUTH)
            self.assertEqual(r.json()["status"], "needs_confirm")
            self.assertEqual(ctrl.published, [])

    def test_patch_safe_setting_applies_live_and_audits(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.patch("/api/settings", headers=AUTH,
                             json={"key": "risk.drawdown_throttle.enabled", "value": True})
            self.assertEqual(r.json()["applied"], "live")
            self.assertIn(("risk.drawdown_throttle.enabled", True), ctrl.applied)
            self.assertEqual(len(ctrl.published), 1)

    def test_patch_invalid_422_no_apply_no_audit(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.patch("/api/settings", headers=AUTH,
                             json={"key": "signal_grading.min_grade", "value": "Z"})
            self.assertEqual(r.status_code, 422)
            self.assertEqual(ctrl.applied, [])
            self.assertEqual(ctrl.published, [])

    def test_patch_restart_key_saved_not_applied(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.patch("/api/settings", headers=AUTH,
                             json={"key": "connection.zeromq.push_port", "value": 40000})
            self.assertTrue(r.json()["restart_required"])
            self.assertEqual(ctrl.applied, [])

    def test_registry_promote_flow(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            r = client.post("/api/registry/gyro/promote", json={}, headers=AUTH)
            self.assertEqual(r.json()["status"], "needs_confirm")
            r2 = client.post("/api/registry/gyro/promote",
                             json={"confirm": "gyro"}, headers=AUTH)
            self.assertEqual(r2.json()["result"], "enabled gyro research=True")


class TestReadOnlyMode(unittest.TestCase):
    def test_mutating_routes_403_reads_stay_200(self):
        with tempfile.TemporaryDirectory() as d:
            client, ctrl, _ = _make(d)
            os.environ["TITAN_GUI_READONLY"] = "1"
            try:
                self.assertEqual(client.post("/api/command", json={"command": "pause"},
                                             headers=AUTH).status_code, 403)
                self.assertEqual(client.patch("/api/settings", headers=AUTH,
                                              json={"key": "signal_grading.min_grade",
                                                    "value": "A"}).status_code, 403)
                self.assertEqual(client.post("/api/registry/x/disable", json={},
                                             headers=AUTH).status_code, 403)
                self.assertEqual(client.get("/api/state", headers=AUTH).status_code, 200)
                self.assertEqual(ctrl.published, [])
            finally:
                os.environ.pop("TITAN_GUI_READONLY", None)


class TestWebSocketAuth(unittest.TestCase):
    def test_first_frame_token_then_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, _ = _make(d)
            with client.websocket_connect("/ws") as ws:
                ws.send_text("sekret")
                first = ws.receive_json()
                self.assertEqual(first["type"], "state")

    def test_wrong_first_frame_closes_1008(self):
        with tempfile.TemporaryDirectory() as d:
            client, _, _ = _make(d)
            with client.websocket_connect("/ws") as ws:
                ws.send_text("wrong")
                with self.assertRaises(Exception):   # closed by server
                    ws.receive_json()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/ops/web/server.py
"""FastAPI app + uvicorn task for the embedded control API (port 8770)."""
import asyncio
import json
import os

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from src.core.events import GuiActionExecuted

from . import auth
from .commands import execute_command
from .registry_view import execute_registry_action, registry_report
from .state_view import build_snapshot, history_rows

_WS_AUTH_TIMEOUT_S = 3.0


def _audit(controller, request, action: str, payload, outcome: str) -> None:
    try:
        controller._publish(GuiActionExecuted(
            action=action, args=json.dumps(payload, default=str)[:500],
            outcome=outcome, client=getattr(getattr(request, "client", None), "host", "?") or "?"))
    except Exception:
        pass  # audit must never break the request path


def create_app(controller, settings_store, bridge) -> FastAPI:
    app = FastAPI(title="Titan Control API")
    app.state.controller = controller

    read = [Depends(auth.require_token)]
    write = [Depends(auth.require_token), Depends(auth.require_writable)]

    @app.get("/api/state", dependencies=read)
    def get_state():
        return build_snapshot(controller)

    @app.get("/api/events", dependencies=read)
    def get_events(limit: int = 200):
        return {"events": bridge.recent(limit=limit)}

    @app.get("/api/history", dependencies=read)
    def get_history(limit: int = 50):
        return {"history": history_rows(controller.state_manager.conn, limit=limit)}

    @app.post("/api/command", dependencies=write)
    async def post_command(payload: dict, request=None):
        result = await execute_command(controller, payload)
        if result.get("status") == "ok":
            _audit(controller, request, f"command:{payload.get('command')}", payload, "ok")
        return result

    @app.get("/api/settings", dependencies=read)
    def get_settings():
        return {"settings": settings_store.describe()}

    @app.patch("/api/settings", dependencies=write)
    def patch_settings(payload: dict, request=None):
        key, value = payload.get("key"), payload.get("value")
        try:
            result = settings_store.set(key, value)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})
        if settings_store.is_safe(key):
            controller.apply_runtime_setting(key, value)
        _audit(controller, request, f"settings:{key}", payload, "ok")
        return result

    @app.get("/api/registry", dependencies=read)
    def get_registry():
        return {"registry": registry_report(controller)}

    @app.post("/api/registry/{sid}/{action}", dependencies=write)
    def post_registry(sid: str, action: str, payload: dict, request=None):
        result = execute_registry_action(controller, sid, action, payload or {})
        if result.get("status") == "ok":
            _audit(controller, request, f"registry:{action}:{sid}", payload, "ok")
        return result

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        token = websocket.headers.get("sec-websocket-protocol")
        if not auth.token_ok(token):
            try:
                token = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT_S)
            except Exception:
                token = None
        if not auth.token_ok(token):
            await websocket.close(code=1008)
            return
        await websocket.send_json({"type": "state", **build_snapshot(controller)})
        queue = bridge.attach()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json({"type": "event", **event})
        except WebSocketDisconnect:
            pass
        finally:
            bridge.detach(queue)

    return app


def start(controller, settings_store, bridge) -> "asyncio.Task":
    """uvicorn Server on the controller's loop; returns the serve() task."""
    import uvicorn  # local import keeps unit-test imports light

    app = create_app(controller, settings_store, bridge)
    host = os.environ.get("TITAN_GUI_BIND", "127.0.0.1")
    config = uvicorn.Config(app, host=host, port=8770, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    return asyncio.create_task(server.serve())
```

> Implementation notes for the `request=None` params: use `fastapi.Request` type
> annotations (`request: Request`) so FastAPI injects the real object — write it that
> way in the actual code (the test's audit assertions only need `.client.host` to be
> readable). If `payload: dict` on the registry route conflicts with an empty body,
> default it (`payload: dict = None`) and coalesce.

- [ ] **Step 4: Run to verify PASS** (11 tests)
- [ ] **Step 5: Commit** — `feat(gui): FastAPI app — v15 routes, WS first-frame auth, read-only mode, audited mutations` (+trailer)

---

### Task 9: Controller integration + housekeeping

**Files:**
- Modify: `src/core/system_controller.py` (`_load_config` :158; new `apply_runtime_setting`; web-task start in `run()` next to the health-probe block :235-243)
- Modify: `.env.example`, `.gitignore`
- Test: `tests/unit/test_gui_apply_runtime.py`

**Interfaces:**
- Produces:
  - Module-level `_apply_runtime_setting(controller, key, value)` in `system_controller.py` + delegating method `apply_runtime_setting(self, key, value)` (module-level fn keeps it testable without constructing the controller, which opens ZMQ).
  - Semantics: update `controller.config` at the dotted key IN PLACE (RiskManager/TradeManager hold the same dict object, and `throttle_factor()` reads it fresh per call — verified). Additionally push to cached attributes when the object caches them: `signal_grading.min_grade`/`.enabled` → set the matching attribute on `controller.signal_grader` ONLY if that attribute already exists (`hasattr` guard — if the grader reads config directly, the config update alone is live).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_apply_runtime.py
import unittest
from src.core.system_controller import _apply_runtime_setting


class Grader:
    def __init__(self):
        self.min_grade = "B"
        self.enabled = True


class FakeController:
    def __init__(self):
        self.config = {"signal_grading": {"min_grade": "B", "enabled": True},
                       "risk": {"trade": {"risk_per_trade_pct": 1.0},
                                "drawdown_throttle": {"enabled": False}}}
        self.signal_grader = Grader()


class TestApplyRuntime(unittest.TestCase):
    def test_min_grade_updates_config_and_cached_attr(self):
        c = FakeController()
        _apply_runtime_setting(c, "signal_grading.min_grade", "A")
        self.assertEqual(c.config["signal_grading"]["min_grade"], "A")
        self.assertEqual(c.signal_grader.min_grade, "A")

    def test_config_dict_mutated_in_place_not_replaced(self):
        c = FakeController()
        risk_ref = c.config["risk"]                 # simulates RiskManager's held ref
        _apply_runtime_setting(c, "risk.drawdown_throttle.enabled", True)
        self.assertTrue(risk_ref["drawdown_throttle"]["enabled"])   # same object saw it

    def test_missing_cached_attr_is_tolerated(self):
        c = FakeController()
        del c.signal_grader.enabled
        _apply_runtime_setting(c, "signal_grading.enabled", False)  # no raise
        self.assertFalse(c.config["signal_grading"]["enabled"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** — `ImportError: cannot import name '_apply_runtime_setting'`

- [ ] **Step 3: Add to `system_controller.py`** (module level, after imports, before the class):

```python
def _apply_runtime_setting(controller, key: str, value) -> None:
    """Live-apply a whitelisted setting: mutate config in place + push cached attrs.

    RiskManager/TradeManager hold the SAME config dict object, so the in-place
    nested update is immediately visible to them; only objects that cache a
    value at __init__ (SignalGrader) need the attribute push.
    """
    parts = key.split(".")
    node = controller.config
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

    if key.startswith("signal_grading."):
        attr = parts[-1]
        grader = getattr(controller, "signal_grader", None)
        if grader is not None and hasattr(grader, attr):
            setattr(grader, attr, value)
```

Inside the class (near `set_system_pause` :859):

```python
    def apply_runtime_setting(self, key: str, value) -> None:
        _apply_runtime_setting(self, key, value)
```

- [ ] **Step 4: Run to verify PASS** (3 tests)

- [ ] **Step 5: Layered `_load_config`** — replace the body at :158 with:

```python
    def _load_config(self):
        cfg_path = self.root_dir / "config" / "config.yaml"
        if not cfg_path.exists():
            sys.exit(f"[FATAL] config.yaml not found at {cfg_path}")
        from src.ops.web.config_layer import load_layered_config
        return load_layered_config(cfg_path, self.root_dir / "config" / "overrides.yaml")
```

- [ ] **Step 6: Start the web task in `run()`** — immediately after the health-probe block (:235-243), add:

```python
        # --- Embedded control API (optional; must never block trading) ---
        try:
            from src.ops.web.bus_bridge import BusBridge
            from src.ops.web.settings import SettingsStore
            from src.ops.web import server as web_server
            self.gui_bridge = BusBridge()
            self.bus.subscribe_all(self.gui_bridge.handle, name="gui")
            self._settings_store = SettingsStore(
                self.config, self.root_dir / "config" / "overrides.yaml")
            self._web_task = web_server.start(self, self._settings_store, self.gui_bridge)
            self.logger.log_event("INFO", "GUI", "Control API on :8770")
        except Exception as e:
            self.logger.log_event("WARN", "GUI", f"Control API failed to start: {e}")
            self._web_task = None
```

> Adjust to the file's actual logger call pattern (`self.logger.log_event(...)` usage
> appears throughout the controller — copy the exact form used by the health-probe
> block). `self.bus` is the EventBus attribute the P02 integration created — verify its
> exact name at the `_publish` helper (:165) and use that.

- [ ] **Step 7: Housekeeping** — `.env.example` append:

```
# Control GUI API (embedded FastAPI on :8770)
TITAN_GUI_TOKEN=change-me-to-a-long-random-string
TITAN_GUI_BIND=127.0.0.1
# TITAN_GUI_READONLY=1   # uncomment for a view-only dashboard
```

`.gitignore` append (overrides are machine state, not source):

```
config/overrides.yaml
```

- [ ] **Step 8: Run the GUI test modules** — `.venv/bin/python -m unittest discover -s tests/unit -p 'test_gui_*.py'` → all green.
- [ ] **Step 9: Commit** — `feat(gui): wire control API into controller — layered config, apply_runtime_setting, bus-fed GUI bridge` (+trailer; files: `src/core/system_controller.py`, `.env.example`, `.gitignore`, `tests/unit/test_gui_apply_runtime.py`)

---

### Task 10: Full-suite + live smoke (verification)

- [ ] **Step 1:** Full suite: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` (FOREGROUND, timeout 600000+; expect 337 + all new GUI tests, all OK; the frozen parity test must be green).
- [ ] **Step 2:** Config regression: with no `config/overrides.yaml` present, `_load_config` must be byte-identical in effect — assert by running any existing controller-dependent test module (e.g. `tests.unit.test_controller_routing`) green in Step 1's run.
- [ ] **Step 3 (live smoke — only if MT5/bridge is available; otherwise record "server-start smoke" only):**
  - `export TITAN_GUI_TOKEN=devtoken && .venv/bin/python main.py` → expect log line `Control API on :8770`.
  - `curl -s localhost:8770/api/state -H "Authorization: Bearer devtoken"` → JSON with `health/account/positions/arbiter/registry`; without token → 401; after 5 bad tokens → 429.
  - `curl -s -X PATCH localhost:8770/api/settings -H "Authorization: Bearer devtoken" -H "Content-Type: application/json" -d '{"key":"risk.drawdown_throttle.enabled","value":true}'` → `{"applied":"live",...}`; `config/overrides.yaml` created; heartbeat cadence in the console unchanged while hammering `/api/state` in a loop (record observed interval).
  - Confirm `data/journal/` tape contains a `GuiActionExecuted` line for the PATCH.
- [ ] **Step 4:** `git status --porcelain` must show ONLY the user's 4 known parallel-work files beyond this branch's commits. No commit for this task (record results in the ledger).

---

## Self-Review

**Spec coverage:** EventBus feed → T4; ring backfill → T4+T8 (`/api/events`); registry panel + Telegram-parity promote → T7+T8; arbiter/throttle in snapshot → T5; settings tiers incl. `risk.drawdown_throttle.*` live and `arbiter.*` restart → T2; hardening: audit events → T4+T8, WS first-frame auth → T8, auth throttling → T3, read-only → T3+T8; layered config + `apply_runtime_setting` → T9; isolation guarantees → T8 `start()` + T9 try/except + bus circuit-breaker (existing); `/api/history` → T5+T8; port non-collision (8770 vs health 8787) → verified fact. Frontend = Phase 1b (separate plan), per spec.
**Placeholder scan:** clean — every step has complete code/commands; the two "adjust to actual pattern" notes in T4/T9 name the exact file:line to copy from, which is a verification instruction, not a gap.
**Type consistency:** `SettingsStore.set/is_safe/describe`, `BusBridge.handle/attach/detach/recent`, `project`, `build_snapshot`, `history_rows`, `execute_command`, `execute_registry_action`, `registry_report`, `create_app(controller, settings_store, bridge)`, `start(...)`, `_apply_runtime_setting` — names and signatures match across Tasks 2–9.
