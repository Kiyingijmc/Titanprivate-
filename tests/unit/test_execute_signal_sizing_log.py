"""A zero-lot sizing skip must be visible in the log.

Found live 2026-08-01: Gyroscope's first signal (BTCUSD, graded C, passed
the floor) vanished with no trace — calculate_lot_size returned 0.0 (lot
below min volume at the current balance) and _execute_signal returned
silently. The fail-safe decision is correct; the silence is not: an
operator cannot distinguish "unsizeable at this balance" from a dead
pipeline. This pins the skip-log.
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.core.system_controller import SystemController


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class RecordingLogger:
    def __init__(self):
        self.events = []

    def log_event(self, level, tag, msg, **kw):
        self.events.append((level, tag, msg))


class ZeroLotRisk:
    def normalize_price(self, p, s):
        return p

    def throttle_factor(self):
        return 1.0

    def calculate_lot_size(self, entry, sl, symbol, htf_bias, risk_mult=1.0):
        return 0.0


class TestZeroLotSkipIsLogged(unittest.TestCase):
    def test_zero_lot_skip_emits_log_event(self):
        c = SystemController.__new__(SystemController)
        c.logger = RecordingLogger()
        c.risk_manager = ZeroLotRisk()
        c.live_prices = {}
        c._news_blocks_symbol = lambda s: (False, "")
        decision = {"signal": "SELL", "type": "MARKET",
                    "price": 115000.0, "sl": 115700.0, "tp": 113600.0}
        run(c._execute_signal("BTCUSD", decision, "Gyroscope", "NEUTRAL", grade="C"))
        joined = " | ".join(f"{lv}:{tg}:{m}" for lv, tg, m in c.logger.events)
        self.assertIn("BTCUSD", joined)
        self.assertTrue(any("lot" in m.lower() or "siz" in m.lower()
                            for _, _, m in c.logger.events),
                        f"no sizing-skip log emitted: {c.logger.events}")


if __name__ == "__main__":
    unittest.main()
