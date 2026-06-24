"""MT5 Bridge FastAPI application.

All MT5 calls run on a worker thread via asyncio.to_thread (handlers are async,
the underlying MT5 Python API is sync). Each call is wrapped with asyncio.wait_for
so a wedged MT5 returns 504 instead of hanging the event loop. Repeated timeouts
trip the circuit breaker, which marks MT5 unhealthy and attempts shutdown+reinit
recovery on the next request.
"""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypeVar

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from loguru import logger

from .circuit import MT5CircuitBreaker
from .models import (
    AccountInfo,
    Candle,
    ClosePartialRequest,
    ConnectionResponse,
    HealthResponse,
    MarketOrderRequest,
    ModifyRequest,
    Order,
    OrderResult,
    PendingOrderRequest,
    Position,
    SymbolInfo,
    Tick,
    Timeframe,
)
from .mt5_client import MT5Client
from .settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable

T = TypeVar("T")

BRIDGE_VERSION = "0.1.0"
DEFAULT_TIMEOUT = 5.0
INIT_TIMEOUT = 15.0

_start_time = time.time()
_mt5: MT5Client = MT5Client()
_circuit: MT5CircuitBreaker = MT5CircuitBreaker()


def configure_logging() -> None:
    settings = get_settings()
    log_path = Path(__file__).parent.parent / settings.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(
        log_path,
        level=settings.log_level,
        rotation="00:00",
        retention="30 days",
        compression="zip",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    logger.info(
        f"Bridge starting v{BRIDGE_VERSION} on {settings.bridge_host}:{settings.bridge_port}"
    )
    try:
        ok = await asyncio.wait_for(
            _mt5.ainitialize(
                login=settings.mt5_login,
                password=settings.mt5_password,
                server=settings.mt5_server,
                path=settings.mt5_path,
            ),
            timeout=INIT_TIMEOUT,
        )
    except TimeoutError:
        ok = False
        logger.error(f"MT5 initialize timed out after {INIT_TIMEOUT}s at startup")
    if ok:
        _circuit.record_success()
        logger.info("MT5 connection initialized at startup")
    else:
        _circuit.force_unhealthy()
        logger.warning("MT5 did not initialize at startup; circuit reports degraded")
    yield
    logger.info("Bridge shutting down")
    try:
        await asyncio.wait_for(_mt5.ashutdown(), timeout=DEFAULT_TIMEOUT)
    except TimeoutError:
        logger.error("MT5 shutdown timed out at lifespan exit")


app = FastAPI(
    title="Titan MT5 Bridge",
    version=BRIDGE_VERSION,
    lifespan=lifespan,
)


def verify_token(authorization: Annotated[str | None, Header()] = None) -> None:
    settings = get_settings()
    expected = f"Bearer {settings.bridge_auth_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing auth token",
        )


AuthDep = Annotated[None, Depends(verify_token)]


async def call_mt5(coro: Awaitable[T], *, timeout: float = DEFAULT_TIMEOUT) -> T:
    """Run an MT5 coroutine with timeout and circuit-breaker integration.

    On timeout: records the failure and raises HTTP 504. If the circuit is open
    on entry, attempts recovery once; if recovery fails, raises HTTP 503 without
    invoking the MT5 call.
    """
    if not _circuit.healthy:
        recovered = await _circuit.attempt_recovery(_mt5, get_settings())
        if not recovered:
            raise HTTPException(
                status_code=503,
                detail="MT5 circuit open; recovery failed",
            )
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError as e:
        _circuit.record_timeout()
        raise HTTPException(
            status_code=504,
            detail=f"MT5 call timed out after {timeout}s",
        ) from e
    _circuit.record_success()
    return result


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Bridge liveness + cached MT5 health.

    Does NOT call MT5. Reports the circuit breaker's view, which is updated
    asynchronously by every other endpoint. A wedged MT5 cannot block /health.
    """
    return HealthResponse(
        status="ok" if _circuit.healthy else "degraded",
        mt5_connected=_circuit.healthy,
        uptime_seconds=int(time.time() - _start_time),
        bridge_version=BRIDGE_VERSION,
    )


@app.get("/connection", response_model=ConnectionResponse)
async def connection(_: AuthDep) -> ConnectionResponse:
    return await call_mt5(_mt5.aconnection_info())


@app.post("/connect", response_model=ConnectionResponse)
async def connect(_: AuthDep) -> ConnectionResponse:
    settings = get_settings()
    await call_mt5(
        _mt5.ainitialize(
            login=settings.mt5_login,
            password=settings.mt5_password,
            server=settings.mt5_server,
            path=settings.mt5_path,
        ),
        timeout=INIT_TIMEOUT,
    )
    return await call_mt5(_mt5.aconnection_info())


@app.post("/disconnect")
async def disconnect(_: AuthDep) -> dict[str, bool]:
    await call_mt5(_mt5.ashutdown())
    return {"disconnected": True}


@app.get("/account", response_model=AccountInfo)
async def account(_: AuthDep) -> AccountInfo:
    info = await call_mt5(_mt5.aget_account())
    if info is None:
        raise HTTPException(status_code=503, detail="MT5 not connected")
    return info


@app.get("/symbols")
async def list_symbols(_: AuthDep) -> dict[str, list[str]]:
    return {"symbols": await call_mt5(_mt5.alist_symbols())}


@app.get("/symbol/{symbol}", response_model=SymbolInfo)
async def symbol_info(symbol: str, _: AuthDep) -> SymbolInfo:
    info = await call_mt5(_mt5.aget_symbol_info(symbol))
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return info


@app.get("/candles/{symbol}/{timeframe}", response_model=list[Candle])
async def candles(
    symbol: str,
    timeframe: Timeframe,
    _: AuthDep,
    count: int = Query(default=500, ge=1, le=10000),
) -> list[Candle]:
    return await call_mt5(_mt5.aget_candles(symbol, timeframe, count))


@app.get("/candles/{symbol}/{timeframe}/range", response_model=list[Candle])
async def candles_range(
    symbol: str,
    timeframe: Timeframe,
    _: AuthDep,
    from_iso: str = Query(alias="from"),
    to_iso: str = Query(alias="to"),
) -> list[Candle]:
    try:
        from_dt = datetime.fromisoformat(from_iso)
        to_dt = datetime.fromisoformat(to_iso)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date: {e}") from e
    return await call_mt5(_mt5.aget_candles_from(symbol, timeframe, from_dt, to_dt))


@app.get("/tick/{symbol}", response_model=Tick)
async def tick(symbol: str, _: AuthDep) -> Tick:
    t = await call_mt5(_mt5.aget_tick(symbol))
    if t is None:
        raise HTTPException(status_code=404, detail=f"No tick for {symbol}")
    return t


@app.get("/positions", response_model=list[Position])
async def positions(_: AuthDep) -> list[Position]:
    return await call_mt5(_mt5.aget_positions())


@app.get("/positions/{ticket}", response_model=Position)
async def position_by_ticket(ticket: int, _: AuthDep) -> Position:
    p = await call_mt5(_mt5.aget_position(ticket))
    if p is None:
        raise HTTPException(status_code=404, detail=f"Position {ticket} not found")
    return p


@app.get("/orders", response_model=list[Order])
async def pending_orders(_: AuthDep) -> list[Order]:
    return await call_mt5(_mt5.aget_orders())


@app.post("/order/market", response_model=OrderResult)
async def market_order(req: MarketOrderRequest, _: AuthDep) -> OrderResult:
    logger.info(f"Market order: {req}")
    result = await call_mt5(_mt5.aplace_market_order(req))
    logger.info(f"Result: {result}")
    return result


@app.post("/order/pending", response_model=OrderResult)
async def pending_order(req: PendingOrderRequest, _: AuthDep) -> OrderResult:
    logger.info(f"Pending order: {req}")
    result = await call_mt5(_mt5.aplace_pending_order(req))
    logger.info(f"Result: {result}")
    return result


@app.put("/position/{ticket}", response_model=OrderResult)
async def modify_position(ticket: int, mod: ModifyRequest, _: AuthDep) -> OrderResult:
    logger.info(f"Modify position {ticket}: {mod}")
    result = await call_mt5(_mt5.amodify_position(ticket, mod))
    logger.info(f"Result: {result}")
    return result


@app.post("/position/{ticket}/close", response_model=OrderResult)
async def close_position(ticket: int, _: AuthDep) -> OrderResult:
    logger.info(f"Close position {ticket}")
    result = await call_mt5(_mt5.aclose_position(ticket))
    logger.info(f"Result: {result}")
    return result


@app.post("/position/{ticket}/partial", response_model=OrderResult)
async def close_partial(ticket: int, req: ClosePartialRequest, _: AuthDep) -> OrderResult:
    logger.info(f"Close partial {ticket} volume={req.volume}")
    result = await call_mt5(_mt5.aclose_position(ticket, volume=req.volume))
    logger.info(f"Result: {result}")
    return result


@app.delete("/order/{ticket}", response_model=OrderResult)
async def cancel_pending(ticket: int, _: AuthDep) -> OrderResult:
    logger.info(f"Cancel pending order {ticket}")
    result = await call_mt5(_mt5.acancel_order(ticket))
    logger.info(f"Result: {result}")
    return result
