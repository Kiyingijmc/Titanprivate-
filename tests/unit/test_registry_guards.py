"""Plan-04 carry-forward guards (Plan 05 Task 3): the registry promote-gate
for research-status strategies, and duplicate-instance-name rejection in
StrategyRegistry.load_all(), plus the Telegram `/enable <id> confirm`
passthrough that exercises the gate override.
"""
import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock

from src.core.events import StrategyActivated
from src.ops.telemetry import TelegramBot
from src.strategies.manifest import StrategyManifest
from src.strategies.registry import RegistryError, StrategyRegistry

_LOGGER = logging.getLogger("test_registry_guards")


def _manifest(**overrides):
    data = dict(
        id="fake_strat",
        version="1.0.0",
        class_path="tests.unit.fake_strategy:FakeStrat",
        family="smc",
        timeframe="H1",
        requires=(),
        status="live",
        priority=50,
    )
    data.update(overrides)
    return StrategyManifest(**data)


class RecordingPublisher:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)


class TestResearchPromoteGate(unittest.TestCase):
    def test_research_enable_refused_without_confirm(self):
        manifest = _manifest(status="research")
        publisher = RecordingPublisher()
        reg = StrategyRegistry([manifest], {}, _LOGGER, publish=publisher)
        reg.load_all()

        msg = reg.enable("fake_strat")

        self.assertEqual(
            msg,
            "⛔ 'fake_strat' is research-status (ungated). "
            "Use `/enable fake_strat confirm` to override.",
        )
        self.assertEqual(reg.state_of("fake_strat"), "LOADED")
        self.assertEqual(publisher.events, [])

    def test_research_enable_with_allow_research_activates_and_publishes(self):
        manifest = _manifest(status="research")
        publisher = RecordingPublisher()
        reg = StrategyRegistry([manifest], {}, _LOGGER, publish=publisher)
        reg.load_all()

        msg = reg.enable("fake_strat", allow_research=True)

        self.assertEqual(reg.state_of("fake_strat"), "ACTIVE")
        self.assertEqual(len(publisher.events), 1)
        self.assertIsInstance(publisher.events[0], StrategyActivated)
        self.assertIsInstance(msg, str)

    def test_live_status_enable_unaffected_by_new_kwarg(self):
        manifest = _manifest(status="live")
        publisher = RecordingPublisher()
        reg = StrategyRegistry([manifest], {}, _LOGGER, publish=publisher)
        reg.load_all()

        msg = reg.enable("fake_strat")  # positional call, unaware of the new kwarg

        self.assertEqual(reg.state_of("fake_strat"), "ACTIVE")
        self.assertEqual(len(publisher.events), 1)
        self.assertEqual(msg, "Strategy 'fake_strat' enabled (now ACTIVE).")


class TestDuplicateInstanceNameRejection(unittest.TestCase):
    def test_duplicate_name_raises_registry_error_naming_both_ids(self):
        m1 = _manifest(id="strat_one", status="live")
        m2 = _manifest(id="strat_two", status="live")
        params_by_id = {"strat_one": {"name": "dup"}, "strat_two": {"name": "dup"}}
        reg = StrategyRegistry([m1, m2], params_by_id, _LOGGER)

        with self.assertRaises(RegistryError) as ctx:
            reg.load_all()

        msg = str(ctx.exception)
        self.assertIn("strat_one", msg)
        self.assertIn("strat_two", msg)
        self.assertIn("dup", msg)


class _DummyLogger:
    def log_event(self, *args, **kwargs):
        pass


class TestTelemetryEnableConfirmRouting(unittest.TestCase):
    def _bot(self, controller):
        bot = TelegramBot(_DummyLogger())
        bot.allowed_chat_id = "555"
        bot.send_message = AsyncMock()
        bot.register_controller(controller)
        return bot

    def test_enable_confirm_routes_allow_research_true(self):
        controller = MagicMock()
        controller.enable_strategy.return_value = "ok"
        bot = self._bot(controller)

        update = {"message": {"from": {"id": "555"}, "text": "/enable my_strat confirm"}}
        asyncio.run(bot._process(update))

        controller.enable_strategy.assert_called_once_with("my_strat", allow_research=True)

    def test_enable_single_arg_routes_without_allow_research(self):
        controller = MagicMock()
        controller.enable_strategy.return_value = "ok"
        bot = self._bot(controller)

        update = {"message": {"from": {"id": "555"}, "text": "/enable my_strat"}}
        asyncio.run(bot._process(update))

        controller.enable_strategy.assert_called_once_with("my_strat")


if __name__ == "__main__":
    unittest.main()
