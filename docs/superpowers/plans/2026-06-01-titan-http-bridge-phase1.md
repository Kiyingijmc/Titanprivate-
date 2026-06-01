# Titan HTTP Bridge — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a Titan-owned HTTP MT5 bridge (copied from `~/mos/bridge`) plus an abstract `Broker` seam + httpx client on the Linux side, and rework history/specs export onto it — eliminating the EA `InpIP`-churn and wedge problems and unblocking reliable M5 data pulls. Execution primitives are implemented + tested in isolation (not wired into the live loop).

**Architecture:** Two processes. A FastAPI bridge runs on Windows (port **8766**, bearer auth) using the `MetaTrader5` package with per-call timeouts + a circuit breaker. WSL is the client: `src/execution/broker/mt5_http.py` (httpx) implements an abstract `Broker` protocol and is the only module coupled to the bridge wire format. Additive — the live ZMQ loop (`system_controller.py`, `bridge_zmq.py`, the EA) is untouched.

**Tech Stack:** Python 3.11 (Windows bridge) / Titan's `.venv` (Linux client); FastAPI + uvicorn + pydantic + MetaTrader5 (bridge, copied from MOS); `httpx` (new Linux runtime dep); stdlib `unittest` + `httpx.MockTransport` for tests (NO pytest, NO respx — see note).

**Spec:** `docs/superpowers/specs/2026-06-01-titan-http-bridge-phase1-design.md`
**Reference source (copy/port from):** `~/mos/bridge/` and `~/mos/src/mos/data/broker/`

> **Deviation from spec (dependencies):** the spec approved `httpx` + `respx`. During planning we found `httpx.MockTransport` (bundled with httpx) covers all client tests under `unittest.IsolatedAsyncioTestCase`, so **`respx` is NOT added** — only `httpx`. Fewer deps, consistent with the repo's stdlib-unittest convention.

> **Test commands:** Titan Linux unit suite — `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`. Bridge surface tests run in the *bridge's* Python env (where fastapi + a mocked `MetaTrader5` are importable) — `python -m unittest discover -s bridge/tests`. The opt-in live test is gated by `TITAN_BRIDGE_LIVE_TEST=1`.

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `bridge/app/{__init__,settings,models,circuit,mt5_client,main}.py` | Windows FastAPI MT5 bridge | Copy from `~/mos/bridge` + edits |
| `bridge/run_bridge.py`, `bridge/requirements.txt`, `bridge/config/.env.example` | Bridge entrypoint/deps/config | Copy + edits |
| `bridge/tests/test_surface.py` | Bridge surface tests (MT5 mocked) | Create |
| `src/execution/broker/__init__.py` | Package | Create |
| `src/execution/broker/types.py` | Linux-side domain types (StrEnums, Account, Candle, SymbolInfo+tick, Position, Order, requests, OrderResult) | Create (port) |
| `src/execution/broker/errors.py` | Typed broker errors | Create (port) |
| `src/execution/broker/base.py` | Abstract `Broker` Protocol (the seam) | Create (port) |
| `src/execution/broker/mt5_http.py` | httpx client implementing `Broker` | Create (port) |
| `scripts/export_history.py` | History export via broker (chunked range) | Rework |
| `scripts/cache_specs.py` | Specs export via broker | Rework |
| `scripts/check_bridge_http.py` | HTTP health check | Create |
| `tests/unit/test_broker_url.py`, `test_broker_mt5_http.py`, `test_export_history_http.py`, `test_cache_specs_http.py` | Linux unit tests | Create |
| `tests/integration/test_bridge_live.py` | Opt-in live round-trip | Create |
| `requirements.txt`, `CLAUDE.md`, `.env.example` | Deps + docs + env template | Modify |
| `scripts/check_bridge.py`, `src/execution/bridge_zmq.py`, `src/core/system_controller.py`, the EA | ZMQ live path | **Leave untouched** |

---

## Task 1: Copy the bridge skeleton (settings, circuit, runner, deps, env)

**Files:**
- Create: `bridge/app/__init__.py`, `bridge/app/settings.py`, `bridge/app/circuit.py`, `bridge/run_bridge.py`, `bridge/requirements.txt`, `bridge/config/.env.example`, `bridge/.gitignore`

- [ ] **Step 1: Copy the proven files verbatim**

```bash
cd /home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro
mkdir -p bridge/app bridge/config bridge/tests bridge/logs
cp ~/mos/bridge/app/__init__.py        bridge/app/__init__.py
cp ~/mos/bridge/app/settings.py        bridge/app/settings.py
cp ~/mos/bridge/app/circuit.py         bridge/app/circuit.py
cp ~/mos/bridge/run_bridge.py          bridge/run_bridge.py
cp ~/mos/bridge/requirements.txt       bridge/requirements.txt
cp ~/mos/bridge/config/.env.example    bridge/config/.env.example
printf 'config/.env\nlogs/*.log\nlogs/*.zip\n__pycache__/\n' > bridge/.gitignore
touch bridge/tests/__init__.py
```

- [ ] **Step 2: Edit `bridge/app/settings.py` — default port 8766**

Change the one line:
```python
    bridge_port: int = 8765
```
to:
```python
    bridge_port: int = 8766
```
(Leave everything else — `bridge_auth_token`, `mt5_*`, `model_config` env_file — exactly as copied.)

- [ ] **Step 3: Edit `bridge/config/.env.example` — port 8766 + fresh token placeholder**

Set:
```
BRIDGE_HOST=0.0.0.0
BRIDGE_PORT=8766
BRIDGE_AUTH_TOKEN=CHANGE_ME_generate_a_long_random_token
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_PATH=
LOG_LEVEL=INFO
LOG_FILE=logs/bridge.log
```

- [ ] **Step 4: Verify the copy is syntactically valid (Linux, no MT5 needed)**

Run: `.venv/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['bridge/app/settings.py','bridge/app/circuit.py','bridge/run_bridge.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add bridge/app/__init__.py bridge/app/settings.py bridge/app/circuit.py bridge/run_bridge.py bridge/requirements.txt bridge/config/.env.example bridge/.gitignore bridge/tests/__init__.py
git commit -m "feat(bridge): scaffold Titan HTTP bridge (copied from MOS, port 8766)"
```

---

## Task 2: Bridge models — copy + add `tick_value`/`tick_size` to `SymbolInfo`

**Files:**
- Create: `bridge/app/models.py`

- [ ] **Step 1: Copy MOS models**

```bash
cp ~/mos/bridge/app/models.py bridge/app/models.py
```

- [ ] **Step 2: Extend `SymbolInfo` with the two fields Titan's risk_manager needs**

In `bridge/app/models.py`, change the `SymbolInfo` model from:
```python
class SymbolInfo(BaseModel):
    name: str
    digits: int
    point: float
    spread: int
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_mode: int
```
to (add `tick_value` and `tick_size`):
```python
class SymbolInfo(BaseModel):
    name: str
    digits: int
    point: float
    spread: int
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_mode: int
    tick_value: float
    tick_size: float
```

- [ ] **Step 3: Verify syntax**

Run: `.venv/bin/python -c "import ast; ast.parse(open('bridge/app/models.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add bridge/app/models.py
git commit -m "feat(bridge): copy models + add tick_value/tick_size to SymbolInfo"
```

---

## Task 3: Bridge mt5_client + main — copy, populate tick fields

**Files:**
- Create: `bridge/app/mt5_client.py`, `bridge/app/main.py`

- [ ] **Step 1: Copy both verbatim**

```bash
cp ~/mos/bridge/app/mt5_client.py bridge/app/mt5_client.py
cp ~/mos/bridge/app/main.py       bridge/app/main.py
```

- [ ] **Step 2: Populate `tick_value`/`tick_size` in `mt5_client.get_symbol_info`**

In `bridge/app/mt5_client.py`, find the `get_symbol_info` method's `SymbolInfo(...)` construction and add the two fields sourced from the MT5 symbol info object (the raw object exposes `trade_tick_value` and `trade_tick_size`). For example, if the code reads:
```python
        return SymbolInfo(
            name=info.name,
            digits=info.digits,
            point=info.point,
            spread=info.spread,
            contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            trade_mode=info.trade_mode,
        )
```
change it to add the two fields:
```python
        return SymbolInfo(
            name=info.name,
            digits=info.digits,
            point=info.point,
            spread=info.spread,
            contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            trade_mode=info.trade_mode,
            tick_value=info.trade_tick_value,
            tick_size=info.trade_tick_size,
        )
```
(Match the surrounding field-sourcing style exactly as copied; only add the two `tick_*` lines.)

- [ ] **Step 3: Verify syntax (Linux; MT5 import will fail at runtime but ast.parse won't)**

Run: `.venv/bin/python -c "import ast; ast.parse(open('bridge/app/mt5_client.py').read()); ast.parse(open('bridge/app/main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add bridge/app/mt5_client.py bridge/app/main.py
git commit -m "feat(bridge): copy mt5_client + main; populate tick_value/tick_size"
```

---

## Task 4: Bridge surface tests (MT5 mocked)

**Files:**
- Create: `bridge/tests/test_surface.py`
- Test runs in the bridge env: `pip install -r bridge/requirements.txt` on the machine running these (or a venv with fastapi+pydantic-settings). `MetaTrader5` is mocked, so it runs on Linux too once fastapi is present.

- [ ] **Step 1: Write the failing test**

```python
# bridge/tests/test_surface.py
import os, sys, types, unittest
from unittest.mock import MagicMock

# The bridge imports `MetaTrader5` (Windows-only). Inject a mock BEFORE importing the app
# so the FastAPI surface is importable/testable anywhere.
sys.modules.setdefault("MetaTrader5", MagicMock())
os.environ.setdefault("BRIDGE_AUTH_TOKEN", "testtoken")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastapi.testclient import TestClient  # noqa: E402
from app import main as bridge_main         # noqa: E402
from app.models import SymbolInfo           # noqa: E402


class Surface(unittest.TestCase):
    def setUp(self):
        # Replace the real MT5Client with a fake so no terminal is needed.
        self.fake = MagicMock()
        bridge_main._mt5 = self.fake
        bridge_main._circuit._healthy = True
        self.client = TestClient(bridge_main.app)
        self.auth = {"Authorization": "Bearer testtoken"}

    def test_health_needs_no_auth_and_no_mt5(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["status"], ("ok", "degraded", "down"))

    def test_symbol_requires_auth(self):
        r = self.client.get("/symbol/EURUSD")           # no header
        self.assertEqual(r.status_code, 401)

    def test_symbol_returns_tick_fields(self):
        async def _aget(_sym):
            return SymbolInfo(name="EURUSD", digits=5, point=1e-5, spread=8,
                              contract_size=100000.0, volume_min=0.01, volume_max=500.0,
                              volume_step=0.01, trade_mode=4, tick_value=1.0, tick_size=1e-5)
        self.fake.aget_symbol_info = _aget
        r = self.client.get("/symbol/EURUSD", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["tick_value"], 1.0)
        self.assertEqual(body["tick_size"], 1e-5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it (expect import/collection to work, tests pass)**

Run (in an env with `fastapi` installed — e.g. `pip install fastapi pydantic-settings loguru`): `python -m unittest discover -s bridge/tests -v`
Expected: 3 tests PASS. (If `fastapi` isn't installed in the Titan `.venv`, install the bridge requirements there or run on the bridge host. This suite is bridge-side, not part of the Titan Linux unit suite.)

- [ ] **Step 3: Commit**

```bash
git add bridge/tests/test_surface.py
git commit -m "test(bridge): surface tests (MT5 mocked) — auth, /health, /symbol tick fields"
```

---

## Task 5: Linux broker types + errors

**Files:**
- Create: `src/execution/broker/__init__.py`, `src/execution/broker/types.py`, `src/execution/broker/errors.py`
- Test: `tests/unit/test_broker_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_broker_types.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker import types as T
from src.execution.broker import errors as E


class Types(unittest.TestCase):
    def test_symbolinfo_has_tick_fields(self):
        s = T.SymbolInfo(name="XAUUSD", digits=2, point=0.01, spread_points=20,
                         contract_size=100.0, volume_min=0.01, volume_max=50.0,
                         volume_step=0.01, tick_value=1.0, tick_size=0.01)
        self.assertEqual(s.tick_value, 1.0)
        self.assertEqual(s.tick_size, 0.01)

    def test_enums(self):
        self.assertEqual(T.OrderSide.BUY.value, "buy")
        self.assertEqual(T.PendingOrderType.BUY_STOP.value, "buy_stop")
        self.assertEqual(T.Timeframe.M5.value, "M5")

    def test_error_hierarchy(self):
        for cls in (E.BrokerConnectionError, E.BrokerAuthError, E.BrokerNotFoundError):
            self.assertTrue(issubclass(cls, E.BrokerError))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_types -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.execution.broker'`

- [ ] **Step 3: Create the package + errors + types**

`src/execution/broker/__init__.py`:
```python
# Titan broker abstraction (HTTP bridge era). See docs/superpowers/specs/2026-06-01-titan-http-bridge-phase1-design.md
```

`src/execution/broker/errors.py`:
```python
"""Typed broker errors. Trading code catches these, never raw httpx/MT5 errors."""
from __future__ import annotations


class BrokerError(Exception):
    """Base for all broker-related errors."""


class BrokerConnectionError(BrokerError):
    """Network/transport failure reaching the bridge. Safe to retry reads; never writes."""


class BrokerAuthError(BrokerError):
    """Auth failure (bad/missing token)."""


class BrokerNotFoundError(BrokerError):
    """Requested resource (symbol, position, order) does not exist."""
```

`src/execution/broker/types.py`:
```python
"""Linux-side broker domain types. Trading code depends on these, never on bridge
wire types. SymbolInfo carries tick_value/tick_size (Titan's risk_manager sizes from
them) — the deliberate extension over MOS's model."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PendingOrderType(StrEnum):
    BUY_LIMIT = "buy_limit"
    SELL_LIMIT = "sell_limit"
    BUY_STOP = "buy_stop"
    SELL_STOP = "sell_stop"


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"


class HealthStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    broker_connected: bool
    uptime_seconds: int


class Account(BaseModel):
    model_config = ConfigDict(frozen=True)
    login: int
    server: str
    currency: str
    leverage: int
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    profit: float


class SymbolInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    digits: int
    point: float
    spread_points: int = Field(description="Current spread in points")
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    tick_value: float
    tick_size: float


class Tick(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    time: datetime
    bid: float
    ask: float
    spread: float = Field(description="ask - bid in price units")


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread_points: int


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticket: int
    symbol: str
    side: OrderSide
    volume: float
    price_open: float
    sl: float | None
    tp: float | None
    price_current: float
    profit: float
    swap: float
    commission: float
    time_open: datetime
    comment: str
    magic: int


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticket: int
    symbol: str
    type: PendingOrderType
    volume: float
    price_open: float
    sl: float | None
    tp: float | None
    time_setup: datetime
    comment: str
    magic: int


class MarketOrderRequest(BaseModel):
    symbol: str
    volume: float = Field(gt=0)
    side: OrderSide
    sl: float | None = None
    tp: float | None = None
    deviation_points: int = 20
    magic: int = 0
    comment: str = ""


class PendingOrderRequest(BaseModel):
    symbol: str
    volume: float = Field(gt=0)
    type: PendingOrderType
    price: float
    sl: float | None = None
    tp: float | None = None
    magic: int = 0
    comment: str = ""


class OrderResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    success: bool
    ticket: int | None = None
    price_filled: float | None = None
    volume_filled: float | None = None
    error_code: int | None = None
    error_message: str | None = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_types -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/execution/broker/__init__.py src/execution/broker/types.py src/execution/broker/errors.py tests/unit/test_broker_types.py
git commit -m "feat(broker): Linux-side domain types (+tick_value/tick_size) + errors (TDD)"
```

---

## Task 6: `Broker` protocol (the seam)

**Files:**
- Create: `src/execution/broker/base.py`
- Test: `tests/unit/test_broker_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_broker_base.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker.base import Broker


class BaseProto(unittest.TestCase):
    def test_protocol_is_runtime_checkable_and_lists_methods(self):
        for m in ("health_check", "get_account", "get_symbol_info", "get_candles",
                  "get_candles_range", "get_current_tick", "get_open_positions",
                  "get_pending_orders", "place_market_order", "place_pending_order",
                  "modify_position", "close_position", "cancel_order"):
            self.assertTrue(hasattr(Broker, m), f"protocol missing {m}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_base -v`
Expected: FAIL — `ModuleNotFoundError: ... base`

- [ ] **Step 3: Create `src/execution/broker/base.py`**

```python
"""Abstract Broker protocol — the seam. Trading code depends only on this + types.
All methods async; datetimes UTC; prices float; volume in lots. Reads raise BrokerError
subclasses on failure; writes return OrderResult(success=False) on broker rejection."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .types import (
    Account, Candle, HealthStatus, MarketOrderRequest, Order, OrderResult,
    PendingOrderRequest, Position, SymbolInfo, Tick, Timeframe,
)


@runtime_checkable
class Broker(Protocol):
    async def health_check(self) -> HealthStatus: ...
    async def get_account(self) -> Account: ...
    async def get_symbol_info(self, symbol: str) -> SymbolInfo: ...
    async def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]: ...
    async def get_candles_range(self, symbol: str, timeframe: Timeframe,
                                from_dt: datetime, to_dt: datetime) -> list[Candle]: ...
    async def get_current_tick(self, symbol: str) -> Tick: ...
    async def get_open_positions(self) -> list[Position]: ...
    async def get_pending_orders(self) -> list[Order]: ...
    async def place_market_order(self, request: MarketOrderRequest) -> OrderResult: ...
    async def place_pending_order(self, request: PendingOrderRequest) -> OrderResult: ...
    async def modify_position(self, ticket: int, sl: float | None = None,
                              tp: float | None = None) -> OrderResult: ...
    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult: ...
    async def cancel_order(self, ticket: int) -> OrderResult: ...
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_base -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/execution/broker/base.py tests/unit/test_broker_base.py
git commit -m "feat(broker): abstract Broker protocol seam (TDD)"
```

---

## Task 7: HTTP client — URL resolution + request/error plumbing

**Files:**
- Create: `src/execution/broker/mt5_http.py`
- Test: `tests/unit/test_broker_url.py`

- [ ] **Step 1: Write the failing test** (pure host-picker — no network)

```python
# tests/unit/test_broker_url.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker.mt5_http import _pick_host


class PickHost(unittest.TestCase):
    def test_mirrored_uses_loopback(self):
        # mirrored: eth0 has a LAN addr (no 172.x NAT) -> 127.0.0.1
        eth0 = "    inet 10.0.0.22/24 ..."
        route = "default via 10.0.0.1 dev eth0 ..."
        self.assertEqual(_pick_host(eth0, route), "127.0.0.1")

    def test_nat_uses_gateway(self):
        # NAT: eth0 has 172.x -> use the default-route gateway (Windows host)
        eth0 = "    inet 172.27.46.252/20 ..."
        route = "default via 172.27.32.1 dev eth0 ..."
        self.assertEqual(_pick_host(eth0, route), "172.27.32.1")

    def test_nat_without_gateway_falls_back_to_loopback(self):
        self.assertEqual(_pick_host("    inet 172.20.0.2/20", ""), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_url -v`
Expected: FAIL — `ModuleNotFoundError: ... mt5_http`

- [ ] **Step 3: Create `src/execution/broker/mt5_http.py` (plumbing + URL resolution; methods added in Tasks 8–9)**

```python
"""MT5HttpBroker: consumes the Titan Windows-side HTTP bridge. The only module coupled
to the bridge wire format. Ported from ~/mos/src/mos/data/broker/mt5_bridge.py.

URL resolution (no manual WSL IP ever): TITAN_BRIDGE_URL env wins; else mirrored mode
-> http://127.0.0.1:8766; else NAT -> http://<default-gateway>:8766.
Token from TITAN_BRIDGE_TOKEN (required). Reads retry once on connection error; writes
never auto-retry (an order may have landed even if the response didn't arrive)."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

import httpx

from .errors import BrokerAuthError, BrokerConnectionError, BrokerError, BrokerNotFoundError
from .types import (
    Account, Candle, HealthStatus, MarketOrderRequest, Order, OrderResult,
    OrderSide, PendingOrderRequest, PendingOrderType, Position, SymbolInfo, Tick, Timeframe,
)

DEFAULT_PORT = 8766
DEFAULT_TIMEOUT = 15.0
RETRY_BACKOFF = 0.25

_TF_TO_BRIDGE: dict[Timeframe, int] = {
    Timeframe.M1: 1, Timeframe.M5: 5, Timeframe.M15: 15, Timeframe.M30: 30,
    Timeframe.H1: 16385, Timeframe.H4: 16388, Timeframe.D1: 16408,
    Timeframe.W1: 32769, Timeframe.MN1: 49153,
}
_POSITION_SIDE = {0: OrderSide.BUY, 1: OrderSide.SELL}
_PENDING_TYPE = {2: PendingOrderType.BUY_LIMIT, 3: PendingOrderType.SELL_LIMIT,
                 4: PendingOrderType.BUY_STOP, 5: PendingOrderType.SELL_STOP}


def _pick_host(eth0_out: str, route_out: str) -> str:
    """Decide the bridge host from `ip addr show eth0` + `ip route show default` text.
    Mirrored mode (no 172.x NAT addr on eth0) -> 127.0.0.1. NAT -> default gateway."""
    addrs = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", eth0_out)
    is_nat = any(a.startswith("172.") for a in addrs)
    if not is_nat:
        return "127.0.0.1"
    gw = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", route_out)
    return gw.group(1) if gw else "127.0.0.1"


def _resolve_base_url() -> str:
    explicit = os.environ.get("TITAN_BRIDGE_URL")
    if explicit:
        return explicit
    def _run(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
        except Exception:  # noqa: BLE001 — best-effort detection
            return ""
    host = _pick_host(_run(["ip", "-4", "addr", "show", "eth0"]),
                      _run(["ip", "route", "show", "default"]))
    return f"http://{host}:{DEFAULT_PORT}"


def _parse_utc(s: Any) -> datetime:
    dt = datetime.fromisoformat(str(s))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _norm_price(v: Any) -> float | None:
    """Bridge 0.0 'no SL/TP' sentinel -> None (exact-equality test)."""
    if v is None:
        return None
    f = float(v)
    return None if f == 0.0 else f


class MT5HttpBroker:
    def __init__(self, base_url: str | None = None, auth_token: str | None = None,
                 *, timeout: float = DEFAULT_TIMEOUT, enable_read_retry: bool = True,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        url = base_url if base_url is not None else _resolve_base_url()
        token = auth_token if auth_token is not None else os.environ.get("TITAN_BRIDGE_TOKEN")
        if not token:
            raise ValueError("MT5HttpBroker requires auth_token or $TITAN_BRIDGE_TOKEN")
        self._base_url = url
        self._enable_read_retry = enable_read_retry
        self._client = httpx.AsyncClient(
            base_url=url, headers={"Authorization": f"Bearer {token}"},
            timeout=timeout, transport=transport)
        self._closed = False

    async def __aenter__(self) -> "MT5HttpBroker":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()

    async def _request(self, method: str, path: str, *, retry: bool,
                       json_body: Any = None, params: dict[str, Any] | None = None) -> Any:
        try:
            return await self._do(method, path, json_body, params)
        except BrokerConnectionError:
            if not (retry and self._enable_read_retry):
                raise
            await asyncio.sleep(RETRY_BACKOFF)
            return await self._do(method, path, json_body, params)

    async def _do(self, method: str, path: str, json_body: Any, params: dict[str, Any] | None) -> Any:
        try:
            resp = await self._client.request(method, path, json=json_body, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.WriteTimeout) as e:
            raise BrokerConnectionError(f"{type(e).__name__}: {e}") from e
        except httpx.RequestError as e:
            raise BrokerConnectionError(f"{type(e).__name__}: {e}") from e
        return self._handle(resp, method, path)

    def _handle(self, resp: httpx.Response, method: str, path: str) -> Any:
        code = resp.status_code
        if 200 <= code < 300:
            try:
                return resp.json()
            except ValueError as e:
                raise BrokerError(f"non-JSON body from {method} {path}: {e}") from e
        try:
            payload = resp.json()
            detail = payload.get("detail", str(payload)) if isinstance(payload, dict) else str(payload)
        except ValueError:
            detail = resp.text or "(no body)"
        if code == 401:
            raise BrokerAuthError(f"auth failed: {detail}")
        if code == 404:
            raise BrokerNotFoundError(f"not found {method} {path}: {detail}")
        if code in (503, 504):
            raise BrokerConnectionError(f"bridge {code}: {detail}")
        raise BrokerError(f"bridge HTTP {code} at {method} {path}: {detail}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_url -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/execution/broker/mt5_http.py tests/unit/test_broker_url.py
git commit -m "feat(broker): MT5HttpBroker plumbing — URL resolution + error mapping (TDD)"
```

---

## Task 8: HTTP client — read methods + translations

**Files:**
- Modify: `src/execution/broker/mt5_http.py`
- Test: `tests/unit/test_broker_mt5_http.py`

- [ ] **Step 1: Write the failing test (httpx.MockTransport — no network)**

```python
# tests/unit/test_broker_mt5_http.py
import os, sys, unittest, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import httpx
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker import types as T
from src.execution.broker import errors as E


def _broker(handler):
    return MT5HttpBroker("http://test", "tok", transport=httpx.MockTransport(handler))


class Reads(unittest.IsolatedAsyncioTestCase):
    async def test_get_symbol_info_maps_tick_fields(self):
        def h(req):
            self.assertEqual(req.headers["Authorization"], "Bearer tok")
            return httpx.Response(200, json={
                "name": "XAUUSD", "digits": 2, "point": 0.01, "spread": 20,
                "contract_size": 100.0, "volume_min": 0.01, "volume_max": 50.0,
                "volume_step": 0.01, "trade_mode": 4, "tick_value": 1.0, "tick_size": 0.01})
        async with _broker(h) as b:
            s = await b.get_symbol_info("XAUUSD")
        self.assertEqual((s.tick_value, s.tick_size, s.spread_points), (1.0, 0.01, 20))

    async def test_get_candles_range_maps_fields(self):
        def h(req):
            self.assertIn("/candles/XAUUSD/5/range", req.url.path)
            return httpx.Response(200, json=[{
                "time": "2026-01-01T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5,
                "close": 1.5, "tick_volume": 10, "spread": 3, "real_volume": 0}])
        async with _broker(h) as b:
            cs = await b.get_candles_range("XAUUSD", T.Timeframe.M5,
                                           __import__("datetime").datetime(2026,1,1),
                                           __import__("datetime").datetime(2026,1,2))
        self.assertEqual(cs[0].close, 1.5)
        self.assertEqual(cs[0].spread_points, 3)

    async def test_position_sl_zero_becomes_none_and_side_maps(self):
        def h(req):
            return httpx.Response(200, json=[{
                "ticket": 5, "symbol": "EURUSD", "type": 1, "volume": 0.01,
                "price_open": 1.1, "sl": 0.0, "tp": 1.2, "price_current": 1.1,
                "profit": 0.0, "swap": 0.0, "commission": 0.0,
                "time": "2026-01-01T00:00:00+00:00", "comment": "", "magic": 88000}])
        async with _broker(h) as b:
            ps = await b.get_open_positions()
        self.assertIsNone(ps[0].sl)
        self.assertEqual(ps[0].side, T.OrderSide.SELL)

    async def test_401_maps_to_auth_error(self):
        def h(req):
            return httpx.Response(401, json={"detail": "bad token"})
        async with _broker(h) as b:
            with self.assertRaises(E.BrokerAuthError):
                await b.get_account()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_mt5_http.Reads -v`
Expected: FAIL — `AttributeError: 'MT5HttpBroker' object has no attribute 'get_symbol_info'`

- [ ] **Step 3: Append read methods + translators to `mt5_http.py`** (inside the class / module)

```python
    # --- translators ---
    def _account(self, d: dict) -> Account:
        return Account(login=int(d["login"]), server=str(d["server"]), currency=str(d["currency"]),
                       leverage=int(d["leverage"]), balance=float(d["balance"]), equity=float(d["equity"]),
                       margin=float(d["margin"]), margin_free=float(d["margin_free"]),
                       margin_level=float(d["margin_level"]), profit=float(d["profit"]))

    def _symbol(self, d: dict) -> SymbolInfo:
        return SymbolInfo(name=str(d["name"]), digits=int(d["digits"]), point=float(d["point"]),
                          spread_points=int(d["spread"]), contract_size=float(d["contract_size"]),
                          volume_min=float(d["volume_min"]), volume_max=float(d["volume_max"]),
                          volume_step=float(d["volume_step"]), tick_value=float(d["tick_value"]),
                          tick_size=float(d["tick_size"]))

    def _candle(self, d: dict) -> Candle:
        return Candle(time=_parse_utc(d["time"]), open=float(d["open"]), high=float(d["high"]),
                      low=float(d["low"]), close=float(d["close"]), tick_volume=int(d["tick_volume"]),
                      spread_points=int(d["spread"]))

    def _tick(self, symbol: str, d: dict) -> Tick:
        return Tick(symbol=symbol, time=_parse_utc(d["time"]), bid=float(d["bid"]),
                    ask=float(d["ask"]), spread=float(d.get("spread", float(d["ask"]) - float(d["bid"]))))

    def _position(self, d: dict) -> Position:
        return Position(ticket=int(d["ticket"]), symbol=str(d["symbol"]),
                        side=_POSITION_SIDE[int(d["type"])], volume=float(d["volume"]),
                        price_open=float(d["price_open"]), sl=_norm_price(d.get("sl")),
                        tp=_norm_price(d.get("tp")), price_current=float(d["price_current"]),
                        profit=float(d["profit"]), swap=float(d["swap"]),
                        commission=float(d.get("commission", 0.0)), time_open=_parse_utc(d["time"]),
                        comment=str(d.get("comment", "")), magic=int(d.get("magic", 0)))

    def _order(self, d: dict) -> Order:
        return Order(ticket=int(d["ticket"]), symbol=str(d["symbol"]),
                     type=_PENDING_TYPE[int(d["type"])], volume=float(d["volume_current"]),
                     price_open=float(d["price_open"]), sl=_norm_price(d.get("sl")),
                     tp=_norm_price(d.get("tp")), time_setup=_parse_utc(d["time_setup"]),
                     comment=str(d.get("comment", "")), magic=int(d.get("magic", 0)))

    # --- reads ---
    async def health_check(self) -> HealthStatus:
        d = await self._request("GET", "/health", retry=True)
        return HealthStatus(status=str(d["status"]), broker_connected=bool(d["mt5_connected"]),
                            uptime_seconds=int(d["uptime_seconds"]))

    async def get_account(self) -> Account:
        return self._account(await self._request("GET", "/account", retry=True))

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return self._symbol(await self._request("GET", f"/symbol/{symbol}", retry=True))

    async def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        tf = _TF_TO_BRIDGE[timeframe]
        d = await self._request("GET", f"/candles/{symbol}/{tf}", retry=True, params={"count": count})
        return [self._candle(c) for c in d]

    async def get_candles_range(self, symbol: str, timeframe: Timeframe,
                                from_dt: datetime, to_dt: datetime) -> list[Candle]:
        tf = _TF_TO_BRIDGE[timeframe]
        d = await self._request("GET", f"/candles/{symbol}/{tf}/range", retry=True,
                                params={"from": from_dt.isoformat(), "to": to_dt.isoformat()})
        return [self._candle(c) for c in d]

    async def get_current_tick(self, symbol: str) -> Tick:
        return self._tick(symbol, await self._request("GET", f"/tick/{symbol}", retry=True))

    async def get_open_positions(self) -> list[Position]:
        return [self._position(p) for p in await self._request("GET", "/positions", retry=True)]

    async def get_pending_orders(self) -> list[Order]:
        return [self._order(o) for o in await self._request("GET", "/orders", retry=True)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_mt5_http.Reads -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/execution/broker/mt5_http.py tests/unit/test_broker_mt5_http.py
git commit -m "feat(broker): read methods + wire->type translation (0.0->None, int->StrEnum) (TDD)"
```

---

## Task 9: HTTP client — write methods (market/pending/modify/close/partial/cancel)

**Files:**
- Modify: `src/execution/broker/mt5_http.py`
- Test: `tests/unit/test_broker_mt5_http.py` (append `Writes`)

- [ ] **Step 1: Write the failing test**

```python
class Writes(unittest.IsolatedAsyncioTestCase):
    async def test_market_order_request_shape(self):
        seen = {}
        def h(req):
            seen["path"] = req.url.path
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"success": True, "ticket": 7, "price_filled": 1.1,
                                             "volume_filled": 0.01})
        async with _broker(h) as b:
            r = await b.place_market_order(T.MarketOrderRequest(
                symbol="EURUSD", volume=0.01, side=T.OrderSide.BUY, sl=1.0, tp=1.2, magic=88000))
        self.assertEqual(seen["path"], "/order/market")
        self.assertEqual(seen["body"]["side"], "buy")
        self.assertEqual(seen["body"]["deviation"], 20)   # broker deviation_points -> bridge deviation
        self.assertTrue(r.success); self.assertEqual(r.ticket, 7)

    async def test_pending_stop_order_allowed(self):
        def h(req):
            body = json.loads(req.content)
            self.assertEqual(body["type"], "buy_stop")
            return httpx.Response(200, json={"success": True, "ticket": 9})
        async with _broker(h) as b:
            r = await b.place_pending_order(T.PendingOrderRequest(
                symbol="XAUUSD", volume=0.01, type=T.PendingOrderType.BUY_STOP, price=5000.0))
        self.assertTrue(r.success)

    async def test_partial_close_uses_partial_endpoint(self):
        def h(req):
            self.assertTrue(req.url.path.endswith("/partial"))
            self.assertEqual(json.loads(req.content)["volume"], 0.01)
            return httpx.Response(200, json={"success": True})
        async with _broker(h) as b:
            r = await b.close_position(5, volume=0.01)
        self.assertTrue(r.success)

    async def test_write_does_not_retry_on_connection_error(self):
        calls = {"n": 0}
        def h(req):
            calls["n"] += 1
            raise httpx.ConnectError("down")
        async with _broker(h) as b:
            with self.assertRaises(E.BrokerConnectionError):
                await b.place_market_order(T.MarketOrderRequest(
                    symbol="EURUSD", volume=0.01, side=T.OrderSide.BUY))
        self.assertEqual(calls["n"], 1)   # never retried
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_mt5_http.Writes -v`
Expected: FAIL — `AttributeError: ... 'place_market_order'`

- [ ] **Step 3: Append write methods to `mt5_http.py`**

```python
    def _result(self, d: dict) -> OrderResult:
        return OrderResult(success=bool(d["success"]), ticket=d.get("ticket"),
                           price_filled=d.get("price_filled"), volume_filled=d.get("volume_filled"),
                           error_code=d.get("error_code"), error_message=d.get("error_message"))

    async def place_market_order(self, request: MarketOrderRequest) -> OrderResult:
        body = request.model_dump(mode="json")
        body["deviation"] = body.pop("deviation_points")   # broker name -> bridge name
        return self._result(await self._request("POST", "/order/market", retry=False, json_body=body))

    async def place_pending_order(self, request: PendingOrderRequest) -> OrderResult:
        body = request.model_dump(mode="json")
        return self._result(await self._request("POST", "/order/pending", retry=False, json_body=body))

    async def modify_position(self, ticket: int, sl: float | None = None,
                              tp: float | None = None) -> OrderResult:
        return self._result(await self._request("PUT", f"/position/{ticket}", retry=False,
                                                 json_body={"sl": sl, "tp": tp}))

    async def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        if volume is None:
            d = await self._request("POST", f"/position/{ticket}/close", retry=False)
        else:
            if volume <= 0:
                raise ValueError(f"close_position volume must be > 0, got {volume}")
            d = await self._request("POST", f"/position/{ticket}/partial", retry=False,
                                    json_body={"volume": volume})
        return self._result(d)

    async def cancel_order(self, ticket: int) -> OrderResult:
        return self._result(await self._request("DELETE", f"/order/{ticket}", retry=False))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_broker_mt5_http -v`
Expected: PASS (Reads + Writes)

- [ ] **Step 5: Commit**

```bash
git add src/execution/broker/mt5_http.py tests/unit/test_broker_mt5_http.py
git commit -m "feat(broker): write methods (market/pending incl stops/modify/close/partial/cancel), no-retry (TDD)"
```

---

## Task 10: Add `httpx` runtime dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append httpx (only if not already present)**

Add a line to `requirements.txt`:
```
httpx>=0.27,<0.29
```

- [ ] **Step 2: Install + import check**

Run: `.venv/bin/python -m pip install -r requirements.txt && .venv/bin/python -c "import httpx; print(httpx.__version__)"`
Expected: prints a version (0.27.x–0.28.x), no error.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "build: add httpx (broker HTTP client) dependency"
```

---

## Task 11: Rework `scripts/export_history.py` — chunked range pull via broker

**Files:**
- Modify: `scripts/export_history.py` (replace the ZMQ body; keep the CSV format)
- Test: `tests/unit/test_export_history_http.py`

- [ ] **Step 1: Write the failing test (pure chunking + CSV against a fake broker)**

```python
# tests/unit/test_export_history_http.py
import os, sys, unittest
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import export_history as eh
from src.execution.broker import types as T


class FakeBroker:
    """Returns candles for the most-recent window only; older windows are empty (history floor)."""
    def __init__(self, newest_from):
        self.newest_from = newest_from
        self.calls = []
    async def get_candles_range(self, symbol, tf, from_dt, to_dt):
        self.calls.append((from_dt, to_dt))
        if from_dt >= self.newest_from:
            t = from_dt
            out = []
            while t < to_dt:
                out.append(T.Candle(time=t, open=1, high=2, low=0.5, close=1.5,
                                    tick_volume=1, spread_points=1))
                t += timedelta(minutes=5)
            return out
        return []   # no more history


class Export(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_pull_stops_at_empty_window(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        fb = FakeBroker(newest_from=now - timedelta(days=30))
        bars = await eh.pull_history(fb, "XAUUSD", T.Timeframe.M5, now=now,
                                     max_lookback=timedelta(days=90), chunk=timedelta(days=30))
        self.assertGreater(len(bars), 0)
        # sorted ascending, unique by time
        times = [b.time for b in bars]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

    def test_csv_text_format_matches_legacy(self):
        c = T.Candle(time=datetime(2026,1,1,0,5,tzinfo=timezone.utc), open=1.1, high=1.2,
                     low=1.0, close=1.15, tick_volume=1, spread_points=1)
        txt = eh.candles_to_csv([c])
        self.assertEqual(txt.splitlines()[0], "datetime,open,high,low,close")
        self.assertEqual(txt.splitlines()[1], "2026-01-01 00:05:00,1.1,1.2,1.0,1.15")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_export_history_http -v`
Expected: FAIL — `AttributeError: module 'scripts.export_history' has no attribute 'pull_history'`

- [ ] **Step 3: Replace `scripts/export_history.py` with the broker version**

```python
#!/usr/bin/env python3
# scripts/export_history.py
# Export MT5 history to backtest CSVs via the Titan HTTP bridge (chunked copy_rates_range).
# Pulls whatever the broker actually retains (empty window = history floor). No EA / no ZMQ.
#   .venv/bin/python scripts/export_history.py --symbol XAUUSD --tf M5 --out data/history/XAUUSD_M5.csv
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.broker.mt5_http import MT5HttpBroker   # noqa: E402
from src.execution.broker import types as T               # noqa: E402

CSV_HEADER = "datetime,open,high,low,close"
TF = {"M1": T.Timeframe.M1, "M5": T.Timeframe.M5, "M15": T.Timeframe.M15,
      "H1": T.Timeframe.H1, "H4": T.Timeframe.H4, "D1": T.Timeframe.D1}


async def pull_history(broker, symbol, timeframe, *, now, max_lookback, chunk):
    """Walk backward in `chunk`-sized windows until an empty window (history floor) or
    max_lookback. Returns candles ascending, de-duplicated by time."""
    floor = now - max_lookback
    cursor = now
    by_time: dict[datetime, T.Candle] = {}
    while cursor > floor:
        frm = max(cursor - chunk, floor)
        window = await broker.get_candles_range(symbol, timeframe, frm, cursor)
        if not window:
            break
        for c in window:
            by_time[c.time] = c
        cursor = frm
    return [by_time[t] for t in sorted(by_time)]


def candles_to_csv(candles) -> str:
    rows = [CSV_HEADER]
    for c in candles:
        ts = c.time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(f"{ts},{c.open},{c.high},{c.low},{c.close}")
    return "\n".join(rows) + "\n"


async def _run(args):
    broker = MT5HttpBroker()   # URL/token from env / auto-resolve
    async with broker:
        bars = await pull_history(
            broker, args.symbol, TF[args.tf], now=datetime.now(tz=timezone.utc),
            max_lookback=timedelta(days=args.max_days), chunk=timedelta(days=args.chunk_days))
    if not bars:
        print(f"[EXPORT] {args.symbol}: no history returned"); return
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(candles_to_csv(bars))
    print(f"[EXPORT] {args.symbol}: wrote {len(bars)} bars "
          f"({bars[0].time.date()} -> {bars[-1].time.date()}) to {args.out}")


def main():
    p = argparse.ArgumentParser(description="Export MT5 history via the Titan HTTP bridge.")
    p.add_argument("--symbol", required=True)
    p.add_argument("--tf", default="M5", choices=list(TF))
    p.add_argument("--out", required=True)
    p.add_argument("--max-days", dest="max_days", type=int, default=1095, help="lookback cap (~3y)")
    p.add_argument("--chunk-days", dest="chunk_days", type=int, default=30)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_export_history_http -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/export_history.py tests/unit/test_export_history_http.py
git commit -m "feat(export): history export via broker chunked range pull (TDD)"
```

---

## Task 12: Rework `scripts/cache_specs.py` — specs via broker

**Files:**
- Modify: `scripts/cache_specs.py`
- Test: `tests/unit/test_cache_specs_http.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cache_specs_http.py
import os, sys, json, unittest, tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import cache_specs as cs
from src.execution.broker import types as T


class FakeBroker:
    async def get_symbol_info(self, symbol):
        return T.SymbolInfo(name=symbol, digits=2, point=0.01, spread_points=20,
                            contract_size=100.0, volume_min=0.01, volume_max=50.0,
                            volume_step=0.01, tick_value=1.0, tick_size=0.01)


class Specs(unittest.IsolatedAsyncioTestCase):
    async def test_builds_specs_dict_in_legacy_shape(self):
        out = await cs.build_specs(FakeBroker(), ["XAUUSD", "EURUSD"])
        self.assertEqual(set(out), {"XAUUSD", "EURUSD"})
        self.assertEqual(out["XAUUSD"], {"tick_value": 1.0, "tick_size": 0.01,
                                         "vol_min": 0.01, "vol_step": 0.01})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_cache_specs_http -v`
Expected: FAIL — `AttributeError: ... 'build_specs'`

- [ ] **Step 3: Replace `scripts/cache_specs.py`**

```python
#!/usr/bin/env python3
# scripts/cache_specs.py
# Cache broker symbol specs to data/specs.json via the Titan HTTP bridge.
#   .venv/bin/python scripts/cache_specs.py --symbols XAUUSD EURUSD ... --out data/specs.json
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.broker.mt5_http import MT5HttpBroker   # noqa: E402
from src.execution.broker.errors import BrokerError       # noqa: E402

DEFAULT_SYMS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
                "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]


async def build_specs(broker, symbols):
    """Return {symbol: {tick_value, tick_size, vol_min, vol_step}} — the shape risk_manager
    consumes. Per-symbol failures are skipped (logged) so one bad symbol never aborts the run."""
    out = {}
    for s in symbols:
        try:
            info = await broker.get_symbol_info(s)
        except BrokerError as e:
            print(f"[SPECS] {s}: skipped ({type(e).__name__}: {e})")
            continue
        out[s] = {"tick_value": info.tick_value, "tick_size": info.tick_size,
                  "vol_min": info.volume_min, "vol_step": info.volume_step}
    return out


async def _run(args):
    broker = MT5HttpBroker()
    async with broker:
        specs = await build_specs(broker, args.symbols)
    with open(args.out, "w") as f:
        json.dump(specs, f, indent=2)
    print(f"[SPECS] wrote {len(specs)} symbols -> {args.out}")


def main():
    p = argparse.ArgumentParser(description="Cache MT5 symbol specs via the Titan HTTP bridge.")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMS)
    p.add_argument("--out", default="data/specs.json")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_cache_specs_http -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/cache_specs.py tests/unit/test_cache_specs_http.py
git commit -m "feat(specs): cache symbol specs via broker (tick_value/size + vol) (TDD)"
```

---

## Task 13: `scripts/check_bridge_http.py` — HTTP health check

**Files:**
- Create: `scripts/check_bridge_http.py`

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
# scripts/check_bridge_http.py
# Prove the Titan HTTP bridge link (GET /health). Prints the resolved URL + health.
#   .venv/bin/python scripts/check_bridge_http.py
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.broker.mt5_http import MT5HttpBroker, _resolve_base_url   # noqa: E402
from src.execution.broker.errors import BrokerError                          # noqa: E402


async def _run():
    url = os.environ.get("TITAN_BRIDGE_URL") or _resolve_base_url()
    print(f"[CHECK] resolved bridge URL: {url}")
    try:
        async with MT5HttpBroker() as b:
            h = await b.health_check()
        print(f"[CHECK] ✅ Bridge is UP: status={h.status} mt5_connected={h.broker_connected} "
              f"uptime={h.uptime_seconds}s")
        return 0
    except BrokerError as e:
        print(f"[CHECK] ❌ Bridge check failed: {type(e).__name__}: {e}")
        print("[CHECK] Verify: bridge running on Windows (py -3.11 bridge/run_bridge.py), "
              "TITAN_BRIDGE_TOKEN set, MT5 logged into FBS-Demo.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
```

- [ ] **Step 2: Sanity-check it imports + errors cleanly without a bridge**

Run: `TITAN_BRIDGE_TOKEN=x .venv/bin/python scripts/check_bridge_http.py; echo "exit=$?"`
Expected: prints a resolved URL and `❌ Bridge check failed: BrokerConnectionError ...`, `exit=1` (no bridge running — correct behavior).

- [ ] **Step 3: Commit**

```bash
git add scripts/check_bridge_http.py
git commit -m "feat(bridge): HTTP health-check script (additive; ZMQ check_bridge.py kept)"
```

---

## Task 14: Opt-in live integration test

**Files:**
- Create: `tests/integration/__init__.py`, `tests/integration/test_bridge_live.py`

- [ ] **Step 1: Create the gated live test**

```python
# tests/integration/test_bridge_live.py
# Opt-in: requires the Titan bridge running on Windows + FBS-Demo terminal.
# Run with:  TITAN_BRIDGE_LIVE_TEST=1 TITAN_BRIDGE_TOKEN=... .venv/bin/python -m unittest tests.integration.test_bridge_live -v
# Places REAL demo orders (0.01 lot), so it is never part of the auto suite.
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker import types as T

_ENABLED = os.environ.get("TITAN_BRIDGE_LIVE_TEST") == "1"


@unittest.skipUnless(_ENABLED, "set TITAN_BRIDGE_LIVE_TEST=1 (needs live bridge + demo terminal)")
class Live(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_account(self):
        async with MT5HttpBroker() as b:
            h = await b.health_check()
            self.assertIn(h.status, ("ok", "degraded"))
            acct = await b.get_account()
            self.assertGreater(acct.balance, 0)

    async def test_symbol_has_tick_fields(self):
        async with MT5HttpBroker() as b:
            s = await b.get_symbol_info("XAUUSD")
            self.assertGreater(s.tick_value, 0)
            self.assertGreater(s.tick_size, 0)

    async def test_execution_round_trip(self):
        async with MT5HttpBroker() as b:
            tick = await b.get_current_tick("EURUSD")
            info = await b.get_symbol_info("EURUSD")
            pip = info.point * (10 if info.digits in (3, 5) else 1)
            sl = round(tick.ask - 30 * pip, info.digits)
            res = await b.place_market_order(T.MarketOrderRequest(
                symbol="EURUSD", volume=0.01, side=T.OrderSide.BUY, sl=sl, magic=88001,
                comment="titan_phase1_integ"))
            self.assertTrue(res.success, f"place failed: {res}")
            ticket = res.ticket
            try:
                pos = [p for p in await b.get_open_positions() if p.ticket == ticket]
                self.assertEqual(len(pos), 1)
                self.assertIsNotNone(pos[0].sl)              # 0.0->None translation works live
                mod = await b.modify_position(ticket, sl=round(tick.ask - 10 * pip, info.digits))
                self.assertTrue(mod.success, f"modify failed: {mod}")
            finally:
                close = await b.close_position(ticket)
                self.assertTrue(close.success, f"close failed: {close}")
            self.assertNotIn(ticket, [p.ticket for p in await b.get_open_positions()])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm it SKIPS without the flag (so it never breaks the auto suite)**

Run: `.venv/bin/python -m unittest tests.integration.test_bridge_live -v`
Expected: tests report `skipped` (flag not set).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_bridge_live.py
git commit -m "test(bridge): opt-in live integration (health/account/symbol/execution round-trip)"
```

---

## Task 15: Docs + env templates

**Files:**
- Modify: `CLAUDE.md` (add HTTP bridge ops), `.env.example` (Linux client vars)

- [ ] **Step 1: Append a Bridge Operations (HTTP) section to `CLAUDE.md`**

Add under the commands/architecture area:
```markdown
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
```

- [ ] **Step 2: Append client env vars to `.env.example`**

```
# Titan HTTP bridge (Linux client) — Phase 1
TITAN_BRIDGE_TOKEN=match_bridge_config_env_BRIDGE_AUTH_TOKEN
# TITAN_BRIDGE_URL=http://127.0.0.1:8766   # optional override; auto-resolved if unset
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .env.example
git commit -m "docs: HTTP bridge operations + client env template"
```

---

## Task 16: Full suite green + manual end-to-end checklist

**Files:** none (verification)

- [ ] **Step 1: Run the full Titan Linux unit suite**

Run: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`
Expected: PASS, no regressions (existing MTF-PB v2 tests + the new broker/export/specs tests).

- [ ] **Step 2: Confirm the live + bridge-surface suites are correctly gated/separate**

Run: `.venv/bin/python -m unittest tests.integration.test_bridge_live -v` → all `skipped`.
(Bridge surface tests under `bridge/tests/` run in the bridge env, not here.)

- [ ] **Step 3: Manual end-to-end (requires the bridge up on Windows)**

```bash
# after: py -3.11 bridge/run_bridge.py  on Windows, TITAN_BRIDGE_TOKEN set in WSL
.venv/bin/python scripts/check_bridge_http.py                  # ✅ UP
.venv/bin/python scripts/cache_specs.py                        # writes data/specs.json
.venv/bin/python scripts/export_history.py --symbol XAUUSD --tf M5 --out data/history/XAUUSD_M5.csv
head -2 data/history/XAUUSD_M5.csv                             # datetime,open,high,low,close
wc -l data/history/XAUUSD_M5.csv                               # how much M5 FBS actually retains
.venv/bin/python scripts/poc_mtf_pb2.py                        # re-run research on the bigger sample
```
Expected: bridge UP; CSV in the legacy format; bar count reveals FBS's true M5 depth; PoC runs on fresh data.

- [ ] **Step 4: Commit any docs/notes from the manual run (optional)**

```bash
git add -A && git commit -m "chore(bridge): phase 1 end-to-end verified" || echo "nothing to commit"
```

---

## Self-review notes (author)

- **Spec coverage:** bridge copy + port 8766 (T1), models + tick fields (T2), mt5_client tick population + main (T3), bridge surface tests (T4), Linux types+errors (T5), Broker protocol (T6), client plumbing+URL resolution (T7), reads+translation (T8), writes incl. stops + no-retry (T9), httpx dep (T10), history export chunked-range (T11), specs export (T12), HTTP health script (T13), opt-in live test incl. execution round-trip (T14), docs/env (T15), suite+e2e (T16). Networking/error-handling/coexistence from the spec are realized across T7/T13/T15.
- **Dependency deviation (documented):** `respx` dropped in favor of `httpx.MockTransport` + `unittest.IsolatedAsyncioTestCase` (fewer deps, matches repo convention). Only `httpx` added.
- **Type/name consistency:** broker types `SymbolInfo.tick_value/tick_size`, `Candle.spread_points`, `Position.side/time_open`, `Order.volume`; `_TF_TO_BRIDGE` codes match the bridge `Timeframe` IntEnum; `deviation_points`→`deviation` rename on market orders matches MOS; method names match the `Broker` protocol exactly.
- **Additive guarantee:** no task modifies `bridge_zmq.py`, `system_controller.py`, the EA, or `scripts/check_bridge.py` — the ZMQ live path is untouched (Phases 2–3 handle migration/decommission).
- **Known constraints:** bridge surface tests need `fastapi` present (bridge env, not the Titan `.venv`); the live test places demo orders (opt-in only); FBS M5 depth is discovered empirically by T16's `wc -l`.
