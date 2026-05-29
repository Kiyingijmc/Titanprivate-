# ==============================================================================
# FILE: tests/unit/test_risk_manager_sizing.py
# calculate_lot_size must size ONLY from real broker specs (tick_value/size).
# If specs haven't loaded for a symbol it must fail safe (return 0, no trade)
# rather than guess with the forex-shaped fallback -- which silently mis-sized
# or zeroed non-forex assets (gold/oil -> 0 lots, indices mis-scaled).
# ==============================================================================

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.risk.risk_manager import RiskManager


def _rm(equity=10000.0):
    rm = RiskManager(
        {"risk": {"account": {"max_daily_drawdown_pct": 3.0}, "trade": {"risk_per_trade_pct": 1.0}}}
    )
    rm.update_account_info(equity, equity)  # locks starting balance + sets equity
    return rm


class CalculateLotSizeSpecGuard(unittest.TestCase):
    def test_missing_specs_fails_safe_to_zero(self):
        """No broker specs for an index -> must skip, not guess."""
        rm = _rm()
        self.assertEqual(rm.calculate_lot_size(50000, 49500, "US30", "BULLISH"), 0.0)

    def test_forex_without_specs_also_skips(self):
        """Intentional: even forex now requires real specs (no silent guess)."""
        rm = _rm()
        self.assertEqual(rm.calculate_lot_size(1.1000, 1.0950, "EURUSD", "BULLISH"), 0.0)

    def test_with_specs_sizes_from_broker_math(self):
        """With specs, sizing uses tick_value/tick_size for any asset class."""
        rm = _rm()
        rm.update_symbol_specs("US30", val=0.1, size=0.01, v_min=0.01, v_step=0.01)
        # gross = $100 / ((500 / 0.01) ticks * 0.1 per tick) = 0.02; after the
        # commission net-risk adjustment and floor-to-volume-step it lands on 0.01.
        self.assertAlmostEqual(rm.calculate_lot_size(50000, 49500, "US30", "BULLISH"), 0.01, places=2)

    def test_zero_volume_step_does_not_crash(self):
        """A broker reporting volume_step=0 must not cause a divide-by-zero."""
        rm = _rm()
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.0, v_step=0.0)
        lots = rm.calculate_lot_size(2000, 1990, "XAUUSD", "BULLISH")
        self.assertGreaterEqual(lots, 0.0)  # a number, not an exception


if __name__ == "__main__":
    unittest.main()
