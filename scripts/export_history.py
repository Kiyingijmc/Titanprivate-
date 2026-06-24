#!/usr/bin/env python3
# scripts/export_history.py
# Export MT5 history to backtest CSVs via the Titan HTTP bridge (chunked copy_rates_range).
# Pulls whatever the broker actually retains (empty window = history floor). No EA / no ZMQ.
#   .venv/bin/python scripts/export_history.py --symbol XAUUSD --tf M5 --out data/history/XAUUSD_M5.csv
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.broker.mt5_http import MT5HttpBroker   # noqa: E402
from src.execution.broker import types as T               # noqa: E402

CSV_HEADER = "datetime,open,high,low,close"
TF = {"M1": T.Timeframe.M1, "M5": T.Timeframe.M5, "M15": T.Timeframe.M15,
      "H1": T.Timeframe.H1, "H4": T.Timeframe.H4, "D1": T.Timeframe.D1}


async def pull_history(broker, symbol, timeframe, *, now, max_lookback, chunk):
    """Walk backward in `chunk`-sized windows until an empty window (history floor) or
    max_lookback. Returns candles ascending, de-duplicated by time."""
    floor = now - max_lookback
    cursor = now
    by_time: dict[datetime, T.Candle] = {}
    while cursor > floor:
        frm = max(cursor - chunk, floor)
        window = await broker.get_candles_range(symbol, timeframe, frm, cursor)
        if not window:
            break
        for c in window:
            by_time[c.time] = c
        cursor = frm
    return [by_time[t] for t in sorted(by_time)]


def candles_to_csv(candles) -> str:
    rows = [CSV_HEADER]
    for c in candles:
        ts = c.time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(f"{ts},{c.open},{c.high},{c.low},{c.close}")
    return "\n".join(rows) + "\n"


async def _run(args):
    broker = MT5HttpBroker()   # URL/token from env / auto-resolve
    async with broker:
        bars = await pull_history(
            broker, args.symbol, TF[args.tf], now=datetime.now(tz=timezone.utc),
            max_lookback=timedelta(days=args.max_days), chunk=timedelta(days=args.chunk_days))
    if not bars:
        print(f"[EXPORT] {args.symbol}: no history returned"); return
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(candles_to_csv(bars))
    print(f"[EXPORT] {args.symbol}: wrote {len(bars)} bars "
          f"({bars[0].time.date()} -> {bars[-1].time.date()}) to {args.out}")


def main():
    p = argparse.ArgumentParser(description="Export MT5 history via the Titan HTTP bridge.")
    p.add_argument("--symbol", required=True)
    p.add_argument("--tf", default="M5", choices=list(TF))
    p.add_argument("--out", required=True)
    p.add_argument("--max-days", dest="max_days", type=int, default=1095, help="lookback cap (~3y)")
    p.add_argument("--chunk-days", dest="chunk_days", type=int, default=30)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
