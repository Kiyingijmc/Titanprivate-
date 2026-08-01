# src/ops/web/state_view.py
"""Read-only assembly of the /api/state snapshot and /api/history rows."""
from datetime import datetime

_HEARTBEAT_STALE_S = 60.0
_REGISTRY_FIELDS = ("id", "version", "status", "state", "tf", "priority")

# Tracked USD pairs used by the "computed" dollar-bias fallback (owner DXY policy:
# broker index symbol if available, else compute from these, else "unavailable").
# USD is the BASE currency in the first three (USDxxx); a +delta_pct there means
# USD strengthened. USD is the QUOTE currency in the last three (xxxUSD); a
# +delta_pct there means the foreign currency strengthened i.e. USD weakened, so
# its contribution is inverted (-delta_pct).
_USD_BASE_PAIRS = ("USDJPY", "USDCAD", "USDCHF")
_USD_QUOTE_PAIRS = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD")
_DOLLAR_BIAS_SCALE = 40.0  # scales avg %-change contribution into the [-100,100] band


def build_snapshot(controller) -> dict:
    age = (datetime.now() - controller.last_heartbeat_time).total_seconds()
    rm = controller.risk_manager
    throttle_cfg = (controller.config.get("risk", {}) or {}).get("drawdown_throttle", {}) or {}
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
        "arbiter": {
            "stats": controller.arbiter.stats(),
            "throttle": {"enabled": bool(throttle_cfg.get("enabled", False)),
                         "current_mult": float(rm.throttle_factor())},
        },
        "registry": [{k: r.get(k) for k in _REGISTRY_FIELDS} for r in controller.registry.report()],
        "dollar": _dollar_block(controller),
        "news": _news_block(controller),
    }


def _dollar_block(controller) -> dict:
    """Best-effort USD-strength snapshot. Defensive by design: the live
    controller may not expose any price data yet — this must NEVER crash the
    snapshot. Sourcing order (owner DXY policy): broker index symbol if the
    controller provides one, else computed from tracked USD pairs, else
    "unavailable"."""
    try:
        index_fn = getattr(controller, "dollar_index", None)
        if callable(index_fn):
            data = index_fn()
            if isinstance(data, dict) and data:
                return {
                    "source": "index",
                    "value": data.get("value"),
                    "bias": float(data.get("bias", 0.0) or 0.0),
                    "trend": list(data.get("trend", []) or []),
                    "contributors": list(data.get("contributors", []) or []),
                }
    except Exception:
        pass

    try:
        prices = getattr(controller, "market_prices", None)
        if isinstance(prices, dict) and prices:
            contributions = []
            for symbol in _USD_BASE_PAIRS:
                row = prices.get(symbol)
                if not isinstance(row, dict) or "delta_pct" not in row:
                    continue
                contributions.append({"symbol": symbol, "contribution": float(row["delta_pct"])})
            for symbol in _USD_QUOTE_PAIRS:
                row = prices.get(symbol)
                if not isinstance(row, dict) or "delta_pct" not in row:
                    continue
                contributions.append({"symbol": symbol, "contribution": -float(row["delta_pct"])})
            if contributions:
                avg = sum(c["contribution"] for c in contributions) / len(contributions)
                bias = max(-100.0, min(100.0, avg * _DOLLAR_BIAS_SCALE))
                # Optional rolling history the controller may maintain itself
                # (e.g. the demo server) so the widget's sparkline has motion;
                # absent on the live controller today, so this defaults to [].
                trend = list(getattr(controller, "dollar_trend", []) or [])
                return {
                    "source": "computed",
                    "value": None,
                    "bias": round(bias, 2),
                    "trend": trend,
                    "contributors": contributions,
                }
    except Exception:
        pass

    return {"source": "unavailable", "value": None, "bias": 0.0, "trend": [], "contributors": []}


def _news_block(controller) -> dict:
    """Economic-calendar snapshot for the GUI. Defensive by the same rule as
    _dollar_block: a news fault must never break the whole payload, so any
    problem degrades to "unavailable" rather than propagating."""
    try:
        manager = getattr(controller, "news_manager", None)
        if manager is None:
            return {"status": "unavailable"}
        data = manager.snapshot()
        if not isinstance(data, dict):
            return {"status": "unavailable"}
        return data
    except Exception:
        return {"status": "unavailable"}


def _map_position(controller, p: dict) -> dict:
    ticket = int(p.get("t", 0))
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
        "grade": (row or {}).get("grade", "") or "",
        "strategy": (row or {}).get("strategy", "") or "",
    }


def history_rows(conn, limit: int = 50) -> list:
    try:
        cur = conn.execute(
            "SELECT * FROM trade_history ORDER BY rowid DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
