#!/usr/bin/env python3
"""Audit the entry experiment and decompose changes in its admitted fills."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def require(ok,message):
    if not ok:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def analyze(directory):
    card=json.loads((directory/'run.json').read_text())
    require(card.get('complete') is True,'run incomplete')
    for name,h in card['source_sha256'].items():
        require(digest(ROOT/name)==h,f'source changed: {name}')
    for sym,meta in card['data'].items():
        require(digest(ROOT/f'data/history/{sym}_M5.csv')==meta['sha256'],f'data changed: {sym}')
    orders=pd.read_csv(directory/'orders.csv')
    summary=pd.read_csv(directory/'summary.csv')
    by_symbol=pd.read_csv(directory/'by_symbol.csv')
    keys=['arm','period','path','cost_mult']
    require(len(summary)==len(card['arms'])*8,'missing scenario cells')
    require((orders.risk>0).all() and np.isfinite(orders.risk).all(),'invalid risk')
    require((orders.net_r.notna()==orders.fill_idx.notna()).all(),'fill/P&L mismatch')
    filled=orders[orders.net_r.notna()]
    commission=filled.apply(lambda x:card['data'][x.symbol]['commission']*x.cost_mult/x.risk,axis=1)
    require(np.allclose(filled.gross_r-filled.net_r,commission,atol=1e-9),'commission mismatch')
    require((pd.to_datetime(orders.created)==pd.to_datetime(orders.time)+pd.Timedelta(minutes=15)).all(),
            'incorrect signal availability')
    for key,group in orders.groupby(['symbol',*keys]):
        group=group.sort_values('created')
        a,b=pd.to_datetime(group.created).to_numpy(),pd.to_datetime(group.release).to_numpy()
        require((b>=a).all() and (a[1:]>=b[:-1]).all(),f'overlap in {key}')
    for _,row in summary.iterrows():
        x=orders
        for k in keys:
            x=x[x[k]==row[k]]
        require(len(x)==row.orders and x.net_r.notna().sum()==row.filled,'count mismatch')
        require(np.isclose(x.net_r.sum(),row.total_net_r),'return mismatch')
        require(row.candidates==row.orders+row.skipped,'admission mismatch')
        require(row.orders==row.filled+row.expired+row.pending,'outcome mismatch')
    pooled=by_symbol.groupby(keys).sum(numeric_only=True).sort_index()
    reported=summary.set_index(keys).sort_index()
    for field in ('filled','orders','total_net_r','gains','losses','marked'):
        require(np.allclose(pooled[field],reported[field],atol=1e-9),f'pool mismatch: {field}')

    # This is a bookkeeping decomposition, not causal attribution or a
    # paired statistical test. Each policy schedules its own order stream.
    identity=['symbol','time','dir']
    changes=[]
    for (period,path,mult),context in orders.groupby(['period','path','cost_mult']):
        base=context[(context.arm=='baseline')&context.net_r.notna()].set_index(identity)
        require(base.index.is_unique,'duplicate baseline fill')
        for arm in card['arms']:
            if arm=='baseline':
                continue
            other=context[(context.arm==arm)&context.net_r.notna()].set_index(identity)
            require(other.index.is_unique,'duplicate alternate fill')
            shared=base.index.intersection(other.index)
            added=other.index.difference(base.index)
            lost=base.index.difference(other.index)
            shared_delta=other.loc[shared].net_r.sum()-base.loc[shared].net_r.sum()
            added_r=other.loc[added].net_r.sum()
            lost_r=base.loc[lost].net_r.sum()
            delta=other.net_r.sum()-base.net_r.sum()
            require(np.isclose(shared_delta+added_r-lost_r,delta),'incremental identity mismatch')
            changes.append(dict(arm=arm,period=period,path=path,cost_mult=mult,
                baseline_fills=len(base),arm_fills=len(other),shared_fills=len(shared),
                added_fills=len(added),lost_fills=len(lost),added_total_r=added_r,
                added_mean_r=added_r/len(added) if len(added) else None,
                lost_baseline_total_r=lost_r,shared_total_r_change=shared_delta,total_r_change=delta))
    pd.DataFrame(changes).to_csv(directory/'incremental.csv',index=False)
    result=dict(verified=True,order_rows=len(orders),scenario_cells=len(summary),
                baseline_reproduced_rows=card['baseline_reproduced_rows'],
                source_and_data_hashes=len(card['source_sha256'])+len(card['data']),
                artifact_sha256={name:digest(directory/name) for name in
                    ('orders.csv','summary.csv','by_symbol.csv','decisions.csv','run.json','incremental.csv')})
    (directory/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    print(json.dumps(analyze(parser.parse_args().directory),indent=2))
