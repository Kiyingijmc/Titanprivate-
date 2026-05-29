# ==============================================================================
# FILE: tests/unit/test_risk_manager_normalize_price.py
# Regression tests for RiskManager.normalize_price.
#
# Reproduces the boot_crash.log fault: an IndexError raised when a broker
# reports a sub-0.0001 tick size (standard 5-digit forex, e.g. 0.00001).
# Python renders such floats in scientific notation ("1e-05"), so the old
# precision logic str(float(ts)).split('.')[1] had no element [1] and threw.
# ==============================================================================

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.risk.risk_manager import RiskManager


def _make_risk_manager():
    """Minimal config matching the keys RiskManager.__init__ reads."""
    config = {
        "risk": {
            "account": {"max_daily_drawdown_pct": 3.0},
            "trade": {"risk_per_trade_pct": 1.0},
        }
    }
    return RiskManager(config)


class NormalizePriceTickSize(unittest.TestCase):
    def test_five_digit_forex_tick_does_not_crash(self):
        """The boot_crash.log case: tick size 0.00001 -> '1e-05' in str()."""
        rm = _make_risk_manager()
        rm.update_symbol_specs("EURUSD", val=1.0, size=0.00001, v_min=0.01, v_step=0.01)

        # Previously raised IndexError: list index out of range.
        result = rm.normalize_price(1.234567, "EURUSD")

        # 1.234567 snapped to the 0.00001 grid and rounded to 5 dp.
        self.assertAlmostEqual(result, 1.23457, places=5)

    def test_index_quarter_tick_still_works(self):
        """Regression guard: 0.25 ticks (indices) must keep snapping correctly."""
        rm = _make_risk_manager()
        rm.update_symbol_specs("US30", val=1.0, size=0.25, v_min=0.1, v_step=0.1)

        self.assertAlmostEqual(rm.normalize_price(100.30, "US30"), 100.25, places=2)
        self.assertAlmostEqual(rm.normalize_price(100.40, "US30"), 100.50, places=2)

    def test_gold_cent_tick_still_works(self):
        """Regression guard: 0.01 ticks (gold) must keep snapping correctly."""
        rm = _make_risk_manager()
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)

        self.assertAlmostEqual(rm.normalize_price(1950.123, "XAUUSD"), 1950.12, places=2)


if __name__ == "__main__":
    unittest.main()
