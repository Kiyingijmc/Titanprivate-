"""PAUSED must not freeze in-trade management.

A manual /pause and the stale-news-calendar auto-pause both flip the bot to
BotState.PAUSED. Management (ratchet/BE/partials/kill-switch) has to keep
running in that state -- a paused bot still has money at risk, and the whole
point of pausing is to stop taking NEW risk, not to abandon the open book.
The 08-03 stopless-GBPJPY incident is the same failure shape (management
silently stopped while every ordinary health check looked fine).

New-signal generation stays gated on ACTIVE alone.
"""
import asyncio
import os, sys, unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.system_controller import SystemController, BotState  # noqa: E402
from src.execution.trade_manager import TradeManager  # noqa: E402


class FakeBridge:
    def __init__(self):
        self.commands = []
    async def send_command(self, action, payload=None):
        self.commands.append((action, dict(payload or {})))
        return True


class FakeState:
    """Ratchet state for one long EURUSD ticket, not yet ratcheted (level 0)."""
    def __init__(self):
        self.levels = []
        self.phases = []
    def get_ratchet_state(self, ticket):
        return (0, 1.1000, 1.1100)      # level, initial_entry, initial_tp
    def update_ratchet_level(self, ticket, level): self.levels.append((ticket, level))
    def update_trade_phase(self, ticket, level): self.phases.append((ticket, level))
    def get_order(self, ticket): return None


class FakeLogger:
    def __init__(self): self.events = []
    def log_event(self, *a, **kw): self.events.append(a)


class FakeTelemetry:
    async def send_message(self, *a, **kw): pass
    async def notify_management(self, *a, **kw): pass
    async def notify_partial(self, *a, **kw): pass


class FakeRisk:
    symbol_specs = {}
    def get_max_risk_amount(self): return 100.0
    def normalize_price(self, price, symbol): return round(price, 5)
    def money_for_move(self, symbol, price_distance, lots): return 0.0
    def has_specs(self, symbol): return True


class RecordingMarketData:
    """Stands in for the per-symbol candle buffer: records whether the TICK
    handler fed it, which is exactly what new-signal generation depends on."""
    def __init__(self): self.ticks = []
    def process_tick(self, msg):
        self.ticks.append(msg)
        return []


def make_controller(state):
    sc = object.__new__(SystemController)
    sc.bridge = FakeBridge()
    sc.state_manager = FakeState()
    sc.logger = FakeLogger()
    sc.telemetry = FakeTelemetry()
    sc.risk_manager = FakeRisk()
    # real TradeManager -- the assertion is on genuine ratchet behaviour
    sc.trade_manager = TradeManager(sc.logger, sc.state_manager, sc.risk_manager)
    sc.market_data = {"EURUSD": RecordingMarketData()}
    sc.live_prices = {}
    sc.live_spreads = {}
    sc.state = state
    # long EURUSD, entry 1.1000 / TP 1.1100; the tick below sits at 50% of the
    # range, past the 0.382 break-even threshold
    sc.current_open_positions = [{"t": 42, "s": "EURUSD", "p": 1.1000, "sl": 1.0950,
                                  "tp": 1.1100, "pf": 5.0, "vol": 0.10, "type": 0}]
    sc.current_pending_orders = []
    sc.strategy_calls = []

    async def _fake_run_strategies(symbol, df, tf):
        sc.strategy_calls.append((symbol, tf))
    sc._run_strategies = _fake_run_strategies
    return sc


TICK = {"type": "TICK", "s": "EURUSD", "b": 1.1050, "a": 1.1051}


def run(coro):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class PausedKeepsManagingOpenTrades(unittest.TestCase):
    def test_paused_tick_still_dispatches_ratchet_modify(self):
        sc = make_controller(BotState.PAUSED)
        run(sc._process_incoming_data(TICK))
        self.assertEqual([a for a, _ in sc.bridge.commands], ["MODIFY"],
                         "in-trade management must survive PAUSED")
        _, payload = sc.bridge.commands[0]
        self.assertEqual(payload["ticket"], 42)
        self.assertEqual(payload["symbol"], "EURUSD")
        # break-even + 3 pip buffer on a long entered at 1.1000
        self.assertAlmostEqual(payload["sl"], 1.1003, places=5)

    def test_active_tick_still_dispatches_ratchet_modify(self):
        sc = make_controller(BotState.ACTIVE)
        run(sc._process_incoming_data(TICK))
        self.assertEqual([a for a, _ in sc.bridge.commands], ["MODIFY"])

    def test_non_trading_states_still_skip_management(self):
        for state in (BotState.BOOTING, BotState.WARMUP, BotState.EMERGENCY):
            with self.subTest(state=state.name):
                sc = make_controller(state)
                run(sc._process_incoming_data(TICK))
                self.assertEqual(sc.bridge.commands, [])


class PausedStillSuppressesNewSignals(unittest.TestCase):
    def test_paused_tick_does_not_feed_the_candle_buffer(self):
        sc = make_controller(BotState.PAUSED)
        run(sc._process_incoming_data(TICK))
        self.assertEqual(sc.market_data["EURUSD"].ticks, [],
                         "paused bot must not build candles / generate entries")
        self.assertEqual(sc.strategy_calls, [])

    def test_active_tick_does_feed_the_candle_buffer(self):
        sc = make_controller(BotState.ACTIVE)
        run(sc._process_incoming_data(TICK))
        self.assertEqual(len(sc.market_data["EURUSD"].ticks), 1)

    def test_paused_tick_still_records_live_price(self):
        sc = make_controller(BotState.PAUSED)
        run(sc._process_incoming_data(TICK))
        self.assertAlmostEqual(sc.live_prices["EURUSD"], 1.1050)


if __name__ == "__main__":
    unittest.main()
