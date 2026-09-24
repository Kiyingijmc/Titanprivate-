"""Broker catalog discovery and explicit per-strategy symbol eligibility.

Discovery never enables a strategy or sends orders. Eligibility means the
mechanics can run, not that a strategy has a demonstrated trading edge.
"""
import asyncio
from copy import deepcopy
from fnmatch import fnmatchcase
import math

from src.execution.broker.errors import BrokerAuthError, BrokerError


def spec_problem(info):
    if info.trade_mode not in (1, 2, 4):
        return "new positions disabled or trading mode unavailable"
    for field in ("point", "tick_size", "tick_value", "contract_size",
                  "volume_min", "volume_max", "volume_step"):
        value = getattr(info, field)
        if not math.isfinite(value) or value <= 0:
            return f"invalid {field}"
    if info.volume_min > info.volume_max or info.volume_step > info.volume_max:
        return "inconsistent volume bounds"
    if info.order_mode is None or info.order_mode < 0 or info.order_mode & 48 != 48:
        return "SL/TP permissions unavailable (update bridge) or unsupported"
    if info.trade_stops_level is None or info.trade_stops_level < 0:
        return "stop-distance metadata unavailable (update bridge)"
    if not info.currency_profit:
        return "profit currency unavailable"
    return None


async def discover_catalog(broker, concurrency=4):
    if not isinstance(concurrency, int) or not 1 <= concurrency <= 16:
        raise ValueError("catalog concurrency must be 1..16")
    names = await broker.list_symbols()
    sem = asyncio.Semaphore(concurrency)

    async def read(name):
        async with sem:
            try:
                info = await broker.get_symbol_info(name)
                if info.name != name:
                    return name, None, "broker returned a different symbol name"
                return name, info, spec_problem(info)
            except BrokerAuthError:
                raise
            except BrokerError as exc:
                return name, None, type(exc).__name__

    results = await asyncio.gather(*(read(name) for name in names))
    catalog = {name: info for name, info, _ in results if info is not None}
    rejected = {name: problem for name, _, problem in results if problem}
    return catalog, rejected


def selected_pairs(strategy_id, params, catalog):
    policy = params.get("universe") or {}
    source = policy.get("source", "configured")
    if source == "configured":
        return params.get("pairs")
    if source != "broker":
        raise ValueError(f"{strategy_id}: unknown universe source {source!r}")
    include, exclude = policy.get("include", ["*"]), policy.get("exclude", [])
    if any(not isinstance(x, list) or any(not isinstance(p, str) or not p for p in x)
           for x in (include, exclude)):
        raise ValueError("universe include/exclude must be lists of symbol patterns")
    if strategy_id not in ("silver_bullet", "gyroscope", "almanac", "gambit", "ma_slope_baseline"):
        raise ValueError(f"{strategy_id}: no broker-universe eligibility policy")
    result = []
    for name, info in sorted(catalog.items()):
        if spec_problem(info) or not any(fnmatchcase(name, p) for p in include):
            continue
        if any(fnmatchcase(name, p) for p in exclude):
            continue
        required = 2 if strategy_id in ("silver_bullet", "gambit") else 1
        if info.order_mode & required == 0:
            continue
        if strategy_id == "almanac":
            # Calendar strategy does not become a month-end buyer of every asset.
            if name not in params.get("pairs", []) or info.trade_mode == 2:
                continue
        if strategy_id == "gambit":
            if (not params.get("symbol_sessions", {}).get(name)
                    or float(params.get("min_stop_price", {}).get(name, 0)) <= 0
                    or float(params.get("max_spread_price", {}).get(name, 0)) <= 0):
                continue
        result.append(name)
    return result


def resolve_config(config, catalog):
    """Return a new runtime config; preserve enablement and all strategy rules."""
    out = deepcopy(config)
    for sid, params in out.get("strategies", {}).items():
        if (params.get("universe") or {}).get("source") == "broker":
            params["pairs"] = selected_pairs(sid, params, catalog)
    return out


def order_problem(info, side, kind, entry, sl, tp, bid, ask):
    """Fresh broker permission and price checks for expanded-universe orders."""
    problem = spec_problem(info)
    if problem:
        return problem
    if side not in ("BUY", "SELL") or kind not in ("MARKET", "LIMIT", "STOP"):
        return "unsupported order side/type"
    if (side == "BUY" and info.trade_mode == 2) or (side == "SELL" and info.trade_mode == 1):
        return "direction prohibited by broker"
    if not info.order_mode & {"MARKET": 1, "LIMIT": 2, "STOP": 4}[kind]:
        return "order type prohibited by broker"
    if not all(math.isfinite(p) and p > 0 for p in (entry, sl, tp, bid, ask)) or ask < bid:
        return "invalid/nonpositive prices"
    distance = info.trade_stops_level * info.point
    long = side == "BUY"
    if not (sl < entry < tp if long else tp < entry < sl):
        return "stop/target on wrong side of entry"
    anchor = (bid if long else ask) if kind == "MARKET" else entry
    if (anchor - sl if long else sl - anchor) < distance:
        return "stop inside broker minimum distance"
    if (tp - anchor if long else anchor - tp) < distance:
        return "target inside broker minimum distance"
    if kind != "MARKET":
        quote = ask if long else bid
        delta = (quote-entry if long else entry-quote) if kind == "LIMIT" else (entry-quote if long else quote-entry)
        if delta < distance or delta <= 0:
            return "pending entry inside broker minimum distance or wrong side"
    return None
