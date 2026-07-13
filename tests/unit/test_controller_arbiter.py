"""Plan 05 / Task 4: intents through the Arbiter on the live path.

Verifies _run_strategies wiring (single-decision transparency, conflict
resolution, open-position blocking) and the config-gated drawdown throttle
(RiskManager.throttle_factor / calculate_lot_size risk_mult). The frozen
parity fixture (tests/unit/test_signal_parity.py) is the byte-identical
transparency gate for today's single-strategy live config; these tests cover
the wiring and the multi-strategy conflict paths the parity fixture can't
exercise (it only ever carries one strategy).
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.core.system_controller import SystemController
from src.arbiter.arbiter import Arbiter
from src.arbiter.intent import Intent
from src.core.events import IntentBlocked
from src.risk.risk_manager import RiskManager
from src.strategies.registry import StrategyRegistry


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class FakeLogger:
    def log_event(self, *a, **kw):
        pass


class FakeTimeEngine:
    def get_current_ny_string(self):
        return "10:00:00 EST"


class FakeStore:
    """market_data[symbol] stand-in: only get_data("H1") is exercised, and
    only for the FeatureBus h1_token computation."""
    def get_data(self, tf):
        return None


class FakeFeatureBus:
    """Minimal FeatureBus stand-in: returns the input window untouched and a
    fixed NEUTRAL bias (so neither BUY nor SELL signals get bias-filtered)."""
    def __init__(self, bias="NEUTRAL"):
        self.bias = bias

    def evaluate(self, name, symbol, tf, token=None, window=None, h1_df=None):
        if name == "smc.enriched_df":
            return window
        if name == "smc.bias_context":
            return (self.bias, {})
        raise ValueError(f"unexpected resource {name}")


class FakeGrader:
    """Stands in for SignalGrader: fixed grade per strategy name, always
    passes -- isolates the arbiter-wiring tests from grading internals
    (SignalGrader has its own dedicated tests)."""
    def __init__(self, grade_by_name=None, default_grade="A+"):
        self.grade_by_name = grade_by_name or {}
        self.default_grade = default_grade
        self.min_grade = "B"

    def grade(self, decision, context, candle=None):
        return {"score": 100, "grade": self.default_grade, "factors": []}

    def passes(self, grade):
        return True


class FakeStrategy:
    def __init__(self, name, decision, timeframe="H1"):
        self.name = name
        self.timeframe = timeframe
        self._decision = decision

    async def on_new_candle(self, df, context=None):
        return self._decision


def _bar_df():
    return pd.DataFrame([{"time": "bar-1"}])


def _decision(signal="BUY", price=1.1000, sl=1.0950, tp=1.1100):
    return {"signal": signal, "type": "MARKET", "price": price, "sl": sl, "tp": tp}


def make_controller(strategies, grade_by_name=None, default_grade="A+",
                     open_positions=None, arbiter_cfg=None):
    c = SystemController.__new__(SystemController)
    c.logger = FakeLogger()
    c.strategies = strategies
    c.market_data = {"EURUSD": FakeStore()}
    c.time_engine = FakeTimeEngine()
    c.feature_bus = FakeFeatureBus()
    c.signal_grader = FakeGrader(grade_by_name, default_grade)
    c.current_open_positions = open_positions or []

    published = []
    c.arbiter = Arbiter(arbiter_cfg or {}, publish=published.append)

    captured = []

    async def _capture_execute_signal(symbol, decision, name, htf_bias, grade=""):
        captured.append((symbol, decision, name, htf_bias, grade))

    c._execute_signal = _capture_execute_signal
    return c, captured, published


class TestTransparency(unittest.TestCase):
    """A single decision must reach _execute_signal with IDENTICAL args to
    the pre-Plan-05 direct-execute call -- the arbiter must be provably
    transparent for the single-strategy case."""

    def test_single_decision_flows_through_arbiter_unchanged(self):
        decision = _decision()
        strat = FakeStrategy("SilverBullet", decision)
        c, captured, published = make_controller([strat], default_grade="A+")

        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))

        self.assertEqual(len(captured), 1)
        symbol, got_decision, name, htf_bias, grade = captured[0]
        self.assertEqual(symbol, "EURUSD")
        self.assertIs(got_decision, decision)
        self.assertEqual(name, "SilverBullet")
        self.assertEqual(htf_bias, "NEUTRAL")
        self.assertEqual(grade, "A+")
        self.assertEqual(
            captured[0],
            ("EURUSD", decision, "SilverBullet", "NEUTRAL", "A+"),
        )


class TestConflictResolution(unittest.TestCase):
    def test_opposite_directions_higher_grade_wins_loser_blocked(self):
        buy_decision = _decision(signal="BUY", price=1.1000, sl=1.0950, tp=1.1100)
        sell_decision = _decision(signal="SELL", price=1.1005, sl=1.1055, tp=1.0905)
        strat_a = FakeStrategy("StratA", buy_decision)
        strat_b = FakeStrategy("StratB", sell_decision)
        c, captured, published = make_controller(
            [strat_a, strat_b],
            arbiter_cfg={"opposition_policy": "higher_grade_wins"},
        )
        # Grade StratA higher so its BUY should win the opposition.
        c.signal_grader = FakeGrader()
        c.signal_grader.grade = lambda decision, context, candle=None: (
            {"score": 100, "grade": "A+" if decision["signal"] == "BUY" else "B", "factors": []}
        )

        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][2], "StratA")
        self.assertEqual(captured[0][1]["signal"], "BUY")

        blocked = [e for e in published if isinstance(e, IntentBlocked)]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "opposition")
        self.assertEqual(blocked[0].direction, "SELL")


class TestOpenPositionBlocks(unittest.TestCase):
    def test_open_position_on_symbol_blocks_new_intent(self):
        decision = _decision()
        strat = FakeStrategy("SilverBullet", decision)
        c, captured, published = make_controller(
            [strat],
            open_positions=[{"t": 1, "s": "EURUSD", "p": 1.1, "dir": "BUY"}],
            arbiter_cfg={"max_positions_per_symbol": 1},
        )

        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))

        self.assertEqual(captured, [])
        blocked = [e for e in published if isinstance(e, IntentBlocked)]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].rule, "symbol_cap")


class ThrottleConfig(unittest.TestCase):
    """RiskManager.throttle_factor() + calculate_lot_size(risk_mult=...)."""

    def _rm(self, throttle_cfg, max_dd=5.0):
        rm = RiskManager({
            "risk": {
                "account": {"max_daily_drawdown_pct": max_dd},
                "trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0,
                          "static_commission_usd": 0.0},
                "drawdown_throttle": throttle_cfg,
            }
        })
        # val=90.0 is chosen (not a real broker tick value) so that, combined
        # with the 1% risk / 3% synthetic drawdown numbers below, lots_gross
        # sits comfortably mid-step (~2.16 and ~1.08 steps, not near an
        # integer floor boundary where float dust could flip the floor) --
        # the halving survives the final floor-to-vol_step rounding exactly,
        # making the "step-normalized, exactly halved" assertion unambiguous.
        rm.update_symbol_specs("EURUSD", val=90.0, size=0.0001, v_min=0.01, v_step=0.01)
        return rm

    def test_throttle_disabled_returns_one(self):
        rm = self._rm({"enabled": False, "trigger_dd_pct": 2.0, "factor": 0.5})
        rm.update_account_info(10000.0, 10000.0)
        rm.update_account_info(10000.0, 9000.0)  # -10% intraday, still disabled
        self.assertEqual(rm.throttle_factor(), 1.0)

    def test_throttle_enabled_synthetic_drawdown_halves_lot_step_normalized(self):
        rm = self._rm({"enabled": True, "trigger_dd_pct": 2.0, "factor": 0.5})
        rm.update_account_info(10000.0, 10000.0)   # day-start anchor = 10000
        self.assertEqual(rm.throttle_factor(), 1.0)  # no drawdown yet

        rm.update_account_info(10000.0, 9700.0)     # -3.0% on the day -> triggers
        self.assertEqual(rm.throttle_factor(), 0.5)

        lot_full = rm.calculate_lot_size(1.1000, 1.0950, "EURUSD", "BULLISH", risk_mult=1.0)
        lot_throttled = rm.calculate_lot_size(1.1000, 1.0950, "EURUSD", "BULLISH",
                                              risk_mult=rm.throttle_factor())
        self.assertAlmostEqual(lot_full, 0.02, places=2)
        self.assertAlmostEqual(lot_throttled, 0.01, places=2)
        self.assertAlmostEqual(lot_throttled, round(lot_full / 2, 2), places=2)
        # step-normalized: an exact multiple of vol_step (0.01)
        self.assertAlmostEqual(lot_throttled / 0.01, round(lot_throttled / 0.01), places=6)

    def test_default_risk_mult_is_byte_identical_to_pre_throttle_sizing(self):
        rm = self._rm({"enabled": False})
        rm.update_account_info(10000.0, 10000.0)
        with_default = rm.calculate_lot_size(1.1000, 1.0950, "EURUSD", "BULLISH")
        with_explicit_one = rm.calculate_lot_size(1.1000, 1.0950, "EURUSD", "BULLISH", risk_mult=1.0)
        self.assertEqual(with_default, with_explicit_one)


class TestIdOf(unittest.TestCase):
    def test_id_of_reverse_lookup(self):
        registry = StrategyRegistry.__new__(StrategyRegistry)
        strat_a = object()
        strat_b = object()
        registry._instances = {"sb_v1": strat_a, "sb_v2": strat_b}

        self.assertEqual(registry.id_of(strat_a), "sb_v1")
        self.assertEqual(registry.id_of(strat_b), "sb_v2")
        self.assertIsNone(registry.id_of(object()))


if __name__ == "__main__":
    unittest.main()
