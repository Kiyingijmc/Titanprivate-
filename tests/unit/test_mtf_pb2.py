# tests/unit/test_mtf_pb2.py
import os, sys, unittest
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import poc_mtf_pb2 as m2


def _zigzag(up=True):
    # lk=1 zigzag: ascending (HH+HL) when up=True, descending (LH+LL) when up=False.
    if up:
        h = [5, 7, 4, 9, 6, 11, 8, 13, 10]
        l = [3, 5, 2, 6, 4,  8, 6, 10,  8]
    else:
        # Descending frame: swing highs 11→9→7 (LH) and swing lows 7→5→3→1 (LL).
        # high >= low at every bar; confirmed BEARISH by bar 5 (lk=1).
        h = [13, 10, 11, 8, 9, 6, 7, 4, 5]
        l = [10,  7,  8, 5, 6, 3, 4, 1, 2]
    return pd.DataFrame({"open": h, "high": h, "low": l, "close": h})


class StructureBias(unittest.TestCase):
    def test_bullish_when_hh_and_hl(self):
        df = _zigzag(up=True)
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(len(bias), len(df))
        self.assertEqual(bias[-1], "BULLISH")

    def test_neutral_during_warmup(self):
        df = _zigzag(up=True)
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(bias[0], "NEUTRAL")  # no confirmed swings yet

    def test_bearish_when_lh_and_ll(self):
        df = _zigzag(up=False)
        # fixture must be valid OHLC (high >= low) and resolve BEARISH at the tail
        self.assertTrue((df["high"] >= df["low"]).all())
        bias = m2.structure_bias(df, lk=1)
        self.assertEqual(bias[-1], "BEARISH")


class CombinedBias(unittest.TestCase):
    def test_requires_both_htf_agree(self):
        # 5m bars hourly-spaced; H4 & H1 both built from the same rising frame -> BULLISH tail.
        rows = []
        price = 1.0
        for k in range(600):
            price += 0.01
            ts = pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * k)
            rows.append({"datetime": str(ts), "open": price, "high": price + 0.02,
                         "low": price - 0.02, "close": price})
        m5 = pd.DataFrame(rows)
        h4 = m2.resample_tf(m5, "4h")
        h1 = m2.resample_tf(m5, "1h")
        bias = m2.combined_structure_bias(m5, h4, h1, lk=2)
        self.assertEqual(len(bias), len(m5))
        self.assertIn(bias[-1], ("BULLISH", "NEUTRAL"))  # never BEARISH on a pure uptrend
        self.assertNotEqual(bias[-1], "BEARISH")


class ImpulseLegAndOTE(unittest.TestCase):
    def setUp(self):
        self.highs = [5, 7, 4, 9, 6, 11, 8, 13, 10]
        self.lows = [3, 5, 2, 6, 4, 8, 6, 10, 8]

    def test_bull_leg_is_most_recent_bos_up(self):
        leg = m2.impulse_leg(self.highs, self.lows, upto=8, lk=1, bias="BULLISH")
        self.assertIsNotNone(leg)
        leg_low, leg_high, lo_idx, hi_idx = leg
        self.assertEqual(leg_high, 13)   # BOS up high
        self.assertEqual(leg_low, 6)     # most recent confirmed swing low before it (idx 6)
        self.assertEqual((lo_idx, hi_idx), (6, 7))

    def test_no_leg_when_bias_neutral(self):
        self.assertIsNone(m2.impulse_leg(self.highs, self.lows, 8, 1, "NEUTRAL"))

    def test_ote_zone_bull(self):
        z_lo, z_hi = m2.ote_zone(6, 13, "BULLISH")  # rng=7
        self.assertAlmostEqual(z_hi, 13 - 0.62 * 7, places=6)
        self.assertAlmostEqual(z_lo, 13 - 0.79 * 7, places=6)


class FVG(unittest.TestCase):
    def test_find_bullish_fvg(self):
        bars = [{"open": 1, "high": 2, "low": 1, "close": 2},   # c1 high=2
                {"open": 2, "high": 5, "low": 2, "close": 5},   # displacement
                {"open": 4, "high": 6, "low": 3, "close": 5}]   # c3 low=3 > c1 high=2 -> gap
        self.assertEqual(m2.find_fvg(bars, 2, "BULLISH"), (2, 3))

    def test_no_fvg_when_no_gap(self):
        bars = [{"open": 1, "high": 4, "low": 1, "close": 3},
                {"open": 3, "high": 5, "low": 2, "close": 4},
                {"open": 4, "high": 6, "low": 3, "close": 5}]   # c3 low=3 < c1 high=4
        self.assertIsNone(m2.find_fvg(bars, 2, "BULLISH"))

    def test_qualifying_fvg_needs_30pct_in_zone(self):
        leg = [{"open": 8, "high": 10, "low": 8, "close": 10},
               {"open": 10, "high": 16, "low": 10, "close": 16},
               {"open": 15, "high": 18, "low": 14, "close": 17}]
        self.assertEqual(m2.qualifying_fvg(leg, (12, 20), "BULLISH"), (10, 14))

    def test_qualifying_fvg_rejected_when_below_threshold(self):
        leg = [{"open": 8, "high": 10, "low": 8, "close": 10},
               {"open": 10, "high": 16, "low": 10, "close": 16},
               {"open": 15, "high": 18, "low": 14, "close": 17}]
        # zone (13.5, 20): overlap (13.5,14)=0.5 of size 4 = 12.5% < 30% -> None
        self.assertIsNone(m2.qualifying_fvg(leg, (13.5, 20), "BULLISH"))


class SweepAndMSS(unittest.TestCase):
    def test_sweep_detects_breached_swing_low(self):
        # lows form a minor swing low at idx 2 (val 4), later bar dips to 3 -> swept.
        highs = [10, 9, 8, 9, 10, 11]
        lows = [7, 6, 4, 6, 3, 5]
        swept, extreme = m2.swept_liquidity(lows, highs, 0, 5, "BULLISH", lk=1)
        self.assertTrue(swept)
        self.assertEqual(extreme, 3)

    def test_no_sweep_when_holds_above(self):
        highs = [10, 9, 8, 9, 10, 11]
        lows = [7, 6, 4, 6, 5, 6]   # never below the 4 swing low
        swept, _ = m2.swept_liquidity(lows, highs, 0, 5, "BULLISH", lk=1)
        self.assertFalse(swept)

    def test_mss_confirms_when_close_breaks_swing_high(self):
        # swing high at idx 2 (val 8); bar 5 closes 9 > 8 -> MSS up.
        highs = [5, 6, 8, 6, 5, 9]
        lows = [3, 4, 6, 4, 3, 7]
        closes = [4, 5, 7, 5, 4, 9]
        confirmed, lvl = m2.mss_confirm(highs, lows, closes, i=5, bias="BULLISH", lk=1)
        self.assertTrue(confirmed)
        self.assertIsInstance(lvl, (int, float))


class Pressure(unittest.TestCase):
    def test_displacement_candle(self):
        med = 1.0
        strong = {"open": 10, "high": 12, "low": 9.8, "close": 11.9}  # body 1.9 of range 2.2
        weak = {"open": 10, "high": 12, "low": 9.8, "close": 10.2}    # tiny body
        self.assertTrue(m2.is_displacement(strong, med, "BULLISH"))
        self.assertFalse(m2.is_displacement(weak, med, "BULLISH"))

    def test_pressure_true_on_displacement_fvg(self):
        # bar i leaves a bullish FVG (c1.high < c3.low) -> pressure ok regardless of body.
        bars = [{"open": 1, "high": 2, "low": 1, "close": 2},
                {"open": 2, "high": 5, "low": 2, "close": 5},
                {"open": 4, "high": 6, "low": 3, "close": 5}]
        highs = [b["high"] for b in bars]; lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        self.assertTrue(m2.pressure_ok(bars, highs, lows, closes, 2, "BULLISH", lk=1))


class Confluence(unittest.TestCase):
    def _htf(self, fvg=True):
        # 3 H1 bars leaving a bullish FVG gap (high0=2 < low2=3) when fvg=True.
        low2 = 3 if fvg else 1
        rows = [{"time": "2026-01-01 00:00:00", "open": 1, "high": 2, "low": 1, "close": 2},
                {"time": "2026-01-01 01:00:00", "open": 2, "high": 5, "low": 2, "close": 5},
                {"time": "2026-01-01 02:00:00", "open": 4, "high": 6, "low": low2, "close": 5}]
        return pd.DataFrame(rows)

    def test_overlap_true_when_zone_hits_h1_fvg(self):
        h1 = self._htf(fvg=True)
        h4 = self._htf(fvg=True)
        t = pd.Timestamp("2026-01-01 05:00:00")     # after the H1 bars closed
        self.assertTrue(m2.htf_poi_overlap((2.4, 2.9), h1, h4, t, "BULLISH", lk=1))

    def test_overlap_false_when_zone_misses(self):
        h1 = self._htf(fvg=True)
        h4 = self._htf(fvg=True)
        t = pd.Timestamp("2026-01-01 05:00:00")
        self.assertFalse(m2.htf_poi_overlap((100.0, 101.0), h1, h4, t, "BULLISH", lk=1))


class ConditionalStop(unittest.TestCase):
    def test_fvg_present_not_swept_uses_leg_origin(self):
        s = m2.conditional_stop("BULLISH", leg_low=6.0, leg_high=13.0, qfvg=(7.0, 8.0),
                                fully_swept=False, sweep_extreme=None, mss_level=9.0)
        self.assertEqual(s, 6.0)

    def test_fvg_present_swept_uses_sweep_extreme(self):
        s = m2.conditional_stop("BULLISH", 6.0, 13.0, qfvg=(7.0, 8.0),
                                fully_swept=True, sweep_extreme=6.7, mss_level=9.0)
        self.assertEqual(s, 6.7)

    def test_no_fvg_uses_mss_level(self):
        s = m2.conditional_stop("BULLISH", 6.0, 13.0, qfvg=None,
                                fully_swept=False, sweep_extreme=None, mss_level=9.0)
        self.assertEqual(s, 9.0)

    def test_fvg_present_not_swept_bear_uses_leg_high(self):
        s = m2.conditional_stop("BEARISH", leg_low=6.0, leg_high=13.0, qfvg=(9.0, 10.0),
                                fully_swept=False, sweep_extreme=None, mss_level=9.0)
        self.assertEqual(s, 13.0)


class ManagedExit(unittest.TestCase):
    def test_tp1_then_runner_hits_tp2(self):
        # long: entry 100, stop 95 (risk 5), TP1 105 (=+1R internal), TP2 115 (+3R external).
        sig = {"bar_idx": 0, "dir": "BUY", "entry": 100.0, "sl": 95.0, "risk": 5.0,
               "tp1": 105.0, "tp2": 115.0}
        bars = [{"open": 100, "high": 100, "low": 100, "close": 100},
                {"open": 101, "high": 106, "low": 100, "close": 105},   # TP1 hit
                {"open": 106, "high": 112, "low": 104, "close": 111},   # higher-low forms
                {"open": 112, "high": 116, "low": 110, "close": 115}]   # TP2 hit
        trades = m2.simulate_managed([sig], bars)
        self.assertEqual(len(trades), 1)
        # 0.33*(1.0) + 0.67*((115-100)/5 = 3.0) = 0.33 + 2.01 = 2.34
        self.assertAlmostEqual(trades[0]["r"], 0.33 * 1.0 + 0.67 * 3.0, places=6)
        self.assertEqual(trades[0]["outcome"], "TP")

    def test_full_stop_before_tp1(self):
        sig = {"bar_idx": 0, "dir": "BUY", "entry": 100.0, "sl": 95.0, "risk": 5.0,
               "tp1": 105.0, "tp2": 115.0}
        bars = [{"open": 100, "high": 100, "low": 100, "close": 100},
                {"open": 99, "high": 100, "low": 94, "close": 95}]      # stop hit, no partial
        trades = m2.simulate_managed([sig], bars)
        self.assertAlmostEqual(trades[0]["r"], -1.0, places=6)
        self.assertEqual(trades[0]["outcome"], "SL")


class Diagnostics(unittest.TestCase):
    def test_mae_mfe_long(self):
        sig = {"dir": "BUY", "entry": 100.0, "risk": 5.0, "entry_idx": 0, "exit_idx": 2}
        bars = [{"open": 100, "high": 101, "low": 98, "close": 100},   # MAE -2 -> -0.4R
                {"open": 100, "high": 110, "low": 99, "close": 108},   # MFE +10 -> +2.0R
                {"open": 108, "high": 109, "low": 107, "close": 108}]
        mae, mfe = m2.mae_mfe(sig, bars)
        self.assertAlmostEqual(mae, -0.4, places=6)
        self.assertAlmostEqual(mfe, 2.0, places=6)

    def test_bootstrap_ci_is_ordered_and_brackets_mean(self):
        rs = [1.0, -1.0, 1.0, -1.0, 2.0, -1.0, 1.0, -1.0, 1.0, -1.0]
        lo, hi = m2.bootstrap_expectancy_ci(rs, n_boot=500, seed=1)
        self.assertLess(lo, hi)
        mean = sum(rs) / len(rs)
        self.assertTrue(lo <= mean <= hi)

    def test_net_with_slippage_charges_more_than_zero(self):
        t = {"r": 2.0, "entry": 100.0, "sl": 95.0, "outcome": "TP"}
        out = m2.net_with_slippage([dict(t)], "XAUUSD", slip_frac=0.05)
        self.assertLess(out[0]["r"], 2.0)        # cost + slippage reduce R


class BuildSignals(unittest.TestCase):
    def test_returns_signals_and_funnel_keys(self):
        # Minimal monotonic uptrend frame; we assert structure of outputs, not trade count.
        rows = []
        price = 100.0
        for k in range(800):
            price += 0.05 if (k % 20) < 15 else -0.03   # drifts up with pullbacks
            ts = pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * k)
            rows.append({"datetime": str(ts), "open": price, "high": price + 0.1,
                         "low": price - 0.1, "close": price})
        m5 = pd.DataFrame(rows)
        sigs, funnel = m2.build_signals(m5, require_sweep=False, require_confluence=False)
        self.assertIsInstance(sigs, list)
        for key in ("bias", "leg", "armed", "sweep", "mss", "pressure", "confluence", "emitted"):
            self.assertIn(key, funnel)
        for s in sigs:
            self.assertIn(s["entry_model"], ("market", "limit"))
            for f in ("bar_idx", "dir", "cmd", "entry", "sl", "tp1", "tp2", "risk"):
                self.assertIn(f, s)


if __name__ == "__main__":
    unittest.main()
