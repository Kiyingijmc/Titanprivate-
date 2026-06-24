# tests/unit/test_broker_base.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker.base import Broker


class BaseProto(unittest.TestCase):
    def test_protocol_is_runtime_checkable_and_lists_methods(self):
        for m in ("health_check", "get_account", "get_symbol_info", "get_candles",
                  "get_candles_range", "get_current_tick", "get_open_positions",
                  "get_pending_orders", "place_market_order", "place_pending_order",
                  "modify_position", "close_position", "cancel_order"):
            self.assertTrue(hasattr(Broker, m), f"protocol missing {m}")


if __name__ == "__main__":
    unittest.main()
