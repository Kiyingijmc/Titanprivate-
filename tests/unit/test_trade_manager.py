import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.execution.trade_manager import TradeManager  # noqa: E402


class FakeLogger:
    def __init__(self): self.events = []
    def log_event(self, *a, **kw): self.events.append(a)


class FakeState:
    """Ratchet state stub keyed by ticket."""
    def __init__(self):
        self.ratchets = {}   # ticket -> (level, entry, tp)
        self.levels = {}
    def get_ratchet_state(self, t):
        return self.ratchets.get(t, (0, 0.0, 0.0))
    def update_ratchet_level(self, t, lvl):
        self.levels[t] = lvl
        lvl_, e, tp = self.ratchets.get(t, (0, 0.0, 0.0))
        self.ratchets[t] = (lvl, e, tp)
    def update_trade_phase(self, t, p): pass


class FakeRisk:
    def __init__(self):
        self.symbol_specs = {"EURUSD": {"val": 1.0, "ts": 1e-05, "vm": 0.01, "vs": 0.01}}
    def get_max_risk_amount(self, bias_multiplier=1.0): return 100.0
    def normalize_price(self, p, symbol): return round(float(p), 5)


def make_tm(config=None):
    return TradeManager(FakeLogger(), FakeState(), FakeRisk(), config=config)


def pos(ticket=101, sym="EURUSD", pf=10.0, vol=0.10, tp=1.1100, sl=0.0):
    return {"t": ticket, "s": sym, "pf": pf, "vol": vol, "tp": tp, "sl": sl}


class RatchetStages(unittest.TestCase):
    """Long trade: entry 1.1000, tp 1.1100 (range 0.0100)."""

    def setUp(self):
        self.tm = make_tm()
        self.tm.state_manager.ratchets[101] = (0, 1.1000, 1.1100)

    def test_l1_breakeven_modify(self):
        # pct = 0.40 >= 0.382 -> BE modify at entry + 3 pips
        cmds = self.tm.sync_positions([pos()], {"EURUSD": 1.1040})
        self.assertEqual(len(cmds), 1)
        c = cmds[0]
        self.assertEqual(c["action"], "MODIFY")
        self.assertEqual(c["ticket"], 101)
        self.assertEqual(c["symbol"], "EURUSD")     # EA needs symbol for SLTP
        self.assertAlmostEqual(c["sl"], 1.1003, places=5)
        self.assertAlmostEqual(c["tp"], 1.1100, places=5)

    def test_l2_partial_uses_absolute_volume(self):
        self.tm.state_manager.ratchets[101] = (1, 1.1000, 1.1100)
        cmds = self.tm.sync_positions([pos(vol=0.10)], {"EURUSD": 1.1065})
        actions = {c["action"]: c for c in cmds}
        self.assertIn("MODIFY", actions)
        self.assertIn("CLOSE_PARTIAL", actions)
        # 30% of 0.10 = 0.03, snapped to step
        self.assertAlmostEqual(actions["CLOSE_PARTIAL"]["volume"], 0.03, places=2)
        # SL trailed to L1 fib price
        self.assertAlmostEqual(actions["MODIFY"]["sl"], 1.10382, places=5)

    def test_l2_dust_skips_partial_but_still_trails(self):
        # 30% of 0.02 = 0.006 -> floors below min lot -> no partial
        self.tm.state_manager.ratchets[101] = (1, 1.1000, 1.1100)
        cmds = self.tm.sync_positions([pos(vol=0.02)], {"EURUSD": 1.1065})
        self.assertEqual([c["action"] for c in cmds], ["MODIFY"])

    def test_cooldown_blocks_immediate_second_command(self):
        self.tm.sync_positions([pos()], {"EURUSD": 1.1040})
        cmds = self.tm.sync_positions([pos()], {"EURUSD": 1.1070})
        self.assertEqual(cmds, [])

    def test_unmanaged_trade_skipped(self):
        # No DB record (entry/tp zero) -> no commands, no crash
        cmds = self.tm.sync_positions([pos(ticket=999)], {"EURUSD": 1.1090})
        self.assertEqual(cmds, [])

    def test_emergency_kill_switch(self):
        cmds = self.tm.sync_positions([pos(pf=-999.0)], {"EURUSD": 1.0900})
        self.assertEqual(cmds[0]["action"], "CLOSE_POS")
        self.assertEqual(cmds[0]["ticket"], 101)


class PartialVolume(unittest.TestCase):
    def setUp(self):
        self.tm = make_tm()

    def test_partial_mode(self):
        mode, vol = self.tm._partial_volume("EURUSD", 0.10, 0.5)
        self.assertEqual(mode, "PARTIAL")
        self.assertAlmostEqual(vol, 0.05, places=2)

    def test_skip_when_close_below_min(self):
        mode, _ = self.tm._partial_volume("EURUSD", 0.02, 0.3)
        self.assertEqual(mode, "SKIP")

    def test_full_close_when_remainder_is_dust(self):
        # close 90% of 0.10 -> close 0.09, remainder 0.01 >= min ok;
        # with min 0.02: close 0.09 floored to 0.09, remainder 0.01 < 0.02 -> FULL
        self.tm.risk_manager.symbol_specs["EURUSD"]["vm"] = 0.02
        mode, _ = self.tm._partial_volume("EURUSD", 0.10, 0.9)
        self.assertEqual(mode, "FULL")

    def test_zero_volume_skips(self):
        mode, _ = self.tm._partial_volume("EURUSD", 0.0, 0.5)
        self.assertEqual(mode, "SKIP")


class RunnerMode(unittest.TestCase):
    """Runner: at L3 the TP is removed and the tail trails behind price."""

    def setUp(self):
        cfg = {"trade_management": {"runner": {"enabled": True}}}
        self.tm = make_tm(config=cfg)
        self.tm.state_manager.ratchets[101] = (2, 1.1000, 1.1100)

    def test_l3_removes_tp_when_runner_enabled(self):
        cmds = self.tm.sync_positions([pos(vol=0.10)], {"EURUSD": 1.1090})
        mods = [c for c in cmds if c["action"] == "MODIFY"]
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]["tp"], 0.0)

    def test_trailing_after_l3(self):
        # Already at L3; price ran past TP. Trail distance = range * (L3-L2 fib) = 0.00268
        self.tm.state_manager.ratchets[101] = (3, 1.1000, 1.1100)
        p = pos(vol=0.05, sl=1.1062, tp=0.0)
        cmds = self.tm.sync_positions([p], {"EURUSD": 1.1150})
        self.assertEqual(len(cmds), 1)
        c = cmds[0]
        self.assertEqual(c["action"], "MODIFY")
        self.assertAlmostEqual(c["sl"], 1.1150 - 0.00268, places=5)
        self.assertEqual(c["tp"], 0.0)

    def test_trailing_never_loosens_sl(self):
        self.tm.state_manager.ratchets[101] = (3, 1.1000, 1.1100)
        # Existing SL already tighter than candidate -> no command
        p = pos(vol=0.05, sl=1.1140, tp=0.0)
        cmds = self.tm.sync_positions([p], {"EURUSD": 1.1150})
        self.assertEqual(cmds, [])

    def test_short_trailing(self):
        self.tm.state_manager.ratchets[102] = (3, 1.1100, 1.1000)  # short
        p = pos(ticket=102, vol=0.05, sl=1.1040, tp=0.0)
        cmds = self.tm.sync_positions([p], {"EURUSD": 1.0950})
        self.assertEqual(len(cmds), 1)
        self.assertAlmostEqual(cmds[0]["sl"], 1.0950 + 0.00268, places=5)

    def test_runner_disabled_keeps_tp_and_no_trailing(self):
        tm = make_tm()  # default config: runner off
        tm.state_manager.ratchets[101] = (2, 1.1000, 1.1100)
        cmds = tm.sync_positions([pos(vol=0.10)], {"EURUSD": 1.1090})
        mods = [c for c in cmds if c["action"] == "MODIFY"]
        self.assertAlmostEqual(mods[0]["tp"], 1.1100, places=5)
        # and at L3 with runner off there is no trailing
        tm2 = make_tm()
        tm2.state_manager.ratchets[101] = (3, 1.1000, 1.1100)
        self.assertEqual(tm2.sync_positions([pos(sl=1.1062)], {"EURUSD": 1.1150}), [])


if __name__ == "__main__":
    unittest.main()
