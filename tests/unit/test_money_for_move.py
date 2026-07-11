import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.risk.risk_manager import RiskManager


def _rm():
    rm = RiskManager({"risk": {"account": {"max_daily_drawdown_pct": 3.0}, "trade": {"risk_per_trade_pct": 1.0}}})
    rm.update_account_info(10000.0, 10000.0)
    return rm


class MoneyForMoveTests(unittest.TestCase):
    def test_no_specs_fails_safe_to_zero(self):
        self.assertEqual(_rm().money_for_move("XAUUSD", 1.5, 0.10), 0.0)

    def test_with_specs_computes_dollars(self):
        rm = _rm()
        # tick_value=1.0 per tick, tick_size=0.01 -> 150 ticks over a 1.5 move; * 0.10 lots = $15.00
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
        self.assertAlmostEqual(rm.money_for_move("XAUUSD", 1.5, 0.10), 15.0, places=6)

    def test_uses_absolute_distance(self):
        rm = _rm()
        rm.update_symbol_specs("EURUSD", val=1.0, size=0.0001, v_min=0.01, v_step=0.01)
        pos = rm.money_for_move("EURUSD", 0.0050, 1.0)
        neg = rm.money_for_move("EURUSD", -0.0050, 1.0)
        self.assertGreater(pos, 0.0)
        self.assertEqual(pos, neg)

    def test_zero_lots_is_zero(self):
        rm = _rm()
        rm.update_symbol_specs("EURUSD", val=1.0, size=0.0001, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.money_for_move("EURUSD", 0.0050, 0.0), 0.0)
