#!/usr/bin/env python3
"""Controlled exit-only diagnostic; no broker access or deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.poc_sb_stops import collect_signals
from scripts.sb_component_diagnostic import select_signals
from src.research.sb_execution import simulate, PATHS
from src.research.structure_execution import ContextCache
from src.research.costs import spread_price
from src.utils.instrument import InstrumentHelper


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--symbols', nargs='+', default=['EURUSD', 'USDJPY', 'XAUUSD'])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--quick', action='store_true', help='Last 30,000 source M5 bars only')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    specs = json.loads((ROOT/'data/specs.json').read_text())
    sources = ['src/analysis/structure_management.py', 'src/research/structure_execution.py',
               'src/research/sb_execution.py', 'scripts/structure_exit_study.py',
               'scripts/poc_sb_stops.py', 'scripts/sb_component_diagnostic.py',
               'src/research/costs.py', 'data/specs.json']
    card = dict(quick=a.quick, sources={f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources},
                data={}, assumptions=['Legacy H1 bias-and-grade collector, unchanged across arms',
                'Constant spread, $7/lot round-turn commission; spread in executable prices',
                'Two assumed M5 paths are sensitivity cases, not bounds',
                'Immediate software execution, continuous volume; no latency, swap, stop-level or lot rounding',
                'Each arm schedules its own one-order occupancy; not paired trades',
                'M15 uses closed bars only; swings require two following closed M15 bars',
                'No fresh holdout; diagnostic only; no parameter search'])
    rows = []
    for sym in a.symbols:
        path = ROOT/f'data/history/{sym}_M5.csv'
        df = pd.read_csv(path)
        if a.quick:
            df = df.tail(30000)
        bars = {key: df[key].to_numpy(float) for key in ['open', 'high', 'low', 'close']}
        bars['time'] = pd.to_datetime(df.datetime).to_numpy(dtype='datetime64[ns]')
        signals, _ = collect_signals(sym, quick=a.quick, tf='H1')
        signals = select_signals(signals, 'bias_and_grade')
        tick, value = specs[sym]['tick_size'], specs[sym]['tick_value']
        spread = spread_price(sym, tick)
        cache = ContextCache(bars)
        card['data'][sym] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                first=str(bars['time'][0]), last=str(bars['time'][-1]),
                                bars=len(df), candidates=len(signals), spread=spread)
        for arm in ['tight_runner', 'structure']:
            for ordering in PATHS:
                result, skipped = simulate(signals, bars, arm=arm, path=ordering, spread=spread,
                    commission=7/value*tick, be_buffer=3*InstrumentHelper.get_pip_size(sym),
                    structure_contexts=cache, tick_size=tick)
                rows.extend(dict(symbol=sym, arm=arm, path=ordering, **r) for r in result)
                card['data'][sym][arm+'_'+ordering+'_busy'] = skipped
                print(sym, arm, ordering, len(result), flush=True)
        (a.out/'run.json').write_text(json.dumps(card, indent=2)+'\n')
    frame = pd.DataFrame(rows)
    frame.to_csv(a.out/'orders.csv', index=False)
    summary = frame.groupby(['symbol','arm','path']).agg(orders=('outcome','size'),
        filled=('net_r','count'), mean_net_r=('net_r','mean'), total_net_r=('net_r','sum'))
    summary.to_csv(a.out/'summary.csv')
    card['complete'] = True
    (a.out/'run.json').write_text(json.dumps(card, indent=2)+'\n')
    print(summary.to_string(), flush=True)

if __name__ == '__main__':
    main()
