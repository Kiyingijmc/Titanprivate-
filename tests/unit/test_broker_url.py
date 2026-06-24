# tests/unit/test_broker_url.py
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.execution.broker.mt5_http import _pick_host


class PickHost(unittest.TestCase):
    def test_mirrored_uses_loopback(self):
        # mirrored: eth0 has a LAN addr (no 172.x NAT) -> 127.0.0.1
        eth0 = "    inet 10.0.0.22/24 ..."
        route = "default via 10.0.0.1 dev eth0 ..."
        self.assertEqual(_pick_host(eth0, route), "127.0.0.1")

    def test_nat_uses_gateway(self):
        # NAT: eth0 has 172.x -> use the default-route gateway (Windows host)
        eth0 = "    inet 172.27.46.252/20 ..."
        route = "default via 172.27.32.1 dev eth0 ..."
        self.assertEqual(_pick_host(eth0, route), "172.27.32.1")

    def test_nat_without_gateway_falls_back_to_loopback(self):
        self.assertEqual(_pick_host("    inet 172.20.0.2/20", ""), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
