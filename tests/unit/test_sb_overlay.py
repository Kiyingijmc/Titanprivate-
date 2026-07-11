import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import numpy as np
from scripts import poc_sb_stops as sb


def _bars(path):
    """path: list of (high, low) -> bars dict with numpy arrays."""
    hi = np.array([p[0] for p in path], dtype=float)
    lo = np.array([p[1] for p in path], dtype=float)
    return {"high": hi, "low": lo}


def _long_trade(fill_idx=0):
    # e=100, sl=95 (risk 5), tp=110 (RR2) -> rng=10; L1=103.82 L2=106.18 L3=108.86
    return {"entry": 100.0, "sl": 95.0, "tp": 110.0, "risk": 5.0,
            "dir": "BUY", "fill_idx": fill_idx}


def _runner_then_pullback():
    # climb to L3, set a runner high, then pull back and finally stop out on trail
    return _bars([
        (100.5, 99.9),    # 0: reach 0.05
        (104.0, 103.0),   # 1: reach 0.40 -> BE
        (106.5, 105.5),   # 2: reach 0.65 -> bank30, sl->103.82
        (109.2, 108.0),   # 3: reach 0.92 -> bank50, runner on, hwm=109.2, trail sl->106.52
        (108.5, 107.4),   # 4: pullback (give 1.8 from hwm)
        (110.5, 109.5),   # 5: new hwm 110.5 -> resumption; trail sl->107.82
        (108.0, 107.0),   # 6: lo 107.0 < sl 107.82 -> stop
    ])


class OverlayControlParity(unittest.TestCase):
    def test_arm_off_equals_managed_runner(self):
        bars = _runner_then_pullback()
        tr = _long_trade()
        managed = sb.replay_managed(tr, bars, runner=True)
        r, extra = sb.replay_overlay(tr, bars, arm="off")
        self.assertAlmostEqual(r, managed, places=9)
        self.assertEqual(extra, 0.0)

    def test_arm_off_parity_across_several_paths(self):
        cases = [_bars([(100.2, 99.5), (100.5, 94.9)]),          # immediate stop
                 _bars([(100.1, 99.9), (111.0, 110.0)]),         # straight to TP
                 _runner_then_pullback()]                        # runner + pullback
        for bars in cases:
            tr = _long_trade()
            managed = sb.replay_managed(tr, bars, runner=True)
            r, extra = sb.replay_overlay(tr, bars, arm="off")
            self.assertAlmostEqual(r, managed, places=9)


class GiveBackArmA(unittest.TestCase):
    def test_bank_then_readd_once(self):
        bars = _runner_then_pullback()
        tr = _long_trade()
        trace = []
        r, extra = sb.replay_overlay(tr, bars, arm="A", signal="giveback",
                                     f=0.5, g=0.5, trace=trace)
        banks = [t for t in trace if t[0] == "bank"]
        readds = [t for t in trace if t[0] == "readd"]
        self.assertEqual(len(banks), 1, trace)
        self.assertEqual(len(readds), 1, trace)
        self.assertAlmostEqual(extra, 0.5 * 0.35, places=6)  # f * runner tail
        # bank price is HWM(109.2) - g*trail(1.34) = 107.86
        self.assertAlmostEqual(banks[0][2], 107.86, places=2)

    def test_no_readd_when_trailed_out_during_pullback(self):
        # bank fires, then price falls straight into the trail: no new HWM -> no re-add
        bars = _bars([
            (100.5, 99.9), (104.0, 103.0), (106.5, 105.5),
            (109.2, 108.0),   # runner on, hwm 109.2, sl->106.52
            (108.5, 105.0),   # pullback banks; lo 105.0 < sl 106.52 -> stop same bar
        ])
        tr = _long_trade()
        trace = []
        r, extra = sb.replay_overlay(tr, bars, arm="A", signal="giveback",
                                     f=0.5, g=0.5, trace=trace)
        self.assertEqual(extra, 0.0, trace)      # nothing re-added
        self.assertFalse([t for t in trace if t[0] == "readd"])

    def test_max_cycles_cap(self):
        # three separate pullback/resume swings, cap at 2 -> only 2 re-adds
        bars = _bars([
            (100.5, 99.9), (104.0, 103.0), (106.5, 105.5),
            (109.2, 108.0),                        # runner on, hwm 109.2
            (108.6, 107.3),                        # pullback -> bank (cycle 1)
            (110.0, 109.4),                        # new hwm -> re-add 1
            (109.3, 108.0),                        # pullback -> bank (cycle 2)
            (111.0, 110.2),                        # new hwm -> re-add 2
            (110.3, 109.0),                        # pullback -> would bank (blocked by cap)
            (112.5, 111.5),                        # new hwm -> would re-add (blocked)
            (108.0, 100.0),                        # stop out
        ])
        tr = _long_trade()
        trace = []
        r, extra = sb.replay_overlay(tr, bars, arm="A", signal="giveback",
                                     f=1.0, g=0.5, max_cycles=2, trace=trace)
        self.assertEqual(len([t for t in trace if t[0] == "readd"]), 2, trace)
        self.assertEqual(len([t for t in trace if t[0] == "bank"]), 2, trace)


if __name__ == "__main__":
    unittest.main()
