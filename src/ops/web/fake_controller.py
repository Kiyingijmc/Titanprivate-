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
        self.applied = []
        self.published = []

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
