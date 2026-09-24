#!/usr/bin/env python3
"""Read-only bridge history collection and frozen, gap-safe window comparison."""
import argparse
import asyncio
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker.types import Timeframe
from src.research.sb_entries import candidates
from src.research.sb_variants import resample_complete
from src.research.sb_execution import simulate, PATHS
from src.research.costs import spread_price
from scripts.sb_variant_study import SYMBOLS, stats, ratios
from scripts.sb_entry_study import digest

START = pd.Timestamp('2026-06-25')
END = pd.Timestamp('2026-09-17')


def segments(frame):
    frame = frame.sort_values('time').reset_index(drop=True)
    if frame.time.duplicated().any():
        raise ValueError('duplicate timestamps')
    groups = frame.time.diff().ne(pd.Timedelta(minutes=5)).cumsum()
    return [part.reset_index(drop=True) for _, part in frame.groupby(groups)]


async def collect(out):
    load_dotenv(ROOT / '.env', override=False)
    card = dict(complete=False, data={}, ticks={}, source_sha256={})
    for file in ['scripts/sb_forward_validation.py', 'src/research/sb_entries.py',
                 'src/research/sb_sessions.py', 'src/research/sb_execution.py',
                 'src/research/sb_variants.py', 'src/research/costs.py',
                 'scripts/sb_variant_study.py', 'scripts/sb_entry_study.py',
                 'data/specs.json', 'docs/research/2026-09-17-sb-forward-validation-design.md']:
        card['source_sha256'][file] = digest(ROOT / file)
    async with MT5HttpBroker(timeout=30) as broker:
        for sym in SYMBOLS:
            tick = await broker.get_current_tick(sym)
            capture = datetime.now(timezone.utc)
            card['ticks'][sym] = dict(captured=capture.isoformat(), time=tick.time.isoformat(),
                clock_delta_seconds=(tick.time-capture).total_seconds())
            rows = {}
            cursor = datetime(2026, 6, 24, tzinfo=timezone.utc)
            end = datetime(2026, 9, 17, tzinfo=timezone.utc)
            while cursor < end:
                stop = min(cursor + timedelta(days=7), end)
                for bar in await broker.get_candles_range(sym, Timeframe.M5, cursor, stop):
                    row = bar.model_dump(mode='json')
                    if row['time'] in rows and rows[row['time']] != row:
                        raise ValueError(f'{sym}: conflicting history')
                    rows[row['time']] = row
                cursor = stop
            frame = pd.DataFrame(sorted(rows.values(), key=lambda x: x['time']))
            file = out / f'{sym}_M5.csv'
            frame.to_csv(file, index=False)
            card['data'][sym] = dict(rows=len(frame), sha256=digest(file))
            (out / 'collection.json').write_text(json.dumps(card, indent=2)+'\n')
            print(f'{sym}: collected {len(frame)} bars', flush=True)
    card['complete'] = True
    (out / 'collection.json').write_text(json.dumps(card, indent=2)+'\n')


def evaluate(out):
    card = json.loads((out / 'collection.json').read_text())
    if not card['complete']:
        raise ValueError('incomplete collection')
    # Two liquid FX clocks must corroborate broker-local summer wall time.
    if not all(abs(card['ticks'][s]['clock_delta_seconds']-10800) < 120
               for s in ('EURUSD', 'GBPUSD')):
        raise ValueError('clock check failed; do not assume seasonal wall time')
    specs = json.loads((ROOT / 'data/specs.json').read_text())
    summaries, orders, coverage = [], [], []
    for sym in SYMBOLS:
        file = out / f'{sym}_M5.csv'
        if digest(file) != card['data'][sym]['sha256']:
            raise ValueError('data hash mismatch')
        raw = pd.read_csv(file)
        if raw.empty:
            raise ValueError(f'{sym}: empty history')
        raw['time'] = pd.to_datetime(raw.time, utc=True).dt.tz_localize(None)
        raw = raw[(raw.time >= START-pd.Timedelta(days=1)) & (raw.time < END)]
        parts = segments(raw)
        spec = specs[sym]
        spread = spread_price(sym, spec['tick_size'])
        commission = 7*spec['tick_size']/spec['tick_value']
        for arm in ('baseline', 'open_window'):
            seen = set()
            for number, part in enumerate(parts):
                if len(part) < 150:
                    continue
                signals, funnel = candidates(resample_complete(part, 15), arm,
                                              spread=spread, commission=commission)
                selected, excluded = [], 0
                for signal in signals:
                    close = pd.Timestamp(signal['time']) + pd.Timedelta(minutes=15)
                    if not START <= close < END:
                        continue
                    day = close.tz_localize('Europe/Helsinki').tz_convert('America/New_York').date()
                    if day in seen:
                        continue
                    seen.add(day)
                    if close + pd.Timedelta(minutes=225) > part.time.iloc[-1]:
                        excluded += 1
                        continue
                    selected.append(signal)
                coverage.append(dict(symbol=sym, arm=arm, segment=number,
                    bars=len(part), selected=len(selected), excluded_horizon=excluded,
                    first=str(part.time.iloc[0]), last=str(part.time.iloc[-1])))
                bars = {k: part[k].to_numpy() for k in ('time','open','high','low','close')}
                for path in PATHS:
                    for mult in (1., 1.5):
                        meta = dict(symbol=sym, arm=arm, path=path, cost_mult=mult)
                        rows, skipped = simulate(selected, bars, arm='fixed', path=path,
                            spread=spread*mult, commission=commission*mult,
                            signal_minutes=15, ttl_minutes=45, max_hold_minutes=180)
                        orders.extend({**meta, **row} for row in rows)
                        summaries.append({**meta, **stats(rows, len(selected), skipped)})
        print(f'{sym}: evaluated {len(parts)} continuous segments', flush=True)
    pd.DataFrame(coverage).to_csv(out / 'coverage.csv', index=False)
    pd.DataFrame(orders).to_csv(out / 'orders.csv', index=False)
    raw = pd.DataFrame(summaries)
    by = ratios(raw.groupby(['symbol','arm','path','cost_mult'], as_index=False).sum(numeric_only=True))
    by.to_csv(out / 'by_symbol.csv', index=False)
    summary = ratios(raw.groupby(['arm','path','cost_mult'], as_index=False).sum(numeric_only=True))
    summary.to_csv(out / 'summary.csv', index=False)
    decisions = []
    for arm, group in summary.groupby('arm'):
        passed = True
        for _, row in group.iterrows():
            breadth = by[(by.arm==arm)&(by.path==row.path)&(by.cost_mult==row.cost_mult)&(by.filled>=20)]
            passed &= row.filled>=100 and row.mean_net_r>0 and len(breadth)>=3 and (breadth.mean_net_r>0).sum()>len(breadth)/2
        decisions.append(dict(arm=arm, verdict='RESEARCH_SHORTLIST' if passed else 'NO_ADVANCE'))
    (out / 'decisions.json').write_text(json.dumps(decisions, indent=2)+'\n')
    print(summary[['arm','path','cost_mult','filled','mean_net_r']].to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--evaluate-only', action='store_true')
    args = ap.parse_args()
    if not args.evaluate_only:
        args.out.mkdir(parents=True, exist_ok=False)
        asyncio.run(collect(args.out))
    evaluate(args.out)


if __name__ == '__main__':
    main()
