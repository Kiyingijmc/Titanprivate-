import unittest
import asyncio
from src.core.bus import EventBus
from src.core.events import (EVENT_TYPES, GuiActionExecuted, IntentBlocked,
                             SystemStateChanged, TickReceived)
from src.ops.web.bus_bridge import BusBridge, project


class TestGuiActionEvent(unittest.TestCase):
    def test_registered_and_serializable(self):
        self.assertIn("GuiActionExecuted", EVENT_TYPES)
        e = GuiActionExecuted(action="pause", args="{}", outcome="ok", client="127.0.0.1")
        d = e.to_dict()
        self.assertEqual(d["evt"], "GuiActionExecuted")
        self.assertEqual(d["action"], "pause")


class TestProject(unittest.TestCase):
    def test_projects_topic_ts_and_fields(self):
        msg = project(IntentBlocked(strategy_id="sb", symbol="EURUSD",
                                    direction="BUY", rule="opposition", detail="x"))
        self.assertEqual(msg["topic"], "IntentBlocked")
        self.assertEqual(msg["rule"], "opposition")
        self.assertIn("ts", msg)
        self.assertNotIn("evt", msg)

    def test_ticks_are_dropped(self):
        self.assertIsNone(project(TickReceived(symbol="EURUSD", bid=1.0)))


class TestBusBridge(unittest.TestCase):
    def test_ring_buffer_and_recent(self):
        bridge = BusBridge(ring_size=2)
        for state in ("ACTIVE", "PAUSED", "ACTIVE"):
            bridge.handle(SystemStateChanged(state=state))
        recent = bridge.recent()
        self.assertEqual(len(recent), 2)                      # ring capped
        self.assertEqual(recent[-1]["state"], "ACTIVE")
        self.assertEqual(bridge.recent(limit=1)[0]["state"], "ACTIVE")

    def test_subscribed_bus_events_reach_client_queue(self):
        bus = EventBus()
        bridge = BusBridge()
        bus.subscribe_all(bridge.handle, name="gui")
        q = bridge.attach()
        bus.publish(SystemStateChanged(state="PAUSED"))
        msg = asyncio.run(q.get())
        self.assertEqual(msg["topic"], "SystemStateChanged")

    def test_full_client_queue_drops_never_raises(self):
        bridge = BusBridge()
        q = bridge.attach(maxsize=1)
        bridge.handle(SystemStateChanged(state="A"))
        bridge.handle(SystemStateChanged(state="B"))          # full -> dropped
        self.assertEqual(asyncio.run(q.get())["state"], "A")
        self.assertTrue(q.empty())

    def test_detach_stops_delivery(self):
        bridge = BusBridge()
        q = bridge.attach()
        bridge.detach(q)
        bridge.handle(SystemStateChanged(state="A"))
        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
