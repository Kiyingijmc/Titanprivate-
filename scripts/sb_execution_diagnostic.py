#!/usr/bin/env python3
"""M5 execution-path sensitivity study; research only, no live settings changed."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sb_component_diagnostic import SYMBOLS, GATES, select_signals
from scripts.poc_sb_stops import collect_signals, metrics
from src.research.costs import spread_price
from src.research.sb_execution import EXITS, PATHS, simulate
from src.utils.instrument import InstrumentHelper


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", choices=SYMBOLS, default=SYMBOLS)
    ap.add_argument("--spread-mult", type=float, default=1.0)
    ap.add_argument("--be-buffer", choices=("zero", "live"), default="live")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if not np.isfinite(args.spread_mult) or args.spread_mult < 0:
        ap.error("spread multiplier must be finite and nonnegative")
    args.out.mkdir(parents=True, exist_ok=False)
    specs = json.loads((ROOT / "data/specs.json").read_text())
    # Hash relevant sources before measurement; preserve prior study untouched.
    sources = [Path(__file__), ROOT / "scripts/sb_component_diagnostic.py",
               ROOT / "scripts/poc_sb_stops.py", ROOT / "src/research/sb_execution.py",
               ROOT / "src/research/costs.py", ROOT / "src/utils/instrument.py",
               ROOT / "data/specs.json"]
    sources += [ROOT / f"src/analysis/{name}.py" for name in
                ("smc_analyzer", "bias_engine", "market_structure", "liquidity", "signal_grader")]
    card = {"purpose": "M5 execution sensitivity, not live validation",
            "symbols": args.symbols, "spread_mult": args.spread_mult,
            "be_buffer": args.be_buffer, "commission_usd_per_lot": 7,
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sources}, "data": {}, "counts": [],
            "assumptions": ["H1 signals/context/grade clock unchanged from historical collector",
                            "M5 BID OHLC, synthetic constant ASK spread",
                            "OHLC and OLHC are sensitivities, not bounds",
                            "independent one-pending-or-open occupancy per exit arm",
                            "12 wall-clock hours pending TTL; signal available at H1 close",
                            "requested limit price, executable gap-stop price, no TP improvement",
                            "commission only; spread already in executable prices",
                            "end tails marked, not silently discarded",
                            "immediate idealized management, no latency/lot rounding/stop-level constraints",
                            "no portfolio/news/swap filters; no fresh holdout"]}
    (args.out / "run.json").write_text(json.dumps(card, indent=2) + "\n")
    all_rows = []
    for sym in args.symbols:
        spec = specs[sym]
        tick, value = float(spec["tick_size"]), float(spec["tick_value"])
        if not all(np.isfinite(v) and v > 0 for v in (tick, value)):
            raise ValueError(f"invalid specs: {sym}")
        spread = spread_price(sym, tick) * args.spread_mult
        commission = 7 / value * tick
        path = ROOT / f"data/history/{sym}_M5.csv"
        df = pd.read_csv(path)
        bars = {k: df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close")}
        bars["time"] = pd.to_datetime(df.datetime).to_numpy(dtype="datetime64[ns]")
        signals, _ = collect_signals(sym, tf="H1")
        buffer = 3 * InstrumentHelper.get_pip_size(sym) if args.be_buffer == "live" else 0.0
        card["data"][sym] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "first": str(bars["time"][0]), "last": str(bars["time"][-1]),
                              "bars": len(df), "signals": len(signals), "spread": spread,
                              "commission_price": commission, "be_buffer_price": buffer}
        for gate in GATES:
            admitted = select_signals(signals, gate)
            for arm in EXITS:
                for ordering in PATHS:
                    rows, skipped = simulate(admitted, bars, arm=arm, path=ordering,
                                             spread=spread, commission=commission, be_buffer=buffer)
                    all_rows.extend({"symbol": sym, "gate": gate, "exit": arm,
                                     "path": ordering, **r} for r in rows)
                    card["counts"].append({"symbol": sym, "gate": gate, "exit": arm,
                                           "path": ordering, "candidates": len(admitted),
                                           "skipped_busy": skipped, "orders": len(rows)})
        print(f"{sym}: {len(signals)} candidates, 32 execution arms complete", flush=True)
    frame = pd.DataFrame(all_rows)
    frame.to_csv(args.out / "orders.csv", index=False)
    summary = []
    for keys, group in frame.groupby(["gate", "exit", "path"]):
        filled = group[group.net_r.notna()]
        closed = filled[filled.outcome != "MARKED_AT_END"]
        m = metrics(filled.net_r.tolist())
        summary.append({"gate": keys[0], "exit": keys[1], "path": keys[2],
                        "orders": len(group), "filled": len(filled),
                        "expired": int((group.outcome == "EXPIRED").sum()),
                        "marked": int((group.outcome == "MARKED_AT_END").sum()),
                        "pending": int((group.outcome == "PENDING_AT_END").sum()),
                        "rejected_be": int(group.rejected_be.sum()),
                        "mean_net_r": m["exp"], "total_net_r": m["totR"], "pf": m["pf"],
                        "closed_mean_net_r": float(closed.net_r.mean()) if len(closed) else None})
    summary = pd.DataFrame(summary)
    summary.to_csv(args.out / "summary.csv", index=False)
    card["complete"] = True
    (args.out / "run.json").write_text(json.dumps(card, indent=2) + "\n")
    print(summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
