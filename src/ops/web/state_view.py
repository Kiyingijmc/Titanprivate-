# src/ops/web/state_view.py
"""Read-only assembly of the /api/state snapshot and /api/history rows."""
from datetime import datetime

_HEARTBEAT_STALE_S = 60.0
_REGISTRY_FIELDS = ("id", "version", "status", "state", "tf", "priority")

# MT5 ENUM_ORDER_TYPE -> (side, kind) for the resting-order types the EA reports
# in the heartbeat's `orders` list (Titan_Gateway.mq5:225). 0/1 are market
# BUY/SELL, which arrive as positions instead and never appear here.
_PENDING_TYPES = {
    2: ("BUY", "LIMIT"),
    3: ("SELL", "LIMIT"),
    4: ("BUY", "STOP"),
    5: ("SELL", "STOP"),
    6: ("BUY", "STOP_LIMIT"),
    7: ("SELL", "STOP_LIMIT"),
}

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
        "orders": [_map_pending(controller, o)
                   for o in (getattr(controller, "current_pending_orders", None) or [])],
        "risk": _risk_block(controller),
        "market": {"has_crypto": _has_crypto(controller)},
        "arbiter": {
            "stats": controller.arbiter.stats(),
            "throttle": {"enabled": bool(throttle_cfg.get("enabled", False)),
                         "current_mult": float(rm.throttle_factor())},
        },
        "registry": [{k: r.get(k) for k in _REGISTRY_FIELDS} for r in controller.registry.report()],
        "dollar": _dollar_block(controller),
    }


def _has_crypto(controller) -> bool:
    """Whether the traded universe includes a 24/7 instrument.

    Deliberately the SAME predicate the trading loop uses to decide whether to
    keep watching over a weekend (SystemController: `has_crypto = any(s for s in
    self.active_symbols if "BTC" in s or "ETH" in s)`). Exported so the GUI can
    mirror engine truth rather than draw a hard "Markets closed" banner off its
    own FX-only calendar while SilverBullet is filling ETHUSD limits on a Sunday.
    Keep the two in step: if the engine's rule widens, widen this with it."""
    try:
        symbols = getattr(controller, "active_symbols", None) or []
        return any("BTC" in s or "ETH" in s for s in symbols)
    except Exception:
        return False


def _risk_block(controller) -> dict:
    """Daily-drawdown breaker + book-wide exposure cap, as the operator sees them.

    Both of these can stop trading outright -- the DD breaker via check_can_trade,
    the portfolio cap by refusing every symbol when one row is un-computable --
    and neither had any GUI surface, so a total trading halt looked exactly like
    a quiet market. Same defensive contract as `dollar`: never crash the snapshot.
    """
    rm = getattr(controller, "risk_manager", None)
    out = {
        "day_anchor": 0.0, "day_pnl": None, "day_pnl_pct": None,
        "max_daily_dd_pct": 0.0, "can_trade": True,
        "book_risk": None, "book_risk_pct": None,
        "max_book_risk_pct": 0.0, "blocker": None,
    }
    if rm is None:
        return out

    equity = float(getattr(rm, "current_equity", 0.0) or 0.0)

    # Day P&L is measured against the RISK-01 persisted anchor, NOT starting_balance
    # (which is latched once at the first heartbeat after boot and therefore
    # re-bases on every restart).
    anchor = float(getattr(rm, "day_start_equity", 0.0) or 0.0)
    out["day_anchor"] = anchor
    if anchor > 0:
        out["day_pnl"] = round(equity - anchor, 2)
        out["day_pnl_pct"] = round((equity - anchor) / anchor * 100.0, 4)

    out["max_daily_dd_pct"] = float(getattr(rm, "max_dd", 0.0) or 0.0)
    try:
        out["can_trade"] = bool(rm.check_can_trade())
    except Exception:
        pass

    account_cfg = ((getattr(controller, "config", None) or {}).get("risk", {}) or {}).get("account", {}) or {}
    out["max_book_risk_pct"] = float(account_cfg.get("max_total_open_risk_pct", 0.0) or 0.0)

    # aggregate_open_risk unconditionally rewrites rm.last_uncomputable_row. This
    # snapshot is polled about once a second and shares the RiskManager with the
    # trading loop, so put back whatever was there: a read-only view must never
    # clobber the diagnostic _alert_uncomputable_book reports to the operator.
    prev_row = getattr(rm, "last_uncomputable_row", None)
    try:
        sm = getattr(controller, "state_manager", None)
        resting = sm.get_pending_orders() if sm is not None else []
        book = rm.aggregate_open_risk(
            getattr(controller, "current_open_positions", None) or [], resting)
        out["blocker"] = getattr(rm, "last_uncomputable_row", None) if book is None else None
        if book is not None:
            # Match what the cap actually evaluates: dispatched-but-unreported
            # sends count too (SystemController._execute_signal).
            reserve_fn = getattr(controller, "_reserved_risk_total", None)
            if callable(reserve_fn):
                book += float(reserve_fn() or 0.0)
            out["book_risk"] = round(book, 2)
            if equity > 0:
                out["book_risk_pct"] = round(book / equity * 100.0, 4)
    except Exception:
        pass
    finally:
        try:
            rm.last_uncomputable_row = prev_row
        except Exception:
            pass

    return out


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


def _map_pending(controller, o: dict) -> dict:
    """One resting LIMIT/STOP order, enriched from its state-DB row.

    The EA's heartbeat rows carry only t/s/p/type/vol -- no stop, no target
    (Titan_Gateway.mq5:225) -- so SL/TP/grade/strategy come from active_orders.
    `tracked` is the load-bearing field: an order Titan did not place has no row,
    which is exactly the case aggregate_open_risk cannot price and therefore does
    not count. Rendering it identically to a managed order hides that gap.
    """
    ticket = int(o.get("t", 0))
    try:
        row = controller.state_manager.get_order(ticket)
    except Exception:
        row = None
    side, kind = _PENDING_TYPES.get(int(o.get("type", -1)), ("?", "?"))
    return {
        "ticket": ticket,
        "symbol": o.get("s", "?"),
        "side": side,
        "kind": kind,
        "lots": float(o.get("vol", 0.0)),
        "price": float(o.get("p", 0.0)),
        "sl": float((row or {}).get("initial_sl", 0.0) or 0.0),
        "tp": float((row or {}).get("initial_tp", 0.0) or 0.0),
        "grade": (row or {}).get("grade", "") or "",
        "strategy": (row or {}).get("strategy", "") or "",
        "tracked": row is not None,
    }


def history_rows(conn, limit: int = 50) -> list:
    try:
        cur = conn.execute(
            "SELECT * FROM trade_history ORDER BY rowid DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
