#!/usr/bin/env python3
"""Independent accounting checks for parent opportunity/stability diagnostics."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.sb_entry_study import digest
from scripts.sb_confirmed_retest_study import PRIOR
from src.research.sb_sessions import utc_from_broker


def audit(directory):
    card=json.loads((directory/'run.json').read_text())
    assert card['complete']
    for f,h in {**card['source_sha256'],**card['data']}.items(): assert digest(ROOT/f)==h,f
    for f,h in card['artifact_sha256'].items(): assert digest(directory/f)==h,f
    assert digest(PRIOR/'orders.csv')==card['control_sha256']
    orders=pd.read_csv(PRIOR/'orders.csv')
    orders=orders[orders.entry_mode=='midpoint'].copy()
    reference=orders[(orders.path=='OHLC')&(orders.cost_mult==1)].copy()
    reconstructed=pd.read_csv(directory/'parents.csv')
    keys=['symbol','period','window','time','dir']
    for frame in (reference,reconstructed): frame['time']=pd.to_datetime(frame.time)
    pd.testing.assert_frame_equal(reference[keys+['entry','risk']].sort_values(keys).reset_index(drop=True),reconstructed[keys+['entry','risk']].sort_values(keys).reset_index(drop=True),check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    by=pd.read_csv(directory/'funnel_by_symbol.csv')
    pooled=pd.read_csv(directory/'funnel.csv')
    pd.testing.assert_frame_equal(by.groupby(['period','window'],as_index=False).sum(numeric_only=True),pooled,check_dtype=False)
    stages=['warmed_closes','fvg','displacement_geometry','sweep_reclaim','in_window','cost_eligible','daily_cap','covered_parent','filled']
    assert all((by[a]>=by[b]).all() for a,b in zip(stages,stages[1:]))
    for _,r in by.iterrows():
        subset=reference[(reference.symbol==r.symbol)&(reference.window==r.window)&(reference.period==r.period)]
        assert len(subset)==r.covered_parent and subset.net_r.count()==r.filled
    groups=['period','window','path','cost_mult']
    orders['quarter']=utc_from_broker(pd.DatetimeIndex(pd.to_datetime(orders.created)),'seasonal_eet').tz_convert('America/New_York').tz_localize(None).to_period('Q').astype(str)
    for axis in ('symbol','quarter','dir'):
        result=pd.read_csv(directory/f'by_{axis}.csv')
        for _,r in result.iterrows():
            subset=orders
            for k in [*groups,axis]: subset=subset[subset[k]==r[k]]
            assert len(subset)==r.orders and subset.net_r.count()==r.filled
            assert np.isclose(subset.net_r.sum(),r.total_net_r)
            assert np.isclose(subset.net_r.mean(),r.mean_net_r,equal_nan=True)
    sensitivity=pd.read_csv(directory/'sensitivity.csv')
    for _,r in sensitivity.iterrows():
        subset=orders
        for k in groups: subset=subset[subset[k]==r[k]]
        if r.excluded=='TOP_5_GAINS':
            values=sorted(subset.net_r.dropna())
            removed=0
            while values and values[-1]>0 and removed<5:
                values.pop()
                removed+=1
            returns=pd.Series(values,dtype=float)
        else:
            returns=subset[subset.symbol!=r.excluded].net_r.dropna()
        assert len(returns)==r.filled and np.isclose(returns.sum(),r.total_net_r)
        assert np.isclose(returns.mean(),r.mean_net_r,equal_nan=True)
    intervals=pd.read_csv(directory/'weekly_intervals.csv')
    assert len(intervals)==24
    for _,r in intervals.iterrows():
        subset=orders
        for k in groups: subset=subset[subset[k]==r[k]]
        assert np.isclose(subset.net_r.mean(),r.mean_net_r)
        assert r.ci_low<=r.ci_high and 0<r.bootstrap_valid<=2000
    result=dict(verified=True,reconciled_parents=len(reference),scenario_rows=len(orders),
                funnel_cells=len(pooled),uncertainty_cells=len(intervals),
                source_data_hashes=len(card['source_sha256'])+len(card['data']),
                audit_script_sha256=digest(Path(__file__)),run_sha256=digest(directory/'run.json'))
    (directory/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    audit(ap.parse_args().directory)
