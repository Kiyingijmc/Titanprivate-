#!/usr/bin/env python3
"""Audit completed-range causality, structural risk and scenario accounting."""
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
from src.research.sb_variants import resample_complete
from src.research.costs import spread_price


def audit(directory):
    card=json.loads((directory/'run.json').read_text())
    assert card['complete']
    for f,h in {**card['source_sha256'],**card['data']}.items(): assert digest(ROOT/f)==h,f
    for f,h in card['artifact_sha256'].items(): assert digest(directory/f)==h,f
    assert digest(PRIOR/'orders.csv')==card['control_sha256']
    orders=pd.read_csv(directory/'orders.csv')
    parents=pd.read_csv(directory/'parents.csv')
    summary=pd.read_csv(directory/'summary.csv')
    assert len(summary)==24
    original=pd.read_csv(PRIOR/'orders.csv')
    original=original[(original.entry_mode=='midpoint')&(original.window=='open_window')].reset_index(drop=True)
    reused=orders[orders.parent_mode=='rolling_control'].reset_index(drop=True)
    pd.testing.assert_frame_equal(original,reused[original.columns],check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    assert not orders.outcome.isin(['MARKED_AT_END','PENDING_AT_END']).any()
    assert (orders.net_r.notna()==orders.fill_idx.notna()).all()
    keys=['period','path','cost_mult','parent_mode']
    for _,r in summary.iterrows():
        g=orders
        for k in keys: g=g[g[k]==r[k]]
        assert len(g)==r.orders and g.net_r.count()==r.filled
        assert np.isclose(g.net_r.sum(),r.total_net_r)
        assert r.orders==r.filled+r.expired
    for key,g in orders.groupby(['symbol',*keys]):
        g=g.sort_values('created')
        a,b=pd.to_datetime(g.created).to_numpy(),pd.to_datetime(g.release).to_numpy()
        assert (b>=a).all() and (a[1:]>=b[:-1]).all(),key
    assert not parents.duplicated(['symbol','range_date']).any()
    specs=json.loads((ROOT/'data/specs.json').read_text())
    for (symbol,period),group in parents.groupby(['symbol','period']):
        file=ROOT/f'data/results/sb_forward_validation_20260917/{symbol}_M5.csv' if period=='extension' else ROOT/f'data/history/{symbol}_M5.csv'
        data=pd.read_csv(file).rename(columns={'datetime':'time'})
        data['time']=pd.to_datetime(data.time,utc=True).dt.tz_localize(None)
        data=data.set_index('time',drop=False)
        for _,p in group.iterrows():
            start=pd.Timestamp(p.range_date).tz_localize('America/New_York').tz_convert('Europe/Helsinki').tz_localize(None)
            stop=(pd.Timestamp(p.range_date)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('Europe/Helsinki').tz_localize(None)
            reference=data[(data.time>=start)&(data.time<stop)]
            assert len(reference)==114 and reference.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all()
            assert np.isclose(reference.high.max(),p.range_high) and np.isclose(reference.low.min(),p.range_low)
            event=pd.Timestamp(p.event_time)
            signal=pd.Timestamp(p.time)
            assert stop<=event and pd.Timedelta(minutes=30)<=signal-event<=pd.Timedelta(minutes=60)
            eventbars=data[(data.time>=event)&(data.time<event+pd.Timedelta(minutes=15))]
            assert len(eventbars)==3
            side=1 if p.dir=='BUY' else -1
            if side==1:
                assert eventbars.low.min()<p.range_low<eventbars.close.iloc[-1]
            else:
                assert eventbars.high.max()>p.range_high>eventbars.close.iloc[-1]
            context=data[(data.time>=signal-pd.Timedelta(minutes=225))&(data.time<signal+pd.Timedelta(minutes=15))].reset_index(drop=True)
            m15=resample_complete(context,15)
            assert len(m15)==16
            assert np.isclose(m15.atr.iloc[-1],p.atr)
            assert side*(m15.close.iloc[-2]-m15.open.iloc[-2])>=m15.atr.iloc[-2]
            expected=(m15.low.iloc[-1]+m15.high.iloc[-3])/2 if side==1 else (m15.high.iloc[-1]+m15.low.iloc[-3])/2
            assert np.isclose(expected,p.entry)
            causal=data[(data.time>=event)&(data.time<signal+pd.Timedelta(minutes=15))]
            extreme=causal.low.min() if side==1 else causal.high.max()
            assert np.isclose(max(p.atr,side*(p.entry-extreme)+.1*p.atr),p.risk)
            if p.covered:
                created=signal+pd.Timedelta(minutes=15)
                horizon=data[(data.time>=created)&(data.time<=created+pd.Timedelta(minutes=225))]
                assert len(horizon)==46 and horizon.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all()
    fresh=orders[orders.parent_mode=='session_range']
    for (path,mult),g in fresh.groupby(['path','cost_mult']):
        identity=['symbol','period','time','dir']
        covered=parents[parents.covered]
        assert set(map(tuple,g[identity].to_numpy()))==set(map(tuple,covered[identity].to_numpy()))
    filled=fresh[fresh.net_r.notna()]
    commission=filled.apply(lambda r:7*specs[r.symbol]['tick_size']/specs[r.symbol]['tick_value']*r.cost_mult/r.risk,axis=1)
    assert np.allclose(filled.gross_r-filled.net_r,commission)
    days=pd.read_csv(directory/'days.csv')
    totals=[]
    for period,g in days.groupby('period'):
        subset=parents[parents.period==period]
        totals.append(dict(period=period,observed_symbol_days=len(g[['symbol','ny_date']].drop_duplicates()),
            complete_ranges=int(g.complete_range.sum()),first_events=int(g.event.sum()),
            ambiguous_days=int(g.ambiguous.sum()),invalidated_events=int(g.invalidated.sum()),
            cost_rejections=int(g.cost_rejected.sum()),eligible=int(g.eligible.sum()),
            covered_parents=int(subset.covered.sum())))
    pd.DataFrame(totals).to_csv(directory/'funnel.csv',index=False)
    result=dict(verified=True,parent_rows=len(parents),new_scenario_rows=len(fresh),reused_control_rows=len(reused),
        scenario_cells=len(summary),source_data_hashes=len(card['source_sha256'])+len(card['data']),
        audit_script_sha256=digest(Path(__file__)),run_sha256=digest(directory/'run.json'),
        funnel_sha256=digest(directory/'funnel.csv'))
    (directory/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('directory',type=Path)
    audit(ap.parse_args().directory)
