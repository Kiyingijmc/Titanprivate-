import os, sys, unittest
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from src.risk.risk_manager import RiskManager  # noqa: E402

CFG = {"risk": {"account": {"max_daily_drawdown_pct": 3.0, "max_global_exposure_pct": 6.0},
                "trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0,
                          "static_commission_usd": 7.0}}}


class DailyDrawdownAnchor(unittest.TestCase):
    """The 3% daily circuit breaker must anchor to TODAY's starting equity,
    not the balance at bot boot (which drifts as the account compounds)."""

    def setUp(self):
        self.rm = RiskManager(CFG)
        self.rm.update_account_info(1000.0, 1000.0)

    def test_blocks_beyond_daily_dd(self):
        self.rm.update_account_info(1000.0, 969.0)  # -3.1% today
        self.assertFalse(self.rm.check_can_trade())

    def test_allows_within_daily_dd(self):
        self.rm.update_account_info(1000.0, 980.0)  # -2% today
        self.assertTrue(self.rm.check_can_trade())

    def test_anchor_resets_daily_after_growth(self):
        # Account grows to 1100, new day starts: a fall back to 1069 is a
        # -2.8% day (allowed), even though it's +6.9% vs boot balance.
        self.rm.update_account_info(1000.0, 1100.0)
        self.rm.reset_daily_metrics()
        self.rm.update_account_info(1000.0, 1069.0)
        self.assertTrue(self.rm.check_can_trade())
        # But dropping to 1060 is -3.6% on the day -> blocked,
        # even though it is still well above boot balance.
        self.rm.update_account_info(1000.0, 1060.0)
        self.assertFalse(self.rm.check_can_trade())

    def test_no_data_defaults_open(self):
        rm = RiskManager(CFG)
        self.assertTrue(rm.check_can_trade())


class RestoredAnchorSurvivesRestart(unittest.TestCase):
    """RISK-01: a restart must not re-anchor the breaker to mid-day equity.

    day_start_equity was in-memory only, so update_account_info's
    `if day_start_equity == 0` guard re-anchored on every boot, discarding the
    day's realised drawdown and granting a fresh 3% allowance.
    """

    def test_restored_anchor_survives_the_first_heartbeat(self):
        # The bug, reproduced: bot restarts already 3.1% down on the day.
        rm = RiskManager(CFG)
        rm.restore_daily_anchor(1000.0)
        rm.update_account_info(1000.0, 969.0)   # first post-boot heartbeat
        self.assertAlmostEqual(rm.day_start_equity, 1000.0)
        # Without the fix update_account_info re-anchors to 969.0, computes a
        # 0% drawdown, and hands back a fresh 3% allowance.
        self.assertFalse(rm.check_can_trade())

    def test_restored_anchor_still_allows_inside_the_limit(self):
        rm = RiskManager(CFG)
        rm.restore_daily_anchor(1000.0)
        rm.update_account_info(1000.0, 980.0)   # -2% on the day
        self.assertTrue(rm.check_can_trade())

    def test_restore_is_a_noop_for_zero_and_negative(self):
        """A corrupt persisted row must not poison the breaker."""
        for bad in (0.0, -1.0, -1000.0):
            rm = RiskManager(CFG)
            rm.restore_daily_anchor(bad)
            self.assertEqual(rm.day_start_equity, 0.0)
            # The normal fresh-anchor path must still work afterwards.
            rm.update_account_info(1000.0, 1000.0)
            self.assertAlmostEqual(rm.day_start_equity, 1000.0)

    def test_restore_is_a_noop_for_unusable_types(self):
        for bad in (None, "", "abc", float("nan"), float("inf")):
            rm = RiskManager(CFG)
            rm.restore_daily_anchor(bad)
            self.assertEqual(rm.day_start_equity, 0.0)

    def test_restored_anchor_also_drives_the_throttle(self):
        """throttle_factor shares the anchor; it must see the restored one."""
        cfg = {"risk": {"account": {"max_daily_drawdown_pct": 3.0,
                                    "max_global_exposure_pct": 6.0},
                        "trade": {"risk_per_trade_pct": 1.0, "hard_max_lots": 5.0,
                                  "static_commission_usd": 7.0},
                        "drawdown_throttle": {"enabled": True,
                                              "trigger_dd_pct": 2.0, "factor": 0.5}}}
        rm = RiskManager(cfg)
        rm.restore_daily_anchor(1000.0)
        rm.update_account_info(1000.0, 975.0)   # -2.5% vs the restored anchor
        self.assertEqual(rm.throttle_factor(), 0.5)


if __name__ == "__main__":
    unittest.main()
