# src/ops/web/fake_controller.py
"""Minimal in-memory controller so the GUI server can run with MT5 offline.

Dev-only: mirrors the shape the Phase 1a unit tests exercise (health/account/
positions/arbiter/registry attrs + the mutation methods used by
src/ops/web/commands.py and src/ops/web/registry_view.py). Not imported by the
live SystemController — only by devserver.py.
"""
from datetime import datetime


class _FakeRisk:
    current_equity = 10000.0
    starting_balance = 10000.0

    @staticmethod
    def throttle_factor():
        return 1.0


class _FakeArbiter:
    @staticmethod
    def stats():
        return {"submitted": 0, "approved": 0, "blocked_by": {}}


class _FakeRegistry:
    @staticmethod
    def report():
        return [{"id": "silver_bullet", "version": "14.4.2", "family": "smc",
                 "tf": "H1", "status": "live", "state": "ACTIVE", "priority": 50}]


class _FakeStateManager:
    @staticmethod
    def get_order(ticket):
        return None


# Plausible static USD-pair mids/deltas so build_snapshot's dollar block resolves
# to a full "computed" reading (mild USD-strong bias) instead of "unavailable".
_MARKET_PRICES = {
    "EURUSD": {"mid": 1.08550, "delta_pct": -0.18},
    "GBPUSD": {"mid": 1.26500, "delta_pct": -0.09},
    "USDJPY": {"mid": 157.20, "delta_pct": 0.22},
    "AUDUSD": {"mid": 0.66500, "delta_pct": -0.12},
    "USDCAD": {"mid": 1.36500, "delta_pct": 0.14},
    "USDCHF": {"mid": 0.88500, "delta_pct": 0.08},
}


class _FakeRecorder:
    """Stand-in for EquityRecorder with the same read surface the GUI uses.

    Carries db_path/cfg/enabled/conn/buffer/last_flush_ts so BOTH the /api/equity
    read path (which opens its own connection by path) and the /api/state health
    block are drivable offline, not just the counters.
    """

    def __init__(self, db_path, conn):
        from src.ops.equity_recorder import _DEFAULTS
        self.db_path = db_path
        self.conn = conn
        self.enabled = True
        self.cfg = dict(_DEFAULTS)
        self.buffer = []
        self.last_flush_ts = None
        self.counters = {"dropped_stale": 0, "dropped_invalid": 0,
                         "dropped_overflow": 0, "flush_errors": 0}


def _fake_equity_recorder():
    """Both tiers seeded, each with a deliberate outage.

    Coarse: 3 days of 300s buckets (drives every range > 12h).
    Fine:   48h of 10s rows (drives 15m/30m/1h/4h/12h — five of the eleven
            ranges returned ZERO points offline before this, which made the
            phase-2 range selector undrivable with MT5 down).

    File-backed (not :memory:) so the route's short-lived read-only connection,
    which reopens the DB by path, behaves offline exactly as it does live.
    """
    import math as _math
    import os as _os
    import sqlite3
    import tempfile as _tempfile
    import time as _time

    from src.ops.equity_recorder import (COARSE_BUCKET_S, FINE_CADENCE_S,
                                         ensure_schema)

    db_path = _os.path.join(_tempfile.mkdtemp(prefix="titan-fake-equity-"), "titan_core.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    ensure_schema(conn)
    now = int(_time.time())

    coarse = []
    equity, peak = 10_000.0, 10_000.0
    n_coarse = 3 * 86_400 // COARSE_BUCKET_S          # 3 days
    for i in range(n_coarse):
        ts = now - (n_coarse - i) * COARSE_BUCKET_S
        if 300 < i < 400:                 # a ~8h outage, so gap rendering is drivable
            continue
        equity += _math.sin(i / 18.0) * 12.0
        peak = max(peak, equity)
        coarse.append((ts, equity, equity - 40.0, peak, equity - 6.0, equity + 6.0))
    conn.executemany(
        "INSERT INTO equity_coarse "
        "(bucket_ts, equity, balance, peak, equity_min, equity_max) VALUES (?,?,?,?,?,?)",
        coarse)

    fine = []
    equity, peak = 10_000.0, 10_000.0
    n_fine = 48 * 3_600 // FINE_CADENCE_S             # 48h of 10s samples
    for i in range(n_fine):
        ts = now - (n_fine - i) * FINE_CADENCE_S
        # Two holes, sized/placed so a gap is visible at BOTH ends of the fine
        # range set: ~53min at ~6h ago (seen by 12h/4h), ~7.5min at ~6min ago
        # (seen by 15m/30m/1h).
        if 14_800 <= i < 15_120 or n_fine - 80 <= i < n_fine - 35:
            continue
        equity += _math.sin(i / 240.0) * 1.5
        peak = max(peak, equity)
        fine.append((float(ts), equity, equity - 40.0, peak))
    conn.executemany(
        "INSERT INTO equity_fine (ts, equity, balance, peak) VALUES (?,?,?,?)", fine)

    conn.commit()
    return _FakeRecorder(db_path, conn)


class FakeController:
    """In-memory stand-in for SystemController, for offline GUI dev/demo."""

    def __init__(self):
        self.last_heartbeat_time = datetime.now()
        self.is_manual_pause = False
        self.last_error = None
        self.risk_manager = _FakeRisk()
        self.arbiter = _FakeArbiter()
        self.registry = _FakeRegistry()
        self.config = {"risk": {"drawdown_throttle": {"enabled": False}}}
        self.current_open_positions = []
        self.state_manager = _FakeStateManager()
        self.market_prices = {k: dict(v) for k, v in _MARKET_PRICES.items()}
        self.applied = []
        self.published = []
        self.equity_recorder = _fake_equity_recorder()

    # --- read-side used by state_view.build_snapshot ---
    def _publish(self, event) -> None:
        self.published.append(event)

    def apply_runtime_setting(self, key, value) -> None:
        self.applied.append((key, value))

    # --- the six GUI command methods (commands.py) ---
    def set_system_pause(self, paused: bool) -> str:
        self.is_manual_pause = paused
        return "PAUSED" if paused else "ACTIVE"

    async def close_specific_market_order(self, ticket: int) -> str:
        return f"closed {ticket}"

    async def close_all_market_orders(self) -> str:
        return "closed_all"

    async def trigger_panic(self) -> str:
        self.is_manual_pause = True
        return "panic_executed"

    async def cancel_pending_orders(self, ticket) -> str:
        return f"cancelled {ticket}"

    # --- registry lifecycle (registry_view.py) ---
    def enable_strategy(self, sid: str, allow_research: bool = False) -> str:
        return f"enabled {sid} research={allow_research}"

    def disable_strategy(self, sid: str) -> str:
        return f"disabled {sid}"


def build_fake_controller() -> FakeController:
    """Factory used by devserver.py — a fresh in-memory controller, MT5 offline."""
    return FakeController()
