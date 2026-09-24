import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from src.core.broker_universe import cap_volume, prepare_universe, refresh_order_specs
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker.types import SymbolInfo, Tick
from src.strategies.models.almanac import Almanac
from src.strategies.universe import discover_catalog, selected_pairs, resolve_config, order_problem


def spec(name="EURUSD.pro", **values):
    return SymbolInfo(**{**dict(name=name, digits=5, point=.00001, spread_points=10,
                               contract_size=100000., tick_size=.00001, tick_value=1.,
                               volume_min=.01, volume_max=5., volume_step=.01,
                               trade_mode=4, order_mode=63, trade_stops_level=10,
                               currency_base="EUR", currency_profit="USD"), **values})


class FakeBroker:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def list_symbols(self):
        return ["EURUSD.pro", "US30", "CLOSED"]

    async def get_symbol_info(self, name):
        return spec(name, trade_mode=0 if name == "CLOSED" else 4)


class UniverseTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_preserves_broker_names_and_records_disabled(self):
        catalog, rejected = await discover_catalog(FakeBroker())
        self.assertIn("EURUSD.pro", catalog)
        self.assertIn("CLOSED", rejected)
        self.assertNotIn("EURUSD.pro", rejected)

    async def test_http_list_deduplicates_and_keeps_permissions(self):
        def handler(req):
            if req.url.path == "/symbols":
                return httpx.Response(200, json={"symbols": ["#ABC", "EURUSD.pro", "#ABC"]})
            self.assertIn("%23ABC", str(req.url))
            d = spec("#ABC").model_dump()
            d["spread"] = d.pop("spread_points")
            return httpx.Response(200, json=d)
        async with MT5HttpBroker("http://test", "tok", transport=httpx.MockTransport(handler)) as b:
            self.assertEqual(await b.list_symbols(), ["#ABC", "EURUSD.pro"])
            self.assertEqual((await b.get_symbol_info("#ABC")).order_mode, 63)

    async def test_boot_resolves_universe_and_keeps_disabled_strategy_disabled(self):
        c = SimpleNamespace(config={"strategies": {
            "silver_bullet": {"enabled": True, "pairs": ["OLD"], "universe": {"source": "broker"}},
            "gambit": {"enabled": False, "pairs": ["US30"]}}},
            logger=Mock(), news_manager=SimpleNamespace())
        await prepare_universe(c, FakeBroker)
        self.assertEqual(c.active_symbols, {"EURUSD.pro", "US30"})
        self.assertFalse(c.config["strategies"]["gambit"]["enabled"])
        self.assertEqual(c.news_manager.policy.currencies_for("EURUSD.pro"), ["EUR", "USD"])

    async def test_capacity_limit_does_not_silently_truncate_or_mutate(self):
        cfg = {"broker_universe": {"max_symbols": 1}, "strategies": {
            "gyroscope": {"enabled": True, "universe": {"source": "broker"}}}}
        c = SimpleNamespace(config=cfg)
        with self.assertRaises(ValueError):
            await prepare_universe(c, FakeBroker)
        self.assertIs(c.config, cfg)

    async def test_default_does_not_connect_to_http(self):
        factory = Mock(side_effect=AssertionError("must not connect"))
        await prepare_universe(SimpleNamespace(config={"strategies": {}}), factory)
        factory.assert_not_called()

    async def test_stale_quotes_block_before_updating_specs(self):
        class StaleBroker(FakeBroker):
            async def get_current_tick(self, name):
                return Tick(symbol=name, time=datetime.now(timezone.utc)-timedelta(hours=1),
                            bid=1.1, ask=1.1001, spread=.0001)
        c = SimpleNamespace(logger=Mock(), risk_manager=Mock())
        self.assertIsNone(await refresh_order_specs(c, "EURUSD.pro", StaleBroker))
        c.risk_manager.update_symbol_specs.assert_not_called()

    async def test_live_controller_blocks_prohibited_direction_before_sizing(self):
        from src.core.system_controller import SystemController
        c = SystemController.__new__(SystemController)
        c.logger = Mock()
        c._news_blocks_symbol = AsyncMock(return_value=(False, ""))
        c._broker_universe_symbols = {"EURUSD.pro"}
        c.risk_manager = Mock()
        c.risk_manager.normalize_price.side_effect = lambda p, symbol: p
        c.live_prices = {"EURUSD.pro": 1.1}
        snapshot = (spec(trade_mode=2), SimpleNamespace(bid=1.1, ask=1.1001))
        with patch("src.core.broker_universe.refresh_order_specs", AsyncMock(return_value=snapshot)):
            await c._execute_signal("EURUSD.pro", {"signal": "BUY", "type": "MARKET",
                                                  "price": 1.1, "sl": 1.09, "tp": 1.12},
                                    "Gyroscope", "NEUTRAL")
        c.risk_manager.calculate_lot_size.assert_not_called()

    async def test_live_controller_preserves_limit_kind_in_expanded_mode(self):
        from src.core.system_controller import SystemController
        c = SystemController.__new__(SystemController)
        c.logger = Mock()
        c._news_blocks_symbol = AsyncMock(return_value=(False, ""))
        c._broker_universe_symbols = {"EURUSD.pro"}
        c.risk_manager = Mock()
        c.risk_manager.normalize_price.side_effect = lambda p, symbol: p
        c.risk_manager.calculate_lot_size.return_value = 0
        c.risk_manager.throttle_factor.return_value = 1
        c.live_prices = {"EURUSD.pro": 1.1001}
        snapshot = (spec(order_mode=50, trade_stops_level=0), SimpleNamespace(bid=1.1001, ask=1.1002))
        # Limit is permitted but MARKET isn't. The old near-price conversion
        # would fail order_problem and never reach sizing.
        with patch("src.core.broker_universe.refresh_order_specs", AsyncMock(return_value=snapshot)):
            await c._execute_signal("EURUSD.pro", {"signal": "BUY", "type": "LIMIT",
                                                  "price": 1.1, "sl": 1.09, "tp": 1.12},
                                    "SilverBullet", "NEUTRAL")
        c.risk_manager.calculate_lot_size.assert_called_once()

    def test_broad_strategies_use_inclusions_and_exclusions(self):
        catalog = {n: spec(n) for n in ("EURUSD.pro", "US30", "BTCUSD")}
        params = {"universe": {"source": "broker", "exclude": ["BTC*"]}}
        self.assertEqual(selected_pairs("gyroscope", params, catalog), ["EURUSD.pro", "US30"])

    def test_almanac_does_not_buy_every_catalog_asset(self):
        catalog = {n: spec(n) for n in ("EURUSD.pro", "US30")}
        params = {"pairs": ["US30"], "universe": {"source": "broker"}}
        self.assertEqual(selected_pairs("almanac", params, catalog), ["US30"])

    def test_gambit_requires_per_symbol_session_and_cost_configuration(self):
        params = {"universe": {"source": "broker"}}
        self.assertEqual(selected_pairs("gambit", params, {"US30": spec("US30")}), [])

    def test_unknown_permissions_and_bad_specs_do_not_become_eligible(self):
        catalog = {"OLD": spec("OLD", order_mode=None), "BAD": spec("BAD", tick_value=0),
                   "NOMARKET": spec("NOMARKET", order_mode=50)}
        self.assertEqual(selected_pairs("gyroscope", {"universe": {"source": "broker"}}, catalog), [])

    def test_empty_dynamic_scope_is_not_unrestricted(self):
        s = Almanac({"pairs": [], "universe": {"source": "broker"}}, Mock())
        self.assertEqual(s.pairs, [])
        config = {"strategies": {"almanac": {"pairs": ["US30"], "universe": {"source": "broker"}}}}
        resolved = resolve_config(config, {})
        self.assertEqual(resolved["strategies"]["almanac"]["pairs"], [])
        self.assertEqual(config["strategies"]["almanac"]["pairs"], ["US30"])

    def test_broker_lot_cap_rounds_down(self):
        self.assertEqual(cap_volume(4.999, spec(volume_max=.035)), .03)
        self.assertEqual(cap_volume(.005, spec()), 0)

    def test_direction_order_type_geometry_and_minimum_distances(self):
        args = ("BUY", "LIMIT", 1.1, 1.09, 1.12, 1.11, 1.1101)
        self.assertIsNone(order_problem(spec(), *args))
        self.assertIn("direction", order_problem(spec(trade_mode=2), *args))
        self.assertIn("order type", order_problem(spec(order_mode=49), *args))
        self.assertIn("wrong side", order_problem(spec(), "BUY", "LIMIT", 1.1, 1.11, 1.12, 1.11, 1.1101))
        self.assertIn("minimum distance", order_problem(spec(), "BUY", "LIMIT", 1.11, 1.10, 1.12, 1.11, 1.11005))


if __name__ == "__main__":
    unittest.main()
