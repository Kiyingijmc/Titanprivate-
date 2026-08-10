"""One strategy's exception must not be bot-fatal.

Audit 2026-08-07 signal D6: _run_strategies awaited on_new_candle bare, so a
single malformed candle in a single strategy on a single symbol propagated
to the main loop's outer `except Exception`, which Telegrams FATAL SYSTEM
CRASH and re-raises -- taking down the whole async loop and, with it,
in-trade management (BE, partials, trail) for every open position on every
OTHER symbol. The fragility was inverted: a code fault killed the bot while
a data fault vanished silently.

These tests pin the blast radius at (this strategy, this symbol, this bar)
and the operator signal at a throttled WARN.

RS024 widened two boundaries that the first cut left open, both of them
still bot-fatal: a strategy that RETURNS a malformed decision dict never
"raises on this bar" but detonates one line later when the controller
dereferences that output (MAJOR-1), and the enrichment prologue runs before
any strategy is called at all (MINOR-2).
"""
import asyncio
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import pandas as pd

from src.core.system_controller import SystemController
from src.strategies.base_strategy import BaseStrategy


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class RecordingLogger:
    def __init__(self):
        self.events = []

    def log_event(self, level, source, message, payload=None):
        self.events.append((level, source, message, payload))

    def errors(self):
        return [e for e in self.events if e[0] == "ERROR"]


class FakeTimeEngine:
    def get_current_ny_string(self):
        return "10:00:00 EST"


class FakeStore:
    def get_data(self, tf):
        return None


class FakeFeatureBus:
    def evaluate(self, name, symbol, tf, token=None, window=None, h1_df=None):
        if name == "smc.enriched_df":
            return window
        if name == "smc.bias_context":
            return ("NEUTRAL", {})
        raise ValueError(name)


class FakeTelemetry:
    def __init__(self):
        self.messages = []

    async def send_message(self, text, parse_mode=None):
        self.messages.append((text, parse_mode))


class FakeGrader:
    min_grade = "C"

    def grade(self, decision, ctx, bar):
        return {"grade": "A", "score": 9, "factors": []}

    def passes(self, grade, strategy_name):
        return True


class Raiser(BaseStrategy):
    """Real BaseStrategy subclass so the plumbing under test is production's."""

    def __init__(self, name="Raiser", exc=None, cfg=None):
        super().__init__(name, cfg or {"timeframe": "H1"}, RecordingLogger())
        self.exc = exc or ValueError("malformed candle")
        self.calls = []

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        self.calls.append((context or {}).get("symbol"))
        raise self.exc


class Survivor(BaseStrategy):
    def __init__(self, name="Survivor", decision=None, cfg=None):
        super().__init__(name, cfg or {"timeframe": "H1"}, RecordingLogger())
        self.decision = decision
        self.calls = []

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        self.calls.append((context or {}).get("symbol"))
        return self.decision


def make_controller(strategies, symbols=("EURUSD",), telemetry=None):
    c = SystemController.__new__(SystemController)
    c.logger = RecordingLogger()
    c.strategies = list(strategies)
    c.market_data = {s: FakeStore() for s in symbols}
    c.time_engine = FakeTimeEngine()
    c.feature_bus = FakeFeatureBus()
    c.current_open_positions = []
    c.signal_grader = FakeGrader()
    if telemetry is not None:
        c.telemetry = telemetry
    return c


def _bar_df():
    return pd.DataFrame([{"time": "bar-1", "close": 1.1, "atr": 0.001}])


class TestExceptionContainment(unittest.TestCase):
    def test_raising_strategy_does_not_propagate(self):
        c = make_controller([Raiser()], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))  # must not raise

    def test_later_strategies_still_run_this_bar(self):
        """Ordering matters: the raiser is FIRST, so a `return`-on-error (or
        an escaping exception) would silently cost every strategy behind it."""
        boom, ok = Raiser(), Survivor()
        c = make_controller([boom, ok], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(boom.calls, ["EURUSD"])
        self.assertEqual(ok.calls, ["EURUSD"])

    def test_surviving_strategy_still_executes_its_signal(self):
        """Not merely "gets called" -- its signal must still reach execution,
        which is the thing the operator actually loses if containment is
        wrong."""
        executed = []
        decision = {"signal": "BUY", "type": "MARKET",
                    "price": 1.1, "sl": 1.09, "tp": 1.12}
        c = make_controller([Raiser(), Survivor(decision=decision)],
                            telemetry=FakeTelemetry())

        async def fake_execute(symbol, dec, name, bias, grade=None):
            executed.append((symbol, name, dec["signal"], grade))

        c._execute_signal = fake_execute
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(executed, [("EURUSD", "Survivor", "BUY", "A")])

    def test_other_symbols_and_later_bars_still_run(self):
        boom, ok = Raiser(), Survivor()
        c = make_controller([boom, ok], symbols=("EURUSD", "GBPUSD"),
                            telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        run(c._run_strategies("GBPUSD", _bar_df(), tf="H1"))
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(ok.calls, ["EURUSD", "GBPUSD", "EURUSD"])
        self.assertEqual(boom.calls, ["EURUSD", "GBPUSD", "EURUSD"])

    def test_missing_telemetry_still_contains(self):
        """__new__-built fixtures (and the backtester) carry no telemetry;
        containment must not depend on the alert path existing."""
        boom, ok = Raiser(), Survivor()
        c = make_controller([boom, ok])
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(ok.calls, ["EURUSD"])


class TestMalformedDecisionContainment(unittest.TestCase):
    """RS024 MAJOR-1: the guarded unit is the loop body, not the await.

    Guarding only `await strat.on_new_candle(...)` leaves every line that
    dereferences that strategy's own output unguarded -- the HTF filter's
    decision['signal'], the grader, the SIGNAL journal's
    float(decision[k]) for 'price'/'sl'/'tp', the Intent constructor. A
    strategy emitting a short dict reaches the main loop's handler by
    exactly the route the narrow guard was meant to close, and takes every
    strategy queued behind it on that bar with it. Not hypothetical here:
    the same audit sweep recorded Gambit Judas dying on a shape the
    controller was not written for.
    """

    SHORT = {"signal": "BUY", "type": "MARKET", "price": 1.1}  # no 'sl'/'tp'

    def test_malformed_decision_does_not_propagate(self):
        c = make_controller([Survivor(name="BadShape", decision=self.SHORT)],
                            telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))  # must not raise

    def test_later_strategies_still_run_after_a_malformed_decision(self):
        """The raiser is FIRST again -- the ordering that a `return` (or an
        escape) sails through."""
        bad = Survivor(name="BadShape", decision=self.SHORT)
        ok = Survivor(name="Downstream")
        c = make_controller([bad, ok], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(ok.calls, ["EURUSD"])

    def test_malformed_decision_is_journalled_and_alerted(self):
        tel = FakeTelemetry()
        c = make_controller([Survivor(name="BadShape", decision=self.SHORT)],
                            telemetry=tel)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        errors = c.logger.errors()
        self.assertEqual(len(errors), 1)
        level, source, message, payload = errors[0]
        self.assertEqual(source, "BadShape")
        self.assertEqual(payload["error_type"], "KeyError")
        self.assertIn("EURUSD", message)
        self.assertEqual(len(tel.messages), 1)
        self.assertIn("BadShape", tel.messages[0][0])
        self.assertNotIn("FATAL", tel.messages[0][0])

    def test_a_grader_fault_is_contained_too(self):
        """The grader is controller machinery reached only via a decision;
        it is inside the same per-strategy unit of work."""
        class BoomGrader(FakeGrader):
            def grade(self, decision, ctx, bar):
                raise TypeError("bad bar")

        good = {"signal": "BUY", "type": "MARKET",
                "price": 1.1, "sl": 1.09, "tp": 1.12}
        first = Survivor(name="Signaller", decision=good)
        ok = Survivor(name="Downstream")
        c = make_controller([first, ok], telemetry=FakeTelemetry())
        c.signal_grader = BoomGrader()
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(ok.calls, ["EURUSD"])
        self.assertEqual(c.logger.errors()[0][1], "Signaller")


class TestBarEnrichmentContainment(unittest.TestCase):
    """RS024 MINOR-2: the prologue runs before any strategy is called.

    own_token = str(tf_df.iloc[-1]['time']) and the two FeatureBus
    evaluations (which re-raise their pack's exception by contract) touch
    the bar first. That is the backlog row's literal headline scenario -- "a
    single malformed candle in ONE symbol ... halts trading AND management
    for everything" -- and it survived the per-strategy guard.
    """

    def _bad_bar(self):
        return pd.DataFrame([{"close": 1.1}])  # no 'time' column

    def test_unenrichable_bar_does_not_propagate(self):
        c = make_controller([Survivor()], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", self._bad_bar(), tf="H1"))

    def test_no_strategy_runs_on_an_unenrichable_bar(self):
        """Skipping is the correct outcome, not a regression: enriched_df
        never got built, so there is nothing to hand a strategy."""
        ok = Survivor()
        c = make_controller([ok], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", self._bad_bar(), tf="H1"))
        self.assertEqual(ok.calls, [])

    def test_the_fault_is_journalled_under_its_own_source(self):
        c = make_controller([Survivor()], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", self._bad_bar(), tf="H1"))
        errors = c.logger.errors()
        self.assertEqual(len(errors), 1)
        level, source, message, payload = errors[0]
        self.assertEqual(source, SystemController.BAR_ENRICHMENT_FAULT_SOURCE)
        self.assertNotIn(source, {s.name for s in c.strategies})
        self.assertIn("EURUSD", message)
        self.assertEqual(payload["error_type"], "KeyError")
        self.assertEqual(payload["symbol"], "EURUSD")

    def test_alert_says_every_strategy_was_lost_not_one(self):
        """A prologue fault costs the whole symbol; reporting it with the
        per-strategy wording would understate the outage."""
        tel = FakeTelemetry()
        c = make_controller([Survivor()], telemetry=tel)
        run(c._run_strategies("EURUSD", self._bad_bar(), tf="H1"))
        self.assertEqual(len(tel.messages), 1)
        text = tel.messages[0][0]
        self.assertNotIn("FATAL", text)
        self.assertIn("every strategy on this symbol", text)

    def test_other_symbols_and_later_bars_are_unaffected(self):
        ok = Survivor()
        c = make_controller([ok], symbols=("EURUSD", "GBPUSD"),
                            telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", self._bad_bar(), tf="H1"))
        run(c._run_strategies("GBPUSD", _bar_df(), tf="H1"))
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(ok.calls, ["GBPUSD", "EURUSD"])

    def test_alert_is_throttled_but_every_bar_is_journalled(self):
        tel = FakeTelemetry()
        c = make_controller([Survivor()], telemetry=tel)
        for _ in range(3):
            run(c._run_strategies("EURUSD", self._bad_bar(), tf="H1"))
        self.assertEqual(len(tel.messages), 1)
        self.assertEqual(len(c.logger.errors()), 3)


class TestFaultJournalling(unittest.TestCase):
    def test_error_event_names_strategy_and_symbol(self):
        c = make_controller([Raiser(name="Gambit")], telemetry=FakeTelemetry())
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        errors = c.logger.errors()
        self.assertEqual(len(errors), 1)
        level, source, message, payload = errors[0]
        self.assertEqual(source, "Gambit")
        self.assertIn("EURUSD", message)
        self.assertIn("ValueError", message)
        self.assertIn("malformed candle", message)
        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(payload["timeframe"], "H1")
        self.assertEqual(payload["error_type"], "ValueError")

    def test_every_faulting_bar_is_journalled(self):
        """The Telegram is throttled; the audit trail is not. Losing the
        per-bar record would make "broken all session" look like one blip."""
        c = make_controller([Raiser()], telemetry=FakeTelemetry())
        for _ in range(3):
            run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(c.logger.errors()), 3)


class TestOperatorAlert(unittest.TestCase):
    def test_sends_a_warn_not_a_fatal_crash(self):
        tel = FakeTelemetry()
        c = make_controller([Raiser(name="Gambit")], telemetry=tel)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(tel.messages), 1)
        text, parse_mode = tel.messages[0]
        self.assertEqual(parse_mode, "Markdown")
        self.assertNotIn("FATAL", text)
        self.assertIn("Gambit", text)
        self.assertIn("EURUSD", text)
        self.assertIn("ValueError", text)

    def test_throttled_per_strategy_per_symbol(self):
        tel = FakeTelemetry()
        c = make_controller([Raiser()], telemetry=tel)
        for _ in range(5):
            run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(tel.messages), 1)

    def test_a_second_symbol_gets_its_own_alert(self):
        """A fault on one pair's feed is a different diagnosis from a
        strategy broken everywhere; a global throttle would hide the second."""
        tel = FakeTelemetry()
        c = make_controller([Raiser()], symbols=("EURUSD", "GBPUSD"),
                            telemetry=tel)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        run(c._run_strategies("GBPUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(tel.messages), 2)
        self.assertIn("GBPUSD", tel.messages[1][0])

    def test_a_second_strategy_gets_its_own_alert(self):
        tel = FakeTelemetry()
        c = make_controller([Raiser(name="A"), Raiser(name="B")], telemetry=tel)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(tel.messages), 2)

    def test_alert_re_arms_after_the_interval(self):
        tel = FakeTelemetry()
        c = make_controller([Raiser()], telemetry=tel)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        # Age the stamp past the throttle rather than sleeping through it.
        key = ("Raiser", "EURUSD")
        c._strategy_fault_alert_at[key] -= (
            SystemController.STRATEGY_FAULT_ALERT_INTERVAL_S + 1)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(tel.messages), 2)

    def test_throttle_state_is_not_shared_between_controllers(self):
        """_strategy_fault_alert_at defaults on the CLASS; writing through it
        instead of shadowing it would let one controller mute another."""
        tel_a, tel_b = FakeTelemetry(), FakeTelemetry()
        a = make_controller([Raiser()], telemetry=tel_a)
        b = make_controller([Raiser()], telemetry=tel_b)
        run(a._run_strategies("EURUSD", _bar_df(), tf="H1"))
        run(b._run_strategies("EURUSD", _bar_df(), tf="H1"))
        self.assertEqual(len(tel_a.messages), 1)
        self.assertEqual(len(tel_b.messages), 1)
        self.assertIsNone(SystemController._strategy_fault_alert_at)

    def test_exception_text_cannot_break_the_markdown_code_span(self):
        """The detail is an arbitrary exception string inside backticks. A
        stray backtick or newline breaks the span and Telegram 400s the whole
        message -- which send_message, being fire-and-forget, never reports."""
        tel = FakeTelemetry()
        boom = Raiser(exc=RuntimeError("bad `tick`\nat row 7"))
        c = make_controller([boom], telemetry=tel)
        run(c._run_strategies("EURUSD", _bar_df(), tf="H1"))
        # Split on the line prefix, not on "Error: " -- the detail itself
        # starts "RuntimeError: " and would eat the split.
        detail = tel.messages[0][0].split("\nError: ", 1)[1].split("\n")[0]
        self.assertTrue(detail.startswith("`") and detail.endswith("`"))
        self.assertEqual(detail.count("`"), 2)
        self.assertIn("bad 'tick' at row 7", detail)


if __name__ == "__main__":
    unittest.main()
