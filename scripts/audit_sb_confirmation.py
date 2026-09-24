#!/usr/bin/env python3
"""Verify confirmation accounting and paired missed/added trade decomposition."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.sb_entry_study import digest


def analyze(directory):
    card=json.loads((directory/'run.json').read_text())
    assert card['complete']
    for f,h in {**card['source_sha256'],**card['data']}.items(): assert digest(ROOT/f)==h,f
    orders=pd.read_csv(directory/'orders.csv')
    summary=pd.read_csv(directory/'summary.csv')
    keys=['period','window','path','cost_mult','entry_mode']
    assert len(summary)==48
    assert not orders.outcome.isin(['MARKED_AT_END','PENDING_AT_END']).any()
    assert (orders.net_r.notna()==orders.fill_idx.notna()).all()
    assert (pd.to_datetime(orders.created)==pd.to_datetime(orders.time)+pd.Timedelta(minutes=15)).all()
    # Independently verify source coverage and the executable next-open price.
    for (symbol, period), group in orders.groupby(['symbol','period']):
        source=(ROOT/f'data/results/sb_forward_validation_20260917/{symbol}_M5.csv'
                if period=='extension' else ROOT/f'data/history/{symbol}_M5.csv')
        frame=pd.read_csv(source).rename(columns={'datetime':'time'})
        times=pd.to_datetime(frame.time,utc=True).dt.tz_localize(None).to_numpy()
        for _, row in group.iterrows():
            created=np.datetime64(row.created,'ns')
            start=int(np.searchsorted(times,created))
            covered=times[start:start+46]
            assert len(covered)==46 and covered[0]==created
            assert (np.diff(covered)==np.timedelta64(5,'m')).all()
            if row.entry_mode=='confirmation' and pd.notna(row.net_r):
                when=np.datetime64(row.confirmation_close,'ns')
                index=int(np.searchsorted(times,when))
                assert times[index]==when
                from src.research.costs import spread_price
                spec=json.loads((ROOT/'data/specs.json').read_text())[symbol]
                spread=spread_price(symbol,spec['tick_size'])*row.cost_mult
                expected=frame.open.iloc[index]+(spread if row.dir=='BUY' else 0.)
                assert np.isclose(row.entry,expected,rtol=1e-12,atol=1e-12)
    specs=json.loads((ROOT/'data/specs.json').read_text())
    filled=orders[orders.net_r.notna()]
    commission=filled.apply(lambda r:7*specs[r.symbol]['tick_size']/specs[r.symbol]['tick_value']*r.cost_mult/r.risk,axis=1)
    assert np.allclose(filled.gross_r-filled.net_r,commission,atol=1e-10)
    for key,g in orders.groupby(['symbol',*keys]):
        g=g.sort_values('created')
        created=pd.to_datetime(g.created).to_numpy()
        released=pd.to_datetime(g.release).to_numpy()
        assert (released>=created).all() and (created[1:]>=released[:-1]).all(),key
    for _,r in summary.iterrows():
        subset=orders
        for k in keys: subset=subset[subset[k]==r[k]]
        assert len(subset)==r.orders and subset.net_r.count()==r.filled
        assert np.isclose(subset.net_r.sum(),r.total_net_r)
        assert r.candidates==r.orders+r.skipped
        assert r.orders==r.filled+r.expired+r.no_confirmation+r.invalidated+r.entry_invalid+r.entry_cost
    paired=[]
    identity=['symbol','time','dir']
    for key,g in orders.groupby(['period','window','path','cost_mult']):
        base=g[g.entry_mode=='midpoint'].set_index(identity)
        alt=g[g.entry_mode=='confirmation'].set_index(identity)
        assert base.index.is_unique and alt.index.is_unique
        assert set(base.index)==set(alt.index)
        basefill=base[base.net_r.notna()]
        altfill=alt[alt.net_r.notna()]
        shared=basefill.index.intersection(altfill.index)
        added=altfill.index.difference(basefill.index)
        lost=basefill.index.difference(altfill.index)
        # Same absolute stop, despite different executable entry and R scale.
        aligned=base.reindex(altfill.index)
        side=np.where(altfill.dir=='BUY',1.,-1.) if 'dir' in altfill else np.array([1. if i[2]=='BUY' else -1. for i in altfill.index])
        assert np.allclose(altfill.entry-side*altfill.risk,aligned.entry-side*aligned.risk)
        assert np.allclose(altfill.risk/altfill.parent_risk,altfill.risk_ratio)
        delay=pd.to_datetime(altfill.confirmation_close)-pd.to_datetime(altfill.created)
        assert (delay>=pd.Timedelta(minutes=5)).all() and (delay<pd.Timedelta(minutes=45)).all()
        added_r=altfill.loc[added].net_r.sum()
        lost_r=basefill.loc[lost].net_r.sum()
        shared_delta=altfill.loc[shared].net_r.sum()-basefill.loc[shared].net_r.sum()
        delta=altfill.net_r.sum()-basefill.net_r.sum()
        assert np.isclose(delta,added_r-lost_r+shared_delta)
        common=altfill.net_r*altfill.risk_ratio
        paired.append(dict(zip(['period','window','path','cost_mult'],key),
            parents=len(base),baseline_fills=len(basefill),confirmation_fills=len(altfill),
            shared_fills=len(shared),added_fills=len(added),lost_fills=len(lost),
            added_net_r=added_r,lost_baseline_net_r=lost_r,shared_net_r_change=shared_delta,
            total_net_r_change=delta,mean_risk_ratio=altfill.risk_ratio.mean(),
            confirmation_mean_parent_r=common.mean(),confirmation_total_parent_r=common.sum(),
            midpoint_mean_parent_r=basefill.net_r.mean(),midpoint_total_parent_r=basefill.net_r.sum()))
    pd.DataFrame(paired).to_csv(directory/'paired.csv',index=False)
    audit=dict(verified=True,order_rows=len(orders),scenario_cells=len(summary),
               checked_hashes=len(card['source_sha256'])+len(card['data']),
               extension_control_rows=card['extension_control_rows'],
               audit_script_sha256=digest(Path(__file__)),
               artifact_sha256={f:digest(directory/f) for f in ['orders.csv','summary.csv','paired.csv','decisions.json','run.json']})
    (directory/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(audit,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    analyze(ap.parse_args().directory)
