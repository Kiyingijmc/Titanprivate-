import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "backtest"))
import backtest_engine as bt  # noqa: E402


def bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


class ResolveTrade(unittest.TestCase):
    def test_market_long_take_profit(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        future = [bar(100, 105, 99, 104), bar(104, 121, 103, 120)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertAlmostEqual(res["r"], 2.0)
        self.assertEqual(res["exit_offset"], 1)
        self.assertTrue(res["filled"])

    def test_market_long_stop_loss(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 101, 89, 95)])
        self.assertEqual(res["outcome"], "SL")
        self.assertAlmostEqual(res["r"], -1.0)

    def test_market_short_take_profit(self):
        sig = {"dir": "SELL", "cmd": "MARKET", "entry": 100, "sl": 110, "tp": 80, "ttl_bars": 24}
        future = [bar(100, 101, 99, 100), bar(100, 101, 79, 80)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertAlmostEqual(res["r"], 2.0)

    def test_limit_never_touched_expires(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 90, "sl": 85, "tp": 100, "ttl_bars": 3}
        future = [bar(100, 101, 95, 96)] * 5
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "EXPIRED")
        self.assertFalse(res["filled"])

    def test_limit_fills_then_take_profit(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 90, "sl": 85, "tp": 100, "ttl_bars": 5}
        future = [bar(95, 96, 92, 94), bar(93, 93, 89, 91), bar(91, 101, 90, 100)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertEqual(res["fill_offset"], 1)
        self.assertAlmostEqual(res["r"], 2.0)

    def test_same_bar_sl_and_tp_is_stop_loss(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 95, "tp": 105, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 106, 94, 100)])
        self.assertEqual(res["outcome"], "SL")

    def test_open_at_end(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 101, 99, 100)])
        self.assertEqual(res["outcome"], "OPEN_AT_END")

    def test_zero_risk_is_invalid(self):
        sig = {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 100, "tp": 110, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 111, 99, 110)])
        self.assertEqual(res["outcome"], "INVALID")
        self.assertFalse(res["filled"])

    def test_unknown_direction_is_invalid(self):
        sig = {"dir": "FLAT", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 120, "ttl_bars": 24}
        res = bt.resolve_trade(sig, [bar(100, 121, 99, 120)])
        self.assertEqual(res["outcome"], "INVALID")

    def test_limit_fills_on_last_ttl_bar_and_resolves_same_bar(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 90, "sl": 85, "tp": 100, "ttl_bars": 2}
        future = [bar(95, 96, 92, 94), bar(91, 101, 89, 100)]  # entry touched at offset 1; TP same bar
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertEqual(res["fill_offset"], 1)


if __name__ == "__main__":
    unittest.main()
