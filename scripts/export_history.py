#!/usr/bin/env python3
# ==============================================================================
# FILE: scripts/export_history.py
# Pull historical bars from MT5 (via the existing ZMQ bridge) into a CSV that
# tests/backtest/backtest_engine.py can read.
#
# Requires: the Titan_Gateway EA running in MT5 and connected to this machine
# (see docs). Run this only when the main bot is NOT running -- both bind the
# same ZMQ ports, so they cannot run at the same time.
#
#   .venv/bin/python scripts/export_history.py --symbol BTCUSD --tf M5 \
#       --count 5000 --out data/history/BTCUSD_M5.csv
# ==============================================================================

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.execution.bridge_zmq import ZMQBridge


CSV_HEADER = "datetime,open,high,low,close"


def bars_to_csv(bars):
    """Convert MT5 HISTORY bars [{"t","o","h","l","c"}, ...] to CSV text.

    The timestamp is the broker's server time (seconds). It is rendered with a
    fixed UTC offset so the output is deterministic regardless of the host
    timezone; backtest_engine.py applies any session shift itself.
    """
    rows = [CSV_HEADER]
    for b in sorted(bars, key=lambda x: x["t"]):
        dt = datetime.fromtimestamp(b["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(f"{dt},{b['o']},{b['h']},{b['l']},{b['c']}")
    return "\n".join(rows) + "\n"


async def fetch_history(bridge, symbol, tf, count, timeout=20.0):
    """Send GET_HISTORY and wait for the matching HISTORY reply (or timeout)."""
    # Confirm the EA is actually connected before asking for data.
    if not await bridge.ping():
        raise RuntimeError("No PONG from MT5 EA -- is the Gateway attached and connected?")

    await bridge.send_command("GET_HISTORY", {"symbol": symbol, "tf": tf, "count": count})

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for msg in await bridge.poll_data():
            if msg.get("type") == "HISTORY" and msg.get("symbol") == symbol and msg.get("tf") == tf:
                return msg.get("data", [])
        await asyncio.sleep(0.1)
    raise TimeoutError(f"No HISTORY for {symbol} {tf} within {timeout}s")


async def _run(args):
    bridge = ZMQBridge(push_port=args.push_port, pull_port=args.pull_port, req_port=args.req_port)
    print(f"[EXPORT] Requesting {args.count} {args.tf} bars of {args.symbol}...")
    bars = await fetch_history(bridge, args.symbol, args.tf, args.count)
    print(f"[EXPORT] Received {len(bars)} bars.")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(bars_to_csv(bars))
    print(f"[EXPORT] Wrote {args.out}")


def main():
    p = argparse.ArgumentParser(description="Export MT5 history to a backtest CSV via the ZMQ bridge.")
    p.add_argument("--symbol", required=True, help="e.g. BTCUSD, EURUSD")
    p.add_argument("--tf", default="M5", choices=["M5", "H1"], help="timeframe the EA supports")
    p.add_argument("--count", type=int, default=5000, help="number of bars")
    p.add_argument("--out", required=True, help="output CSV path")
    p.add_argument("--push-port", type=int, default=32768)
    p.add_argument("--pull-port", type=int, default=32769)
    p.add_argument("--req-port", type=int, default=32770)
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
