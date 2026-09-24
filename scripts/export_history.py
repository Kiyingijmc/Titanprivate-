#!/usr/bin/env python3
"""Extend broker history to ten years without truncating existing research data.

Single: --symbol EURUSD --tf M5 --out data/history/EURUSD_M5.csv
Batch:  --all-history --years 10 --import-lake
"""
import argparse
import asyncio
import csv
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker.errors import BrokerConnectionError, BrokerAuthError
from src.execution.broker import types as T

CSV_HEADER = "datetime,open,high,low,close"
TF = {name: getattr(T.Timeframe, name) for name in
      ("M1", "M5", "M15", "M30", "H1", "H4", "D1")}
HISTORY_NAME = re.compile(r"^([A-Za-z0-9]+)_(M1|M5|M15|M30|H1|H4|D1)\.csv$")


def history_floor(now, years):
    try:
        return now.replace(year=now.year - years)
    except ValueError:  # leap day -> last day of February
        return now.replace(year=now.year - years, day=28)


async def pull_history(broker, symbol, timeframe, *, now, max_lookback, chunk):
    """Scan the entire requested interval; an empty window is not a history floor.

    Brokers can have gaps or temporarily unloaded intervals. Output is bounded,
    chronological and de-duplicated, including inclusive window endpoints.
    """
    if max_lookback <= timedelta(0) or chunk <= timedelta(0):
        raise ValueError("lookback and chunk must be positive")
    floor = now - max_lookback
    cursor = now
    by_time = {}
    while cursor > floor:
        frm = max(cursor - chunk, floor)
        window = await broker.get_candles_range(symbol, timeframe, frm, cursor)
        for candle in window:
            if floor <= candle.time <= now:
                by_time[candle.time] = candle
        cursor = frm
    return [by_time[t] for t in sorted(by_time)]


def candles_to_csv(candles):
    rows = [CSV_HEADER]
    for c in candles:
        ts = c.time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(f"{ts},{c.open},{c.high},{c.low},{c.close}")
    return "\n".join(rows) + "\n"


def read_existing(path):
    if not Path(path).exists():
        return []
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_HEADER.split(','):
            raise ValueError(f"{path}: unexpected CSV schema; refusing to replace it")
        bars = []
        for row in reader:
            dt = datetime.fromisoformat(row['datetime'])
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            bars.append(T.Candle(time=dt, **{k: float(row[k]) for k in ('open', 'high', 'low', 'close')},
                                 tick_volume=0, spread_points=0))
        return bars


def merge_history(existing, fetched):
    merged = {}
    for c in [*existing, *fetched]:
        values = (c.open, c.high, c.low, c.close)
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f"Invalid OHLC at {c.time}")
        if c.low > min(c.open, c.close) or c.high < max(c.open, c.close) or c.low > c.high:
            raise ValueError(f"Invalid OHLC bounds at {c.time}")
        merged[c.time] = c
    return [merged[t] for t in sorted(merged)]


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def export_jobs(args):
    if args.all_history:
        jobs = []
        for path in sorted(Path(args.history_dir).glob('*.csv')):
            match = HISTORY_NAME.fullmatch(path.name)
            if match:
                jobs.append((match[1], match[2], path))
        if not jobs:
            raise ValueError("No SYMBOL_TIMEFRAME.csv history files found")
        return jobs
    return [(args.symbol, args.tf, Path(args.out))]


async def _run(args):
    load_dotenv(ROOT / '.env')
    jobs = export_jobs(args)
    now = datetime.now(timezone.utc)
    floor = now - timedelta(days=args.max_days) if args.max_days else history_floor(now, args.years)
    report = {'requested_from': floor.isoformat(), 'requested_to': now.isoformat(),
              'series': [{'symbol': symbol, 'timeframe': tf, 'path': str(path),
                          'status': 'not_attempted'} for symbol, tf, path in jobs]}
    report_path = Path(args.report or (Path(args.history_dir) / 'coverage.json'
                                      if args.all_history else str(args.out) + '.coverage.json'))
    failed = False
    try:
        async with MT5HttpBroker(timeout=args.timeout) as broker:
            for index, (symbol, tf, path) in enumerate(jobs):
                print(f"[EXPORT] {symbol} {tf}: scanning {floor.date()} -> {now.date()}", flush=True)
                row = report['series'][index]
                try:
                    existing = read_existing(path)
                    if existing:
                        row.update(existing_bars=len(existing),
                                   existing_first=min(c.time for c in existing).isoformat(),
                                   existing_last=max(c.time for c in existing).isoformat())
                    fetched = await pull_history(broker, symbol, TF[tf], now=now,
                        max_lookback=now - floor, chunk=timedelta(days=args.chunk_days))
                    if not fetched:
                        row.update(status='no_history_returned', existing_bars=len(existing))
                        failed = True
                    else:
                        bars = merge_history(existing, fetched)
                        atomic_write(path, candles_to_csv(bars))
                        span = (bars[-1].time - bars[0].time).total_seconds() / (365.25 * 86400)
                        row.update(status='updated', bars=len(bars), fetched_bars=len(fetched),
                                   added_bars=len(bars) - len(existing), first=bars[0].time.isoformat(),
                                   last=bars[-1].time.isoformat(), span_years=round(span, 3),
                                   reaches_requested_start=bars[0].time <= floor + timedelta(days=7),
                                   fetched_first=fetched[0].time.isoformat(),
                                   fetched_last=fetched[-1].time.isoformat())
                        if args.import_lake:
                            from scripts.lake_import import sniff_and_read
                            from src.data.lake import Lake
                            Lake(args.lake_root).ingest(sniff_and_read(path), broker=args.broker,
                                                      symbol=symbol, tf=tf, source=str(path))
                        print(f"[EXPORT] {symbol} {tf}: {len(bars)} bars; {span:.2f}-year span", flush=True)
                except Exception as exc:
                    row.update(status='error', error=f"{type(exc).__name__}: {exc}")
                    failed = True
                    print(f"[EXPORT] {symbol} {tf}: {row['error']}", flush=True)
                    if isinstance(exc, (BrokerConnectionError, BrokerAuthError)):
                        # A dead/auth-failing bridge affects every symbol. Do
                        # not spend hours repeating the same failure per file.
                        report['aborted'] = True
                        break
                atomic_write(report_path, json.dumps(report, indent=2) + '\n')
    except Exception as exc:
        report['error'] = f"{type(exc).__name__}: {exc}"
        failed = True
        print(f"[EXPORT] {report['error']}", flush=True)
    atomic_write(report_path, json.dumps(report, indent=2) + '\n')
    print(f"[EXPORT] Coverage report: {report_path}", flush=True)
    return 1 if failed else 0


def _positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return result


def _build_parser():
    p = argparse.ArgumentParser(description="Extend MT5 research history, preserving existing bars.")
    p.add_argument('--symbol')
    p.add_argument('--tf', default='M5', choices=list(TF))
    p.add_argument('--out')
    p.add_argument('--all-history', action='store_true', help='extend all existing symbol/timeframe CSVs')
    p.add_argument('--history-dir', default='data/history')
    limit = p.add_mutually_exclusive_group()
    limit.add_argument('--years', type=int, choices=range(5, 11), default=10)
    limit.add_argument('--max-days', type=_positive_int, help='explicit lookback override')
    p.add_argument('--chunk-days', type=_positive_int, default=30)
    p.add_argument('--timeout', type=_positive_int, default=60, help='HTTP timeout per request, seconds')
    p.add_argument('--import-lake', action='store_true', help='merge successful exports into the research lake')
    p.add_argument('--lake-root', default='data/lake')
    p.add_argument('--broker', default='fbs')
    p.add_argument('--report', help='coverage JSON output path')
    return p


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.all_history and (args.symbol or args.out):
        parser.error('--all-history cannot be combined with --symbol or --out')
    if not args.all_history and (not args.symbol or not args.out):
        parser.error('--symbol and --out are required unless --all-history is given')
    return asyncio.run(_run(args))


if __name__ == '__main__':
    sys.exit(main())
