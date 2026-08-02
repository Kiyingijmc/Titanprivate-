import unittest
from datetime import datetime, timedelta
import pytz

from src.strategies.models.gambit_setups import detect_judas

NY = pytz.timezone("US/Eastern")
CFG = {"sweep_ttl_bars": 12, "body_min_atr": 0.8, "stop_buffer_atr": 0.2, "rr": 2.0}


def ny_seq(start_ny, n):
    t0 = NY.localize(start_ny)
    return [t0 + timedelta(minutes=5 * i) for i in range(n)]


def flat_bars(n, price=100.0, atr=1.0):
    """n quiet bars: no sweep, no displacement, no FVG."""
    return {
        "open": [price] * n, "high": [price + 0.1] * n,
        "low": [price - 0.1] * n, "close": [price] * n,
        "atr": [atr] * n,
        "is_fvg_bull": [False] * n, "is_fvg_bear": [False] * n,
        "fvg_top": [0.0] * n, "fvg_bottom": [0.0] * n,
    }


def judas_sell_fixture(n_after_sweep=1):
    """Session bars from 08:30; bar 1 sweeps range-high 105 (high 106),
    then after n_after_sweep-1 quiet bars the LAST bar is a bearish
    displacement closing back inside with a bear FVG."""
    n = 2 + n_after_sweep
    b = flat_bars(n)
    b["high"][1] = 106.0                      # sweep: strictly above 105
    i = n - 1                                  # current bar
    b["open"][i] = 104.5
    b["close"][i] = 103.0                      # body 1.5 >= 0.8*ATR(1.0)
    b["high"][i] = 104.8
    b["low"][i] = 102.9
    b["is_fvg_bear"][i] = True
    b["fvg_bottom"][i] = 104.0                 # entry (SELL limit at gap edge)
    b["fvg_top"][i] = 104.6
    ts = ny_seq(datetime(2026, 7, 15, 8, 30), n)
    return b, ts


class TestJudas(unittest.TestCase):
    RNG = (105.0, 95.0)
    S = 8 * 60 + 30   # session opens 08:30

    def test_sell_after_high_sweep(self):
        b, ts = judas_sell_fixture()
        out = detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG)
        self.assertIsNotNone(out)
        self.assertEqual(out["signal"], "SELL")
        self.assertEqual(out["type"], "LIMIT")
        self.assertEqual(out["price"], 104.0)
        # SL beyond the sweep extreme: 106 + 0.2*1.0
        self.assertAlmostEqual(out["sl"], 106.2)
        risk = out["sl"] - out["price"]
        self.assertAlmostEqual(out["tp"], out["price"] - 2.0 * risk)
        self.assertEqual(out["setup"], "judas")

    def test_bias_must_agree(self):
        b, ts = judas_sell_fixture()
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BULLISH", CFG))
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "NEUTRAL", CFG))

    def test_touch_is_not_a_sweep(self):
        b, ts = judas_sell_fixture()
        b["high"][1] = 105.0                   # exactly the extreme: NOT swept
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_close_back_inside_is_strict(self):
        b, ts = judas_sell_fixture()
        b["close"][-1] = 105.0                 # close AT range-hi: not inside
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_both_sides_swept_is_ambiguous(self):
        b, ts = judas_sell_fixture(n_after_sweep=2)
        b["low"][2] = 94.0                     # second side swept too
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_ttl_boundary(self):
        # Breach at bar 1; current bar index 1+12 -> still eligible;
        # 1+13 -> expired.
        b, ts = judas_sell_fixture(n_after_sweep=12)   # last idx = 13 = 1+12
        self.assertIsNotNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))
        b, ts = judas_sell_fixture(n_after_sweep=13)   # last idx = 14 = 1+13
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_weak_body_rejected(self):
        b, ts = judas_sell_fixture()
        b["open"][-1] = 103.5                  # body 0.5 < 0.8*ATR
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_no_fvg_rejected(self):
        b, ts = judas_sell_fixture()
        b["is_fvg_bear"][-1] = False
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_sweep_before_session_open_ignored(self):
        # The sweep bar sits BEFORE the session window: not a Judas.
        b, ts = judas_sell_fixture()
        ts = ny_seq(datetime(2026, 7, 15, 8, 20), len(ts))  # bar1=08:25 < 08:30
        self.assertIsNone(detect_judas(b, ts, self.RNG, self.S, "BEARISH", CFG))

    def test_buy_mirror(self):
        n = 3
        b = flat_bars(n)
        b["low"][1] = 94.0                     # sweep of range-lo 95
        b["open"][2] = 95.5
        b["close"][2] = 97.0
        b["high"][2] = 97.1
        b["low"][2] = 95.4
        b["is_fvg_bull"][2] = True
        b["fvg_top"][2] = 96.0                 # BUY limit at gap edge
        b["fvg_bottom"][2] = 95.6
        ts = ny_seq(datetime(2026, 7, 15, 8, 30), n)
        out = detect_judas(b, ts, self.RNG, self.S, "BULLISH", CFG)
        self.assertEqual(out["signal"], "BUY")
        self.assertEqual(out["price"], 96.0)
        self.assertAlmostEqual(out["sl"], 94.0 - 0.2)


if __name__ == "__main__":
    unittest.main()
