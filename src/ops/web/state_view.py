# src/ops/web/state_view.py
"""Read-only assembly of the /api/state snapshot and /api/history rows."""
from datetime import datetime

_HEARTBEAT_STALE_S = 60.0
_REGISTRY_FIELDS = ("id", "version", "status", "state", "tf", "priority")


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
    }


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
