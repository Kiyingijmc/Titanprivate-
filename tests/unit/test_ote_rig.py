# tests/unit/test_ote_rig.py
# Golden regression anchors: the OTE rig imports replay_managed/cost_r from the
# SB stop study UNMODIFIED (spec section 5 reconciliation rule). These tests pin
# their exact arithmetic so any drift breaks the build, not the study.
import unittest

import pandas as pd

from scripts.poc_sb_stops import replay_managed, cost_r
from scripts.poc_ote_canonical import scan_symbol, RR, STOP_FLOOR_ATR
from src.analysis.ote_structure import zone_invalidation


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


def _mk_m5(segments, start=100.0, t0="2024-01-02"):
    """Deterministic M5 candles from linear (n_bars, delta) segments.
    open=prev close, close=linear step, high/low = body +/- 0.01, plus a
    monotonic 1e-12*bar_index epsilon on the wick.

    Why the epsilon: each segment's first bar opens exactly where the prior
    segment's last bar closed (the vertex price). At every direction
    reversal this makes `max(o,c)+0.01` (or `min(o,c)-0.01`) IDENTICAL on
    both bars either side of the vertex -- verified empirically (exact
    float equality, not a rounding artifact) for all 14 reversals in
    SEGMENTS below. `is_swing_high`/`is_swing_low` require a *strict*
    inequality against every neighbour (src/analysis/ote_structure.py), so
    every candidate swing point in the whole series was tied and
    confirmed_swings() returned nothing -- structure_bias stayed NEUTRAL
    forever and the funnel never got past legs=0. This is a fixture defect,
    not a scan_symbol wiring bug (see task-6-report.md for the full trace).
    The epsilon is >=4 orders of magnitude below the smallest real per-bar
    step in SEGMENTS (0.00625) and >=3 orders below the tightest test
    tolerance (1e-9), so it only ever breaks exact ties and never reorders
    a genuine price difference."""
    rows = []
    px = start
    t = pd.Timestamp(t0)
    idx = 0
    for n, delta in segments:
        step = delta / n
        for _ in range(n):
            o, c = px, px + step
            eps = 1e-12 * idx
            rows.append({"time": t, "open": o, "close": c,
                         "high": max(o, c) + 0.01 + eps,
                         "low": min(o, c) - 0.01 - eps})
            px = c
            t += pd.Timedelta(minutes=5)
            idx += 1
    return pd.DataFrame(rows)


# Synthetic bullish market (~3,111 M5 bars ~ 259 H1 ~ 65 H4):
# 5 trend cycles (24 H1 up +3.0 / 16 H1 down -1.2: HH+HL on H1 AND H4, pullback
# depth 0.4 -> never reaches the 0.62-0.79 zone, so no early entries), then an
# impulse leg +4.0 (24 H1), a pullback -2.9 into the zone (depth 0.725), an M5
# chop that prints a confirmed lk=2 swing high and breaks it (MSS), then +2.8
# continuation that reaches the 2.5R target.
SEGMENTS = (5 * [(288, +3.0), (192, -1.2)]
            + [(288, +4.0), (120, -2.9),
               (6, +0.15), (6, -0.10), (3, +0.20),
               (288, +2.8)])


class TestScanSymbolSynthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trades, cls.bars, cls.funnel = scan_symbol(_mk_m5(SEGMENTS))

    def test_exactly_one_buy_entry(self):
        self.assertEqual(self.funnel["entries"], 1, msg=f"funnel={self.funnel}")
        self.assertEqual(len(self.trades), 1)
        self.assertEqual(self.trades[0]["dir"], "BUY")

    def test_funnel_progression(self):
        f = self.funnel
        self.assertGreater(f["legs"], 0)
        self.assertGreater(f["setups"], 0)
        self.assertGreaterEqual(f["setups"], f["zone_touch"])
        self.assertGreaterEqual(f["zone_touch"], f["mss"])

    def test_stop_is_h1_anchored(self):
        t = self.trades[0]
        inval = zone_invalidation(t["z_lo"], t["z_hi"], t["atr_h1"], True)
        self.assertLessEqual(t["sl"], inval + 1e-9)             # beyond invalidation
        self.assertLessEqual(t["sl"], t["pullback_ext"] + 1e-9)  # beyond pullback
        self.assertGreaterEqual(t["entry"] - t["sl"],
                                STOP_FLOOR_ATR * t["atr_h1"] - 1e-9)

    def test_tp_is_25R_and_hit(self):
        t = self.trades[0]
        self.assertAlmostEqual(t["tp"], t["entry"] + RR * t["risk"], places=9)
        self.assertEqual(t["outcome"], "TP")
        self.assertAlmostEqual(t["r"], RR, places=9)

    def test_entry_inside_or_above_zone(self):
        t = self.trades[0]
        self.assertGreaterEqual(t["entry"], t["z_lo"])
        self.assertLess(t["entry"], t["leg_high"])


if __name__ == "__main__":
    unittest.main()
