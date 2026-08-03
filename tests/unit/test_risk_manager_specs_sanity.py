# ==============================================================================
# FILE: tests/unit/test_risk_manager_specs_sanity.py
# SEC-05 / OPS-07: update_symbol_specs is fed straight off an unauthenticated
# ZMQ socket. One bad HISTORY message -- hostile, or a broker misquoting
# tick_value after a symbol-spec change -- drives ticks_at_risk towards 0 and
# every subsequent trade to hard_max_lots against an intended 1% risk, with
# risk_to_stop validating it as safe off the same poisoned numbers.
#
# So a spec update must be sanity-bounded, and a rejected update must be a
# NO-OP: the previously accepted specs stay, a never-specced symbol stays
# spec-less (and therefore keeps calculate_lot_size's fail-safe 0.0).
# ==============================================================================

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.risk.risk_manager import RiskManager

# A known-good spec set (5-digit forex), used as the "prior accepted" state.
GOOD = {"val": 1.0, "size": 0.0001, "v_min": 0.01, "v_step": 0.01}


class _SpyLogger:
    """Captures log_event calls so we can assert the operator is told WHY."""

    def __init__(self):
        self.events = []

    def log_event(self, type, module, msg, payload=None):
        self.events.append((type, module, msg, payload))

    def risk_messages(self):
        return [e[2] for e in self.events if e[0] == "RISK"]


def _rm(equity=10000.0, logger=None):
    rm = RiskManager(
        {"risk": {"account": {"max_daily_drawdown_pct": 3.0}, "trade": {"risk_per_trade_pct": 1.0}}},
        logger=logger,
    )
    rm.update_account_info(equity, equity)
    return rm


class AcceptedSpecs(unittest.TestCase):
    """The happy path: real broker numbers across asset classes must survive."""

    ACCEPTED = [
        # (label, val, size, v_min, v_step)
        ("5-digit forex", 1.0, 0.00001, 0.01, 0.01),
        ("4-digit forex", 1.0, 0.0001, 0.01, 0.01),
        ("USDJPY 3-digit", 0.9, 0.001, 0.01, 0.01),
        ("XAUUSD", 1.0, 0.01, 0.01, 0.01),
        ("US30 quarter tick", 0.25, 0.25, 0.1, 0.1),
        ("BTCUSD", 0.1, 0.1, 0.01, 0.01),
        ("whole-unit tick", 1.0, 1.0, 1.0, 1.0),
        ("lower bounds", 1e-4, 1e-6, 1e-6, 1e-6),
        ("upper bounds", 1e4, 100.0, 1000.0, 1000.0),
    ]

    def test_real_broker_specs_are_accepted_unchanged(self):
        for label, val, size, v_min, v_step in self.ACCEPTED:
            with self.subTest(label=label):
                rm = _rm()
                rm.update_symbol_specs("SYM", val=val, size=size, v_min=v_min, v_step=v_step)
                self.assertEqual(
                    rm.symbol_specs.get("SYM"),
                    {"val": val, "ts": size, "vm": v_min, "vs": v_step},
                    f"{label} must be accepted verbatim",
                )

    def test_string_numerics_from_json_are_still_accepted(self):
        """MQL5 JSON has been seen sending numbers as strings; keep coercing."""
        rm = _rm()
        rm.update_symbol_specs("EURUSD", val="1.0", size="0.0001", v_min="0.01", v_step="0.01")
        self.assertEqual(
            rm.symbol_specs["EURUSD"], {"val": 1.0, "ts": 0.0001, "vm": 0.01, "vs": 0.01}
        )

    def test_a_change_of_exactly_10x_is_not_a_jump(self):
        """A 4-digit -> 5-digit tick regrade is legitimate; only >10x is not."""
        rm = _rm()
        rm.update_symbol_specs("EURUSD", **GOOD)
        rm.update_symbol_specs("EURUSD", val=1.0, size=0.00001, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.symbol_specs["EURUSD"]["ts"], 0.00001)


class RejectedSpecs(unittest.TestCase):
    """One case per rejection class. Every one must be a no-op + a RISK log."""

    REJECTED = [
        # (label, field, val, size, v_min, v_step)
        ("tick_value NaN", "val", float("nan"), 0.0001, 0.01, 0.01),
        ("tick_value inf", "val", float("inf"), 0.0001, 0.01, 0.01),
        ("tick_size NaN", "ts", 1.0, float("nan"), 0.01, 0.01),
        ("vol_min inf", "vm", 1.0, 0.0001, float("inf"), 0.01),
        ("vol_step NaN", "vs", 1.0, 0.0001, 0.01, float("nan")),
        ("tick_size below 1e-6", "ts", 1.0, 1e-7, 0.01, 0.01),
        ("tick_size above 100", "ts", 1.0, 101.0, 0.01, 0.01),
        ("tick_size zero", "ts", 1.0, 0.0, 0.01, 0.01),
        ("tick_size negative", "ts", 1.0, -0.0001, 0.01, 0.01),
        ("tick_value below 1e-4", "val", 1e-5, 0.0001, 0.01, 0.01),
        ("tick_value above 1e4", "val", 1e5, 0.0001, 0.01, 0.01),
        ("tick_value zero", "val", 0.0, 0.0001, 0.01, 0.01),
        ("tick_value negative", "val", -1.0, 0.0001, 0.01, 0.01),
        ("vol_min zero", "vm", 1.0, 0.0001, 0.0, 0.01),
        ("vol_min negative", "vm", 1.0, 0.0001, -0.01, 0.01),
        ("vol_step zero", "vs", 1.0, 0.0001, 0.01, 0.0),
        ("vol_step negative", "vs", 1.0, 0.0001, 0.01, -0.01),
        ("non-numeric garbage", "val", "abc", 0.0001, 0.01, 0.01),
        ("None tick_size", "ts", 1.0, None, 0.01, 0.01),
    ]

    def test_each_bad_update_leaves_a_specless_symbol_specless(self):
        for label, field, val, size, v_min, v_step in self.REJECTED:
            with self.subTest(label=label):
                rm = _rm()
                rm.update_symbol_specs("NEW", val=val, size=size, v_min=v_min, v_step=v_step)
                self.assertNotIn(
                    "NEW", rm.symbol_specs, f"{label} must not create a spec entry"
                )

    def test_each_bad_update_leaves_prior_specs_intact(self):
        for label, field, val, size, v_min, v_step in self.REJECTED:
            with self.subTest(label=label):
                rm = _rm()
                rm.update_symbol_specs("EURUSD", **GOOD)
                before = dict(rm.symbol_specs["EURUSD"])

                rm.update_symbol_specs("EURUSD", val=val, size=size, v_min=v_min, v_step=v_step)

                self.assertEqual(
                    rm.symbol_specs["EURUSD"], before,
                    f"{label} must be a no-op, not a partial or coerced write",
                )

    def test_each_bad_update_logs_a_risk_event_naming_symbol_field_and_value(self):
        for label, field, val, size, v_min, v_step in self.REJECTED:
            with self.subTest(label=label):
                spy = _SpyLogger()
                rm = _rm(logger=spy)
                rm.update_symbol_specs("EURUSD", val=val, size=size, v_min=v_min, v_step=v_step)

                msgs = spy.risk_messages()
                self.assertTrue(msgs, f"{label} must emit a RISK event")
                joined = " ".join(msgs)
                self.assertIn("EURUSD", joined, "the operator must be told which symbol")
                self.assertIn(field, joined, "the operator must be told which field")

    def test_a_rejected_update_is_silent_about_healthy_symbols(self):
        """A reject must not blanket-wipe the store."""
        rm = _rm()
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
        rm.update_symbol_specs("EURUSD", val=0.0, size=0.0001, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.symbol_specs["XAUUSD"]["val"], 1.0)
        self.assertNotIn("EURUSD", rm.symbol_specs)


class TenfoldJumpGuard(unittest.TestCase):
    """The poisoning case the audit found: plausible-looking but a huge jump."""

    JUMPS = [
        # (label, field, val, size, v_min, v_step)
        ("tick_value 1.0 -> 100.0", "val", 100.0, 0.0001, 0.01, 0.01),
        ("tick_value 1.0 -> 0.001", "val", 0.001, 0.0001, 0.01, 0.01),
        ("tick_size 0.0001 -> 0.01", "ts", 1.0, 0.01, 0.01, 0.01),
        ("tick_size 0.0001 -> 1e-6", "ts", 1.0, 1e-6, 0.01, 0.01),
        ("vol_min 0.01 -> 1.0", "vm", 1.0, 0.0001, 1.0, 0.01),
        ("vol_step 0.01 -> 0.0001", "vs", 1.0, 0.0001, 0.01, 0.0001),
    ]

    def test_a_more_than_tenfold_change_is_rejected_and_logged(self):
        for label, field, val, size, v_min, v_step in self.JUMPS:
            with self.subTest(label=label):
                spy = _SpyLogger()
                rm = _rm(logger=spy)
                rm.update_symbol_specs("EURUSD", **GOOD)
                before = dict(rm.symbol_specs["EURUSD"])

                rm.update_symbol_specs("EURUSD", val=val, size=size, v_min=v_min, v_step=v_step)

                self.assertEqual(rm.symbol_specs["EURUSD"], before, f"{label} must be a no-op")
                joined = " ".join(spy.risk_messages())
                self.assertIn("EURUSD", joined)
                self.assertIn(field, joined)

    def test_the_logged_value_is_the_field_that_actually_jumped(self):
        """The message must name the OFFENDING value, not some other field's.

        `_reject_specs` exists so an operator can tell 'this pair stopped
        trading' apart from 'this pair never had specs'. A message that names
        the right field beside the wrong number sends them looking at a healthy
        value. The pre-existing jump test only asserted the field NAME appeared,
        which a stale value survives.
        """
        for label, field, val, size, v_min, v_step in self.JUMPS:
            with self.subTest(label=label):
                spy = _SpyLogger()
                rm = _rm(logger=spy)
                rm.update_symbol_specs("EURUSD", **GOOD)

                rm.update_symbol_specs("EURUSD", val=val, size=size, v_min=v_min, v_step=v_step)

                offending = {"val": val, "ts": size, "vm": v_min, "vs": v_step}[field]
                payloads = [e[3] for e in spy.events if e[0] == "RISK"]
                self.assertTrue(payloads, f"{label} logged no RISK event")
                self.assertEqual(payloads[-1]["field"], field)
                self.assertEqual(
                    payloads[-1]["value"],
                    repr(offending),
                    f"{label}: reported {payloads[-1]['value']} for {field}, "
                    f"expected {offending!r}",
                )

    def test_the_first_update_for_a_symbol_has_nothing_to_jump_from(self):
        """No prior accepted value -> the jump rule cannot fire."""
        rm = _rm()
        rm.update_symbol_specs("BTCUSD", val=5000.0, size=0.1, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.symbol_specs["BTCUSD"]["val"], 5000.0)

    def test_a_rejected_update_does_not_become_the_new_jump_baseline(self):
        """Otherwise two bad messages walk the specs anywhere they like."""
        rm = _rm()
        rm.update_symbol_specs("EURUSD", **GOOD)
        rm.update_symbol_specs("EURUSD", val=100.0, size=0.0001, v_min=0.01, v_step=0.01)  # rejected
        rm.update_symbol_specs("EURUSD", val=1000.0, size=0.0001, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.symbol_specs["EURUSD"]["val"], 1.0, "baseline must stay the last ACCEPTED value")


class FailSafeIsPreserved(unittest.TestCase):
    """CLAUDE.md: sizing fails safe to 0 when specs have not loaded. A rejected
    update must leave the symbol in exactly that state -- not half-specced."""

    def test_symbol_whose_only_update_was_rejected_still_sizes_to_zero(self):
        rm = _rm()
        # The poisoning payload: tick_value ~0 makes money_loss_per_lot ~0 and
        # lots blow out to hard_max_lots. Pre-fix this wrote {'val': 1e-9,...}
        # and calculate_lot_size sized off it; post-fix the symbol stays spec-less.
        rm.update_symbol_specs("XAUUSD", val=1e-9, size=0.01, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.calculate_lot_size(2000, 1990, "XAUUSD", "BULLISH"), 0.0)

    def test_poisoned_tick_size_does_not_produce_a_max_lots_trade(self):
        rm = _rm()
        rm.update_symbol_specs("XAUUSD", val=1.0, size=1e9, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.calculate_lot_size(2000, 1990, "XAUUSD", "BULLISH"), 0.0)

    def test_a_rejected_update_cannot_inflate_an_already_sized_symbol(self):
        rm = _rm()
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
        healthy = rm.calculate_lot_size(2000, 1990, "XAUUSD", "BULLISH")
        self.assertGreater(healthy, 0.0)

        rm.update_symbol_specs("XAUUSD", val=1e-9, size=0.01, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.calculate_lot_size(2000, 1990, "XAUUSD", "BULLISH"), healthy)

    def test_money_for_move_is_not_poisoned_either(self):
        rm = _rm()
        rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.01, v_step=0.01)
        before = rm.money_for_move("XAUUSD", 1.5, 0.10)
        rm.update_symbol_specs("XAUUSD", val=500.0, size=0.01, v_min=0.01, v_step=0.01)
        self.assertEqual(rm.money_for_move("XAUUSD", 1.5, 0.10), before)


class NoLoggerIsSurvivable(unittest.TestCase):
    """RiskManager's logger is optional (backtester/replay pass None)."""

    def test_rejecting_without_a_logger_does_not_raise(self):
        rm = _rm(logger=None)
        rm.update_symbol_specs("EURUSD", val=float("nan"), size=0.0001, v_min=0.01, v_step=0.01)
        self.assertNotIn("EURUSD", rm.symbol_specs)


if __name__ == "__main__":
    unittest.main()
