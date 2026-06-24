#!/usr/bin/env python3
# scripts/cache_specs.py
# Cache broker symbol specs to data/specs.json via the Titan HTTP bridge.
#   .venv/bin/python scripts/cache_specs.py --symbols XAUUSD EURUSD ... --out data/specs.json
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.broker.mt5_http import MT5HttpBroker   # noqa: E402
from src.execution.broker.errors import BrokerError       # noqa: E402

DEFAULT_SYMS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPCAD",
                "GBPJPY", "XAUUSD", "US30", "BTCUSD", "XBRUSD"]


async def build_specs(broker, symbols):
    """Return {symbol: {tick_value, tick_size, vol_min, vol_step}} — the shape data/specs.json
    uses (read by the offline backtester / PoC scripts; risk_manager receives the same values at
    runtime via update_symbol_specs). Per-symbol failures are skipped (logged) so one bad symbol
    never aborts the run."""
    out = {}
    for s in symbols:
        try:
            info = await broker.get_symbol_info(s)
        except BrokerError as e:
            print(f"[SPECS] {s}: skipped ({type(e).__name__}: {e})")
            continue
        out[s] = {"tick_value": info.tick_value, "tick_size": info.tick_size,
                  "vol_min": info.volume_min, "vol_step": info.volume_step}
    return out


async def _run(args):
    broker = MT5HttpBroker()
    async with broker:
        specs = await build_specs(broker, args.symbols)
    if not specs:
        print(f"[SPECS] ERROR: no specs fetched for any of {len(args.symbols)} symbols; "
              f"leaving {args.out} untouched")
        return
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(specs, f, indent=2)
    print(f"[SPECS] wrote {len(specs)} symbols -> {args.out}")


def main():
    p = argparse.ArgumentParser(description="Cache MT5 symbol specs via the Titan HTTP bridge.")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMS)
    p.add_argument("--out", default="data/specs.json")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
