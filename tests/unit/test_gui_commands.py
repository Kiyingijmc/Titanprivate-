import unittest
import asyncio
from src.ops.web.commands import execute_command


class FakeController:
    def __init__(self):
        self.calls = []

    def set_system_pause(self, p):
        self.calls.append(("pause", p))
        return "PAUSED" if p else "ACTIVE"

    async def close_specific_market_order(self, ticket_id):
        self.calls.append(("close", ticket_id))
        return f"closed {ticket_id}"

    async def close_all_market_orders(self):
        self.calls.append(("closeall",))
        return 3

    async def trigger_panic(self):
        self.calls.append(("panic",))

    async def cancel_pending_orders(self, target_id="all"):
        self.calls.append(("cancel", target_id))
        return "cancelled"


class TestCommands(unittest.TestCase):
    def test_pause_and_resume(self):
        c = FakeController()
        self.assertEqual(asyncio.run(execute_command(c, {"command": "pause"}))["result"], "PAUSED")
        self.assertEqual(asyncio.run(execute_command(c, {"command": "resume"}))["result"], "ACTIVE")

    def test_close_requires_int_ticket(self):
        c = FakeController()
        self.assertEqual(asyncio.run(execute_command(c, {"command": "close"}))["status"], "error")
        res = asyncio.run(execute_command(c, {"command": "close", "ticket": 42}))
        self.assertEqual(res["result"], "closed 42")

    def test_destructive_need_confirm_and_do_not_touch_controller(self):
        c = FakeController()
        for cmd in ("closeall", "panic"):
            res = asyncio.run(execute_command(c, {"command": cmd}))
            self.assertEqual(res["status"], "needs_confirm")
        self.assertEqual(c.calls, [])
        self.assertEqual(asyncio.run(execute_command(c, {"command": "closeall", "confirm": True}))["result"], 3)
        asyncio.run(execute_command(c, {"command": "panic", "confirm": True}))
        self.assertIn(("panic",), c.calls)

    def test_cancel_and_unknown(self):
        c = FakeController()
        self.assertEqual(asyncio.run(execute_command(c, {"command": "cancel"}))["result"], "cancelled")
        self.assertEqual(asyncio.run(execute_command(c, {"command": "boom"}))["status"], "error")


if __name__ == "__main__":
    unittest.main()
