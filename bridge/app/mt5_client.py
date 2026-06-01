"""Thin wrapper around the MetaTrader5 Python package.

Centralizes all MT5 interactions. Translates between MT5's tuple/object responses
and our Pydantic models. Handles connection lifecycle and error normalization.

Two layers:
- Sync methods (the originals) — call MT5 directly. Used by tests and scripts.
- Async wrappers (a-prefixed) — delegate the sync method to a worker thread via
  asyncio.to_thread. Used by FastAPI handlers so the event loop is never blocked
  by a wedged MT5 call. Combined with asyncio.wait_for in the handler layer,
  this gives the bridge per-call timeout protection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import MetaTrader5 as mt5
from loguru import logger

from .models import (
    AccountInfo,
    Candle,
    ConnectionResponse,
    MarketOrderRequest,
    ModifyRequest,
    Order,
    OrderResult,
    OrderType,
    PendingOrderRequest,
    Position,
    SymbolInfo,
    Tick,
    Timeframe,
)


class MT5Client:
    """Wraps MetaTrader5 calls with our typed contracts."""

    def __init__(self) -> None:
        self._connected: bool = False

    # ---------- Connection ----------

    def initialize(
        self,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        path: str | None = None,
    ) -> bool:
        """Initialize MT5 connection. If credentials are None, uses currently logged-in terminal."""
        kwargs: dict[str, Any] = {}
        if path:
            kwargs["path"] = path
        if login is not None:
            kwargs["login"] = login
        if password:
            kwargs["password"] = password
        if server:
            kwargs["server"] = server

        result = mt5.initialize(**kwargs) if kwargs else mt5.initialize()
        self._connected = bool(result)
        if not self._connected:
            err = mt5.last_error()
            logger.error(f"MT5 initialize failed: {err}")
        else:
            logger.info("MT5 connection initialized")
        return self._connected

    def shutdown(self) -> None:
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 connection shut down")

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        info = mt5.terminal_info()
        return bool(info and info.connected)

    def connection_info(self) -> ConnectionResponse:
        info = mt5.terminal_info()
        if info is None:
            err = mt5.last_error()
            return ConnectionResponse(
                connected=False,
                last_error_code=err[0] if err else None,
                last_error_message=err[1] if err else None,
            )
        return ConnectionResponse(
            connected=info.connected,
            terminal_company=info.company,
            terminal_name=info.name,
            terminal_build=info.build,
            trade_allowed=info.trade_allowed,
        )

    # ---------- Account ----------

    def get_account(self) -> AccountInfo | None:
        info = mt5.account_info()
        if info is None:
            return None
        return AccountInfo(
            login=info.login,
            server=info.server,
            company=info.company,
            currency=info.currency,
            leverage=info.leverage,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            margin_free=info.margin_free,
            margin_level=info.margin_level,
            profit=info.profit,
        )

    # ---------- Symbol Info ----------

    def get_symbol_info(self, symbol: str) -> SymbolInfo | None:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
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

    def list_symbols(self) -> list[str]:
        symbols = mt5.symbols_get()
        if symbols is None:
            return []
        return [s.name for s in symbols]

    # ---------- Market Data ----------

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> list[Candle]:
        rates = mt5.copy_rates_from_pos(symbol, int(timeframe), 0, count)
        if rates is None:
            err = mt5.last_error()
            logger.warning(f"copy_rates_from_pos returned None for {symbol}: {err}")
            return []
        return [
            Candle(
                time=datetime.fromtimestamp(r["time"], tz=UTC),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                tick_volume=int(r["tick_volume"]),
                spread=int(r["spread"]),
                real_volume=int(r["real_volume"]),
            )
            for r in rates
        ]

    def get_candles_from(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[Candle]:
        rates = mt5.copy_rates_range(symbol, int(timeframe), from_dt, to_dt)
        if rates is None:
            err = mt5.last_error()
            logger.warning(f"copy_rates_range returned None for {symbol}: {err}")
            return []
        return [
            Candle(
                time=datetime.fromtimestamp(r["time"], tz=UTC),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                tick_volume=int(r["tick_volume"]),
                spread=int(r["spread"]),
                real_volume=int(r["real_volume"]),
            )
            for r in rates
        ]

    def get_tick(self, symbol: str) -> Tick | None:
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        return Tick(
            time=datetime.fromtimestamp(t.time, tz=UTC),
            bid=t.bid,
            ask=t.ask,
            last=t.last,
            volume=t.volume,
            spread=t.ask - t.bid,
        )

    # ---------- Positions ----------

    def get_positions(self) -> list[Position]:
        positions = mt5.positions_get()
        if positions is None:
            return []
        return [self._position_from_mt5(p) for p in positions]

    def get_position(self, ticket: int) -> Position | None:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None
        return self._position_from_mt5(positions[0])

    def _position_from_mt5(self, p: Any) -> Position:
        return Position(
            ticket=p.ticket,
            symbol=p.symbol,
            type=OrderType(p.type),
            volume=p.volume,
            price_open=p.price_open,
            sl=p.sl,
            tp=p.tp,
            price_current=p.price_current,
            profit=p.profit,
            swap=p.swap,
            commission=getattr(p, "commission", 0.0),
            time=datetime.fromtimestamp(p.time, tz=UTC),
            comment=p.comment,
            magic=p.magic,
        )

    # ---------- Pending Orders ----------

    def get_orders(self) -> list[Order]:
        orders = mt5.orders_get()
        if orders is None:
            return []
        return [
            Order(
                ticket=o.ticket,
                symbol=o.symbol,
                type=OrderType(o.type),
                volume_current=o.volume_current,
                price_open=o.price_open,
                sl=o.sl,
                tp=o.tp,
                time_setup=datetime.fromtimestamp(o.time_setup, tz=UTC),
                comment=o.comment,
                magic=o.magic,
            )
            for o in orders
        ]

    # ---------- Order Execution ----------

    def place_market_order(self, req: MarketOrderRequest) -> OrderResult:
        side_code = mt5.ORDER_TYPE_BUY if req.side == "buy" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(req.symbol)
        if tick is None:
            return OrderResult(
                success=False, error_code=-1, error_message=f"No tick for {req.symbol}"
            )
        price = tick.ask if req.side == "buy" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": req.symbol,
            "volume": req.volume,
            "type": side_code,
            "price": price,
            "deviation": req.deviation,
            "magic": req.magic,
            "comment": req.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if req.sl is not None:
            request["sl"] = req.sl
        if req.tp is not None:
            request["tp"] = req.tp

        result = mt5.order_send(request)
        return self._result_to_order_result(result)

    def place_pending_order(self, req: PendingOrderRequest) -> OrderResult:
        type_map = {
            "buy_limit": mt5.ORDER_TYPE_BUY_LIMIT,
            "sell_limit": mt5.ORDER_TYPE_SELL_LIMIT,
            "buy_stop": mt5.ORDER_TYPE_BUY_STOP,
            "sell_stop": mt5.ORDER_TYPE_SELL_STOP,
        }
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": req.symbol,
            "volume": req.volume,
            "type": type_map[req.type],
            "price": req.price,
            "magic": req.magic,
            "comment": req.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        if req.sl is not None:
            request["sl"] = req.sl
        if req.tp is not None:
            request["tp"] = req.tp

        result = mt5.order_send(request)
        return self._result_to_order_result(result)

    def modify_position(self, ticket: int, mod: ModifyRequest) -> OrderResult:
        position = self.get_position(ticket)
        if position is None:
            return OrderResult(
                success=False, error_code=-1, error_message=f"Position {ticket} not found"
            )
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": mod.sl if mod.sl is not None else position.sl,
            "tp": mod.tp if mod.tp is not None else position.tp,
        }
        result = mt5.order_send(request)
        return self._result_to_order_result(result)

    def close_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        position = self.get_position(ticket)
        if position is None:
            return OrderResult(
                success=False, error_code=-1, error_message=f"Position {ticket} not found"
            )
        opposite_type = (
            mt5.ORDER_TYPE_SELL if position.type == OrderType.BUY else mt5.ORDER_TYPE_BUY
        )
        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return OrderResult(success=False, error_code=-1, error_message="No tick available")
        price = tick.bid if position.type == OrderType.BUY else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": position.symbol,
            "volume": volume if volume is not None else position.volume,
            "type": opposite_type,
            "price": price,
            "deviation": 20,
            "magic": position.magic,
            "comment": "close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return self._result_to_order_result(result)

    def cancel_order(self, ticket: int) -> OrderResult:
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        result = mt5.order_send(request)
        return self._result_to_order_result(result)

    # ---------- Helpers ----------

    def _result_to_order_result(self, result: Any) -> OrderResult:
        if result is None:
            err = mt5.last_error()
            return OrderResult(
                success=False,
                error_code=err[0] if err else -1,
                error_message=err[1] if err else "Unknown error",
            )
        success = result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(
            success=success,
            ticket=int(result.order) if success and result.order else None,
            price_filled=float(result.price) if success else None,
            volume_filled=float(result.volume) if success else None,
            error_code=result.retcode if not success else None,
            error_message=result.comment if not success else None,
            raw_retcode=result.retcode,
        )

    # ---------- Async Wrappers ----------
    #
    # Each delegates the sync method to a worker thread via asyncio.to_thread.
    # The handler layer wraps these calls in asyncio.wait_for so a wedged MT5
    # cannot block the event loop or other concurrent requests.

    async def ainitialize(
        self,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        path: str | None = None,
    ) -> bool:
        return await asyncio.to_thread(self.initialize, login, password, server, path)

    async def ashutdown(self) -> None:
        await asyncio.to_thread(self.shutdown)

    async def ais_connected(self) -> bool:
        return await asyncio.to_thread(self.is_connected)

    async def aconnection_info(self) -> ConnectionResponse:
        return await asyncio.to_thread(self.connection_info)

    async def aget_account(self) -> AccountInfo | None:
        return await asyncio.to_thread(self.get_account)

    async def aget_symbol_info(self, symbol: str) -> SymbolInfo | None:
        return await asyncio.to_thread(self.get_symbol_info, symbol)

    async def alist_symbols(self) -> list[str]:
        return await asyncio.to_thread(self.list_symbols)

    async def aget_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> list[Candle]:
        return await asyncio.to_thread(self.get_candles, symbol, timeframe, count)

    async def aget_candles_from(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[Candle]:
        return await asyncio.to_thread(self.get_candles_from, symbol, timeframe, from_dt, to_dt)

    async def aget_tick(self, symbol: str) -> Tick | None:
        return await asyncio.to_thread(self.get_tick, symbol)

    async def aget_positions(self) -> list[Position]:
        return await asyncio.to_thread(self.get_positions)

    async def aget_position(self, ticket: int) -> Position | None:
        return await asyncio.to_thread(self.get_position, ticket)

    async def aget_orders(self) -> list[Order]:
        return await asyncio.to_thread(self.get_orders)

    async def aplace_market_order(self, req: MarketOrderRequest) -> OrderResult:
        return await asyncio.to_thread(self.place_market_order, req)

    async def aplace_pending_order(self, req: PendingOrderRequest) -> OrderResult:
        return await asyncio.to_thread(self.place_pending_order, req)

    async def amodify_position(self, ticket: int, mod: ModifyRequest) -> OrderResult:
        return await asyncio.to_thread(self.modify_position, ticket, mod)

    async def aclose_position(self, ticket: int, volume: float | None = None) -> OrderResult:
        return await asyncio.to_thread(self.close_position, ticket, volume)

    async def acancel_order(self, ticket: int) -> OrderResult:
        return await asyncio.to_thread(self.cancel_order, ticket)
