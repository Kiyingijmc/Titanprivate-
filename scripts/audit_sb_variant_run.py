#!/usr/bin/env python3
"""Independently check study provenance, schedule occupancy and R accounting."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KEYS = ['symbol', 'variant', 'timeframe', 'window', 'exit', 'path', 'cost_mult', 'period']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit(directory):
    card = json.loads((directory/'run.json').read_text())
    require(card.get('complete') is True, 'run incomplete')
    for name, value in card['source_sha256'].items():
        require(digest(ROOT/name) == value, f'source changed: {name}')
    for sym, meta in card['data'].items():
        require(digest(ROOT/f'data/history/{sym}_M5.csv') == meta['sha256'], f'history changed: {sym}')
    totals, releases, count = {}, {}, 0
    for chunk in pd.read_csv(directory/'orders.csv', chunksize=100000):
        count += len(chunk)
        require((chunk.risk > 0).all(), 'invalid risk')
        require(np.isfinite(chunk.risk).all(), 'nonfinite risk')
        filled = chunk.fill_idx.notna()
        require((filled == chunk.net_r.notna()).all(), 'fill/P&L mismatch')
        require((filled == chunk.gross_r.notna()).all(), 'fill/gross mismatch')
        x = chunk[filled]
        expected = x.apply(lambda row: card['data'][row.symbol]['commission']*row.cost_mult/row.risk, axis=1)
        require(np.allclose(x.gross_r-x.net_r, expected, rtol=1e-8, atol=1e-9), 'commission accounting mismatch')
        created = pd.to_datetime(chunk.created)
        release = pd.to_datetime(chunk.release)
        require((release >= created).all(), 'negative order duration')
        minutes = chunk.timeframe.map({'M5':5, 'M15':15, 'M30':30, 'H1':60, 'H2':120})
        require((created == pd.to_datetime(chunk.time)+pd.to_timedelta(minutes, unit='m')).all(), 'signal close mismatch')
        for key, group in chunk.groupby(KEYS, sort=False):
            starts, ends = pd.to_datetime(group.created), pd.to_datetime(group.release)
            require(starts.is_monotonic_increasing, f'unordered schedule: {key}')
            require((starts.to_numpy()[1:] >= ends.to_numpy()[:-1]).all(), f'overlap: {key}')
            if key in releases:
                require(starts.iloc[0] >= releases[key], f'cross-chunk overlap: {key}')
            releases[key] = ends.iloc[-1]
            v = totals.setdefault(key, dict(orders=0, filled=0, total_net_r=0., gains=0., losses=0.,
                                           marked=0, expired=0, pending=0, time_exits=0, wins=0))
            ret = group.net_r.dropna()
            for field, value in dict(orders=len(group), filled=len(ret), total_net_r=ret.sum(),
                gains=ret[ret>0].sum(), losses=-ret[ret<0].sum(), wins=(ret>0).sum(),
                marked=(group.outcome=='MARKED_AT_END').sum(), expired=(group.outcome=='EXPIRED').sum(),
                pending=(group.outcome=='PENDING_AT_END').sum(), time_exits=(group.outcome=='TIME_EXIT').sum()).items():
                v[field] += value
    symbols = pd.read_csv(directory/'by_symbol.csv')
    for _, row in symbols.iterrows():
        key = tuple(row[k] for k in KEYS)
        values = totals.get(key, {'orders':0, 'filled':0, 'total_net_r':0.})
        for field, value in values.items():
            require(math.isclose(value, row[field], abs_tol=1e-7, rel_tol=1e-9), f'summary mismatch {key}/{field}')
        require(row.candidates == row.orders+row.skipped, f'admission mismatch: {key}')
        require(row.orders == row.filled+row.expired+row.pending, f'outcome mismatch: {key}')
    pooled = pd.read_csv(directory/'summary.csv').set_index(KEYS[1:]).sort_index()
    summed = symbols.groupby(KEYS[1:]).sum(numeric_only=True).sort_index()
    for field in ('filled', 'orders', 'total_net_r', 'gains', 'losses', 'wins', 'marked'):
        require(np.allclose(pooled[field], summed[field], atol=1e-7), f'pooled mismatch: {field}')
    require(len(pooled) == card['models']*8, 'missing path/cost/period cells')
    return dict(verified=True, rows=count, nonempty_schedules=len(totals), pooled_cells=len(pooled),
                artifact_sha256={name:digest(directory/name) for name in
                                 ('orders.csv','summary.csv','by_symbol.csv','decisions.csv','run.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    (args.directory/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
