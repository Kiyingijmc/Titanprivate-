# ==============================================================================
# FILE: tests/unit/test_check_bridge_ip.py
# The IP check_bridge.py tells the operator to put in the EA's InpIP must match
# the WSL networking mode: mirrored mode shares localhost between Windows and
# WSL (the eth0 IP is the host's own LAN IP and does NOT hairpin back), while
# NAT mode needs the WSL eth0 address.
# ==============================================================================

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))

from check_bridge import _ea_target_ip

ETH0_MIRRORED = "    inet 10.64.151.252/24 brd 10.64.151.255 scope global noprefixroute eth0"
ETH0_NAT = "    inet 172.29.112.5/20 brd 172.29.127.255 scope global eth0"


class TestEaTargetIp(unittest.TestCase):
    def test_mirrored_mode_targets_localhost(self):
        self.assertEqual(_ea_target_ip("mirrored\n", ETH0_MIRRORED), "127.0.0.1")

    def test_nat_mode_targets_eth0_ip(self):
        self.assertEqual(_ea_target_ip("nat\n", ETH0_NAT), "172.29.112.5")

    def test_no_wslinfo_falls_back_to_nat_heuristic(self):
        # 172.x on eth0 -> NAT (same heuristic as broker._pick_host)
        self.assertEqual(_ea_target_ip("", ETH0_NAT), "172.29.112.5")

    def test_no_wslinfo_non_nat_addr_means_mirrored(self):
        self.assertEqual(_ea_target_ip("", ETH0_MIRRORED), "127.0.0.1")

    def test_nat_mode_without_eth0_addr_gives_hint(self):
        self.assertIn("ip -4 addr", _ea_target_ip("nat\n", ""))


if __name__ == "__main__":
    unittest.main()
