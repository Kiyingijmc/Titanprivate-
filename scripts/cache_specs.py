#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/cache_specs.py
# Pull per-instrument tick specs from MT5 via the ZMQ bridge into data/specs.json,
# so the offline backtester can compute realistic dollar PnL + costs.
#
# Run only when the main bot is NOT running (shared ZMQ ports) and the EA is
# connected (see CLAUDE.md). Example:
#   .venv/bin/python scripts/cache_specs.py EURUSD GBPUSD XAUUSD US30 BTCUSD
# ==============================================================================

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.execution.bridge_zmq import ZMQBridge

DEFAULT = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
           "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]


async def _run(symbols, out):
    bridge = ZMQBridge()
    if not await asyncio.wait_for(bridge.ping(), 6):
        print("bridge down — attach the EA (InpIP = WSL IP) and retry")
        return 1
    specs = {}
    for s in symbols:
        await bridge.send_command("GET_HISTORY", {"symbol": s, "tf": "M5", "count": 5})
        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            for m in await bridge.poll_data():
                if m.get("type") == "HISTORY" and m.get("symbol") == s:
                    specs[s] = {"tick_value": m.get("tv"), "tick_size": m.get("ts"),
                                "vol_min": m.get("vm"), "vol_step": m.get("vs")}
                    break
            if s in specs:
                break
            await asyncio.sleep(0.1)
        print(f"  {s}: {specs.get(s, 'NO DATA')}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(specs, f, indent=2)
    print(f"wrote {len(specs)} specs -> {out}")
    return 0


def main():
    symbols = sys.argv[1:] or DEFAULT
    raise SystemExit(asyncio.run(_run(symbols, "data/specs.json")))


if __name__ == "__main__":
    main()
