#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/check_bridge.py
# End-to-end connectivity check for the MT5 <-> Python ZMQ bridge.
#
# Binds the same ports the bot uses and sends PING over the REQ socket; the
# Titan_Gateway EA replies PONG. Use this to prove the Windows<->WSL link works
# before starting the full bot. Run only when the main bot is NOT running.
#
#   .venv/bin/python scripts/check_bridge.py
# ==============================================================================

import asyncio
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.execution.bridge_zmq import ZMQBridge

_EA_IP_HINT = "<unknown: run `ip -4 addr show eth0`>"


def _ea_target_ip(wslinfo_out, eth0_out):
    """The IP the EA's InpIP must point at, from `wslinfo --networking-mode` and
    `ip -4 addr show eth0` text.

    Mirrored mode shares localhost across the Windows/WSL boundary, so the EA
    connects to 127.0.0.1 — the eth0 address there is the host's own LAN IP and
    does NOT hairpin back. NAT mode needs WSL's eth0 address. When wslinfo is
    unavailable, fall back to the 172.x NAT heuristic broker._pick_host uses.
    """
    addrs = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", eth0_out)
    mode = wslinfo_out.strip().lower()
    is_nat = mode == "nat" if mode else any(a.startswith("172.") for a in addrs)
    if not is_nat:
        return "127.0.0.1"
    return addrs[0] if addrs else _EA_IP_HINT


def _probe(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except Exception:  # noqa: BLE001 — best-effort detection
        return ""


def _detect_ea_target_ip():
    return _ea_target_ip(_probe(["wslinfo", "--networking-mode"]),
                         _probe(["ip", "-4", "addr", "show", "eth0"]))


async def _run(attempts):
    bridge = ZMQBridge()
    print(f"[CHECK] Python is listening. Point the EA's InpIP at: {_detect_ea_target_ip()}")
    print("[CHECK] Pinging the EA over the REQ/REP handshake socket (port 32770)...")
    for i in range(1, attempts + 1):
        # A bound REQ socket blocks on send until a peer exists, so bound each
        # attempt: a timeout here simply means the EA isn't connected yet.
        try:
            if await asyncio.wait_for(bridge.ping(), timeout=2.5):
                print(f"[CHECK] ✅ PONG received on attempt {i}. Bridge is UP.")
                return 0
        except asyncio.TimeoutError:
            pass
        print(f"[CHECK] attempt {i}/{attempts}: no reply yet...")
        await asyncio.sleep(1.0)
    print("[CHECK] ❌ No PONG. Verify: EA attached + AutoTrading on, 'Allow DLL imports' enabled,")
    print("        libzmq.dll present in MQL5/Libraries, and InpIP set to the IP above.")
    return 1


def main():
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    raise SystemExit(asyncio.run(_run(attempts)))


if __name__ == "__main__":
    main()
