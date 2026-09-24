#!/usr/bin/env python3
"""Frozen M15 sweep/reclaim clock and supplemental-data validation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.sb_sessions import CLOCKS, select_ny, assemble_snapshots
from src.research.sb_variants import collect, resample_complete
from src.research.sb_execution import simulate, PATHS
from src.research.costs import spread_price
from src.utils.instrument import InstrumentHelper
from scripts.sb_variant_study import SYMBOLS, stats, ratios


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def summarize(rows, n, skipped):
    closed = [r['net_r'] for r in rows if r['net_r'] is not None and r['outcome'] != 'MARKED_AT_END']
    return {**stats(rows, n, skipped), 'closed_fills':len(closed), 'closed_net_r':sum(closed)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    sources = ['scripts/sb_session_validation.py', 'scripts/sb_variant_study.py',
               'src/research/sb_sessions.py', 'src/research/sb_variants.py',
               'src/research/sb_execution.py', 'src/research/costs.py',
               'src/utils/instrument.py', 'data/specs.json',
               'docs/research/2026-09-17-sb-session-validation-design.md']
    card = dict(complete=False, purpose='post-selection clock/supplemental diagnostic; no promotion',
                source_sha256={p:digest(ROOT/p) for p in sources}, inputs={}, inventory={})
    specs = json.loads((ROOT/'data/specs.json').read_text())
    output, summaries = [], []

    def evaluate(sym, period, clock, segment, signals, frame, spread, commission):
        bars = {k:frame[k].to_numpy() for k in ['time','open','high','low','close']}
        for arm in ('fixed','runner'):
            for path in PATHS:
                for mult in (1.,1.5):
                    meta = dict(symbol=sym, period=period, clock=clock, segment=segment,
                                exit=arm, path=path, cost_mult=mult)
                    rows, skipped = simulate(signals, bars, arm=arm, path=path,
                        spread=spread*mult, commission=commission*mult,
                        be_buffer=3*InstrumentHelper.get_pip_size(sym),
                        signal_minutes=15, ttl_minutes=45, max_hold_minutes=180)
                    output.extend({**meta, **row} for row in rows)
                    summaries.append({**meta, **summarize(rows,len(signals),skipped)})

    for sym in SYMBOLS:
        file = ROOT/f'data/history/{sym}_M5.csv'
        card['inputs'][str(file.relative_to(ROOT))] = digest(file)
        source = pd.read_csv(file).rename(columns={'datetime':'time'})
        source['time'] = pd.to_datetime(source.time)
        spec = specs[sym]
        spread = spread_price(sym,spec['tick_size'])
        commission = 7*spec['tick_size']/spec['tick_value']
        candles = resample_complete(source,15)
        raw, _ = collect(candles,15,'sweep_reclaim','all_hours',spread=spread,commission=commission)
        for clock in CLOCKS:
            signals = select_ny(raw,15,clock)
            for period, mask in [('early',source.time<'2025-01-01'),('late',source.time>='2025-01-08')]:
                part = source[mask]
                eligible = [s for s in signals if part.time.iloc[0] <= pd.Timestamp(s['time'])+pd.Timedelta(minutes=15) <= part.time.iloc[-1]]
                evaluate(sym,period,clock,0,eligible,part,spread,commission)
        snapshots = sorted((ROOT/'data/journal/warmup').glob(f'*/{sym}_M5.csv'))
        for snapshot in snapshots:
            card['inputs'][str(snapshot.relative_to(ROOT))] = digest(snapshot)
        segments, inventory = assemble_snapshots(snapshots,source.time.max())
        inventory['first'] = str(segments[0].time.iloc[0]) if segments else None
        inventory['last'] = str(segments[-1].time.iloc[-1]) if segments else None
        inventory['long_segments'] = 0
        seen = set()
        for segment, part in enumerate(segments):
            if len(part) < 153:
                continue  # cannot supply >=51 complete M15 candles
            candles = resample_complete(part,15)
            if len(candles) <= 50:
                continue
            inventory['long_segments'] += 1
            raw, _ = collect(candles,15,'sweep_reclaim','all_hours',spread=spread,commission=commission)
            signals = select_ny(raw,15,'seasonal_eet',seen)
            # Need an execution bar at/after signal availability. Last closed
            # TF bar may have no later quote; retain it as pending-at-end.
            evaluate(sym,'supplemental','seasonal_eet',segment,signals,part,spread,commission)
        card['inventory'][sym] = inventory
        print(f'{sym}: clocks complete; {inventory["unique_bars"]} supplemental bars, {inventory["long_segments"]} usable segments',flush=True)
        (args.out/'run.json').write_text(json.dumps(card,indent=2)+'\n')

    orders = pd.DataFrame(output)
    orders.to_csv(args.out/'orders.csv',index=False)
    raw = pd.DataFrame(summaries)
    raw.to_csv(args.out/'schedules.csv',index=False)
    groupkeys = ['period','clock','exit','path','cost_mult']
    for filename, keys in [('summary.csv',groupkeys),('by_symbol.csv',['symbol',*groupkeys])]:
        df = ratios(raw.drop(columns='segment').groupby(keys,as_index=False).sum(numeric_only=True))
        df['closed_mean_net_r'] = df.closed_net_r/df.closed_fills.replace(0,np.nan)
        df.to_csv(args.out/filename,index=False)

    old = pd.read_csv(ROOT/'data/results/sb_variants_20260916/orders.csv')
    old = old[(old.variant=='sweep_reclaim')&(old.timeframe=='M15')&(old.window=='ny_am')]
    common = [c for c in orders if c not in ('clock','segment')]
    sort = ['symbol','period','exit','path','cost_mult','created']
    a = old[common].sort_values(sort).reset_index(drop=True)
    b = orders[orders.clock=='fixed_2'][common].sort_values(sort).reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    card['baseline_reproduced_rows'] = len(a)
    card['complete'] = True
    (args.out/'run.json').write_text(json.dumps(card,indent=2)+'\n')
    print(pd.read_csv(args.out/'summary.csv').to_string(index=False),flush=True)


if __name__ == '__main__':
    main()
