#!/usr/bin/env python3
"""Frozen exploratory SB variant screen. No production configuration imports."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.sb_variants import TIMEFRAMES, VARIANTS, WINDOWS, resample_complete, collect
from src.research.sb_execution import simulate, PATHS
from src.research.costs import spread_price
from src.utils.instrument import InstrumentHelper

SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'GBPJPY', 'XAUUSD', 'US30', 'BTCUSD']
KEYS = ['variant', 'timeframe', 'window', 'exit', 'path', 'cost_mult', 'period']


def stats(rows, candidates, skipped):
    filled = [r for r in rows if r['net_r'] is not None]
    returns = np.array([r['net_r'] for r in filled])
    return dict(candidates=candidates, orders=len(rows), filled=len(filled), skipped=skipped,
                expired=sum(r['outcome'] == 'EXPIRED' for r in rows),
                pending=sum(r['outcome'] == 'PENDING_AT_END' for r in rows),
                marked=sum(r['outcome'] == 'MARKED_AT_END' for r in rows),
                time_exits=sum(r['outcome'] == 'TIME_EXIT' for r in rows),
                total_net_r=float(returns.sum()), gains=float(returns[returns>0].sum()),
                losses=float(-returns[returns<0].sum()), wins=int((returns>0).sum()))


def ratios(df):
    df = df.copy()
    df['mean_net_r'] = df.total_net_r / df.filled.replace(0, np.nan)
    df['pf'] = df.gains / df.losses.replace(0, np.nan)
    df['win_rate'] = df.wins / df.filled.replace(0, np.nan)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--symbols', nargs='+', choices=SYMBOLS, default=SYMBOLS)
    ap.add_argument('--broker-offset', type=int, choices=(2, 3), default=2)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    sources = ['scripts/sb_variant_study.py', 'src/research/sb_variants.py',
               'src/research/sb_execution.py', 'src/research/costs.py',
               'src/utils/instrument.py', 'data/specs.json',
               'docs/research/2026-09-16-sb-variant-design.md']
    card = dict(complete=False, symbols=args.symbols, broker_offset=args.broker_offset,
                models=60, purpose='exploratory historical screen; NOT fresh holdout or live GO',
                source_sha256={s: hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources},
                data={}, funnel=[])
    runpath = args.out/'run.json'
    runpath.write_text(json.dumps(card, indent=2)+'\n')
    specs = json.loads((ROOT/'data/specs.json').read_text())
    summaries = []
    wrote_orders = False
    for sym in args.symbols:
        file = ROOT/f'data/history/{sym}_M5.csv'
        source = pd.read_csv(file).rename(columns={'datetime': 'time'})
        source['time'] = pd.to_datetime(source.time)
        tick, value = (float(specs[sym][k]) for k in ('tick_size', 'tick_value'))
        if not all(np.isfinite(x) and x > 0 for x in (tick, value)):
            raise ValueError(f'invalid specs: {sym}')
        spread, commission = spread_price(sym, tick), 7*tick/value
        card['data'][sym] = dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                                first=str(source.time.iloc[0]), last=str(source.time.iloc[-1]),
                                spread=spread, commission=commission)
        partitions = {}
        for period, mask in [('early', source.time < '2025-01-01'),
                             ('late', source.time >= '2025-01-08')]:
            part = source[mask]
            partitions[period] = {k: part[k].to_numpy() for k in ('time', 'open', 'high', 'low', 'close')}
        for tf, minutes in TIMEFRAMES.items():
            frame = resample_complete(source, minutes)
            for variant in VARIANTS:
                for window in WINDOWS:
                    signals, counts = collect(frame, minutes, variant, window,
                                              spread=spread, commission=commission,
                                              broker_offset=args.broker_offset)
                    card['funnel'].append(dict(symbol=sym, timeframe=tf, variant=variant, window=window, **counts))
                    for period, bars in partitions.items():
                        selected = [s for s in signals if
                                    bars['time'][0] <= np.datetime64(s['time']) + np.timedelta64(minutes, 'm')
                                    <= bars['time'][-1]]
                        for arm in ('fixed', 'runner'):
                            for path in PATHS:
                                for mult in (1., 1.5):
                                    meta = dict(symbol=sym, variant=variant, timeframe=tf,
                                                window=window, exit=arm, path=path,
                                                cost_mult=mult, period=period)
                                    rows, skipped = simulate(selected, bars, arm=arm, path=path,
                                        spread=mult*spread, commission=mult*commission,
                                        be_buffer=3*InstrumentHelper.get_pip_size(sym),
                                        signal_minutes=minutes, ttl_minutes=3*minutes,
                                        max_hold_minutes=12*minutes)
                                    summaries.append({**meta, **stats(rows, len(selected), skipped)})
                                    if rows:
                                        pd.DataFrame([{**meta, **r} for r in rows]).to_csv(
                                            args.out/'orders.csv', mode='a', header=not wrote_orders, index=False)
                                        wrote_orders = True
            print(f'{sym} {tf}: complete', flush=True)
        runpath.write_text(json.dumps(card, indent=2)+'\n')
    raw = pd.DataFrame(summaries)
    by_symbol = ratios(raw)
    by_symbol.to_csv(args.out/'by_symbol.csv', index=False)
    pooled = ratios(raw.groupby(KEYS, as_index=False).sum(numeric_only=True))
    pooled.to_csv(args.out/'summary.csv', index=False)
    decisions = []
    for keys, group in pooled.groupby(['variant', 'timeframe', 'window', 'exit']):
        variant, tf, window, arm = keys
        failures = []
        for _, row in group.iterrows():
            label = f'{row.period}/{row.path}/{row.cost_mult}x'
            floor = 150 if row.period == 'early' else 100
            if row.filled < floor:
                failures.append(label+': insufficient fills')
            if not np.isfinite(row.mean_net_r) or row.mean_net_r <= 0:
                failures.append(label+': nonpositive mean')
            if row.period == 'late':
                sub = by_symbol[(by_symbol.variant==variant)&(by_symbol.timeframe==tf)
                    &(by_symbol.window==window)&(by_symbol.exit==arm)&(by_symbol.period=='late')
                    &(by_symbol.path==row.path)&(by_symbol.cost_mult==row.cost_mult)&(by_symbol.filled>=20)]
                if len(sub)<3 or (sub.mean_net_r>0).sum() <= len(sub)/2:
                    failures.append(label+': insufficient positive breadth')
        decisions.append(dict(variant=variant, timeframe=tf, window=window, exit=arm,
                              verdict='RESEARCH_SHORTLIST' if not failures else 'NO_ADVANCE',
                              failures='; '.join(failures)))
    decisions = pd.DataFrame(decisions)
    decisions.to_csv(args.out/'decisions.csv', index=False)
    card['complete'] = True
    card['shortlisted'] = int((decisions.verdict=='RESEARCH_SHORTLIST').sum())
    runpath.write_text(json.dumps(card, indent=2)+'\n')
    print(decisions[['variant','timeframe','window','exit','verdict']].to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
