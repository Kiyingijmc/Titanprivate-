#!/usr/bin/env python3
"""Frozen M5 confirmation versus identical midpoint parents; offline only."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.research.sb_confirmation import confirm_order
from src.research.sb_entries import candidates
from src.research.sb_variants import resample_complete
from src.research.sb_execution import simulate, PATHS
from src.research.costs import spread_price
from scripts.sb_variant_study import SYMBOLS, stats, ratios
from scripts.sb_entry_study import digest
from scripts.sb_forward_validation import segments


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    sources=['src/research/sb_confirmation.py','src/research/sb_entries.py',
             'src/research/sb_variants.py','src/research/sb_sessions.py',
             'src/research/sb_execution.py','src/research/costs.py','src/utils/instrument.py',
             'scripts/sb_confirmation_study.py','scripts/sb_forward_validation.py',
             'scripts/sb_variant_study.py','scripts/sb_entry_study.py','data/specs.json',
             'docs/research/2026-09-17-sb-m5-confirmation-design.md']
    card=dict(complete=False,source_sha256={f:digest(ROOT/f) for f in sources},data={},coverage=[])
    run=args.out/'run.json'
    run.write_text(json.dumps(card,indent=2)+'\n')
    specs=json.loads((ROOT/'data/specs.json').read_text())
    orders,summaries=[],[]
    extension=ROOT/'data/results/sb_forward_validation_20260917'
    collection=json.loads((extension/'collection.json').read_text())
    assert collection['complete']
    for sym in SYMBOLS:
        spec=specs[sym]
        spread=spread_price(sym,spec['tick_size'])
        commission=7*spec['tick_size']/spec['tick_value']
        for dataset in ('history','extension'):
            file=ROOT/f'data/history/{sym}_M5.csv' if dataset=='history' else extension/f'{sym}_M5.csv'
            sha=digest(file)
            if dataset=='extension': assert sha==collection['data'][sym]['sha256']
            card['data'][str(file.relative_to(ROOT))]=sha
            frame=pd.read_csv(file).rename(columns={'datetime':'time'})
            frame['time']=pd.to_datetime(frame.time,utc=True).dt.tz_localize(None)
            if dataset=='extension': frame=frame[(frame.time>='2026-06-24')&(frame.time<'2026-09-17')]
            seen={'baseline':set(),'open_window':set()}
            for segment,part in enumerate(segments(frame)):
                if len(part)<150: continue
                m15=resample_complete(part,15)
                bars={k:part[k].to_numpy() for k in ('time','open','high','low','close')}
                for window in ('baseline','open_window'):
                    parents,_=candidates(m15,window,spread=spread,commission=commission)
                    selected={'early':[],'late':[],'extension':[]}
                    excluded=0
                    for signal in parents:
                        close=pd.Timestamp(signal['time'])+pd.Timedelta(minutes=15)
                        period=('extension' if dataset=='extension' and close>=pd.Timestamp('2026-06-25') else
                                'early' if dataset=='history' and close<pd.Timestamp('2025-01-01') else
                                'late' if dataset=='history' and close>=pd.Timestamp('2025-01-08') else None)
                        if period is None: continue
                        day=close.tz_localize('Europe/Helsinki').tz_convert('America/New_York').date()
                        if day in seen[window]: continue
                        seen[window].add(day)
                        if close+pd.Timedelta(minutes=225)>part.time.iloc[-1] or (period=='early' and close+pd.Timedelta(minutes=225)>=pd.Timestamp('2025-01-01')):
                            excluded+=1
                            continue
                        selected[period].append(signal)
                    card['coverage'].append(dict(symbol=sym,dataset=dataset,segment=segment,window=window,
                                                selected=sum(map(len,selected.values())),excluded_horizon=excluded))
                    for period,signals in selected.items():
                        if not signals: continue
                        for path in PATHS:
                            for mult in (1.,1.5):
                                for entry in ('midpoint','confirmation'):
                                    meta=dict(symbol=sym,period=period,window=window,path=path,cost_mult=mult,entry_mode=entry)
                                    if entry=='midpoint':
                                        rows,skipped=simulate(signals,bars,arm='fixed',path=path,spread=spread*mult,
                                            commission=commission*mult,signal_minutes=15,ttl_minutes=45,max_hold_minutes=180)
                                    else:
                                        rows,skipped=[],0
                                        release=np.datetime64('1678-01-01','ns')
                                        for signal in signals:
                                            created=np.datetime64(signal['time'],'ns')+np.timedelta64(15,'m')
                                            if created<release:
                                                skipped+=1
                                                continue
                                            row=confirm_order(signal,bars,path=path,spread=spread*mult,commission=commission*mult)
                                            release=np.datetime64(row['release'],'ns')
                                            rows.append(row)
                                    orders.extend({**meta,**row} for row in rows)
                                    record={**meta,**stats(rows,len(signals),skipped)}
                                    for outcome in ('NO_CONFIRMATION','INVALIDATED','ENTRY_INVALID','ENTRY_COST'):
                                        record[outcome.lower()]=sum(r['outcome']==outcome for r in rows)
                                    summaries.append(record)
            print(f'{sym} {dataset}: complete',flush=True)
    df=pd.DataFrame(orders)
    df.to_csv(args.out/'orders.csv',index=False)
    raw=pd.DataFrame(summaries)
    keys=['period','window','path','cost_mult','entry_mode']
    by=ratios(raw.groupby(['symbol',*keys],as_index=False).sum(numeric_only=True))
    by.to_csv(args.out/'by_symbol.csv',index=False)
    summary=ratios(raw.groupby(keys,as_index=False).sum(numeric_only=True))
    summary.to_csv(args.out/'summary.csv',index=False)
    # Frozen extension midpoint controls must reproduce previous trade outcomes.
    prior=pd.read_csv(extension/'orders.csv').rename(columns={'arm':'window'})
    now=df[(df.period=='extension')&(df.entry_mode=='midpoint')]
    sort=['symbol','window','path','cost_mult','created']
    cols=sort+['dir','entry','risk','release','outcome','gross_r','net_r']
    pd.testing.assert_frame_equal(prior[cols].sort_values(sort).reset_index(drop=True),
                                  now[cols].sort_values(sort).reset_index(drop=True),
                                  check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    decisions=[]
    for window in ('baseline','open_window'):
        failures=[]
        for _,r in summary[(summary.window==window)&(summary.entry_mode=='confirmation')].iterrows():
            label=f'{r.period}/{r.path}/{r.cost_mult}'
            if r.filled<(150 if r.period=='early' else 100): failures.append(label+': sample')
            if not r.mean_net_r>0: failures.append(label+': nonpositive')
            control=summary[(summary.window==window)&(summary.entry_mode=='midpoint')&(summary.period==r.period)&(summary.path==r.path)&(summary.cost_mult==r.cost_mult)].iloc[0]
            if not r.mean_net_r>control.mean_net_r: failures.append(label+': no improvement')
            if r.period!='early':
                breadth=by[(by.window==window)&(by.entry_mode=='confirmation')&(by.period==r.period)&(by.path==r.path)&(by.cost_mult==r.cost_mult)&(by.filled>=20)]
                if len(breadth)<3 or (breadth.mean_net_r>0).sum()<=len(breadth)/2: failures.append(label+': breadth')
        decisions.append(dict(window=window,verdict='NO_ADVANCE' if failures else 'RESEARCH_SHORTLIST',failures=failures))
    (args.out/'decisions.json').write_text(json.dumps(decisions,indent=2)+'\n')
    card.update(complete=True,extension_control_rows=len(prior))
    run.write_text(json.dumps(card,indent=2)+'\n')
    print(summary.query('path == "OHLC"')[['period','window','entry_mode','cost_mult','filled','mean_net_r']].to_string(index=False))


if __name__=='__main__': main()
