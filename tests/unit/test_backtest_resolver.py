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


class AggregateMetrics(unittest.TestCase):
    def test_known_trade_list(self):
        trades = [
            {"strat": "A", "outcome": "TP", "r": 2.0},
            {"strat": "A", "outcome": "SL", "r": -1.0},
            {"strat": "A", "outcome": "TP", "r": 2.0},
            {"strat": "A", "outcome": "SL", "r": -1.0},
            {"strat": "A", "outcome": "EXPIRED", "r": 0.0},
            {"strat": "A", "outcome": "OPEN_AT_END", "r": 0.0},
        ]
        m = bt.aggregate_metrics(trades)
        self.assertEqual(m["trades"], 4)
        self.assertEqual(m["wins"], 2)
        self.assertEqual(m["losses"], 2)
        self.assertAlmostEqual(m["win_rate"], 0.5)
        self.assertAlmostEqual(m["expectancy"], 0.5)
        self.assertAlmostEqual(m["total_r"], 2.0)
        self.assertAlmostEqual(m["profit_factor"], 2.0)
        self.assertAlmostEqual(m["max_drawdown_r"], 1.0)
        self.assertEqual(m["max_losing_streak"], 1)
        self.assertEqual(m["expired"], 1)
        self.assertEqual(m["open_at_end"], 1)

    def test_empty_is_safe(self):
        m = bt.aggregate_metrics([])
        self.assertEqual(m["trades"], 0)
        self.assertEqual(m["expectancy"], 0.0)


class SimulateSignals(unittest.TestCase):
    def test_skips_overlapping_then_takes_later(self):
        # 10 bars; flat at 100 except TP spikes at index 3 and 6.
        bars = [bar(100, 101, 99, 100) for _ in range(10)]
        bars[3] = bar(100, 111, 99, 110)  # A's TP
        bars[6] = bar(100, 111, 99, 110)  # C's TP
        common = {"dir": "BUY", "cmd": "MARKET", "sl": 90, "tp": 110, "ttl_bars": 24}
        signals = [
            {**common, "entry": 100, "bar_idx": 0, "strat": "A"},  # fills at bar1 open, TP bar3 -> busy_until 3
            {**common, "entry": 100, "bar_idx": 1, "strat": "B"},  # 1 <= 3 -> skipped
            {**common, "entry": 100, "bar_idx": 5, "strat": "C"},  # 5 > 3 -> taken, TP bar6
        ]
        trades = bt.simulate_signals(signals, bars)
        self.assertEqual([t["bar_idx"] for t in trades], [0, 5])
        self.assertTrue(all(t["outcome"] == "TP" for t in trades))

    def test_invalid_signal_does_not_occupy_symbol(self):
        bars = [bar(100, 111, 99, 110) for _ in range(5)]
        signals = [
            {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 100, "tp": 110, "ttl_bars": 24, "bar_idx": 0, "strat": "A"},
            {"dir": "BUY", "cmd": "MARKET", "entry": 100, "sl": 90, "tp": 110, "ttl_bars": 24, "bar_idx": 1, "strat": "B"},
        ]
        trades = bt.simulate_signals(signals, bars)
        self.assertEqual(len(trades), 1)          # invalid dropped, B taken
        self.assertEqual(trades[0]["strat"], "B")


if __name__ == "__main__":
    unittest.main()
