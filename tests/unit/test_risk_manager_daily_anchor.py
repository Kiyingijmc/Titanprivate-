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


if __name__ == "__main__":
    unittest.main()
