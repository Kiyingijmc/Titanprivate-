"""Pydantic models for bridge API request/response contracts."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field

# ---------- Enumerations ----------


class OrderType(IntEnum):
    """MT5 order type codes."""

    BUY = 0
    SELL = 1
    BUY_LIMIT = 2
    SELL_LIMIT = 3
    BUY_STOP = 4
    SELL_STOP = 5


class Timeframe(IntEnum):
    """MT5 timeframe codes (minutes for intraday, special codes for higher)."""

    M1 = 1
    M5 = 5
    M15 = 15
    M30 = 30
    H1 = 16385
    H4 = 16388
    D1 = 16408
    W1 = 32769
    MN1 = 49153


# ---------- Health & Status ----------


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    mt5_connected: bool
    uptime_seconds: int
    bridge_version: str


class ConnectionResponse(BaseModel):
    connected: bool
    terminal_company: str | None = None
    terminal_name: str | None = None
    terminal_build: int | None = None
    trade_allowed: bool = False
    last_error_code: int | None = None
    last_error_message: str | None = None


# ---------- Account ----------


class AccountInfo(BaseModel):
    login: int
    server: str
    company: str
    currency: str
    leverage: int
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    profit: float


# ---------- Symbol & Market Data ----------


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


class Candle(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int
    real_volume: int


class Tick(BaseModel):
    time: datetime
    bid: float
    ask: float
    last: float
    volume: int
    spread: float = Field(description="ask - bid")


# ---------- Positions & Orders ----------


class Position(BaseModel):
    ticket: int
    symbol: str
    type: OrderType
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    profit: float
    swap: float
    commission: float
    time: datetime
    comment: str
    magic: int


class Order(BaseModel):
    ticket: int
    symbol: str
    type: OrderType
    volume_current: float
    price_open: float
    sl: float
    tp: float
    time_setup: datetime
    comment: str
    magic: int


# ---------- Order Requests ----------


class MarketOrderRequest(BaseModel):
    symbol: str
    volume: float
    side: Literal["buy", "sell"]
    sl: float | None = None
    tp: float | None = None
    deviation: int = 20
    comment: str = ""
    magic: int = 0


class PendingOrderRequest(BaseModel):
    symbol: str
    volume: float
    type: Literal["buy_limit", "sell_limit", "buy_stop", "sell_stop"]
    price: float
    sl: float | None = None
    tp: float | None = None
    comment: str = ""
    magic: int = 0


class ModifyRequest(BaseModel):
    sl: float | None = None
    tp: float | None = None


class ClosePartialRequest(BaseModel):
    volume: float


class OrderResult(BaseModel):
    success: bool
    ticket: int | None = None
    price_filled: float | None = None
    volume_filled: float | None = None
    error_code: int | None = None
    error_message: str | None = None
    raw_retcode: int | None = None


# ---------- Errors ----------


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error_code: int
    error_message: str
