"""Hand-calculated execution cases, independent of historical performance."""
import unittest

import numpy as np

from src.research.sb_execution import Position, replay_order, simulate


def bars(rows, times=None):
    data = {key: np.array([r[i] for r in rows], dtype=float)
            for i, key in enumerate(("open", "high", "low", "close"))}
    data["time"] = (np.array(times, dtype="datetime64[ns]") if times else
                    np.datetime64("2024-01-01T01:00", "ns")
                    + np.arange(len(rows)) * np.timedelta64(5, "m"))
    return data


def sig(**changes):
    return {"time": "2024-01-01T00:00", "dir": "BUY", "entry": 100., "atr": 1., **changes}


def run(data, signal=None, **changes):
    options = dict(arm="fixed", path="OHLC", spread=0., commission=0.)
    options.update(changes)
    return replay_order(signal or sig(), data, **options)


class ExecutionTests(unittest.TestCase):
    def test_bid_touch_without_ask_touch_does_not_fill_buy(self):
        r = run(bars([(101., 101., 99.95, 100.5)]), spread=.1)
        self.assertIsNone(r["fill_idx"])

    def test_spread_is_embedded_not_deducted_twice(self):
        # ASK entry 100, terminal BID 100.5: gross +0.5R, commission .02R.
        r = run(bars([(99.9, 100.5, 99.9, 100.5)]), spread=.1, commission=.02)
        self.assertEqual(r["outcome"], "MARKED_AT_END")
        self.assertAlmostEqual(r["net_r"], .48)

    def test_short_stop_triggers_on_ask(self):
        r = run(bars([(100., 100.95, 99.9, 100.5)]), sig(dir="SELL"), spread=.1)
        self.assertEqual(r["outcome"], "STOP")
        self.assertAlmostEqual(r["gross_r"], -1.)

    def test_short_tp_requires_ask_to_reach_target(self):
        r = run(bars([(100., 100.1, 98.05, 98.2)]), sig(dir="SELL"), spread=.1)
        self.assertEqual(r["outcome"], "MARKED_AT_END")
        self.assertAlmostEqual(r["gross_r"], 1.7)

    def test_gap_through_limit_and_stop_realizes_gap_loss(self):
        r = run(bars([(98., 98.5, 97., 98.)]))
        self.assertEqual(r["fill_idx"], 0)
        self.assertEqual(r["outcome"], "STOP")
        self.assertAlmostEqual(r["gross_r"], -2.)

    def test_existing_position_gap_stop_uses_open(self):
        r = run(bars([(100., 100.2, 99.5, 99.8), (98., 98.5, 97., 98.)]))
        self.assertAlmostEqual(r["gross_r"], -2.)

    def test_broker_tp_at_gap_precedes_unarmed_runner_management(self):
        r = run(bars([(100., 100.2, 99.5, 100.), (103., 104., 102., 103.)]),
                arm="runner")
        self.assertEqual(r["outcome"], "TP")
        self.assertAlmostEqual(r["gross_r"], 2.)

    def test_long_short_symmetry_in_executable_price_space(self):
        rows = [(99.9, 101.4, 99.8, 101.3), (101.3, 102.5, 101.2, 102.3),
                (102.3, 102.4, 100., 100.5)]
        # Reflection accounts for the short's ASK exit and BID entry.
        mirror = [(199.9-o, 199.9-lo, 199.9-hi, 199.9-c) for o, hi, lo, c in rows]
        for arm in ("fixed", "ratchet", "runner", "tight_runner"):
            a = run(bars(rows), arm=arm, path="OHLC", spread=.1, commission=.02)
            b = run(bars(mirror), sig(dir="SELL"), arm=arm,
                    path="OLHC", spread=.1, commission=.02)
            self.assertEqual(a["outcome"], b["outcome"])
            self.assertAlmostEqual(a["net_r"], b["net_r"])

    def test_pre_fill_high_cannot_win_a_trade(self):
        data = bars([(101., 103., 99.5, 100.5)])
        high_first = run(data, path="OHLC")
        low_first = run(data, path="OLHC")
        self.assertEqual(high_first["outcome"], "MARKED_AT_END")
        self.assertAlmostEqual(high_first["gross_r"], .5)
        self.assertEqual(low_first["outcome"], "TP")

    def test_same_bar_stop_target_order_is_explicit(self):
        data = bars([(100., 103., 98., 100.)])
        self.assertEqual(run(data, path="OHLC")["gross_r"], 2.)
        self.assertEqual(run(data, path="OLHC")["gross_r"], -1.)

    def test_no_fill_in_signal_hour(self):
        data = bars([(100., 103., 98., 100.)], ["2024-01-01T00:55"])
        self.assertIsNone(run(data)["fill_idx"])

    def test_ttl_is_wall_clock_exclusive_across_missing_bars(self):
        data = bars([(101., 102., 100.5, 101.), (100., 103., 99.5, 102.)],
                    ["2024-01-01T01:00", "2024-01-01T13:00"])
        self.assertEqual(run(data)["outcome"], "EXPIRED")

    def test_partial_volume_arithmetic_and_runner_tail(self):
        p = Position("runner")
        p.segment(0., 1.8)
        self.assertAlmostEqual(p.volume, .35)
        self.assertAlmostEqual(p.realized, .3 * 1.236 + .35 * 1.772)
        p.segment(1.8, 1.)
        self.assertAlmostEqual(p.realized, .3 * 1.236 + .35 * 1.772 + .35 * 1.264)

    def test_stop_raised_during_bar_applies_on_reversal(self):
        r = run(bars([(100., 100.9, 99.5, 100.5)]), arm="ratchet")
        self.assertEqual(r["outcome"], "STOP")
        self.assertAlmostEqual(r["gross_r"], 0.)

    def test_tightening_is_monotonic_and_persists(self):
        p = Position("tight_runner")
        p.segment(0., 2.2)
        old = p.stop
        p.segment(2.2, 1.79)
        self.assertTrue(p.tightened)
        self.assertGreaterEqual(p.stop, old)
        p.segment(1.79, 2.3)
        self.assertAlmostEqual(p.stop, 2.1)

    def test_each_exit_releases_its_own_slot(self):
        data = bars([(100., 100.9, 100., 100.2), (100.2, 100.5, 99.8, 100.2),
                     (100., 100.5, 99.8, 100.1), (100., 102.5, 99.8, 102.)],
                    ["2024-01-01T01:00", "2024-01-01T01:05",
                     "2024-01-01T02:00", "2024-01-01T02:05"])
        signals = [sig(), sig(time="2024-01-01T01:00")]
        fixed, sf = simulate(signals, data, arm="fixed", path="OHLC", spread=0., commission=0.)
        managed, sm = simulate(signals, data, arm="ratchet", path="OHLC", spread=0., commission=0.)
        self.assertEqual((len(fixed), sf), (1, 1))
        self.assertEqual((len(managed), sm), (2, 0))

    def test_runner_can_block_entry_after_fixed_target_exits(self):
        data = bars([(100., 102.1, 100., 102.), (102., 102.1, 101.9, 102.),
                     (102., 102.2, 101.9, 102.)],
                    ["2024-01-01T01:00", "2024-01-01T01:05", "2024-01-01T02:00"])
        signals = [sig(), sig(time="2024-01-01T01:00", entry=102.)]
        fixed, sf = simulate(signals, data, arm="fixed", path="OLHC", spread=0., commission=0.)
        runner, sr = simulate(signals, data, arm="runner", path="OLHC", spread=0., commission=0.)
        self.assertEqual((len(fixed), sf), (2, 0))
        self.assertEqual((len(runner), sr), (1, 1))
        self.assertEqual(runner[0]["outcome"], "MARKED_AT_END")

    def test_new_signal_at_exit_bar_close_can_enter(self):
        data = bars([(100., 102., 99.5, 102.), (100., 102., 99.5, 102.)],
                    ["2024-01-01T01:55", "2024-01-01T02:00"])
        rows, skipped = simulate([sig(), sig(time="2024-01-01T01:00")], data,
                                 arm="fixed", path="OHLC", spread=0., commission=0.)
        self.assertEqual((len(rows), skipped), (2, 0))

    def test_bad_bars_and_unsorted_signals_fail(self):
        data = bars([(100., 99., 98., 100.)])
        with self.assertRaises(ValueError):
            simulate([sig()], data, arm="fixed", path="OHLC", spread=0., commission=0.)
        data = bars([(100., 101., 99., 100.)])
        with self.assertRaises(ValueError):
            simulate([sig(time="2024-01-02"), sig()], data,
                     arm="fixed", path="OHLC", spread=0., commission=0.)


if __name__ == "__main__":
    unittest.main()
