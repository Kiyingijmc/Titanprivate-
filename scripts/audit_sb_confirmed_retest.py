#!/usr/bin/env python3
"""Audit post-confirmation order timing and decompose paired trade changes."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.sb_entry_study import digest
from scripts.sb_confirmed_retest_study import KEYS, PRIOR
from src.research.costs import spread_price


def audit(directory):
    card=json.loads((directory/'run.json').read_text())
    assert card['complete']
    for f,h in {**card['source_sha256'],**card['data']}.items(): assert digest(ROOT/f)==h,f
    for f,h in card['control_sha256'].items(): assert digest(PRIOR/f)==h,f
    orders=pd.read_csv(directory/'orders.csv')
    summary=pd.read_csv(directory/'summary.csv')
    assert len(summary)==72
    original=pd.read_csv(PRIOR/'orders.csv')
    reused=orders[orders.entry_mode!='confirmed_retest']
    pd.testing.assert_frame_equal(original,reused[original.columns].reset_index(drop=True),check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    assert not orders.outcome.isin(['MARKED_AT_END','PENDING_AT_END']).any()
    assert (orders.net_r.notna()==orders.fill_idx.notna()).all()
    assert (pd.to_datetime(orders.created)==pd.to_datetime(orders.time)+pd.Timedelta(minutes=15)).all()
    for key,g in orders.groupby(['symbol',*KEYS]):
        g=g.sort_values('created')
        created=pd.to_datetime(g.created).to_numpy()
        released=pd.to_datetime(g.release).to_numpy()
        assert (released>=created).all() and (created[1:]>=released[:-1]).all(),key
    for _,r in summary.iterrows():
        g=orders
        for k in KEYS: g=g[g[k]==r[k]]
        assert len(g)==r.orders and g.net_r.count()==r.filled
        assert np.isclose(g.net_r.sum(),r.total_net_r)
        assert r.orders==r.filled+r.expired+r.no_confirmation+r.invalidated+r.entry_invalid+r.entry_cost
    specs=json.loads((ROOT/'data/specs.json').read_text())
    new=orders[orders.entry_mode=='confirmed_retest']
    for (symbol,period),g in new.groupby(['symbol','period']):
        file=ROOT/f'data/results/sb_forward_validation_20260917/{symbol}_M5.csv' if period=='extension' else ROOT/f'data/history/{symbol}_M5.csv'
        frame=pd.read_csv(file).rename(columns={'datetime':'time'})
        times=pd.to_datetime(frame.time,utc=True).dt.tz_localize(None).to_numpy()
        spec=specs[symbol]
        for _,r in g.iterrows():
            start=int(np.searchsorted(times,np.datetime64(r.created,'ns')))
            assert (np.diff(times[start-1:start+46])==np.timedelta64(5,'m')).all()
            spread=spread_price(symbol,spec['tick_size'])*r.cost_mult
            side=1 if r.dir=='BUY' else -1
            stop=r.entry-side*r.risk
            if pd.notna(r.confirmation_close):
                available=np.datetime64(r.confirmation_close,'ns')
                k=int(np.searchsorted(times,available))-1
                observed=frame.iloc[start:k+1]
                assert times[k]+np.timedelta64(5,'m')==available
                assert np.datetime64(r.created,'ns')<available<np.datetime64(r.created,'ns')+np.timedelta64(45,'m')
                last=frame.iloc[k]
                assert side*(last.close-last.open)>0 and side*(last.close-r.entry)>0
                if side==1:
                    assert (observed.low+spread<=r.entry).any()
                    assert (observed.low>stop).all()
                    assert last.close>frame.high.iloc[k-1]
                else:
                    assert (observed.high>=r.entry).any()
                    assert (observed.high+spread<stop).all()
                    assert last.close<frame.low.iloc[k-1]
                if r.outcome=='EXPIRED':
                    assert np.datetime64(r.release)==np.datetime64(r.created)+np.timedelta64(45,'m')
            if pd.notna(r.net_r):
                assert r.risk_ratio==1. and np.isclose(r.risk,r.parent_risk)
                fill=np.datetime64(r.fill_time,'ns')
                assert available<=fill<np.datetime64(r.created,'ns')+np.timedelta64(45,'m')
                assert times[start-1+int(r.fill_idx)]==fill
                commission=7*spec['tick_size']/spec['tick_value']*r.cost_mult
                assert np.isclose(r.gross_r-r.net_r,commission/r.risk)
    changes=[]
    identity=['symbol','time','dir']
    for key,g in orders.groupby(KEYS[:-1]):
        alt=g[g.entry_mode=='confirmed_retest'].set_index(identity)
        for control in ('midpoint','confirmation'):
            base=g[g.entry_mode==control].set_index(identity)
            assert base.index.is_unique and alt.index.is_unique and set(base.index)==set(alt.index)
            if control=='midpoint':
                aligned=base.reindex(alt.index)
                assert np.allclose(alt.entry,aligned.entry) and np.allclose(alt.risk,aligned.risk)
            b=base[base.net_r.notna()]
            a=alt[alt.net_r.notna()]
            shared=b.index.intersection(a.index)
            added=a.index.difference(b.index)
            lost=b.index.difference(a.index)
            shared_delta=a.loc[shared].net_r.sum()-b.loc[shared].net_r.sum()
            added_r=a.loc[added].net_r.sum()
            lost_r=b.loc[lost].net_r.sum()
            delta=a.net_r.sum()-b.net_r.sum()
            assert np.isclose(delta,shared_delta+added_r-lost_r)
            common=b.net_r*b.risk_ratio.fillna(1.)
            changes.append(dict(zip(KEYS[:-1],key),control=control,parents=len(base),
                control_fills=len(b),retest_fills=len(a),shared_fills=len(shared),added_fills=len(added),lost_fills=len(lost),
                added_net_r=added_r,lost_control_net_r=lost_r,shared_net_r_change=shared_delta,total_net_r_change=delta,
                control_total_parent_r=common.sum(),retest_total_parent_r=a.net_r.sum(),
                control_mean_parent_r=common.mean(),retest_mean_parent_r=a.net_r.mean()))
    pd.DataFrame(changes).to_csv(directory/'paired.csv',index=False)
    result=dict(verified=True,order_rows=len(orders),new_retest_rows=len(new),scenario_cells=len(summary),
                reused_control_rows=len(reused),checked_hashes=len(card['source_sha256'])+len(card['data'])+len(card['control_sha256']),
                audit_script_sha256=digest(Path(__file__)),
                artifact_sha256={f:digest(directory/f) for f in ('orders.csv','summary.csv','by_symbol.csv','paired.csv','run.json','decisions.json')})
    (directory/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    audit(ap.parse_args().directory)
