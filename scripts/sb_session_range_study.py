#!/usr/bin/env python3
"""Frozen session-range parent versus prior wider-window midpoint control."""
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.sb_confirmed_retest_study import verify_prior, PRIOR
from scripts.sb_entry_study import digest
from scripts.sb_parent_audit import period_of
from scripts.sb_forward_validation import segments
from scripts.sb_variant_study import SYMBOLS, stats, ratios
from src.research.sb_session_range import collect_session_range
from src.research.sb_variants import resample_complete
from src.research.sb_execution import simulate, PATHS
from src.research.costs import spread_price


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    prior=verify_prior()
    args.out.mkdir(parents=True,exist_ok=False)
    sources=['src/research/sb_session_range.py','scripts/sb_session_range_study.py',
             'scripts/sb_parent_audit.py','scripts/sb_confirmed_retest_study.py',
             'tests/unit/test_sb_session_range.py','docs/research/2026-09-18-sb-session-range-design.md']
    card=dict(complete=False,source_sha256={**prior['source_sha256'],**{f:digest(ROOT/f) for f in sources}},
              data=prior['data'],control_sha256=digest(PRIOR/'orders.csv'),purpose='reused development data; no independent validation')
    run=args.out/'run.json'
    run.write_text(json.dumps(card,indent=2)+'\n')
    original=pd.read_csv(PRIOR/'orders.csv')
    control=original[(original.entry_mode=='midpoint')&(original.window=='open_window')].copy()
    control['parent_mode']='rolling_control'
    specs=json.loads((ROOT/'data/specs.json').read_text())
    orders=[]
    parents=[]
    days=[]
    for symbol in SYMBOLS:
        spec=specs[symbol]
        spread=spread_price(symbol,spec['tick_size'])
        commission=7*spec['tick_size']/spec['tick_value']
        for dataset in ('history','extension'):
            file=ROOT/f'data/history/{symbol}_M5.csv' if dataset=='history' else ROOT/f'data/results/sb_forward_validation_20260917/{symbol}_M5.csv'
            frame=pd.read_csv(file).rename(columns={'datetime':'time'})
            frame['time']=pd.to_datetime(frame.time,utc=True).dt.tz_localize(None)
            if dataset=='extension': frame=frame[(frame.time>='2026-06-24')&(frame.time<'2026-09-17')]
            seen=set()
            for part in segments(frame):
                if len(part)<150: continue
                signals,diagnostics=collect_session_range(resample_complete(part,15),spread=spread,commission=commission)
                for day in diagnostics:
                    period=period_of(pd.Timestamp(day['ny_date'])+pd.Timedelta(hours=12),dataset)
                    if period: days.append(dict(symbol=symbol,period=period,**day))
                selected={p:[] for p in ('early','late','extension')}
                for signal in signals:
                    close=pd.Timestamp(signal['time'])+pd.Timedelta(minutes=15)
                    period=period_of(close,dataset)
                    if not period or signal['range_date'] in seen: continue
                    seen.add(signal['range_date'])
                    covered=close+pd.Timedelta(minutes=225)<=part.time.iloc[-1] and not (period=='early' and close+pd.Timedelta(minutes=225)>=pd.Timestamp('2025-01-01'))
                    parents.append(dict(symbol=symbol,period=period,covered=covered,**signal))
                    if covered: selected[period].append(signal)
                bars={k:part[k].to_numpy() for k in ('time','open','high','low','close')}
                for period,signals in selected.items():
                    if not signals: continue
                    for path in PATHS:
                        for mult in (1.,1.5):
                            rows,skipped=simulate(signals,bars,arm='fixed',path=path,spread=spread*mult,
                                commission=commission*mult,signal_minutes=15,ttl_minutes=45,max_hold_minutes=180)
                            assert skipped==0
                            orders.extend(dict(symbol=symbol,period=period,path=path,cost_mult=mult,parent_mode='session_range',**row) for row in rows)
            print(f'{symbol} {dataset}: range parent evaluated',flush=True)
    new=pd.DataFrame(orders)
    if new.empty: new=pd.DataFrame(columns=control.columns)
    combined=pd.concat([control,new],ignore_index=True)
    combined.to_csv(args.out/'orders.csv',index=False)
    pd.DataFrame(parents).to_csv(args.out/'parents.csv',index=False)
    pd.DataFrame(days).to_csv(args.out/'days.csv',index=False)
    records=[]
    for symbol in SYMBOLS:
        for period in ('early','late','extension'):
            for path in PATHS:
                for mult in (1.,1.5):
                    for mode in ('rolling_control','session_range'):
                        g=combined[(combined.symbol==symbol)&(combined.period==period)&(combined.path==path)&(combined.cost_mult==mult)&(combined.parent_mode==mode)]
                        rows=g.replace({float('nan'):None}).to_dict('records')
                        records.append(dict(symbol=symbol,period=period,path=path,cost_mult=mult,parent_mode=mode,**stats(rows,len(rows),0)))
    keys=['period','path','cost_mult','parent_mode']
    raw=pd.DataFrame(records)
    by=ratios(raw)
    by.to_csv(args.out/'by_symbol.csv',index=False)
    summary=ratios(raw.groupby(keys,as_index=False).sum(numeric_only=True))
    summary.to_csv(args.out/'summary.csv',index=False)
    previous=pd.read_csv(PRIOR/'summary.csv')
    previous=previous[(previous.window=='open_window')&(previous.entry_mode=='midpoint')].set_index(['period','path','cost_mult']).sort_index()
    current=summary[summary.parent_mode=='rolling_control'].set_index(['period','path','cost_mult']).sort_index()
    for field in ('orders','filled','expired','total_net_r','mean_net_r'):
        pd.testing.assert_series_equal(previous[field],current[field],check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    failures=[]
    for _,r in summary[summary.parent_mode=='session_range'].iterrows():
        label=f'{r.period}/{r.path}/{r.cost_mult}'
        if r.filled<(150 if r.period=='early' else 100): failures.append(label+': sample')
        if not r.mean_net_r>0: failures.append(label+': nonpositive')
        baseline=current.loc[(r.period,r.path,r.cost_mult)]
        if not r.mean_net_r>baseline.mean_net_r: failures.append(label+': no improvement')
        if r.period!='early':
            breadth=by[(by.period==r.period)&(by.path==r.path)&(by.cost_mult==r.cost_mult)&(by.parent_mode=='session_range')&(by.filled>=20)]
            if len(breadth)<3 or (breadth.mean_net_r>0).sum()<=len(breadth)/2: failures.append(label+': breadth')
    (args.out/'decision.json').write_text(json.dumps(dict(verdict='NO_ADVANCE' if failures else 'RESEARCH_SHORTLIST',failures=failures),indent=2)+'\n')
    card.update(complete=True,reused_control_rows=len(control),new_order_rows=len(new),
                artifact_sha256={f.name:digest(f) for f in args.out.glob('*.csv')})
    run.write_text(json.dumps(card,indent=2)+'\n')
    print(summary.query('path=="OHLC"')[['period','parent_mode','cost_mult','orders','filled','mean_net_r']].to_string(index=False))


if __name__=='__main__': main()
