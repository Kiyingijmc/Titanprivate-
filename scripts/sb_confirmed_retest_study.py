#!/usr/bin/env python3
"""Offline delayed midpoint LIMIT study using frozen, hash-verified parents."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.research.sb_confirmed_retest import retest_order
from src.research.costs import spread_price
from scripts.sb_entry_study import digest
from scripts.sb_variant_study import stats, ratios

PRIOR=ROOT/'data/results/sb_confirmation_20260917'
KEYS=['period','window','path','cost_mult','entry_mode']


def verify_prior():
    card=json.loads((PRIOR/'run.json').read_text())
    if not card['complete']:
        raise ValueError('prior run incomplete')
    for f,h in {**card['source_sha256'],**card['data']}.items():
        if digest(ROOT/f)!=h:
            raise ValueError(f'prior source/data changed: {f}')
    audit=json.loads((PRIOR/'audit.json').read_text())
    if not audit['verified']:
        raise ValueError('prior audit incomplete')
    for f,h in audit['artifact_sha256'].items():
        if digest(PRIOR/f)!=h:
            raise ValueError(f'prior artifact changed: {f}')
    return card


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    prior=verify_prior()
    args.out.mkdir(parents=True,exist_ok=False)
    source=['src/research/sb_confirmed_retest.py','scripts/sb_confirmed_retest_study.py',
            'tests/unit/test_sb_confirmed_retest.py',
            'docs/research/2026-09-17-sb-confirmed-retest-design.md']
    card=dict(complete=False,source_sha256={**prior['source_sha256'],**{f:digest(ROOT/f) for f in source}},
              data=prior['data'],control_sha256={f:digest(PRIOR/f) for f in ('orders.csv','summary.csv','run.json','audit.json')},
              purpose='post-selection exploratory test; frozen controls reused, no live GO')
    run=args.out/'run.json'
    run.write_text(json.dumps(card,indent=2)+'\n')
    controls=pd.read_csv(PRIOR/'orders.csv')
    parents=controls[controls.entry_mode=='midpoint']
    specs=json.loads((ROOT/'data/specs.json').read_text())
    results=[]
    for symbol, symbol_parents in parents.groupby('symbol'):
        spec=specs[symbol]
        spread=spread_price(symbol,spec['tick_size'])
        commission=7*spec['tick_size']/spec['tick_value']
        for dataset in ('history','extension'):
            selected=symbol_parents[(symbol_parents.period=='extension') if dataset=='extension' else (symbol_parents.period!='extension')]
            file=ROOT/f'data/history/{symbol}_M5.csv' if dataset=='history' else ROOT/f'data/results/sb_forward_validation_20260917/{symbol}_M5.csv'
            frame=pd.read_csv(file).rename(columns={'datetime':'time'})
            frame['time']=pd.to_datetime(frame.time,utc=True).dt.tz_localize(None)
            times=frame.time.to_numpy()
            for _, parent in selected.iterrows():
                created=np.datetime64(parent.created,'ns')
                start=int(np.searchsorted(times,created))-1
                end=int(np.searchsorted(times,created+np.timedelta64(225,'m')))+1
                part=frame.iloc[start:end]
                bars={k:part[k].to_numpy() for k in ('time','open','high','low','close')}
                signal=dict(time=parent.time,dir=parent.dir,entry=parent.entry,risk=parent.risk)
                row=retest_order(signal,bars,path=parent.path,spread=spread*parent.cost_mult,commission=commission*parent.cost_mult)
                results.append(dict(symbol=symbol,period=parent.period,window=parent.window,
                                    path=parent.path,cost_mult=parent.cost_mult,entry_mode='confirmed_retest',**row))
        print(f'{symbol}: frozen parents replayed',flush=True)
    orders=pd.concat([controls,pd.DataFrame(results)],ignore_index=True)
    orders.to_csv(args.out/'orders.csv',index=False)
    records=[]
    for key,g in orders.groupby(['symbol',*KEYS]):
        rows=g.replace({np.nan:None}).to_dict('records')
        record=dict(zip(['symbol',*KEYS],key),**stats(rows,len(rows),0))
        for outcome in ('NO_CONFIRMATION','INVALIDATED','ENTRY_INVALID','ENTRY_COST'):
            record[outcome.lower()]=int((g.outcome==outcome).sum())
        record['submitted']=int(g.confirmation_close.notna().sum()-(g.outcome=='ENTRY_COST').sum()) if key[-1]=='confirmed_retest' else 0
        records.append(record)
    raw=pd.DataFrame(records)
    by=ratios(raw)
    by.to_csv(args.out/'by_symbol.csv',index=False)
    summary=ratios(raw.groupby(KEYS,as_index=False).sum(numeric_only=True))
    summary.to_csv(args.out/'summary.csv',index=False)
    assert len(summary)==72
    # Recompute both controls from reused rows rather than trusting old totals.
    previous=pd.read_csv(PRIOR/'summary.csv').set_index(KEYS).sort_index()
    now=summary[summary.entry_mode!='confirmed_retest'].set_index(KEYS).sort_index()
    pd.testing.assert_frame_equal(previous,now[previous.columns],check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    decisions=[]
    for window in ('baseline','open_window'):
        failures=[]
        for _,r in summary[(summary.window==window)&(summary.entry_mode=='confirmed_retest')].iterrows():
            label=f'{r.period}/{r.path}/{r.cost_mult}'
            if r.filled<(150 if r.period=='early' else 100): failures.append(label+': sample')
            if not r.mean_net_r>0: failures.append(label+': nonpositive')
            for control in ('midpoint','confirmation'):
                b=summary[(summary.window==window)&(summary.period==r.period)&(summary.path==r.path)&(summary.cost_mult==r.cost_mult)&(summary.entry_mode==control)].iloc[0]
                if not r.mean_net_r>b.mean_net_r: failures.append(label+': no improvement over '+control)
            if r.period!='early':
                breadth=by[(by.window==window)&(by.period==r.period)&(by.path==r.path)&(by.cost_mult==r.cost_mult)&(by.entry_mode=='confirmed_retest')&(by.filled>=20)]
                if len(breadth)<3 or (breadth.mean_net_r>0).sum()<=len(breadth)/2: failures.append(label+': breadth')
        decisions.append(dict(window=window,verdict='NO_ADVANCE' if failures else 'RESEARCH_SHORTLIST',failures=failures))
    (args.out/'decisions.json').write_text(json.dumps(decisions,indent=2)+'\n')
    card.update(complete=True,reused_control_rows=len(controls),new_retest_rows=len(results))
    run.write_text(json.dumps(card,indent=2)+'\n')
    print(summary.query('path=="OHLC" and cost_mult==1')[['period','window','entry_mode','orders','filled','mean_net_r','submitted','expired']].to_string(index=False))


if __name__=='__main__': main()
