#!/usr/bin/env python3
"""Historical-model diagnostic, NOT a live backtest or a new strategy gate.

Compare bias/grade filters BEFORE order resolution, using the frozen stop
study's fills, costs, context and exit replays. See the accompanying research
note for material limitations, particularly fixed-exit occupancy and fills.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import poc_sb_stops as sb
from src.analysis.signal_grader import SignalGrader

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
           "GBPJPY", "XAUUSD", "US30", "BTCUSD"]
GATES = ("raw", "bias", "grade", "bias_and_grade")
EXITS = ("fixed", "ratchet", "runner", "tight_runner")


def bias_passes(sig):
    return not ((sig["bias"] == "BULLISH" and sig["dir"] == "SELL")
                or (sig["bias"] == "BEARISH" and sig["dir"] == "BUY"))


def grade_passes(sig):
    """Use real grader arithmetic with the OLD study's fixed -7h clock.

    Preserve historical timing to isolate admission-order effects; this is
    explicitly not the controller's DST-aware wall-clock context.
    """
    grader = SignalGrader({"signal_grading": {"min_grade": "B"}})
    sl = sb.stop_price(sig, "ATR10")
    risk = abs(sig["entry"] - sl)
    tp = sig["entry"] + (2 * risk if sig["dir"] == "BUY" else -2 * risk)
    decision = {"signal": sig["dir"], "price": sig["entry"], "sl": sl, "tp": tp}
    context = {"bias": sig["bias"], "liquidity": {"STATUS": sig["liq_status"]},
               "ny_time": f"{(sig['hour'] + sb.NY_SHIFT) % 24:02d}:00:00"}
    candle = {"open": 0.0, "close": sig["body_atr"] * sig["atr"], "ATR": sig["atr"]}
    return grader.passes(grader.grade(decision, context, candle)["grade"])


def select_signals(signals, gate):
    if gate not in GATES:
        raise ValueError(gate)
    return [s for s in signals
            if (gate not in ("bias", "bias_and_grade") or bias_passes(s))
            and (gate not in ("grade", "bias_and_grade") or grade_passes(s))]


def evaluate(signals, bars, sym, specs):
    rows, counts = [], {}
    for gate in GATES:
        admitted = select_signals(signals, gate)
        trades = sb.resolve(admitted, bars, "ATR10")
        counts[gate] = {"candidates": len(admitted), "resolved": len(trades)}
        for tr in trades:
            cost = sb.cost_r(tr, sym, specs)
            returns = {
                "fixed": tr["r"],
                "ratchet": sb.replay_managed(tr, bars),
                "runner": sb.replay_managed(tr, bars, runner=True),
                "tight_runner": sb.replay_overlay(tr, bars, arm="C", g=0.75)[0],
            }
            for arm, gross in returns.items():
                rows.append({"symbol": sym, "time": str(tr["time"]),
                             "gate": gate, "exit": arm, "net_r": gross - cost})
    return rows, counts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", nargs="+", default=SYMBOLS, choices=sb.SYMS)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    # Never overwrite a prior diagnostic run.
    args.out.mkdir(parents=True, exist_ok=False)
    specs = json.loads((ROOT / "data/specs.json").read_text())
    rows, counts, provenance = [], {}, {}
    for sym in args.symbols:
        path = ROOT / f"data/history/{sym}_M5.csv"
        if not path.is_file() or sym not in specs or sym not in sb.SPREADS:
            raise ValueError(f"Missing history/specs/spread: {sym}")
        if any(float(specs[sym].get(k, 0)) <= 0 for k in ("tick_size", "tick_value")):
            raise ValueError(f"Invalid specs: {sym}")
        signals, bars = sb.collect_signals(sym, tf="H1")
        provenance[sym] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "first_h1": str(bars["times"][0]),
                           "last_h1": str(bars["times"][-1]),
                           "h1_bars": len(bars["times"])}
        result, counts[sym] = evaluate(signals, bars, sym, specs)
        rows.extend(result)
        print(f"{sym}: {counts[sym]}", flush=True)
    frame = pd.DataFrame(rows).sort_values(["time", "symbol"])
    frame.to_csv(args.out / "trades.csv", index=False)
    summary = []
    for gate in GATES:
        for arm in EXITS:
            subset = frame[(frame.gate == gate) & (frame.exit == arm)]
            # No drawdown claim: these are fixed-entry replay comparisons,
            # not independently scheduled managed portfolios.
            m = sb.metrics(subset.net_r.tolist())
            summary.append({"gate": gate, "exit": arm,
                            **{k: m[k] for k in ("n", "exp", "totR", "pf", "winpct")}})
    pd.DataFrame(summary).to_csv(args.out / "summary.csv", index=False)
    sources = [Path(__file__), ROOT / "scripts/poc_sb_stops.py",
               ROOT / "src/analysis/signal_grader.py", ROOT / "data/specs.json",
               ROOT / "src/research/costs.py", ROOT / "src/analysis/smc_analyzer.py",
               ROOT / "src/analysis/bias_engine.py", ROOT / "src/analysis/market_structure.py",
               ROOT / "src/analysis/liquidity.py"]
    card = {"purpose": "historical-model diagnostic; NOT live validation",
            "symbols": args.symbols, "timeframe": "H1", "stop": "ATR10",
            "gate_order": "before resolve", "clock": "legacy broker hour minus 7",
            "limitations": ["legacy direction-blind bid-touch limit fills",
                            "fixed-exit occupancy reused by managed arms",
                            "prior-100-H1-bar bias context, unlike live window",
                            "no news, portfolio, slippage or swap simulation",
                            "H1 intrabar ordering and partial-fill approximations",
                            "unresolved fixed trades excluded; open managed tail valued at zero"],
            "counts": counts, "data": provenance,
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sources}}
    (args.out / "run.json").write_text(json.dumps(card, indent=2) + "\n")
    print(pd.DataFrame(summary).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
