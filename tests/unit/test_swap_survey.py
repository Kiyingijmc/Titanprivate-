import csv
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts import swap_survey as sv
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker.types import SymbolInfo


class TestCarryMath(unittest.TestCase):
    def test_points_mode_negative(self):
        # -6.0 points nightly on EURUSD-like: -6 * 1e-5 * 364 / 1.10
        pct, exact = sv.annualised_carry_pct(
            mode=1, rate=-6.0, point=1e-5, mid=1.10, contract_size=100_000)
        self.assertAlmostEqual(pct, -1.9855, places=3)
        self.assertTrue(exact)

    def test_points_mode_positive(self):
        pct, exact = sv.annualised_carry_pct(
            mode=1, rate=2.0, point=1e-5, mid=1.10, contract_size=100_000)
        self.assertAlmostEqual(pct, 0.6618, places=3)
        self.assertTrue(exact)

    def test_disabled_mode(self):
        pct, exact = sv.annualised_carry_pct(
            mode=0, rate=-5.0, point=1e-5, mid=1.10, contract_size=100_000)
        self.assertIsNone(pct)

    def test_base_currency_mode(self):
        # +0.5 base-ccy units per lot nightly, contract 100k base units
        pct, exact = sv.annualised_carry_pct(
            mode=2, rate=0.5, point=1e-5, mid=1.10, contract_size=100_000)
        self.assertAlmostEqual(pct, 0.182, places=3)
        self.assertTrue(exact)

    def test_margin_currency_mode_is_approximate(self):
        # -15 ccy/lot/night, contract 100, mid 2000 -> -15*364/200000
        pct, exact = sv.annualised_carry_pct(
            mode=3, rate=-15.0, point=0.01, mid=2000.0, contract_size=100)
        self.assertAlmostEqual(pct, -2.73, places=2)
        self.assertFalse(exact)

    def test_interest_mode_passthrough(self):
        pct, exact = sv.annualised_carry_pct(
            mode=5, rate=-3.5, point=1e-5, mid=1.10, contract_size=100_000)
        self.assertAlmostEqual(pct, -3.5, places=6)
        self.assertTrue(exact)

    def test_zero_mid_is_safe(self):
        pct, exact = sv.annualised_carry_pct(
            mode=1, rate=-6.0, point=1e-5, mid=0.0, contract_size=100_000)
        self.assertIsNone(pct)


class TestGate(unittest.TestCase):
    def test_gate_fails_when_all_below_threshold(self):
        rows = [{"sym": "EURUSD", "carry_long_pct": -2.0, "carry_short_pct": 1.4},
                {"sym": "XAUUSD", "carry_long_pct": -5.0, "carry_short_pct": 2.9}]
        passed, winners = sv.gate(rows)
        self.assertFalse(passed)
        self.assertEqual(winners, [])

    def test_gate_passes_on_any_side_above_3pct(self):
        rows = [{"sym": "EURUSD", "carry_long_pct": -2.0, "carry_short_pct": 3.2},
                {"sym": "US30", "carry_long_pct": None, "carry_short_pct": None}]
        passed, winners = sv.gate(rows)
        self.assertTrue(passed)
        self.assertEqual(winners, [("EURUSD", "SHORT", 3.2)])


class TestAppendLog(unittest.TestCase):
    def test_append_creates_then_appends_without_rewriting(self):
        tmp = tempfile.mkdtemp(prefix="swapsurvey_")
        try:
            path = os.path.join(tmp, "swap_log.csv")
            row = {"date": "2026-07-31", "sym": "EURUSD", "mode": 1,
                   "swap_long": -6.0, "swap_short": 1.0, "mid": 1.10,
                   "contract_size": 100000, "point": 1e-5,
                   "carry_long_pct": -1.99, "carry_short_pct": 0.33,
                   "exact": True}
            sv.append_log(path, [row])
            sv.append_log(path, [{**row, "date": "2026-08-01"}])
            with open(path) as f:
                lines = list(csv.DictReader(f))
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["date"], "2026-07-31")
            self.assertEqual(lines[1]["date"], "2026-08-01")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestClientBackCompat(unittest.TestCase):
    """Old bridge responses (no swap fields) must still parse with defaults."""

    OLD = {"name": "EURUSD", "digits": 5, "point": 1e-5, "spread": 8,
           "contract_size": 100000.0, "volume_min": 0.01, "volume_max": 100.0,
           "volume_step": 0.01, "trade_mode": 4, "tick_value": 1.0,
           "tick_size": 1e-5}

    def test_symbolinfo_defaults(self):
        broker = MT5HttpBroker.__new__(MT5HttpBroker)
        info = broker._symbol(dict(self.OLD))
        self.assertEqual(info.swap_mode, 0)
        self.assertEqual(info.swap_long, 0.0)
        self.assertEqual(info.swap_short, 0.0)

    def test_symbolinfo_new_fields_parse(self):
        broker = MT5HttpBroker.__new__(MT5HttpBroker)
        d = {**self.OLD, "swap_mode": 1, "swap_long": -6.2, "swap_short": 0.9,
             "swap_rollover3days": 3}
        info = broker._symbol(d)
        self.assertEqual(info.swap_mode, 1)
        self.assertAlmostEqual(info.swap_long, -6.2)
        self.assertAlmostEqual(info.swap_short, 0.9)
        self.assertEqual(info.swap_rollover3days, 3)
        self.assertIsInstance(info, SymbolInfo)


if __name__ == "__main__":
    unittest.main()
