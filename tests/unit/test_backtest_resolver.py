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


class LimitFillTrigger(unittest.TestCase):
    """MT5 triggers BUY orders on ASK (bid + spread), SELL orders on BID.

    Bars here are BID OHLC, so a BUY LIMIT at `entry` requires bid to reach
    entry - spread, while a SELL LIMIT at `entry` triggers at bid >= entry.
    Ignoring that filled buy limits one whole spread too easily.
    """

    def test_buy_limit_needs_bid_to_reach_entry_minus_spread(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 100.0, "sl": 95.0, "tp": 110.0,
               "ttl_bars": 3, "spread": 0.5}
        # Bid low grazes 99.7: touches entry, but ask never reaches 100.0
        # (ask low = 99.7 + 0.5 = 100.2). Must NOT fill.
        future = [bar(100.5, 100.6, 99.7, 100.0)] * 3
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "EXPIRED")
        self.assertFalse(res["filled"])

    def test_buy_limit_fills_once_bid_clears_the_spread(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 100.0, "sl": 95.0, "tp": 110.0,
               "ttl_bars": 3, "spread": 0.5}
        # Bid low 99.4 -> ask low 99.9 <= 100.0. Fills.
        future = [bar(100.5, 100.6, 99.4, 110.5)] * 3
        res = bt.resolve_trade(sig, future)
        self.assertTrue(res["filled"])
        self.assertEqual(res["fill_offset"], 0)

    def test_sell_limit_takes_no_spread_haircut(self):
        """SELL LIMIT triggers on bid, which IS the data -- so the mirrored
        price fills where the buy side did not."""
        sig = {"dir": "SELL", "cmd": "LIMIT", "entry": 100.0, "sl": 105.0, "tp": 90.0,
               "ttl_bars": 3, "spread": 0.5}
        future = [bar(99.5, 100.0, 99.4, 99.5)] * 3   # bid high exactly 100.0
        res = bt.resolve_trade(sig, future)
        self.assertTrue(res["filled"])
        self.assertEqual(res["fill_offset"], 0)

    def test_zero_spread_reproduces_legacy_touch_behaviour(self):
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 90.0, "sl": 85.0, "tp": 100.0,
               "ttl_bars": 5}          # no "spread" key at all
        future = [bar(95, 96, 92, 94), bar(93, 93, 89, 91), bar(91, 101, 90, 100)]
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "TP")
        self.assertEqual(res["fill_offset"], 1)

    def test_bar_gapping_fully_past_the_limit_fills(self):
        """A bar entirely below a BUY LIMIT means price gapped through it. The
        legacy `low <= entry <= high` test wrongly expired these."""
        sig = {"dir": "BUY", "cmd": "LIMIT", "entry": 100.0, "sl": 95.0, "tp": 110.0,
               "ttl_bars": 3}
        future = [bar(98.0, 98.5, 97.0, 97.5), bar(97.5, 110.5, 97.0, 110.0)]
        res = bt.resolve_trade(sig, future)
        self.assertTrue(res["filled"])
        self.assertEqual(res["fill_offset"], 0)


class StopFillTrigger(unittest.TestCase):
    """STOP orders trigger on the OPPOSITE side of the price from LIMITs.

    BUY STOP: ask >= price  -> bid >= entry - spread  (fills EASIER)
    SELL STOP: bid <= price -> low <= entry
    Treating a STOP as a LIMIT inverts the trigger entirely.
    """

    def test_buy_stop_fills_where_a_limit_never_could(self):
        """Bid stays ABOVE the limit trigger the whole time (low 99.6 > 99.5),
        so limit semantics expire. Ask reaches 100.7 >= 100.0, so stop
        semantics fill. A test whose bars satisfy BOTH triggers proves nothing.
        """
        sig = {"dir": "BUY", "cmd": "STOP", "entry": 100.0, "sl": 95.0, "tp": 110.0,
               "ttl_bars": 3, "spread": 0.5}
        future = [bar(99.7, 100.2, 99.6, 100.1), bar(100.1, 110.5, 100.0, 110.0)]
        res = bt.resolve_trade(sig, future)
        self.assertTrue(res["filled"])
        self.assertEqual(res["fill_offset"], 0)
        self.assertEqual(res["outcome"], "TP")

    def test_buy_stop_does_not_fill_on_downward_move(self):
        """A LIMIT would have filled here (low 96.0 <= 99.5). A STOP must not:
        bid high 99.2 -> ask high 99.7, never reaching 100.0."""
        sig = {"dir": "BUY", "cmd": "STOP", "entry": 100.0, "sl": 95.0, "tp": 110.0,
               "ttl_bars": 3, "spread": 0.5}
        future = [bar(99.0, 99.2, 96.0, 96.5)] * 3   # only ever moves down
        res = bt.resolve_trade(sig, future)
        self.assertEqual(res["outcome"], "EXPIRED")
        self.assertFalse(res["filled"])

    def test_sell_stop_fills_where_a_sell_limit_never_could(self):
        """Bid high 99.9 never reaches 100.0, so SELL LIMIT semantics expire.
        Bid low 99.0 <= 100.0, so SELL STOP fills. No spread haircut on the
        sell side -- bid IS the data."""
        sig = {"dir": "SELL", "cmd": "STOP", "entry": 100.0, "sl": 105.0, "tp": 90.0,
               "ttl_bars": 3, "spread": 0.5}
        future = [bar(99.8, 99.9, 99.0, 99.2), bar(99.2, 99.5, 89.5, 90.0)]
        res = bt.resolve_trade(sig, future)
        self.assertTrue(res["filled"])
        self.assertEqual(res["fill_offset"], 0)
        self.assertEqual(res["outcome"], "TP")

    def test_unknown_cmd_keeps_limit_semantics(self):
        sig = {"dir": "BUY", "cmd": "WEIRD", "entry": 100.0, "sl": 95.0, "tp": 110.0,
               "ttl_bars": 3}
        future = [bar(101.0, 101.5, 99.0, 110.5)] * 2
        res = bt.resolve_trade(sig, future)
        self.assertTrue(res["filled"])


if __name__ == "__main__":
    unittest.main()
