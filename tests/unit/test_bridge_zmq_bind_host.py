# ==============================================================================
# FILE: tests/unit/test_bridge_zmq_bind_host.py
# SEC-05: the three bridge sockets used to bind the literal "tcp://*", i.e.
# every interface -- verified live on 2026-07-31 with 32768/32769/32770 on
# 0.0.0.0 while the bot held positions. Anyone routable to the host could feed
# HISTORY/EXECUTION frames or drain the command stream. They must bind the host
# declared in config (config/config.yaml connection.zeromq.host: "127.0.0.1"),
# defaulting to loopback when the key is absent.
#
# The sockets are faked: these ports belong to the live bot, and a test must
# never race it for them.
# ==============================================================================

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.execution import bridge_zmq


class _FakeSocket:
    def __init__(self, sock_type, log):
        self.sock_type = sock_type
        self._log = log
        self.closed = False

    def setsockopt(self, *args, **kwargs):
        pass

    def bind(self, endpoint):
        self._log.append((self.sock_type, endpoint))

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.binds = []

    def socket(self, sock_type):
        return _FakeSocket(sock_type, self.binds)


def _build(**kwargs):
    """Construct a ZMQBridge against fake sockets; return (bridge, binds)."""
    ctx = _FakeContext()
    with mock.patch.object(bridge_zmq.zmq.asyncio, "Context", return_value=ctx):
        bridge = bridge_zmq.ZMQBridge(**kwargs)
    return bridge, ctx.binds


class BindHost(unittest.TestCase):
    def test_default_is_loopback_on_all_three_sockets(self):
        _, binds = _build()
        self.assertEqual(
            sorted(e for _, e in binds),
            ["tcp://127.0.0.1:32768", "tcp://127.0.0.1:32769", "tcp://127.0.0.1:32770"],
        )

    def test_no_socket_binds_the_wildcard(self):
        _, binds = _build()
        for sock_type, endpoint in binds:
            self.assertNotIn("*", endpoint, f"socket {sock_type} still binds every interface")
            self.assertNotIn("0.0.0.0", endpoint)

    def test_each_socket_binds_the_configured_host(self):
        _, binds = _build(host="10.0.0.5")
        self.assertEqual(
            sorted(e for _, e in binds),
            ["tcp://10.0.0.5:32768", "tcp://10.0.0.5:32769", "tcp://10.0.0.5:32770"],
        )

    def test_ports_are_unchanged_by_the_host_wiring(self):
        _, binds = _build(push_port=1, pull_port=2, req_port=3, host="127.0.0.1")
        by_type = {t: e for t, e in binds}
        self.assertEqual(by_type[bridge_zmq.zmq.PUSH], "tcp://127.0.0.1:1")
        self.assertEqual(by_type[bridge_zmq.zmq.PULL], "tcp://127.0.0.1:2")
        self.assertEqual(by_type[bridge_zmq.zmq.REQ], "tcp://127.0.0.1:3")

    def test_an_empty_or_missing_host_falls_back_to_loopback(self):
        """config.get('host') returning None/"" must not build "tcp://:32768"."""
        for absent in (None, ""):
            with self.subTest(host=absent):
                _, binds = _build(host=absent)
                self.assertEqual(
                    sorted(e for _, e in binds),
                    ["tcp://127.0.0.1:32768", "tcp://127.0.0.1:32769", "tcp://127.0.0.1:32770"],
                )

    def test_req_socket_reset_rebinds_the_same_configured_host(self):
        """_init_req_socket runs again on every REQ timeout -- it must not
        silently revert to the wildcard on the reset path."""
        bridge, binds = _build(host="10.0.0.5")
        binds.clear()
        bridge._init_req_socket()
        self.assertEqual(binds, [(bridge_zmq.zmq.REQ, "tcp://10.0.0.5:32770")])


class ControllerWiring(unittest.TestCase):
    """The config key existed and was never read; prove the wiring is real."""

    def test_shipped_config_declares_a_loopback_host(self):
        import yaml

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "config", "config.yaml")) as fh:
            cfg = yaml.safe_load(fh)
        self.assertEqual(cfg["connection"]["zeromq"]["host"], "127.0.0.1")

    def test_boot_sequence_passes_the_configured_host_to_the_bridge(self):
        from src.core import system_controller

        captured = {}

        class _Recorder:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        controller = system_controller.SystemController.__new__(
            system_controller.SystemController
        )
        controller.config = {
            "connection": {
                "zeromq": {"push_port": 32768, "pull_port": 32769, "host": "10.0.0.5"}
            }
        }

        with mock.patch.object(system_controller, "ZMQBridge", _Recorder):
            import asyncio

            self.assertTrue(asyncio.run(controller._boot_sequence()))

        self.assertEqual(captured.get("host"), "10.0.0.5")

    def test_boot_sequence_defaults_to_loopback_when_the_key_is_absent(self):
        from src.core import system_controller

        captured = {}

        class _Recorder:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        controller = system_controller.SystemController.__new__(
            system_controller.SystemController
        )
        controller.config = {"connection": {"zeromq": {}}}

        with mock.patch.object(system_controller, "ZMQBridge", _Recorder):
            import asyncio

            self.assertTrue(asyncio.run(controller._boot_sequence()))

        self.assertEqual(captured.get("host"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
