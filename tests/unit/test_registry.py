import logging
import unittest

from src.core.events import StrategyActivated, StrategySuspended
from src.features.feature_bus import FeatureBus, ResourceSpec
from src.strategies.manifest import StrategyManifest
from src.strategies.registry import RegistryError, StrategyRegistry

_LOGGER = logging.getLogger("test_registry")


def _manifest(**overrides):
    data = dict(
        id="fake_strat",
        version="1.0.0",
        class_path="tests.unit.fake_strategy:FakeStrat",
        family="smc",
        timeframe="H1",
        requires=("smc.enriched_df",),
        status="live",
        priority=50,
    )
    data.update(overrides)
    return StrategyManifest(**data)


def _bus_with(*names):
    bus = FeatureBus()
    for name in names:
        bus.register(ResourceSpec(name=name, compute=lambda ctx: None))
    return bus


class RecordingPublisher:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)


class TestLoadAll(unittest.TestCase):
    def test_imports_and_instantiates_with_right_params(self):
        manifest = _manifest(requires=())
        params_by_id = {"fake_strat": {"name": "custom", "timeframe": "M5"}}
        reg = StrategyRegistry([manifest], params_by_id, _LOGGER)
        reg.load_all()
        inst = reg.instance_of("fake_strat")
        self.assertIsNotNone(inst)
        self.assertEqual(inst.name, "custom")
        self.assertEqual(inst.timeframe, "M5")
        self.assertEqual(reg.state_of("fake_strat"), "LOADED")

    def test_import_failure_raises_registry_error(self):
        manifest = _manifest(class_path="no.such.module:NoSuchClass", requires=())
        reg = StrategyRegistry([manifest], {}, _LOGGER)
        with self.assertRaises(RegistryError):
            reg.load_all()

    def test_missing_requires_resource_raises_registry_error(self):
        manifest = _manifest(requires=("smc.enriched_df", "smc.does_not_exist"))
        bus = _bus_with("smc.enriched_df")
        reg = StrategyRegistry([manifest], {}, _LOGGER, feature_bus=bus)
        with self.assertRaises(RegistryError) as ctx:
            reg.load_all()
        self.assertIn("smc.does_not_exist", str(ctx.exception))

    def test_requires_satisfied_loads_cleanly(self):
        manifest = _manifest(requires=("smc.enriched_df",))
        bus = _bus_with("smc.enriched_df")
        reg = StrategyRegistry([manifest], {}, _LOGGER, feature_bus=bus)
        reg.load_all()
        self.assertEqual(reg.state_of("fake_strat"), "LOADED")

    def test_feature_bus_none_skips_requires_validation(self):
        manifest = _manifest(requires=("smc.anything_at_all",))
        reg = StrategyRegistry([manifest], {}, _LOGGER, feature_bus=None)
        reg.load_all()  # must not raise
        self.assertEqual(reg.state_of("fake_strat"), "LOADED")


class TestActivateEligible(unittest.TestCase):
    def test_activates_live_and_demo_not_research(self):
        live = _manifest(id="live_strat", status="live", requires=())
        demo = _manifest(id="demo_strat", status="demo", requires=())
        research = _manifest(id="research_strat", status="research", requires=())
        publisher = RecordingPublisher()
        reg = StrategyRegistry([live, demo, research], {}, _LOGGER, publish=publisher)
        reg.load_all()
        reg.activate_eligible()
        self.assertEqual(reg.state_of("live_strat"), "ACTIVE")
        self.assertEqual(reg.state_of("demo_strat"), "ACTIVE")
        self.assertEqual(reg.state_of("research_strat"), "LOADED")
        activated_ids = {e.strategy_id for e in publisher.events if isinstance(e, StrategyActivated)}
        self.assertEqual(activated_ids, {"live_strat", "demo_strat"})

    def test_respects_enabled_false_param(self):
        manifest = _manifest(id="disabled_strat", status="live", requires=())
        publisher = RecordingPublisher()
        reg = StrategyRegistry(
            [manifest], {"disabled_strat": {"enabled": False}}, _LOGGER, publish=publisher
        )
        reg.load_all()
        reg.activate_eligible()
        self.assertEqual(reg.state_of("disabled_strat"), "LOADED")
        self.assertEqual(publisher.events, [])

    def test_publish_none_is_safe(self):
        manifest = _manifest(status="live", requires=())
        reg = StrategyRegistry([manifest], {}, _LOGGER, publish=None)
        reg.load_all()
        reg.activate_eligible()  # must not raise
        self.assertEqual(reg.state_of("fake_strat"), "ACTIVE")


class TestEnableDisable(unittest.TestCase):
    def _loaded_registry(self, publisher=None, status="live"):
        manifest = _manifest(status=status, requires=())
        reg = StrategyRegistry([manifest], {}, _LOGGER, publish=publisher)
        reg.load_all()
        return reg

    def test_enable_from_loaded_activates_and_publishes(self):
        publisher = RecordingPublisher()
        reg = self._loaded_registry(publisher)
        msg = reg.enable("fake_strat")
        self.assertEqual(reg.state_of("fake_strat"), "ACTIVE")
        self.assertIsInstance(msg, str)
        self.assertEqual(len(publisher.events), 1)
        self.assertIsInstance(publisher.events[0], StrategyActivated)

    def test_disable_from_active_suspends_and_publishes(self):
        publisher = RecordingPublisher()
        reg = self._loaded_registry(publisher)
        reg.enable("fake_strat")
        publisher.events.clear()
        msg = reg.disable("fake_strat", reason="risk_breach")
        self.assertEqual(reg.state_of("fake_strat"), "SUSPENDED")
        self.assertIsInstance(msg, str)
        self.assertEqual(len(publisher.events), 1)
        evt = publisher.events[0]
        self.assertIsInstance(evt, StrategySuspended)
        self.assertEqual(evt.reason, "risk_breach")
        self.assertEqual(evt.strategy_id, "fake_strat")

    def test_re_enable_from_suspended_works(self):
        reg = self._loaded_registry()
        reg.enable("fake_strat")
        reg.disable("fake_strat")
        msg = reg.enable("fake_strat")
        self.assertEqual(reg.state_of("fake_strat"), "ACTIVE")
        self.assertIsInstance(msg, str)

    def test_enable_unknown_id_returns_message_no_raise(self):
        reg = self._loaded_registry()
        msg = reg.enable("nope")
        self.assertIsInstance(msg, str)
        self.assertIsNone(reg.state_of("nope"))

    def test_disable_unknown_id_returns_message_no_raise(self):
        reg = self._loaded_registry()
        msg = reg.disable("nope")
        self.assertIsInstance(msg, str)

    def test_disable_illegal_transition_state_unchanged(self):
        publisher = RecordingPublisher()
        reg = self._loaded_registry(publisher)
        # fake_strat is LOADED, not ACTIVE -> disable should be illegal
        msg = reg.disable("fake_strat")
        self.assertIsInstance(msg, str)
        self.assertEqual(reg.state_of("fake_strat"), "LOADED")
        self.assertEqual(publisher.events, [])

    def test_enable_illegal_transition_from_registered_state_unchanged(self):
        manifest = _manifest(requires=())
        reg = StrategyRegistry([manifest], {}, _LOGGER)
        # never called load_all() -> still REGISTERED
        msg = reg.enable("fake_strat")
        self.assertIsInstance(msg, str)
        self.assertEqual(reg.state_of("fake_strat"), "REGISTERED")


class TestActiveInstancesOrderingAndReport(unittest.TestCase):
    def test_active_instances_ordered_by_priority_then_id(self):
        m_b = _manifest(id="b_strat", priority=10, requires=())
        m_a = _manifest(id="a_strat", priority=10, requires=())
        m_c = _manifest(id="c_strat", priority=5, requires=())
        params_by_id = {mid: {"name": mid} for mid in ("b_strat", "a_strat", "c_strat")}
        reg = StrategyRegistry([m_b, m_a, m_c], params_by_id, _LOGGER)
        reg.load_all()
        reg.activate_eligible()
        ordered = reg.active_instances()
        self.assertEqual([i.name for i in ordered], ["c_strat", "a_strat", "b_strat"])

    def test_active_instances_excludes_non_active(self):
        active = _manifest(id="act", status="live", requires=())
        research = _manifest(id="res", status="research", requires=())
        params_by_id = {"act": {"name": "act"}, "res": {"name": "res"}}
        reg = StrategyRegistry([active, research], params_by_id, _LOGGER)
        reg.load_all()
        reg.activate_eligible()
        ordered = reg.active_instances()
        self.assertEqual(len(ordered), 1)
        self.assertEqual(ordered[0].name, "act")

    def test_report_shape(self):
        manifest = _manifest(status="live", requires=())
        reg = StrategyRegistry([manifest], {}, _LOGGER)
        reg.load_all()
        reg.activate_eligible()
        report = reg.report()
        self.assertEqual(len(report), 1)
        row = report[0]
        for key in ("id", "version", "family", "tf", "status", "state", "priority"):
            self.assertIn(key, row)
        self.assertEqual(row["id"], "fake_strat")
        self.assertEqual(row["state"], "ACTIVE")
        self.assertEqual(row["status"], "live")


if __name__ == "__main__":
    unittest.main()
