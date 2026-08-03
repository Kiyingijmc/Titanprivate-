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
    # swap survey (defaults tolerate bridges that predate these fields)
    swap_mode: int = 0
    swap_long: float = 0.0
    swap_short: float = 0.0
    swap_rollover3days: int = 3
    currency_base: str = ""
    currency_profit: str = ""


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
