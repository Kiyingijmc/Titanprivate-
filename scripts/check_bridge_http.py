#!/usr/bin/env python3
# scripts/check_bridge_http.py
# Prove the Titan HTTP bridge link (GET /health). Prints the resolved URL + health.
#   .venv/bin/python scripts/check_bridge_http.py
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.broker.mt5_http import MT5HttpBroker, _resolve_base_url   # noqa: E402
from src.execution.broker.errors import BrokerError                          # noqa: E402


async def _run():
    url = os.environ.get("TITAN_BRIDGE_URL") or _resolve_base_url()
    print(f"[CHECK] resolved bridge URL: {url}")
    try:
        async with MT5HttpBroker() as b:
            h = await b.health_check()
        print(f"[CHECK] ✅ Bridge is UP: status={h.status} mt5_connected={h.broker_connected} "
              f"uptime={h.uptime_seconds}s")
        return 0
    except BrokerError as e:
        print(f"[CHECK] ❌ Bridge check failed: {type(e).__name__}: {e}")
        print("[CHECK] Verify: bridge running on Windows (py -3.11 bridge/run_bridge.py), "
              "TITAN_BRIDGE_TOKEN set, MT5 logged into FBS-Demo.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
