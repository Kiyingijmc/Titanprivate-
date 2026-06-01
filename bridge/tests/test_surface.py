# bridge/tests/test_surface.py
import os, sys, types, unittest
from unittest.mock import MagicMock

# The bridge imports `MetaTrader5` (Windows-only). Inject a mock BEFORE importing the app
# so the FastAPI surface is importable/testable anywhere.
sys.modules.setdefault("MetaTrader5", MagicMock())
os.environ.setdefault("BRIDGE_AUTH_TOKEN", "testtoken")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastapi.testclient import TestClient  # noqa: E402
from app import main as bridge_main         # noqa: E402
from app.models import SymbolInfo           # noqa: E402


class Surface(unittest.TestCase):
    def setUp(self):
        # Replace the real MT5Client with a fake so no terminal is needed.
        self.fake = MagicMock()
        bridge_main._mt5 = self.fake
        bridge_main._circuit._healthy = True
        self.client = TestClient(bridge_main.app)
        self.auth = {"Authorization": "Bearer testtoken"}

    def test_health_needs_no_auth_and_no_mt5(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["status"], ("ok", "degraded", "down"))

    def test_symbol_requires_auth(self):
        r = self.client.get("/symbol/EURUSD")           # no header
        self.assertEqual(r.status_code, 401)

    def test_symbol_returns_tick_fields(self):
        async def _aget(_sym):
            return SymbolInfo(name="EURUSD", digits=5, point=1e-5, spread=8,
                              contract_size=100000.0, volume_min=0.01, volume_max=500.0,
                              volume_step=0.01, trade_mode=4, tick_value=1.0, tick_size=1e-5)
        self.fake.aget_symbol_info = _aget
        r = self.client.get("/symbol/EURUSD", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["tick_value"], 1.0)
        self.assertEqual(body["tick_size"], 1e-5)


if __name__ == "__main__":
    unittest.main()
