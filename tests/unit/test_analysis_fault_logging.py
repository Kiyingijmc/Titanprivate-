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

RS024 MINOR-1: "visible" means the record reaches a HANDLER, not merely a
logger. assertLogs() attaches its own handler, so it passes even for a
logger nothing in the process is configured to write anywhere -- hence the
TestFaultLogsReachTheConfiguredHandler cases at the bottom, which assert
against the sink AuditLogger really uses.
"""
import contextlib
import logging
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.analysis.bias_engine import BiasEngine
from src.analysis.liquidity import LiquidityEngine

BIAS_LOGGER = "TitanBot.src.analysis.bias_engine"
LIQ_LOGGER = "TitanBot.src.analysis.liquidity"


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


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def titanbot_sink():
    """A handler where AuditLogger._setup_logging puts its RotatingFileHandler.

    Not assertLogs(): that attaches to the named logger itself and so cannot
    tell a logger that is wired into Titan's handler tree from one that is
    not. Attaching at "TitanBot" instead means only a record that actually
    PROPAGATES there is seen -- which is the property under test.
    """
    parent = logging.getLogger("TitanBot")
    sink = _Collector()
    prev_level = parent.level
    parent.addHandler(sink)
    parent.setLevel(logging.INFO)
    try:
        yield sink
    finally:
        parent.removeHandler(sink)
        parent.setLevel(prev_level)


class TestBiasEngineFaultLogging(unittest.TestCase):
    def test_exception_path_logs_a_warning(self):
        with self.assertLogs(BIAS_LOGGER, level="WARNING") as cm:
            BiasEngine(_faulting_bias_df()).get_bias_context()
        self.assertEqual(len(cm.records), 1)
        msg = cm.records[0].getMessage()
        # The operator needs the failing type in the line itself; a bare
        # "bias failed" would send them back to the code to guess.
        self.assertIn("KeyError", msg)
        self.assertIn("NEUTRAL", msg)

    def test_fallback_value_is_unchanged(self):
        with self.assertLogs(BIAS_LOGGER, level="WARNING"):
            bias, liq = BiasEngine(_faulting_bias_df()).get_bias_context()
        self.assertEqual(bias, "NEUTRAL")
        self.assertEqual(liq, {})

    def test_healthy_path_logs_nothing(self):
        """The guard returns, not the except branch: a short frame is normal
        during warmup and must not page anyone."""
        logger = logging.getLogger(BIAS_LOGGER)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertEqual(BiasEngine(pd.DataFrame()).get_bias_context(),
                             ("NEUTRAL", {}))


class TestLiquidityEngineFaultLogging(unittest.TestCase):
    def test_exception_path_logs_a_warning(self):
        with self.assertLogs(LIQ_LOGGER, level="WARNING") as cm:
            LiquidityEngine(_faulting_liquidity_df()).get_pd_arrays()
        self.assertEqual(len(cm.records), 1)
        self.assertIn("KeyError", cm.records[0].getMessage())

    def test_fallback_value_is_unchanged(self):
        with self.assertLogs(LIQ_LOGGER, level="WARNING"):
            self.assertEqual(
                LiquidityEngine(_faulting_liquidity_df()).get_pd_arrays(), {})

    def test_legitimate_empty_returns_log_nothing(self):
        """Short history and a flat range both return {} by design. If those
        logged, the WARNING would be pure noise and get tuned out."""
        logger = logging.getLogger(LIQ_LOGGER)
        flat = pd.DataFrame({
            "high": [1.0] * 60, "low": [1.0] * 60, "close": [1.0] * 60,
        })
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertEqual(LiquidityEngine(pd.DataFrame()).get_pd_arrays(), {})
            self.assertEqual(LiquidityEngine(flat).get_pd_arrays(), {})


class TestFaultLogsReachTheConfiguredHandler(unittest.TestCase):
    """RS024 MINOR-1 -- the record must land where the operator reads.

    Titan's only logging configuration is AuditLogger._setup_logging, which
    attaches its RotatingFileHandler to the logger named "TitanBot"
    (src/core/audit_logger.py:78). There is no basicConfig and no root
    handler anywhere in src/ or main.py. A logger named by a bare __name__
    therefore sits in a sibling hierarchy with no handler at all: the record
    goes to logging.lastResort -- bare stderr -- and appears in neither
    data/logs/titan_system.log nor the audit_log table, i.e. it is visible
    only if the process happened to be launched with stderr captured. On an
    unattended forward test that is the difference between "visible" and
    "visible in principle".
    """

    def test_bias_warning_reaches_the_titanbot_handler(self):
        with titanbot_sink() as sink:
            BiasEngine(_faulting_bias_df()).get_bias_context()
        messages = [r.getMessage() for r in sink.records]
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("BiasEngine", messages[0])
        self.assertIn("KeyError", messages[0])

    def test_liquidity_warning_reaches_the_titanbot_handler(self):
        with titanbot_sink() as sink:
            LiquidityEngine(_faulting_liquidity_df()).get_pd_arrays()
        messages = [r.getMessage() for r in sink.records]
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("LiquidityEngine", messages[0])
        self.assertIn("KeyError", messages[0])

    def test_healthy_paths_put_nothing_in_the_operator_log(self):
        """The handler-level counterpart of the assertNoLogs cases above:
        the legitimate empty returns must not reach titan_system.log either."""
        flat = pd.DataFrame({
            "high": [1.0] * 60, "low": [1.0] * 60, "close": [1.0] * 60,
        })
        with titanbot_sink() as sink:
            BiasEngine(pd.DataFrame()).get_bias_context()
            LiquidityEngine(pd.DataFrame()).get_pd_arrays()
            LiquidityEngine(flat).get_pd_arrays()
        self.assertEqual([r.getMessage() for r in sink.records], [])


if __name__ == "__main__":
    unittest.main()
