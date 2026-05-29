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
import socket
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.execution.bridge_zmq import ZMQBridge


def _wsl_ip():
    """Best-effort: the eth0 IP Windows should target in the EA's InpIP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "<run: ip -4 addr show eth0>"


async def _run(attempts):
    bridge = ZMQBridge()
    print(f"[CHECK] Python is listening. Point the EA's InpIP at this WSL IP: {_wsl_ip()}")
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
    print("        libzmq.dll present in MQL5/Libraries, and InpIP set to the WSL IP above.")
    return 1


def main():
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    raise SystemExit(asyncio.run(_run(attempts)))


if __name__ == "__main__":
    main()
