# flat_at_ny time-exit variant: close once any listed NY wall-clock time has
# been crossed since placement. Epochs are fixed so DST is exercised for real
# (Jan = EST/UTC-5, Jul = EDT/UTC-4).
import unittest
from datetime import datetime
import pytz

from src.execution.trade_manager import TradeManager

NY = pytz.timezone("US/Eastern")
UTC = pytz.utc


def ny_epoch(y, mo, d, h, mi):
    """Epoch seconds for an NY wall-clock instant."""
    return NY.localize(datetime(y, mo, d, h, mi)).timestamp()


class _Logger:
    def log_event(self, *a, **k):
        pass


class _State:
    def __init__(self, meta):
        self._meta = meta

    def get_order_meta(self, ticket):
        return self._meta.get(ticket)


def make_tm(meta, rule):
    cfg = {"trade_management": {"time_exits": {"Gambit": rule}}}
    return TradeManager(_Logger(), _State(meta), risk_manager=None, config=cfg)


class TestFlatAtNY(unittest.TestCase):
    RULE = {"flat_at_ny": ["05:00", "11:00"]}

    def test_not_due_before_boundary(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)      # EDT, in London window
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 4, 59)))

    def test_due_at_boundary(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 5, 0)))

    def test_ny_am_trade_ignores_morning_boundary_already_past(self):
        # Placed 08:35 — the 05:00 boundary is already behind it; only 11:00 counts.
        placed = ny_epoch(2026, 7, 15, 8, 35)
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 10, 59)))
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 7, 15, 11, 0)))

    def test_outage_spanning_boundary_closes_on_restart(self):
        # Bot down over the 05:00 boundary and past midnight: still due.
        placed = ny_epoch(2026, 7, 15, 4, 0)
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 7, 16, 3, 0)))

    def test_est_winter_dates(self):
        placed = ny_epoch(2026, 1, 15, 8, 35)      # EST
        tm = make_tm({1: ("Gambit", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 1, 15, 10, 59)))
        self.assertTrue(tm._time_exit_due(1, ny_epoch(2026, 1, 15, 11, 1)))

    def test_other_strategy_inert(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)
        tm = make_tm({1: ("SilverBullet", placed)}, self.RULE)
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 16, 12, 0)))

    def test_unknown_ticket_inert(self):
        tm = make_tm({}, self.RULE)
        self.assertFalse(tm._time_exit_due(99, ny_epoch(2026, 7, 15, 12, 0)))

    def test_bad_time_string_rule_is_dropped(self):
        placed = ny_epoch(2026, 7, 15, 2, 30)
        tm = make_tm({1: ("Gambit", placed)}, {"flat_at_ny": ["nonsense"]})
        self.assertFalse(tm._time_exit_due(1, ny_epoch(2026, 7, 16, 12, 0)))


if __name__ == "__main__":
    unittest.main()
