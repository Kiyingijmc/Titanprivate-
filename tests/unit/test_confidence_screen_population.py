import unittest
import pandas as pd

from scripts.confidence_screen.population import add_stop_and_target, build_population


def _sig(bar_idx=100, direction="BUY", entry=1.1000, atr=0.0010, **kw):
    base = {
        "bar_idx": bar_idx, "time": pd.Timestamp("2024-01-02 10:00:00"),
        "dir": direction, "entry": entry, "far_extreme": entry - 0.002,
        "sig_high": entry + 0.001, "sig_low": entry - 0.001,
        "atr": atr, "body_atr": 1.2, "bias": "BULLISH", "liq_status": "DISCOUNT",
        "hour": 10, "year": 2024,
    }
    base.update(kw)
    return base


class TestStopAndTarget(unittest.TestCase):
    def test_buy_stop_is_one_atr_below_entry(self):
        out = add_stop_and_target(_sig(direction="BUY", entry=1.1000, atr=0.0010))
        self.assertAlmostEqual(out["sl"], 1.0990, places=9)
        self.assertAlmostEqual(out["risk"], 0.0010, places=9)

    def test_sell_stop_is_one_atr_above_entry(self):
        out = add_stop_and_target(_sig(direction="SELL", entry=1.1000, atr=0.0010))
        self.assertAlmostEqual(out["sl"], 1.1010, places=9)

    def test_target_is_exactly_two_r(self):
        for direction, expected in (("BUY", 1.1020), ("SELL", 1.0980)):
            out = add_stop_and_target(_sig(direction=direction, entry=1.1000, atr=0.0010))
            self.assertAlmostEqual(out["tp"], expected, places=9)

    def test_zero_atr_signal_is_rejected_not_silently_zero_risk(self):
        with self.assertRaises(ValueError):
            add_stop_and_target(_sig(atr=0.0))


class TestBuildPopulation(unittest.TestCase):
    def test_overlapping_signals_are_all_retained(self):
        """The spec forbids busy_until: a signal arriving while a prior trade
        would still be open must NOT be dropped. Three signals one bar apart
        must all survive."""
        signals = [_sig(bar_idx=100), _sig(bar_idx=101), _sig(bar_idx=102)]

        def fake_collect(sym, quick=False, tf="H1"):
            return list(signals), {}

        pop = build_population(["EURUSD"], collect=fake_collect)
        self.assertEqual(len(pop), 3)
        self.assertEqual([p["bar_idx"] for p in pop], [100, 101, 102])

    def test_symbol_is_stamped_on_every_signal(self):
        def fake_collect(sym, quick=False, tf="H1"):
            return [_sig()], {}

        pop = build_population(["EURUSD", "XAUUSD"], collect=fake_collect)
        self.assertEqual(sorted(p["symbol"] for p in pop), ["EURUSD", "XAUUSD"])

    def test_symbol_with_no_data_is_skipped_not_crashed(self):
        def fake_collect(sym, quick=False, tf="H1"):
            return (None, None) if sym == "MISSING" else ([_sig()], {})

        pop = build_population(["MISSING", "EURUSD"], collect=fake_collect)
        self.assertEqual(len(pop), 1)


if __name__ == "__main__":
    unittest.main()
