"""A bias/liquidity data fault must be visible, not silent.

Audit 2026-08-07 signal D7: both engines swallowed every exception to a
neutral-looking value -- BiasEngine to ("NEUTRAL", {}), LiquidityEngine to
{} -- with the only diagnostic a commented-out print. That is worse than it
looks: "NEUTRAL" is the value the controller reads as "no HTF opinion", so
it stops filtering and lets BOTH directions through; and {} is
indistinguishable from the two legitimate empty returns (short history, flat
range). A persistent H1 data fault therefore degraded the bias filter with
zero operator trace.

These tests pin the visibility only. The fallback VALUES are deliberately
unchanged -- asserted here too, so a later "fix" that starts raising or
returns something else has to argue with a test.
"""
import logging
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.analysis.bias_engine import BiasEngine
from src.analysis.liquidity import LiquidityEngine


def _faulting_bias_df():
    """Long enough to clear the >=50-bar guard, but missing 'high'/'low' so
    the fractal swing scan raises inside the try."""
    return pd.DataFrame({"close": [1.1 + i * 0.001 for i in range(60)]})


def _faulting_liquidity_df():
    """Clears the >=50-bar guard AND the numeric-dtype check on high/low,
    then raises on the missing 'close' when reading the current price."""
    return pd.DataFrame({
        "high": [1.1 + i * 0.001 for i in range(60)],
        "low": [1.0 + i * 0.001 for i in range(60)],
    })


class TestBiasEngineFaultLogging(unittest.TestCase):
    def test_exception_path_logs_a_warning(self):
        with self.assertLogs("src.analysis.bias_engine", level="WARNING") as cm:
            BiasEngine(_faulting_bias_df()).get_bias_context()
        self.assertEqual(len(cm.records), 1)
        msg = cm.records[0].getMessage()
        # The operator needs the failing type in the line itself; a bare
        # "bias failed" would send them back to the code to guess.
        self.assertIn("KeyError", msg)
        self.assertIn("NEUTRAL", msg)

    def test_fallback_value_is_unchanged(self):
        with self.assertLogs("src.analysis.bias_engine", level="WARNING"):
            bias, liq = BiasEngine(_faulting_bias_df()).get_bias_context()
        self.assertEqual(bias, "NEUTRAL")
        self.assertEqual(liq, {})

    def test_healthy_path_logs_nothing(self):
        """The guard returns, not the except branch: a short frame is normal
        during warmup and must not page anyone."""
        logger = logging.getLogger("src.analysis.bias_engine")
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertEqual(BiasEngine(pd.DataFrame()).get_bias_context(),
                             ("NEUTRAL", {}))


class TestLiquidityEngineFaultLogging(unittest.TestCase):
    def test_exception_path_logs_a_warning(self):
        with self.assertLogs("src.analysis.liquidity", level="WARNING") as cm:
            LiquidityEngine(_faulting_liquidity_df()).get_pd_arrays()
        self.assertEqual(len(cm.records), 1)
        self.assertIn("KeyError", cm.records[0].getMessage())

    def test_fallback_value_is_unchanged(self):
        with self.assertLogs("src.analysis.liquidity", level="WARNING"):
            self.assertEqual(
                LiquidityEngine(_faulting_liquidity_df()).get_pd_arrays(), {})

    def test_legitimate_empty_returns_log_nothing(self):
        """Short history and a flat range both return {} by design. If those
        logged, the WARNING would be pure noise and get tuned out."""
        logger = logging.getLogger("src.analysis.liquidity")
        flat = pd.DataFrame({
            "high": [1.0] * 60, "low": [1.0] * 60, "close": [1.0] * 60,
        })
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertEqual(LiquidityEngine(pd.DataFrame()).get_pd_arrays(), {})
            self.assertEqual(LiquidityEngine(flat).get_pd_arrays(), {})


if __name__ == "__main__":
    unittest.main()
