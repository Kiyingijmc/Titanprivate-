# tests/unit/test_broker_types.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker import types as T
from src.execution.broker import errors as E


class Types(unittest.TestCase):
    def test_symbolinfo_has_tick_fields(self):
        s = T.SymbolInfo(name="XAUUSD", digits=2, point=0.01, spread_points=20,
                         contract_size=100.0, volume_min=0.01, volume_max=50.0,
                         volume_step=0.01, tick_value=1.0, tick_size=0.01)
        self.assertEqual(s.tick_value, 1.0)
        self.assertEqual(s.tick_size, 0.01)

    def test_enums(self):
        self.assertEqual(T.OrderSide.BUY.value, "buy")
        self.assertEqual(T.PendingOrderType.BUY_STOP.value, "buy_stop")
        self.assertEqual(T.Timeframe.M5.value, "M5")

    def test_error_hierarchy(self):
        for cls in (E.BrokerConnectionError, E.BrokerAuthError, E.BrokerNotFoundError):
            self.assertTrue(issubclass(cls, E.BrokerError))


if __name__ == "__main__":
    unittest.main()
