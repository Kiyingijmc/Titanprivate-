#!/usr/bin/env python3
"""Read the account's broker catalog and preview strategy eligibility; no orders."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker.errors import BrokerError
from src.ops.web.config_layer import load_layered_config
from src.strategies.universe import discover_catalog, selected_pairs


async def build_report(broker, config):
    catalog, rejected = await discover_catalog(broker)
    strategies = {}
    for sid, original in config.get("strategies", {}).items():
        params = deepcopy(original)
        params["universe"] = {"source": "broker", "include": ["*"]}
        strategies[sid] = {"enabled": original.get("enabled", False),
                           "eligible": selected_pairs(sid, params, catalog)}
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "purpose": "operational eligibility only, not profitability or activation",
            "catalog": {name: info.model_dump() for name, info in catalog.items()},
            "unavailable": rejected, "strategies": strategies}


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output already exists; choose a new file")
    load_dotenv(ROOT / ".env")
    config = load_layered_config(ROOT / "config/config.yaml", ROOT / "config/overrides.yaml")
    async with MT5HttpBroker(timeout=5, enable_read_retry=False) as broker:
        report = await build_report(broker, config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write("\n")
    print(f"Catalog: {len(report['catalog'])}; unavailable: {len(report['unavailable'])}")
    for sid, row in report["strategies"].items():
        print(f"{sid}: {len(row['eligible'])} operationally eligible (enabled={row['enabled']})")
    print(f"Saved {args.out}; no strategies enabled and no orders sent.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (BrokerError, ValueError) as exc:
        sys.exit(f"Catalog unavailable ({type(exc).__name__}): {exc}; no configuration changed.")
