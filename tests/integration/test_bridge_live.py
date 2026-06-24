# tests/integration/test_bridge_live.py
# Opt-in: requires the Titan bridge running on Windows + FBS-Demo terminal.
# Run with:  TITAN_BRIDGE_LIVE_TEST=1 TITAN_BRIDGE_TOKEN=... .venv/bin/python -m unittest tests.integration.test_bridge_live -v
# Places REAL demo orders (0.01 lot), so it is never part of the auto suite.
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker import types as T

_ENABLED = os.environ.get("TITAN_BRIDGE_LIVE_TEST") == "1"


@unittest.skipUnless(_ENABLED, "set TITAN_BRIDGE_LIVE_TEST=1 (needs live bridge + demo terminal)")
class Live(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_account(self):
        async with MT5HttpBroker() as b:
            h = await b.health_check()
            self.assertIn(h.status, ("ok", "degraded"))
            acct = await b.get_account()
            self.assertGreater(acct.balance, 0)

    async def test_symbol_has_tick_fields(self):
        async with MT5HttpBroker() as b:
            s = await b.get_symbol_info("XAUUSD")
            self.assertGreater(s.tick_value, 0)
            self.assertGreater(s.tick_size, 0)

    async def test_execution_round_trip(self):
        async with MT5HttpBroker() as b:
            tick = await b.get_current_tick("EURUSD")
            info = await b.get_symbol_info("EURUSD")
            pip = info.point * (10 if info.digits in (3, 5) else 1)
            sl = round(tick.ask - 30 * pip, info.digits)
            res = await b.place_market_order(T.MarketOrderRequest(
                symbol="EURUSD", volume=0.01, side=T.OrderSide.BUY, sl=sl, magic=88001,
                comment="titan_phase1_integ"))
            self.assertTrue(res.success, f"place failed: {res}")
            ticket = res.ticket
            try:
                pos = [p for p in await b.get_open_positions() if p.ticket == ticket]
                self.assertEqual(len(pos), 1)
                self.assertIsNotNone(pos[0].sl)
                mod = await b.modify_position(ticket, sl=round(tick.ask - 10 * pip, info.digits))
                self.assertTrue(mod.success, f"modify failed: {mod}")
            finally:
                close = await b.close_position(ticket)
                self.assertTrue(close.success, f"close failed: {close}")
            self.assertNotIn(ticket, [p.ticket for p in await b.get_open_positions()])


if __name__ == "__main__":
    unittest.main()
