# Titan Control GUI — Backend API Implementation Plan (Phase 1a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an embedded FastAPI + WebSocket control API to the running controller so a browser (or future mobile/SaaS client) can monitor live state, issue control actions, and edit safe-subset bot settings — without ever touching the ZMQ bridge or risking the trading loop.

**Architecture:** A second asyncio task inside `SystemController` serves a FastAPI app (REST + WS) on `:8770`. Read endpoints assemble JSON from `current_open_positions` + `StateManager`; command endpoints reuse the controller's existing `set_system_pause` / `close_*` / `trigger_panic` methods; a layered config store (defaults → `overrides.yaml`) applies a whitelisted safe-subset live and flags the rest restart-required. New code lives isolated under `src/ops/web/`; the trading loop is untouched except for three additive hooks.

**Tech Stack:** Python 3.10+, FastAPI 0.136 + uvicorn 0.48 (already installed), stdlib `unittest`, `fastapi.testclient.TestClient` (uses installed httpx), PyYAML.

## Global Constraints

- Tests use **stdlib `unittest`** (no pytest). Run with `.venv/bin/python -m unittest ...`.
- The GUI is **optional infrastructure**: any web-layer exception must be caught and logged; it must never crash, block, or slow the bridge loop.
- **No new trade-path logic** — command endpoints call existing controller methods only.
- **No new ZMQ binding.** The web layer never opens a socket to MT5.
- All web modules live under `src/ops/web/` and are unit-testable against a **fake controller** — they must not import or start the real bridge.
- Auth token env var: `TITAN_GUI_TOKEN`. Bind host env var: `TITAN_GUI_BIND` (default `127.0.0.1`). Port: `8770`.
- Safe-subset live-apply allowlist (exact dotted keys, `<name>` = any strategy key):
  `signal_grading.enabled`, `signal_grading.min_grade`, `risk.trade.risk_per_trade_pct`,
  `risk.account.max_daily_drawdown_pct`, `risk.account.max_global_exposure_pct`,
  `strategies.<name>.enabled`, `trade_management.runner.enabled`,
  `trade_management.runner.tighten_on_giveback`, `trade_management.runner.giveback_frac`,
  `trade_management.runner.tight_trail_frac`.
- HEARTBEAT position dict keys: `t`(ticket), `s`(symbol), `p`(entry), `sl`, `tp`,
  `pf`(profit), `vol`(lots), `type`(0=BUY/1=SELL), `comment`.

---

## File Structure

- `src/ops/web/__init__.py` — package marker (empty).
- `src/ops/web/config_layer.py` — `deep_merge()` + `load_layered_config()`. One job: merge defaults + overrides.
- `src/ops/web/settings.py` — `SettingsStore`: effective view with source/tier tags, validation, override persistence, safe-subset test. Pure logic, no controller.
- `src/ops/web/auth.py` — bearer-token check for REST (FastAPI dependency) and WS (token string check).
- `src/ops/web/state_view.py` — `build_snapshot(controller)` → the `/api/state` dict.
- `src/ops/web/commands.py` — `execute_command(controller, payload)` → maps to existing controller methods, enforces confirm-gate.
- `src/ops/web/events.py` — `EventHub`: in-process async pub/sub for the WS feed.
- `src/ops/web/server.py` — `create_app(controller, settings_store, event_hub)` + `start(controller, settings_store, event_hub)` (uvicorn Server task).
- `src/core/system_controller.py` — MODIFY: layered config in `_load_config`; add `apply_runtime_setting`; start web task in `run()`.
- `src/ops/telemetry.py` — MODIFY: `notify_*` also publish to the `EventHub`.
- `tests/unit/test_gui_*.py` — one test module per web module.
- Housekeeping: `requirements.txt`, `.env.example`, `.gitignore`, `config/overrides.yaml` (created empty/ignored).

---

## Task 1: Layered config loading

**Files:**
- Create: `src/ops/web/__init__.py` (empty)
- Create: `src/ops/web/config_layer.py`
- Create: `tests/unit/test_gui_config_layer.py`

**Interfaces:**
- Produces: `deep_merge(base: dict, override: dict) -> dict` (returns a new dict; `override` scalars/lists replace, nested dicts merge recursively). `load_layered_config(defaults_path: Path, overrides_path: Path) -> dict` (reads both YAML files; missing/empty overrides file → defaults unchanged).

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
        self.assertEqual(merged["risk"]["trade"]["risk_per_trade_pct"], 0.5)   # override wins
        self.assertEqual(merged["risk"]["trade"]["hard_max_lots"], 5.0)        # default survives
        self.assertEqual(merged["signal_grading"]["min_grade"], "B")          # untouched branch
        self.assertEqual(base["risk"]["trade"]["risk_per_trade_pct"], 1.0)    # base not mutated

    def test_list_value_is_replaced_not_merged(self):
        merged = deep_merge({"pairs": ["A", "B"]}, {"pairs": ["C"]})
        self.assertEqual(merged["pairs"], ["C"])


class TestLoadLayered(unittest.TestCase):
    def test_missing_overrides_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            defaults = Path(d) / "config.yaml"
            defaults.write_text("signal_grading:\n  min_grade: B\n")
            overrides = Path(d) / "overrides.yaml"  # does not exist
            cfg = load_layered_config(defaults, overrides)
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

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_config_layer -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.config_layer'`

- [ ] **Step 3: Write minimal implementation**

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
    """Return a new dict: override wins key-by-key; nested dicts merge recursively.
    Lists and scalars replace wholesale. `base` is never mutated."""
    result = copy.deepcopy(base)
    for key, ovr_val in override.items():
        base_val = result.get(key)
        if isinstance(base_val, dict) and isinstance(ovr_val, dict):
            result[key] = deep_merge(base_val, ovr_val)
        else:
            result[key] = copy.deepcopy(ovr_val)
    return result


def load_layered_config(defaults_path: Path, overrides_path: Path) -> dict:
    """Load defaults YAML, then deep-merge overrides YAML on top if present."""
    with open(defaults_path, "r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}
    overrides = {}
    if Path(overrides_path).exists():
        with open(overrides_path, "r", encoding="utf-8") as f:
            overrides = yaml.safe_load(f) or {}
    return deep_merge(defaults, overrides)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_config_layer -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/__init__.py src/ops/web/config_layer.py tests/unit/test_gui_config_layer.py
git commit -m "feat(gui): layered config loader (defaults + overrides deep-merge)"
```

---

## Task 2: SettingsStore (validation, tiers, override persistence)

**Files:**
- Create: `src/ops/web/settings.py`
- Create: `tests/unit/test_gui_settings.py`

**Interfaces:**
- Consumes: `deep_merge`, `load_layered_config` from Task 1.
- Produces:
  - `SettingsStore(defaults: dict, overrides_path: Path)`
  - `.is_safe(key: str) -> bool` — True iff key matches the safe-subset allowlist.
  - `.validate(key: str, value) -> str | None` — returns an error string, or `None` if valid.
  - `.describe() -> list[dict]` — `[{"key","value","source","tier"}, ...]` for flattened leaf keys.
  - `.set(key: str, value) -> dict` — validates, writes override file, returns
    `{"applied": "live"|"on_restart", "restart_required": bool, "value": value}`.
    Raises `ValueError(msg)` if validation fails.

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
    "risk": {"trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0},
             "account": {"max_daily_drawdown_pct": 3.0, "max_global_exposure_pct": 6.0}},
    "strategies": {"silver_bullet": {"enabled": True, "timeframe": "H1"}},
    "connection": {"zeromq": {"push_port": 32768}},
}


def _store(tmp):
    return SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")


class TestSafeSubset(unittest.TestCase):
    def test_whitelisted_keys_are_safe(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertTrue(s.is_safe("signal_grading.min_grade"))
            self.assertTrue(s.is_safe("strategies.silver_bullet.enabled"))
            self.assertTrue(s.is_safe("risk.trade.risk_per_trade_pct"))

    def test_restart_tier_keys_are_not_safe(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertFalse(s.is_safe("connection.zeromq.push_port"))
            self.assertFalse(s.is_safe("strategies.silver_bullet.timeframe"))


class TestValidate(unittest.TestCase):
    def test_min_grade_enum(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("signal_grading.min_grade", "A"))
            self.assertIsNotNone(s.validate("signal_grading.min_grade", "Z"))

    def test_risk_pct_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("risk.trade.risk_per_trade_pct", 0.5))
            self.assertIsNotNone(s.validate("risk.trade.risk_per_trade_pct", 0))     # must be > 0
            self.assertIsNotNone(s.validate("risk.trade.risk_per_trade_pct", 999))   # absurd

    def test_bool_keys_reject_non_bool(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            self.assertIsNone(s.validate("signal_grading.enabled", False))
            self.assertIsNotNone(s.validate("signal_grading.enabled", "yes"))


class TestSetAndDescribe(unittest.TestCase):
    def test_set_safe_key_applies_live_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            res = s.set("signal_grading.min_grade", "A")
            self.assertEqual(res["applied"], "live")
            self.assertFalse(res["restart_required"])
            written = yaml.safe_load((Path(d) / "overrides.yaml").read_text())
            self.assertEqual(written["signal_grading"]["min_grade"], "A")

    def test_set_restart_key_flags_restart(self):
        with tempfile.TemporaryDirectory() as d:
            s = _store(d)
            res = s.set("connection.zeromq.push_port", 40000)
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
            self.assertEqual(rows["signal_grading.min_grade"]["value"], "A")
            self.assertEqual(rows["signal_grading.min_grade"]["source"], "override")
            self.assertEqual(rows["signal_grading.min_grade"]["tier"], "live")
            self.assertEqual(rows["signal_grading.enabled"]["source"], "default")
            self.assertEqual(rows["connection.zeromq.push_port"]["tier"], "restart")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_settings -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.settings'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/settings.py
"""Layered-config store: effective view (tagged), validation, and override writes.

The safe-subset allowlist is the safety boundary — only these keys may ever be
applied to a running bot. Everything else is saved and flagged restart-required.
"""
import copy
import re
from pathlib import Path

import yaml

from .config_layer import deep_merge

# Exact dotted keys; "*" matches any single strategy name segment.
_SAFE_PATTERNS = [
    r"signal_grading\.enabled",
    r"signal_grading\.min_grade",
    r"risk\.trade\.risk_per_trade_pct",
    r"risk\.account\.max_daily_drawdown_pct",
    r"risk\.account\.max_global_exposure_pct",
    r"strategies\.[^.]+\.enabled",
    r"trade_management\.runner\.enabled",
    r"trade_management\.runner\.tighten_on_giveback",
    r"trade_management\.runner\.giveback_frac",
    r"trade_management\.runner\.tight_trail_frac",
]
_SAFE_RE = [re.compile(f"^{p}$") for p in _SAFE_PATTERNS]

_VALID_GRADES = {"A++", "A+", "A", "B", "C"}


class SettingsStore:
    def __init__(self, defaults: dict, overrides_path: Path):
        self._defaults = copy.deepcopy(defaults)
        self._overrides_path = Path(overrides_path)
        self._overrides = {}
        if self._overrides_path.exists():
            self._overrides = yaml.safe_load(self._overrides_path.read_text()) or {}

    # --- tier / safety ---
    def is_safe(self, key: str) -> bool:
        return any(rx.match(key) for rx in _SAFE_RE)

    # --- validation ---
    def validate(self, key: str, value) -> str | None:
        if key == "signal_grading.min_grade":
            return None if value in _VALID_GRADES else f"min_grade must be one of {sorted(_VALID_GRADES)}"
        if key.endswith("risk_per_trade_pct"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 < value <= 10 else "risk_per_trade_pct must be in (0, 10]"
        if key.endswith("_pct"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 < value <= 100 else "percent must be in (0, 100]"
        if key.endswith(".enabled") or key.endswith(".tighten_on_giveback"):
            return None if isinstance(value, bool) else "must be a boolean"
        if key.endswith("_frac"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 <= value <= 1 else "frac must be in [0, 1]"
        # Restart-tier keys: accept as-is (validated more strictly at Phase 2 if needed).
        return None

    # --- read ---
    def effective(self) -> dict:
        return deep_merge(self._defaults, self._overrides)

    def describe(self) -> list:
        eff = self.effective()
        rows = []
        for key, value in _flatten(eff):
            source = "override" if _has_key(self._overrides, key) else "default"
            tier = "live" if self.is_safe(key) else "restart"
            rows.append({"key": key, "value": value, "source": source, "tier": tier})
        return rows

    # --- write ---
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

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_settings -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/settings.py tests/unit/test_gui_settings.py
git commit -m "feat(gui): SettingsStore — safe-subset whitelist, validation, override writes"
```

---

## Task 3: Auth (bearer-token check)

**Files:**
- Create: `src/ops/web/auth.py`
- Create: `tests/unit/test_gui_auth.py`

**Interfaces:**
- Produces:
  - `token_ok(supplied: str | None) -> bool` — constant-time compare against `TITAN_GUI_TOKEN` env; if the env var is unset/empty, returns `False` (fail closed).
  - `require_token(authorization: str | None)` — FastAPI dependency; raises `HTTPException(401)` unless the `Authorization: Bearer <token>` header matches. Used on REST routes.
  - `ws_token_ok(token: str | None) -> bool` — for the WS query-param check.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_auth.py
import unittest
import os
from src.ops.web import auth
from fastapi import HTTPException


class TestTokenOk(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("TITAN_GUI_TOKEN")
        os.environ["TITAN_GUI_TOKEN"] = "sekret"

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("TITAN_GUI_TOKEN", None)
        else:
            os.environ["TITAN_GUI_TOKEN"] = self._prev

    def test_correct_token_passes(self):
        self.assertTrue(auth.token_ok("sekret"))
        self.assertTrue(auth.ws_token_ok("sekret"))

    def test_wrong_or_missing_token_fails(self):
        self.assertFalse(auth.token_ok("nope"))
        self.assertFalse(auth.token_ok(None))
        self.assertFalse(auth.ws_token_ok(None))

    def test_unset_env_fails_closed(self):
        os.environ.pop("TITAN_GUI_TOKEN", None)
        self.assertFalse(auth.token_ok("sekret"))

    def test_require_token_dependency(self):
        # Correct header → no raise
        auth.require_token("Bearer sekret")
        # Missing / malformed → 401
        with self.assertRaises(HTTPException) as ctx:
            auth.require_token(None)
        self.assertEqual(ctx.exception.status_code, 401)
        with self.assertRaises(HTTPException):
            auth.require_token("sekret")  # no "Bearer " prefix


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_auth -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.auth'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/auth.py
"""Bearer-token auth for the control API. Fails closed when the token is unset."""
import hmac
import os

from fastapi import Header, HTTPException


def _expected() -> str:
    return os.environ.get("TITAN_GUI_TOKEN", "") or ""


def token_ok(supplied: str | None) -> bool:
    expected = _expected()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def ws_token_ok(token: str | None) -> bool:
    return token_ok(token)


def require_token(authorization: str | None = Header(default=None)) -> None:
    prefix = "Bearer "
    supplied = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else None
    if not token_ok(supplied):
        raise HTTPException(status_code=401, detail="invalid or missing token")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_auth -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/auth.py tests/unit/test_gui_auth.py
git commit -m "feat(gui): bearer-token auth (fail-closed) for REST + WS"
```

---

## Task 4: State snapshot builder

**Files:**
- Create: `src/ops/web/state_view.py`
- Create: `tests/unit/test_gui_state_view.py`

**Interfaces:**
- Produces: `build_snapshot(controller) -> dict` with shape:
  ```
  {"health": {"bridge_connected": bool, "last_heartbeat_age_s": float,
              "paused": bool, "last_error": str | None},
   "account": {"balance": float, "equity": float},
   "positions": [{"ticket","symbol","side","lots","entry","sl","tp","pnl","grade","strategy"}]}
  ```
- Consumes (read-only, from the controller): `.current_open_positions` (list of HEARTBEAT
  dicts), `.last_heartbeat_time` (datetime), `.is_manual_pause` (bool),
  `.risk_manager.current_equity` / `.starting_balance`, `.state_manager.get_order(ticket)`
  (returns a row dict with `grade`, `strategy`, or `None`), and optional `.last_error` (str).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_state_view.py
import unittest
from datetime import datetime, timedelta
from src.ops.web.state_view import build_snapshot


class FakeRisk:
    current_equity = 10250.0
    starting_balance = 10000.0


class FakeState:
    def __init__(self, rows):
        self._rows = rows

    def get_order(self, ticket):
        return self._rows.get(ticket)


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now() - timedelta(seconds=2)
        self.is_manual_pause = False
        self.risk_manager = FakeRisk()
        self.last_error = None
        self.current_open_positions = [
            {"t": 123, "s": "EURUSD", "p": 1.1000, "sl": 1.0950, "tp": 1.1100,
             "pf": 12.5, "vol": 0.10, "type": 0, "comment": "SB"},
        ]
        self.state_manager = FakeState({123: {"grade": "A+", "strategy": "silver_bullet"}})


class TestSnapshot(unittest.TestCase):
    def test_positions_mapped_with_side_and_journal_fields(self):
        snap = build_snapshot(FakeController())
        self.assertEqual(len(snap["positions"]), 1)
        pos = snap["positions"][0]
        self.assertEqual(pos["ticket"], 123)
        self.assertEqual(pos["symbol"], "EURUSD")
        self.assertEqual(pos["side"], "BUY")     # type 0
        self.assertEqual(pos["lots"], 0.10)
        self.assertEqual(pos["pnl"], 12.5)
        self.assertEqual(pos["grade"], "A+")     # backfilled from state_manager
        self.assertEqual(pos["strategy"], "silver_bullet")

    def test_sell_side_and_missing_journal_row(self):
        c = FakeController()
        c.current_open_positions[0]["type"] = 1
        c.state_manager = type("S", (), {"get_order": staticmethod(lambda t: None)})()
        pos = build_snapshot(c)["positions"][0]
        self.assertEqual(pos["side"], "SELL")
        self.assertEqual(pos["grade"], "")       # graceful default
        self.assertEqual(pos["strategy"], "")

    def test_health_and_account(self):
        snap = build_snapshot(FakeController())
        self.assertTrue(snap["health"]["bridge_connected"])   # 2s < 60s threshold
        self.assertLess(snap["health"]["last_heartbeat_age_s"], 60)
        self.assertFalse(snap["health"]["paused"])
        self.assertEqual(snap["account"]["equity"], 10250.0)
        self.assertEqual(snap["account"]["balance"], 10000.0)

    def test_stale_heartbeat_marks_disconnected(self):
        c = FakeController()
        c.last_heartbeat_time = datetime.now() - timedelta(seconds=120)
        self.assertFalse(build_snapshot(c)["health"]["bridge_connected"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_state_view -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.state_view'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/state_view.py
"""Assemble the read-only /api/state snapshot from live controller state."""
from datetime import datetime

_HEARTBEAT_STALE_S = 60.0


def build_snapshot(controller) -> dict:
    age = (datetime.now() - controller.last_heartbeat_time).total_seconds()
    rm = controller.risk_manager
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
    }


def _map_position(controller, p: dict) -> dict:
    ticket = int(p.get("t", 0))
    row = None
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
        "grade": (row or {}).get("grade", "") if row else "",
        "strategy": (row or {}).get("strategy", "") if row else "",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_state_view -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/state_view.py tests/unit/test_gui_state_view.py
git commit -m "feat(gui): build_snapshot — /api/state from live positions + journal"
```

---

## Task 5: Command router (with confirm-gate)

**Files:**
- Create: `src/ops/web/commands.py`
- Create: `tests/unit/test_gui_commands.py`

**Interfaces:**
- Produces: `async execute_command(controller, payload: dict) -> dict`.
  - `payload`: `{"command": str, "ticket"?: int, "confirm"?: bool}`.
  - Valid commands: `pause`, `resume`, `close`, `closeall`, `panic`, `cancel`.
  - Destructive (`closeall`, `panic`) require `confirm is True`, else return
    `{"status": "needs_confirm"}` WITHOUT calling the controller.
  - Unknown command → returns `{"status": "error", "detail": "unknown command"}`.
  - Maps to existing controller coroutines/methods:
    `set_system_pause(bool)`, `close_specific_market_order(int)` (needs `ticket`),
    `close_all_market_orders()`, `trigger_panic()`, `cancel_pending_orders(target|None)`.
  - Returns `{"status": "ok", "result": <method return>}` on success.

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

    async def close_specific_market_order(self, ticket):
        self.calls.append(("close", ticket))
        return f"closed {ticket}"

    async def close_all_market_orders(self):
        self.calls.append(("closeall",))
        return 3

    async def trigger_panic(self):
        self.calls.append(("panic",))

    async def cancel_pending_orders(self, target):
        self.calls.append(("cancel", target))
        return "cancelled"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCommands(unittest.TestCase):
    def test_pause_and_resume(self):
        c = FakeController()
        self.assertEqual(run(execute_command(c, {"command": "pause"}))["result"], "PAUSED")
        self.assertEqual(run(execute_command(c, {"command": "resume"}))["result"], "ACTIVE")
        self.assertIn(("pause", True), c.calls)
        self.assertIn(("pause", False), c.calls)

    def test_close_requires_ticket(self):
        c = FakeController()
        res = run(execute_command(c, {"command": "close"}))
        self.assertEqual(res["status"], "error")
        res2 = run(execute_command(c, {"command": "close", "ticket": 42}))
        self.assertEqual(res2["result"], "closed 42")

    def test_closeall_needs_confirm(self):
        c = FakeController()
        res = run(execute_command(c, {"command": "closeall"}))
        self.assertEqual(res["status"], "needs_confirm")
        self.assertEqual(c.calls, [])                                  # not called
        res2 = run(execute_command(c, {"command": "closeall", "confirm": True}))
        self.assertEqual(res2["result"], 3)

    def test_panic_needs_confirm(self):
        c = FakeController()
        self.assertEqual(run(execute_command(c, {"command": "panic"}))["status"], "needs_confirm")
        run(execute_command(c, {"command": "panic", "confirm": True}))
        self.assertIn(("panic",), c.calls)

    def test_unknown_command(self):
        c = FakeController()
        self.assertEqual(run(execute_command(c, {"command": "boom"}))["status"], "error")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_commands -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.commands'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/commands.py
"""Map GUI command payloads onto existing controller methods. No new trade logic."""

_DESTRUCTIVE = {"closeall", "panic"}


async def execute_command(controller, payload: dict) -> dict:
    command = payload.get("command")
    confirm = payload.get("confirm") is True

    if command in _DESTRUCTIVE and not confirm:
        return {"status": "needs_confirm", "command": command}

    if command == "pause":
        return {"status": "ok", "result": controller.set_system_pause(True)}
    if command == "resume":
        return {"status": "ok", "result": controller.set_system_pause(False)}
    if command == "close":
        ticket = payload.get("ticket")
        if not isinstance(ticket, int):
            return {"status": "error", "detail": "close requires integer 'ticket'"}
        return {"status": "ok", "result": await controller.close_specific_market_order(ticket)}
    if command == "closeall":
        return {"status": "ok", "result": await controller.close_all_market_orders()}
    if command == "panic":
        await controller.trigger_panic()
        return {"status": "ok", "result": "panic_executed"}
    if command == "cancel":
        target = payload.get("ticket")
        return {"status": "ok", "result": await controller.cancel_pending_orders(target)}

    return {"status": "error", "detail": "unknown command"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_commands -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/commands.py tests/unit/test_gui_commands.py
git commit -m "feat(gui): command router with confirm-gate over existing controller methods"
```

---

## Task 6: EventHub (WS pub/sub)

**Files:**
- Create: `src/ops/web/events.py`
- Create: `tests/unit/test_gui_events.py`

**Interfaces:**
- Produces:
  - `EventHub()` — in-process fan-out.
  - `.subscribe() -> asyncio.Queue` — registers a new subscriber queue.
  - `.unsubscribe(queue)` — removes it.
  - `.publish(event: dict) -> None` — non-blocking put to every subscriber; drops the
    event for any full queue (a slow/dead client must never block the publisher).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_events.py
import unittest
import asyncio
from src.ops.web.events import EventHub


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestEventHub(unittest.TestCase):
    def test_publish_reaches_all_subscribers(self):
        hub = EventHub()
        q1, q2 = hub.subscribe(), hub.subscribe()
        hub.publish({"type": "event", "kind": "signal"})
        self.assertEqual(run(q1.get())["kind"], "signal")
        self.assertEqual(run(q2.get())["kind"], "signal")

    def test_unsubscribe_stops_delivery(self):
        hub = EventHub()
        q = hub.subscribe()
        hub.unsubscribe(q)
        hub.publish({"type": "event"})
        self.assertTrue(q.empty())

    def test_full_queue_is_dropped_not_raised(self):
        hub = EventHub()
        q = hub.subscribe(maxsize=1)
        hub.publish({"n": 1})
        hub.publish({"n": 2})   # queue full → dropped, must not raise
        self.assertEqual(run(q.get())["n"], 1)
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_events -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.events'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/events.py
"""In-process async pub/sub for the WebSocket feed. Publisher never blocks."""
import asyncio


class EventHub:
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self, event: dict) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow/dead client — drop rather than block the publisher
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_events -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/events.py tests/unit/test_gui_events.py
git commit -m "feat(gui): EventHub in-process pub/sub for WS feed"
```

---

## Task 7: FastAPI app (routes wired end-to-end)

**Files:**
- Create: `src/ops/web/server.py`
- Create: `tests/unit/test_gui_server.py`

**Interfaces:**
- Consumes: `require_token` (Task 3), `build_snapshot` (Task 4), `execute_command`
  (Task 5), `EventHub` (Task 6), `SettingsStore` (Task 2).
- Produces:
  - `create_app(controller, settings_store, event_hub) -> FastAPI` — routes:
    `GET /api/state`, `GET /api/settings`, `PATCH /api/settings`, `POST /api/command`
    (all require token), plus `WS /ws`. When a PATCHed key is safe-subset, the route
    calls `controller.apply_runtime_setting(key, value)` after `settings_store.set(...)`.
  - `start(controller, settings_store, event_hub) -> asyncio.Task` — builds a
    `uvicorn.Server` bound to `TITAN_GUI_BIND`/`:8770` and returns
    `asyncio.create_task(server.serve())`. (Not exercised in unit tests.)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gui_server.py
import unittest
import os
import tempfile
from pathlib import Path
from datetime import datetime
from fastapi.testclient import TestClient
from src.ops.web.server import create_app
from src.ops.web.settings import SettingsStore
from src.ops.web.events import EventHub

DEFAULTS = {"signal_grading": {"enabled": True, "min_grade": "B"},
            "connection": {"zeromq": {"push_port": 32768}}}


class FakeRisk:
    current_equity = 10000.0
    starting_balance = 10000.0


class FakeController:
    def __init__(self):
        self.last_heartbeat_time = datetime.now()
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = FakeRisk()
        self.current_open_positions = []
        self.state_manager = type("S", (), {"get_order": staticmethod(lambda t: None)})()
        self.applied = []

    def set_system_pause(self, p):
        self.is_manual_pause = p
        return "PAUSED" if p else "ACTIVE"

    def apply_runtime_setting(self, key, value):
        self.applied.append((key, value))


def _client(tmp):
    os.environ["TITAN_GUI_TOKEN"] = "sekret"
    store = SettingsStore(DEFAULTS, Path(tmp) / "overrides.yaml")
    app = create_app(FakeController(), store, EventHub())
    return TestClient(app), app


AUTH = {"Authorization": "Bearer sekret"}


class TestServer(unittest.TestCase):
    def test_state_requires_auth(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = _client(d)
            self.assertEqual(client.get("/api/state").status_code, 401)
            r = client.get("/api/state", headers=AUTH)
            self.assertEqual(r.status_code, 200)
            self.assertIn("positions", r.json())

    def test_command_pause(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = _client(d)
            r = client.post("/api/command", json={"command": "pause"}, headers=AUTH)
            self.assertEqual(r.json()["result"], "PAUSED")

    def test_patch_safe_setting_applies_live(self):
        with tempfile.TemporaryDirectory() as d:
            client, app = _client(d)
            r = client.patch("/api/settings",
                             json={"key": "signal_grading.min_grade", "value": "A"}, headers=AUTH)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["applied"], "live")
            self.assertIn(("signal_grading.min_grade", "A"),
                          app.state.controller.applied)

    def test_patch_invalid_returns_422(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = _client(d)
            r = client.patch("/api/settings",
                             json={"key": "signal_grading.min_grade", "value": "Z"}, headers=AUTH)
            self.assertEqual(r.status_code, 422)

    def test_patch_restart_key_not_applied_live(self):
        with tempfile.TemporaryDirectory() as d:
            client, app = _client(d)
            r = client.patch("/api/settings",
                             json={"key": "connection.zeromq.push_port", "value": 40000}, headers=AUTH)
            self.assertTrue(r.json()["restart_required"])
            self.assertEqual(app.state.controller.applied, [])   # never live-applied

    def test_get_settings_lists_tagged_rows(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = _client(d)
            rows = client.get("/api/settings", headers=AUTH).json()["settings"]
            keys = {r["key"] for r in rows}
            self.assertIn("signal_grading.min_grade", keys)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_server -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.server'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ops/web/server.py
"""FastAPI app + uvicorn task for the embedded control API."""
import asyncio
import os

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import auth
from .commands import execute_command
from .state_view import build_snapshot


def create_app(controller, settings_store, event_hub) -> FastAPI:
    app = FastAPI(title="Titan Control API")
    app.state.controller = controller
    app.state.settings = settings_store
    app.state.events = event_hub

    @app.get("/api/state", dependencies=[Depends(auth.require_token)])
    def get_state():
        return build_snapshot(controller)

    @app.post("/api/command", dependencies=[Depends(auth.require_token)])
    async def post_command(payload: dict):
        return await execute_command(controller, payload)

    @app.get("/api/settings", dependencies=[Depends(auth.require_token)])
    def get_settings():
        return {"settings": settings_store.describe()}

    @app.patch("/api/settings", dependencies=[Depends(auth.require_token)])
    def patch_settings(payload: dict):
        key, value = payload.get("key"), payload.get("value")
        try:
            result = settings_store.set(key, value)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})
        if settings_store.is_safe(key):
            controller.apply_runtime_setting(key, value)
        return result

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        token = websocket.query_params.get("token")
        if not auth.ws_token_ok(token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "state", **build_snapshot(controller)})
        queue = event_hub.subscribe()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            event_hub.unsubscribe(queue)

    return app


def start(controller, settings_store, event_hub) -> asyncio.Task:
    """Build a uvicorn Server on the same loop and return its serve() task."""
    import uvicorn  # local import: keep module import light for unit tests

    app = create_app(controller, settings_store, event_hub)
    host = os.environ.get("TITAN_GUI_BIND", "127.0.0.1")
    config = uvicorn.Config(app, host=host, port=8770, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    return asyncio.create_task(server.serve())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_server -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/server.py tests/unit/test_gui_server.py
git commit -m "feat(gui): FastAPI app — state/command/settings routes + WS, token-gated"
```

---

## Task 8: Controller integration + housekeeping

**Files:**
- Modify: `src/core/system_controller.py` (`_load_config` ~126-131; add `apply_runtime_setting`; start web task in `run()` before the `while True:` ~163)
- Modify: `src/ops/telemetry.py` (`notify_signal`/`notify_execution`/`notify_close`/`notify_management`/`notify_partial` — add event-hub publish)
- Modify: `requirements.txt`, `.env.example`, `.gitignore`
- Create: `tests/unit/test_gui_apply_runtime.py`

**Interfaces:**
- Consumes: `load_layered_config` (Task 1), `SettingsStore` (Task 2), `EventHub` (Task 6),
  `server.start` (Task 7).
- Produces on the controller:
  - `.apply_runtime_setting(key: str, value) -> None` — updates in-memory `self.config`
    at the dotted key AND pushes to the owning object for the known live keys
    (`signal_grading.min_grade`/`enabled` → `self.signal_grader`;
    `risk.*` → already read live from `self.config` by RiskManager, so config update
    suffices; `strategies.<name>.enabled` → toggles the matching strategy's `enabled`;
    `trade_management.runner.*` → `self.trade_manager`).
  - `.event_hub` (EventHub instance) available to telemetry.

- [ ] **Step 1: Write the failing test (apply_runtime_setting, in isolation)**

```python
# tests/unit/test_gui_apply_runtime.py
import unittest
from src.core.system_controller import _apply_runtime_setting


class Grader:
    def __init__(self):
        self.min_grade = "B"
        self.enabled = True


class Strat:
    def __init__(self, name):
        self.name = name
        self.enabled = True


class FakeController:
    def __init__(self):
        self.config = {"signal_grading": {"min_grade": "B", "enabled": True},
                       "risk": {"trade": {"risk_per_trade_pct": 1.0}},
                       "strategies": {"silver_bullet": {"enabled": True}}}
        self.signal_grader = Grader()
        self.strategies = [Strat("silver_bullet")]


class TestApplyRuntime(unittest.TestCase):
    def test_min_grade_updates_config_and_grader(self):
        c = FakeController()
        _apply_runtime_setting(c, "signal_grading.min_grade", "A")
        self.assertEqual(c.config["signal_grading"]["min_grade"], "A")
        self.assertEqual(c.signal_grader.min_grade, "A")

    def test_risk_pct_updates_config(self):
        c = FakeController()
        _apply_runtime_setting(c, "risk.trade.risk_per_trade_pct", 0.5)
        self.assertEqual(c.config["risk"]["trade"]["risk_per_trade_pct"], 0.5)

    def test_strategy_enabled_toggles_matching_strategy(self):
        c = FakeController()
        _apply_runtime_setting(c, "strategies.silver_bullet.enabled", False)
        self.assertFalse(c.config["strategies"]["silver_bullet"]["enabled"])
        self.assertFalse(c.strategies[0].enabled)


if __name__ == "__main__":
    unittest.main()
```

> Implementation note: `_apply_runtime_setting(controller, key, value)` is a **module-level
> function** in `system_controller.py`; the controller method `apply_runtime_setting`
> delegates to it. This keeps the logic unit-testable without constructing the full
> controller (which opens ZMQ). Match the `signal_grader` attribute name to the real
> field set in `__init__` (line 92: `self.signal_grader = SignalGrader(self.config)`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_apply_runtime -v`
Expected: FAIL — `ImportError: cannot import name '_apply_runtime_setting'`

- [ ] **Step 3: Add the module-level helper + method to `system_controller.py`**

Add near the top-level of the module (after imports, before the class):

```python
def _apply_runtime_setting(controller, key: str, value) -> None:
    """Update in-memory config at `key` and push to the owning live object."""
    # 1. Update the nested config dict.
    parts = key.split(".")
    node = controller.config
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

    # 2. Push to the owning object for keys that cache their value.
    if key == "signal_grading.min_grade":
        controller.signal_grader.min_grade = value
    elif key == "signal_grading.enabled":
        controller.signal_grader.enabled = value
    elif key.startswith("strategies.") and key.endswith(".enabled"):
        target = key.split(".")[1]
        for strat in controller.strategies:
            if getattr(strat, "name", None) == target:
                strat.enabled = value
    # risk.* and trade_management.runner.* are re-read from controller.config each
    # cycle by RiskManager / TradeManager, so the config update above is sufficient.
```

Add the delegating method inside the `SystemController` class (near the other control
methods, e.g. after `set_system_pause` ~658):

```python
    def apply_runtime_setting(self, key: str, value) -> None:
        _apply_runtime_setting(self, key, value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_apply_runtime -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire layered config into `_load_config`**

Replace the body of `_load_config` (currently reads only `config.yaml`) with:

```python
    def _load_config(self):
        from src.ops.web.config_layer import load_layered_config
        cfg_dir = self.root_dir / "config"
        cfg_path = cfg_dir / "config.yaml"
        if not cfg_path.exists():
            sys.exit(f"[FATAL] config.yaml not found at {cfg_path}")
        return load_layered_config(cfg_path, cfg_dir / "overrides.yaml")
```

- [ ] **Step 6: Create the EventHub + SettingsStore on the controller and start the web task**

In `__init__` (after `self.telemetry` is created, ~71), add:

```python
        from src.ops.web.events import EventHub
        from src.ops.web.settings import SettingsStore
        self.event_hub = EventHub()
        self._settings_store = SettingsStore(
            self.config, self.root_dir / "config" / "overrides.yaml")
        self.telemetry.event_hub = self.event_hub
```

In `run()`, immediately before `try:` / `while True:` (~163), add:

```python
        # --- Embedded control API (optional; never blocks trading) ---
        try:
            from src.ops.web import server as web_server
            self._web_task = web_server.start(self, self._settings_store, self.event_hub)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Control API on :8770")
        except Exception as e:
            self.logger.log_event("WARN", "GUI", f"Control API failed to start: {e}")
            self._web_task = None
```

- [ ] **Step 7: Publish events from telemetry**

In `src/ops/telemetry.py`, add a helper near the top of `TelegramBot` and call it from
each `notify_*`. Add after `__init__` sets fields:

```python
    def _publish(self, kind, **data):
        hub = getattr(self, "event_hub", None)
        if hub is not None:
            try:
                hub.publish({"type": "event", "kind": kind, **data})
            except Exception:
                pass  # telemetry/GUI must never break the trading path
```

Then in each notify method add one line (example for `notify_signal`):

```python
        self._publish("signal", symbol=symbol, strategy=strategy, side=side,
                      size=size, price=price, sl=sl, tp=tp)
```

Add analogous `self._publish(...)` calls in `notify_execution` (kind `"execution"`),
`notify_close` (kind `"close"`), `notify_management` (kind `"management"`), and
`notify_partial` (kind `"partial"`), passing that method's arguments as kwargs.

- [ ] **Step 8: Housekeeping — deps, env, gitignore**

Add to `requirements.txt` under "Network & Telemetry":

```
# Control GUI API (embedded)
fastapi>=0.115,<1.0
uvicorn>=0.30,<1.0
```

Add to `.env.example`:

```
# Control GUI API bearer token (required for the web dashboard)
TITAN_GUI_TOKEN=change-me-to-a-long-random-string
# Bind address: 127.0.0.1 (default, local only) or 0.0.0.0 (VPS, behind TLS proxy only)
TITAN_GUI_BIND=127.0.0.1
```

Add to `.gitignore` (config overrides are machine-specific state, not source):

```
config/overrides.yaml
```

- [ ] **Step 9: Run the full GUI suite + the existing suite (no regressions)**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_gui_*.py' -v`
Expected: PASS (all GUI modules)

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: PASS — existing tests still green (config-loading change is backward-compatible:
no `overrides.yaml` → identical behavior).

- [ ] **Step 10: Commit**

```bash
git add src/core/system_controller.py src/ops/telemetry.py requirements.txt .env.example .gitignore tests/unit/test_gui_apply_runtime.py
git commit -m "feat(gui): wire control API into controller — layered config, apply_runtime_setting, event publish"
```

---

## Task 9: Live smoke test against a running controller (manual verify)

**Files:** none (verification only).

This proves the API actually serves from a live process end-to-end. Requires MT5 + the
EA reachable (or run it and accept that positions may be empty). If MT5 is unavailable,
at minimum confirm the server starts and auth works.

- [ ] **Step 1: Set a token and launch the bot**

```bash
export TITAN_GUI_TOKEN=devtoken
.venv/bin/python main.py
```
Expected: console prints `Control API on :8770` shortly after `TRANSITION TO ACTIVE MODE`.

- [ ] **Step 2: Hit the API from a second shell**

```bash
curl -s localhost:8770/api/state -H "Authorization: Bearer devtoken" | head -c 400
curl -s -o /dev/null -w "%{http_code}\n" localhost:8770/api/state      # no token → 401
```
Expected: first prints a JSON snapshot with `health`/`account`/`positions`; second prints `401`.

- [ ] **Step 3: Exercise a safe setting live**

```bash
curl -s -X PATCH localhost:8770/api/settings \
  -H "Authorization: Bearer devtoken" -H "Content-Type: application/json" \
  -d '{"key":"signal_grading.min_grade","value":"A"}'
```
Expected: `{"applied":"live","restart_required":false,"value":"A"}`; `config/overrides.yaml`
now exists with that key; the bot did NOT restart and kept logging heartbeats.

- [ ] **Step 4: Confirm the trading loop was never blocked**

Watch the console/logs for continued HEARTBEAT processing while hitting the API. Confirm
no stall in heartbeat cadence during requests (this is the "loop must yield" risk from
the spec — record the observed heartbeat interval as evidence).

- [ ] **Step 5: Commit (docs only, if you captured notes)**

```bash
git commit --allow-empty -m "test(gui): manual smoke — control API live, loop unblocked"
```

---

## Self-Review

**Spec coverage:**
- Embedded FastAPI+WS in controller loop → Tasks 7, 8. ✅
- Token auth, localhost default, VPS bind env → Task 3, Task 8 (env). ✅
- `/api/state`, `/api/command`, `/api/settings`, `/ws` contract → Tasks 4–7. ✅
- Layered config defaults→overrides → Tasks 1, 8. ✅
- Safe-subset live vs restart-tier, server-side whitelist, 422 validation → Tasks 2, 7, 8. ✅
- Reuse existing control methods, no new trade logic → Task 5. ✅
- Isolation: optional start, never blocks loop → Task 8 (try/except start), Task 9 (verify). ✅
- Event feed mirrors Telegram → Task 6, Task 8 Step 7. ✅
- Tests in stdlib unittest, isolated via fakes → every task. ✅
- Frontend (React Live + Settings tabs) → **separate plan** (Phase 1b), not covered here.

**Placeholder scan:** none — every step has complete code or an exact command.

**Type consistency:** `SettingsStore.set/is_safe/describe/validate`, `build_snapshot`,
`execute_command`, `EventHub.subscribe/unsubscribe/publish`, `create_app(controller,
settings_store, event_hub)`, `apply_runtime_setting(key, value)` are used consistently
across Tasks 2–8. Position keys (`t/s/p/sl/tp/pf/vol/type`) match the EA serialization.

## Out of scope (this plan)

The React frontend (Vite app, Live tab, Settings tab, WS hook) is **Phase 1b** — a
separate plan that consumes this API. The backend here is independently testable and
shippable via `curl`/TestClient.
