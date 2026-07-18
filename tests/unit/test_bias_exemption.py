# tests/unit/test_bias_exemption.py
# Plan 07 / Task 6: manifest-driven HTF-bias exemption. An exempt strategy's
# counter-bias signal survives to submission; a bias-honoring strategy's is
# still dropped; ABSENT attribute == honoring (the parity-safety default --
# the SB parity harness has no registry and must stay filtered).
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd

from src.research.kernel_replay import replay

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Lenient grading floor so the bare MARKET decision executes (mirrors
# tests/unit/test_kernel_replay.py's FakeStrat config -- align with it if
# these dicts have drifted).
CONFIG = {
    "signal_grading": {"enabled": True, "min_grade": "C"},
    "arbiter": {"max_positions_per_symbol": 99, "max_total_positions": 99,
                "thesis_ttl_bars": 1},
}


class _AlwaysBuy:
    """Minimal strategy stub: unconditional BUY MARKET each close."""
    name = "AlwaysBuy"
    timeframe = "H1"
    active = True

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        c = float(df["close"].iloc[-1])
        return {"signal": "BUY", "type": "MARKET",
                "price": c, "sl": c - 0.01, "tp": c + 0.02}


def _h1():
    sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "backtest"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    from research_run import _load_csv_h1
    return _load_csv_h1(os.path.join(REPO_ROOT, "test_data.csv"), "H1")


class TestBiasExemption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h1 = _h1()

    def _counter_bias_signals(self, strat):
        records = replay(self.h1, "EURUSD", [strat], CONFIG, window=300, start=60)
        return [r for r in records
                if r["signal"] == "BUY" and r["bias"] == "BEARISH"]

    def test_exempt_strategy_counter_bias_signal_survives(self):
        strat = _AlwaysBuy()
        strat.honors_htf_bias = False
        self.assertGreater(len(self._counter_bias_signals(strat)), 0,
                           "exempt strategy was still bias-filtered")

    def test_honoring_strategy_counter_bias_signal_still_dropped(self):
        strat = _AlwaysBuy()
        strat.honors_htf_bias = True
        self.assertEqual(len(self._counter_bias_signals(strat)), 0)

    def test_absent_attribute_defaults_to_honoring(self):
        # THE parity-safety invariant: no attribute (registry-less harness,
        # e.g. the frozen SB parity fixture) == filtered, today's behavior.
        strat = _AlwaysBuy()
        self.assertEqual(len(self._counter_bias_signals(strat)), 0)


if __name__ == "__main__":
    unittest.main()
