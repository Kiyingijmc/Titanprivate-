# tests/unit/test_cache_specs_http.py
import os, sys, json, unittest, tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import cache_specs as cs
from src.execution.broker import types as T


class FakeBroker:
    async def get_symbol_info(self, symbol):
        return T.SymbolInfo(name=symbol, digits=2, point=0.01, spread_points=20,
                            contract_size=100.0, volume_min=0.01, volume_max=50.0,
                            volume_step=0.01, tick_value=1.0, tick_size=0.01)


class Specs(unittest.IsolatedAsyncioTestCase):
    async def test_builds_specs_dict_in_legacy_shape(self):
        out = await cs.build_specs(FakeBroker(), ["XAUUSD", "EURUSD"])
        self.assertEqual(set(out), {"XAUUSD", "EURUSD"})
        self.assertEqual(out["XAUUSD"], {"tick_value": 1.0, "tick_size": 0.01,
                                         "vol_min": 0.01, "vol_step": 0.01})

    async def test_skips_symbol_on_broker_error(self):
        from src.execution.broker.errors import BrokerNotFoundError

        class FlakyBroker:
            async def get_symbol_info(self, symbol):
                if symbol == "BAD":
                    raise BrokerNotFoundError("no such symbol")
                return T.SymbolInfo(name=symbol, digits=2, point=0.01, spread_points=20,
                                    contract_size=100.0, volume_min=0.01, volume_max=50.0,
                                    volume_step=0.01, tick_value=1.0, tick_size=0.01)

        out = await cs.build_specs(FlakyBroker(), ["XAUUSD", "BAD", "EURUSD"])
        self.assertEqual(set(out), {"XAUUSD", "EURUSD"})   # BAD skipped, others kept


if __name__ == "__main__":
    unittest.main()
