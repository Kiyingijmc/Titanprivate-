# tests/unit/test_ote_rig.py
# Golden regression anchors: the OTE rig imports replay_managed/cost_r from the
# SB stop study UNMODIFIED (spec section 5 reconciliation rule). These tests pin
# their exact arithmetic so any drift breaks the build, not the study.
import unittest

from scripts.poc_sb_stops import replay_managed, cost_r


def _trade():
    # long, entry 100, sl 99 (risk 1.0), tp 102.5 (2.5R); range = 2.5
    return {"entry": 100.0, "sl": 99.0, "tp": 102.5, "risk": 1.0,
            "dir": "BUY", "fill_idx": 1}


BARS = {
    # bar0 = signal bar (unused), bar1 sweeps to L3 without stopping,
    # bar2 pulls back to the tightened trail.
    "high": [100.0, 102.6, 102.0],
    "low":  [99.5, 100.2, 101.5],
}


class TestReplayManagedGolden(unittest.TestCase):
    def test_ratchet_runner_golden_value(self):
        # bar1: BE@0.382 -> bank 30% @101.545 (0.4635R) -> bank 50% of 0.70
        # @102.215 (0.77525R) -> runner drops TP, trail=0.268*2.5=0.67,
        # sl -> 102.6-0.67=101.93; bar2 low 101.5 <= 101.93 -> exit
        # 0.35*1.93 = 0.6755R. Total 1.91425R.
        r = replay_managed(_trade(), BARS, runner=True)
        self.assertAlmostEqual(r, 1.91425, places=6)

    def test_ratchet_fixed_tp_golden_value(self):
        # runner=False: after both banks, remaining 0.35 exits at TP 102.5
        # same bar: 1.23875 + 0.35*2.5 = 2.11375R.
        r = replay_managed(_trade(), BARS, runner=False)
        self.assertAlmostEqual(r, 2.11375, places=6)

    def test_stop_first_same_bar(self):
        bars = {"high": [100.0, 102.6], "low": [99.5, 98.9]}   # sweeps SL too
        r = replay_managed(_trade(), bars, runner=True)
        self.assertAlmostEqual(r, -1.0, places=6)              # pessimistic


class TestCostRGolden(unittest.TestCase):
    def test_eurusd_cost_arithmetic(self):
        specs = {"EURUSD": {"tick_size": 1e-05, "tick_value": 1.0}}
        tr = {"risk": 0.001}   # 10 pips
        # spread 8 ticks*1e-5 + (7/1.0)*1e-5 commission = 15e-5 / 1e-3 = 0.15R
        self.assertAlmostEqual(cost_r(tr, "EURUSD", specs), 0.15, places=9)

    def test_spread_stress_multiplier(self):
        specs = {"EURUSD": {"tick_size": 1e-05, "tick_value": 1.0}}
        tr = {"risk": 0.001}
        # 1.5x: (12e-5 + 7e-5)/1e-3 = 0.19R
        self.assertAlmostEqual(cost_r(tr, "EURUSD", specs, 1.5), 0.19, places=9)


if __name__ == "__main__":
    unittest.main()
