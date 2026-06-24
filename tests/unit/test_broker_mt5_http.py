# tests/unit/test_broker_mt5_http.py
import os, sys, unittest, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import httpx
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker import types as T
from src.execution.broker import errors as E


def _broker(handler):
    return MT5HttpBroker("http://test", "tok", transport=httpx.MockTransport(handler))


class Reads(unittest.IsolatedAsyncioTestCase):
    async def test_get_symbol_info_maps_tick_fields(self):
        def h(req):
            self.assertEqual(req.headers["Authorization"], "Bearer tok")
            return httpx.Response(200, json={
                "name": "XAUUSD", "digits": 2, "point": 0.01, "spread": 20,
                "contract_size": 100.0, "volume_min": 0.01, "volume_max": 50.0,
                "volume_step": 0.01, "trade_mode": 4, "tick_value": 1.0, "tick_size": 0.01})
        async with _broker(h) as b:
            s = await b.get_symbol_info("XAUUSD")
        self.assertEqual((s.tick_value, s.tick_size, s.spread_points), (1.0, 0.01, 20))

    async def test_get_candles_range_maps_fields(self):
        def h(req):
            self.assertIn("/candles/XAUUSD/5/range", req.url.path)
            return httpx.Response(200, json=[{
                "time": "2026-01-01T00:00:00+00:00", "open": 1, "high": 2, "low": 0.5,
                "close": 1.5, "tick_volume": 10, "spread": 3, "real_volume": 0}])
        async with _broker(h) as b:
            cs = await b.get_candles_range("XAUUSD", T.Timeframe.M5,
                                           __import__("datetime").datetime(2026,1,1),
                                           __import__("datetime").datetime(2026,1,2))
        self.assertEqual(cs[0].close, 1.5)
        self.assertEqual(cs[0].spread_points, 3)

    async def test_position_sl_zero_becomes_none_and_side_maps(self):
        def h(req):
            return httpx.Response(200, json=[{
                "ticket": 5, "symbol": "EURUSD", "type": 1, "volume": 0.01,
                "price_open": 1.1, "sl": 0.0, "tp": 1.2, "price_current": 1.1,
                "profit": 0.0, "swap": 0.0, "commission": 0.0,
                "time": "2026-01-01T00:00:00+00:00", "comment": "", "magic": 88000}])
        async with _broker(h) as b:
            ps = await b.get_open_positions()
        self.assertIsNone(ps[0].sl)
        self.assertEqual(ps[0].side, T.OrderSide.SELL)

    async def test_401_maps_to_auth_error(self):
        def h(req):
            return httpx.Response(401, json={"detail": "bad token"})
        async with _broker(h) as b:
            with self.assertRaises(E.BrokerAuthError):
                await b.get_account()


if __name__ == "__main__":
    unittest.main()
