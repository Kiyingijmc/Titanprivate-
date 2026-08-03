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
                          tick_size=float(d["tick_size"]),
                          swap_mode=int(d.get("swap_mode", 0)),
                          swap_long=float(d.get("swap_long", 0.0)),
                          swap_short=float(d.get("swap_short", 0.0)),
                          swap_rollover3days=int(d.get("swap_rollover3days", 3)),
                          currency_base=str(d.get("currency_base", "")),
                          currency_profit=str(d.get("currency_profit", "")))

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

    # --- writes (never auto-retry: an order may have landed even if the response didn't) ---
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
