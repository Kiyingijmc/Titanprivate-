"""Opt-in broker-wide universe integration for the existing ZMQ controller."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR

from src.analysis.news.policy import NewsPolicy
from src.execution.broker.mt5_http import MT5HttpBroker
from src.strategies.universe import discover_catalog, resolve_config, spec_problem


async def prepare_universe(controller, broker_factory=MT5HttpBroker):
    requested = {sid for sid, cfg in controller.config.get("strategies", {}).items()
                 if (cfg.get("universe") or {}).get("source") == "broker"
                 and cfg.get("enabled", True)}
    if not requested:
        return
    cfg = controller.config.get("broker_universe") or {}
    limit = cfg.get("max_symbols", 128)
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("broker_universe.max_symbols must be a positive integer")
    async with broker_factory(timeout=5) as broker:
        catalog, rejected = await discover_catalog(broker)
    resolved = resolve_config(controller.config, catalog)
    dynamic = set().union(*(set(resolved["strategies"][s].get("pairs") or []) for s in requested))
    if not dynamic:
        raise ValueError("broker universe has no eligible symbols; check catalog report and bridge metadata")
    active = {name for p in resolved.get("strategies", {}).values() if p.get("enabled", False)
              for name in p.get("pairs", [])}
    if not active:
        raise ValueError("broker universe resolved to no active instruments")
    if len(active) > limit:
        raise ValueError(f"broker universe needs {len(active)} feeds, limit is {limit}; "
                         "narrow include/exclude or increase max_symbols after capacity review")
    # Build exact-name news mapping from metadata, preserving explicit mappings.
    mapping = resolved.setdefault("news", {}).setdefault("symbol_currencies", {})
    for name in dynamic:
        info = catalog[name]
        currencies = [c.upper() for c in (info.currency_base, info.currency_profit)
                      if len(c) == 3 and c.upper() not in ("XAU", "XAG", "BTC", "ETH")]
        mapping.setdefault(name, list(dict.fromkeys(currencies)))
    controller.config = resolved
    controller.active_symbols = active
    controller._broker_universe_symbols = dynamic
    controller.news_manager.policy = NewsPolicy(resolved)
    controller.news_manager.policy.logger = controller.logger
    controller.logger.log_event("INFO", "UNIVERSE",
                                f"Broker catalog {len(catalog)} instruments; "
                                f"{len(dynamic)} selected, {len(rejected)} unavailable; "
                                "strategy enablement unchanged")


async def refresh_order_specs(controller, symbol, broker_factory=MT5HttpBroker):
    """Read fresh permissions/quotes; unknown or rejected specs stop the order."""
    try:
        async with broker_factory(timeout=5, enable_read_retry=False) as broker:
            info, tick = await asyncio.gather(broker.get_symbol_info(symbol),
                                             broker.get_current_tick(symbol))
        if info.name != symbol or tick.symbol != symbol:
            raise ValueError("broker symbol mismatch")
        age = (datetime.now(timezone.utc) - tick.time).total_seconds()
        if not -5 <= age <= 60:
            raise ValueError("broker quote is stale or future-dated")
        problem = spec_problem(info)
        if problem:
            raise ValueError(problem)
        rm = controller.risk_manager
        rm.update_symbol_specs(symbol, info.tick_value, info.tick_size, info.volume_min, info.volume_step)
        expected = {"val": info.tick_value, "ts": info.tick_size,
                    "vm": info.volume_min, "vs": info.volume_step}
        if rm.symbol_specs.get(symbol) != expected:
            raise ValueError("risk engine rejected fresh broker specifications")
        return info, tick
    except Exception as exc:
        controller.logger.log_event("RISK", "UNIVERSE", f"{symbol} skipped: {type(exc).__name__}: {exc}")
        return None


def cap_volume(lots, info):
    """Never round up risk; respect the broker maximum and lot step."""
    step = Decimal(str(info.volume_step))
    units = (min(Decimal(str(lots)), Decimal(str(info.volume_max))) / step).to_integral_value(rounding=ROUND_FLOOR)
    volume = units * step
    return float(volume) if volume >= Decimal(str(info.volume_min)) else 0.0
