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
