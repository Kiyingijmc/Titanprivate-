import asyncio
import os, sys, time, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.strategies.models.silver_bullet import SilverBullet
from src.core.system_controller import SystemController


class MockLogger:
    def log_event(self, *a, **kw): pass


def sb_frame(direction="SELL"):
    """60-bar frame whose last candle is a displacement FVG signal."""
    n = 60
    base = {
        "open": [1.1000] * n, "high": [1.1005] * n, "low": [1.0995] * n,
        "close": [1.1000] * n, "ATR": [0.0010] * n,
        "is_swing_high": [False] * n, "is_swing_low": [False] * n,
        "is_fvg_bull": [False] * n, "is_fvg_bear": [False] * n,
        "fvg_top": [0.0] * n, "fvg_bottom": [0.0] * n,
    }
    df = pd.DataFrame(base)
    i = n - 1
    if direction == "SELL":
        df.loc[i, ["open", "close", "high", "low"]] = [1.1010, 1.0990, 1.1012, 1.0988]
        df.loc[i, "is_fvg_bear"] = True
        df.loc[i, "fvg_top"] = 1.1015
        df.loc[i, "fvg_bottom"] = 1.1012
    else:
        df.loc[i, ["open", "close", "high", "low"]] = [1.0990, 1.1010, 1.1012, 1.0988]
        df.loc[i, "is_fvg_bull"] = True
        df.loc[i, "fvg_top"] = 1.0988
        df.loc[i, "fvg_bottom"] = 1.0985
    return df


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class StopAtrConfig(unittest.TestCase):
    """v14.4.2: the SL distance is stop_atr * ATR from the ENTRY (validated
    H1 config = 1.0; the legacy 0.2 buffer was cost-fatal, see
    docs/research/2026-07-11-silverbullet-h1-stop-study.md)."""

    def _signal(self, cfg, direction="SELL"):
        sb = SilverBullet(cfg, MockLogger())
        ctx = {"ny_time": "10:15:00 EST"}
        return run(sb.on_new_candle(sb_frame(direction), context=ctx))

    def test_default_stop_is_one_atr(self):
        d = self._signal({"windows": [[0, 24]]})
        self.assertIsNotNone(d)
        self.assertAlmostEqual(abs(d["price"] - d["sl"]), 0.0010, places=6)  # 1.0 x ATR

    def test_legacy_stop_configurable(self):
        d = self._signal({"windows": [[0, 24]], "stop_atr": 0.2})
        self.assertAlmostEqual(abs(d["price"] - d["sl"]), 0.0002, places=6)

    def test_buy_side_symmetry_and_rr(self):
        d = self._signal({"windows": [[0, 24]], "risk_reward": 2.0}, direction="BUY")
        self.assertEqual(d["signal"], "BUY")
        risk = d["price"] - d["sl"]
        self.assertAlmostEqual(risk, 0.0010, places=6)
        self.assertAlmostEqual(d["tp"] - d["price"], 2.0 * risk, places=6)

    def test_default_timeframe_h1(self):
        sb = SilverBullet({}, MockLogger())
        self.assertEqual(sb.timeframe, "H1")
        sb5 = SilverBullet({"timeframe": "M5"}, MockLogger())
        self.assertEqual(sb5.timeframe, "M5")


class FakeStrategy:
    def __init__(self, name, tf):
        self.name = name
        self.timeframe = tf
        self.calls = 0
    async def on_new_candle(self, df, context=None):
        self.calls += 1
        return None


class FakeStore:
    def get_data(self, tf):
        return pd.DataFrame()   # BiasEngine returns NEUTRAL on short data


class TimeframeRouting(unittest.TestCase):
    def make_controller(self):
        sc = object.__new__(SystemController)
        sc.logger = MockLogger()
        sc.market_data = {"EURUSD": FakeStore()}
        sc.time_engine = type("T", (), {"get_current_ny_string": lambda s: "10:00:00"})()
        sc.strategies = [FakeStrategy("SB_H1", "H1"), FakeStrategy("CRT_M5", "M5")]
        return sc

    def test_h1_close_runs_only_h1_strategies(self):
        sc = self.make_controller()
        df = sb_frame()
        run(sc._run_strategies("EURUSD", df, tf="H1"))
        self.assertEqual(sc.strategies[0].calls, 1)
        self.assertEqual(sc.strategies[1].calls, 0)

    def test_m5_close_runs_only_m5_strategies(self):
        sc = self.make_controller()
        df = sb_frame()
        run(sc._run_strategies("EURUSD", df, tf="M5"))
        self.assertEqual(sc.strategies[0].calls, 0)
        self.assertEqual(sc.strategies[1].calls, 1)

    def test_no_matching_strategies_is_cheap_noop(self):
        sc = self.make_controller()
        sc.strategies = [FakeStrategy("SB_H1", "H1")]
        run(sc._run_strategies("EURUSD", sb_frame(), tf="M15"))
        self.assertEqual(sc.strategies[0].calls, 0)


class TtlPerTimeframe(unittest.TestCase):
    """Pending-limit TTL = 12 bars of the strategy's timeframe (H1 SB limits
    must live 12h, not the legacy 1h)."""

    def make_controller(self, age_s):
        sc = object.__new__(SystemController)
        sc.logger = MockLogger()
        sc.strategy_ttls = {"SilverBullet": 12 * 3600}
        class Bridge:
            def __init__(self): self.commands = []
            async def send_command(self, a, p=None): self.commands.append((a, p))
        class State:
            def __init__(self): self.deleted = []
            def get_pending_orders(self):
                return [{"ticket_id": 5, "strategy": "SilverBullet",
                         "time_placed": time.time() - age_s}]
            def delete_order(self, t): self.deleted.append(t)
        class Tele:
            async def send_message(self, *a, **kw): pass
        sc.bridge = Bridge(); sc.state_manager = State(); sc.telemetry = Tele()
        return sc

    def test_h1_limit_survives_two_hours(self):
        sc = self.make_controller(age_s=2 * 3600)
        run(sc._cleanup_ghost_orders())
        self.assertEqual(sc.bridge.commands, [])

    def test_h1_limit_cancelled_after_12_bars(self):
        sc = self.make_controller(age_s=13 * 3600)
        run(sc._cleanup_ghost_orders())
        self.assertEqual(sc.bridge.commands[0][0], "CANCEL")
        self.assertEqual(sc.state_manager.deleted, [5])


if __name__ == "__main__":
    unittest.main()
