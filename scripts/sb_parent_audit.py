#!/usr/bin/env python3
"""Reconstruct parent funnel and diagnose unchanged midpoint result stability."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.sb_confirmed_retest_study import verify_prior, PRIOR
from scripts.sb_entry_study import digest
from scripts.sb_forward_validation import segments
from src.research.sb_variants import collect, resample_complete
from src.research.sb_entries import candidates
from src.research.sb_sessions import utc_from_broker
from src.research.costs import spread_price


def period_of(stamp,dataset):
    if dataset=='extension':
        return 'extension' if pd.Timestamp('2026-06-25')<=stamp<pd.Timestamp('2026-09-17') else None
    if stamp<pd.Timestamp('2025-01-01'): return 'early'
    if stamp>=pd.Timestamp('2025-01-08'): return 'late'
    return None


def week_interval(group, seed=17092026, repetitions=2000):
    """Joint-symbol NY calendar-week bootstrap of return/fill ratio."""
    dates=utc_from_broker(pd.DatetimeIndex(pd.to_datetime(group.created)),'seasonal_eet').tz_convert('America/New_York').tz_localize(None)
    weeks=dates.to_period('W-SUN')
    data=pd.DataFrame(dict(week=weeks,returns=group.net_r.fillna(0).to_numpy(),fills=group.net_r.notna().astype(int).to_numpy()))
    weekly=data.groupby('week')[['returns','fills']].sum().reindex(pd.period_range(weeks.min(),weeks.max(),freq='W-SUN'),fill_value=0)
    rng=np.random.default_rng(seed)
    indices=rng.integers(0,len(weekly),size=(repetitions,len(weekly)))
    sums=weekly.to_numpy()[indices].sum(axis=1)
    valid=sums[:,1]>0
    ratios=sums[valid,0]/sums[valid,1]
    low,high=np.quantile(ratios,[.025,.975]) if len(ratios) else (np.nan,np.nan)
    return dict(weeks=len(weekly),bootstrap_valid=int(valid.sum()),mean_net_r=group.net_r.mean(),ci_low=float(low),ci_high=float(high))


def without_top_gains(returns):
    """Remove up to five positive gains, never discard a loss as a gain."""
    return returns.drop(returns[returns>0].nlargest(5).index)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    prior=verify_prior()
    args.out.mkdir(parents=True,exist_ok=False)
    inputs=['scripts/sb_parent_audit.py','scripts/sb_confirmed_retest_study.py',
            'docs/research/2026-09-17-sb-parent-audit-design.md']
    card=dict(complete=False,source_sha256={**prior['source_sha256'],**{f:digest(ROOT/f) for f in inputs}},
              data=prior['data'],control_sha256=digest(PRIOR/'orders.csv'))
    run=args.out/'run.json'
    run.write_text(json.dumps(card,indent=2)+'\n')
    orders=pd.read_csv(PRIOR/'orders.csv')
    orders=orders[orders.entry_mode=='midpoint'].copy()
    specs=json.loads((ROOT/'data/specs.json').read_text())
    counters={}
    days={}
    selected=[]
    def count(symbol,window,period,stage,amount=1):
        if period is None: return
        key=(symbol,window,period)
        counters.setdefault(key,{})[stage]=counters.setdefault(key,{}).get(stage,0)+amount
    for symbol in sorted(specs.keys() & set(orders.symbol)):
        spec=specs[symbol]
        spread=spread_price(symbol,spec['tick_size'])
        commission=7*spec['tick_size']/spec['tick_value']
        for dataset in ('history','extension'):
            file=ROOT/f'data/history/{symbol}_M5.csv' if dataset=='history' else ROOT/f'data/results/sb_forward_validation_20260917/{symbol}_M5.csv'
            source=pd.read_csv(file).rename(columns={'datetime':'time'})
            source['time']=pd.to_datetime(source.time,utc=True).dt.tz_localize(None)
            if dataset=='extension': source=source[(source.time>='2026-06-24')&(source.time<'2026-09-17')]
            seen={w:set() for w in ('baseline','open_window')}
            for part in segments(source):
                if len(part)<150: continue
                frame=resample_complete(part,15)
                stamps=pd.DatetimeIndex(frame.time)+pd.Timedelta(minutes=15)
                warmed=frame.iloc[50:]
                idx=warmed.index
                side=np.where(frame.low>frame.high.shift(2),1,np.where(frame.high<frame.low.shift(2),-1,0))
                fvg=idx[(side[idx]!=0)&np.isfinite(frame.atr.iloc[idx])&(frame.atr.iloc[idx]>0)]
                middle,_=collect(frame,15,'middle_retest','all_hours',spread=0.,commission=0.)
                sweep,_=collect(frame,15,'sweep_reclaim','all_hours',spread=0.,commission=0.)
                stage_times={'warmed_closes':stamps[50:],'fvg':stamps[fvg],
                             'displacement_geometry':pd.DatetimeIndex([s['time'] for s in middle])+pd.Timedelta(minutes=15),
                             'sweep_reclaim':pd.DatetimeIndex([s['time'] for s in sweep])+pd.Timedelta(minutes=15)}
                for window in ('baseline','open_window'):
                    for stage,times in stage_times.items():
                        masks=({'extension':(times>=pd.Timestamp('2026-06-25'))&(times<pd.Timestamp('2026-09-17'))}
                               if dataset=='extension' else {'early':times<pd.Timestamp('2025-01-01'),'late':times>=pd.Timestamp('2025-01-08')})
                        for period,mask in masks.items(): count(symbol,window,period,stage,int(mask.sum()))
                    ny=utc_from_broker(stamps[50:],'seasonal_eet').tz_convert('America/New_York')
                    minute=ny.hour*60+ny.minute
                    mask=ny.notna()&(minute>=(570 if window=='open_window' else 600))&(minute<660)
                    for close,local in zip(stamps[50:][mask],ny[mask]):
                        period=period_of(close,dataset)
                        if period and pd.notna(local) and (570 if window=='open_window' else 600)<=local.hour*60+local.minute<660:
                            days.setdefault((symbol,window,period),set()).add(local.date())
                    times=pd.DatetimeIndex([s['time'] for s in sweep])+pd.Timedelta(minutes=15)
                    ny=utc_from_broker(times,'seasonal_eet').tz_convert('America/New_York')
                    for s,close,local in zip(sweep,times,ny):
                        period=period_of(close,dataset)
                        if pd.isna(local) or not (570 if window=='open_window' else 600)<=local.hour*60+local.minute<660: continue
                        count(symbol,window,period,'in_window')
                        if (spread+commission)/s['risk']<=.25: count(symbol,window,period,'cost_eligible')
                    parents,_=candidates(frame,window,spread=spread,commission=commission)
                    for s in parents:
                        close=pd.Timestamp(s['time'])+pd.Timedelta(minutes=15)
                        period=period_of(close,dataset)
                        if period is None: continue
                        day=utc_from_broker([close],'seasonal_eet').tz_convert('America/New_York')[0].date()
                        if day in seen[window]: continue
                        seen[window].add(day)
                        count(symbol,window,period,'daily_cap')
                        if close+pd.Timedelta(minutes=225)>part.time.iloc[-1] or (period=='early' and close+pd.Timedelta(minutes=225)>=pd.Timestamp('2025-01-01')): continue
                        count(symbol,window,period,'covered_parent')
                        selected.append(dict(symbol=symbol,window=window,period=period,time=pd.Timestamp(s['time']),dir=s['dir'],entry=s['entry'],risk=s['risk']))
            print(f'{symbol} {dataset}: funnel reconstructed',flush=True)
    reference=orders[(orders.path=='OHLC')&(orders.cost_mult==1)].copy()
    reference['time']=pd.to_datetime(reference.time)
    selected=pd.DataFrame(selected)
    keys=['symbol','window','period','time','dir']
    columns=keys+['entry','risk']
    pd.testing.assert_frame_equal(selected[columns].sort_values(keys).reset_index(drop=True),reference[columns].sort_values(keys).reset_index(drop=True),check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    selected.to_csv(args.out/'parents.csv',index=False)
    stages=['warmed_closes','fvg','displacement_geometry','sweep_reclaim','in_window','cost_eligible','daily_cap','covered_parent']
    rows=[]
    for key,values in counters.items():
        symbol,window,period=key
        record=dict(symbol=symbol,window=window,period=period,observed_session_days=len(days.get(key,set())),**{s:values.get(s,0) for s in stages})
        fills=reference[(reference.symbol==symbol)&(reference.window==window)&(reference.period==period)].net_r.count()
        record['filled']=fills
        assert all(record[a]>=record[b] for a,b in zip(stages,stages[1:])),key
        assert record['covered_parent']>=fills
        rows.append(record)
    funnel=pd.DataFrame(rows)
    funnel.to_csv(args.out/'funnel_by_symbol.csv',index=False)
    pooled=funnel.groupby(['period','window'],as_index=False).sum(numeric_only=True)
    pooled.to_csv(args.out/'funnel.csv',index=False)
    orders['quarter']=utc_from_broker(pd.DatetimeIndex(pd.to_datetime(orders.created)),'seasonal_eet').tz_convert('America/New_York').tz_localize(None).to_period('Q').astype(str)
    groupkeys=['period','window','path','cost_mult']
    for axis in ('symbol','quarter','dir'):
        result=orders.groupby([*groupkeys,axis],as_index=False).agg(orders=('net_r','size'),filled=('net_r','count'),total_net_r=('net_r','sum'),mean_net_r=('net_r','mean'))
        result.to_csv(args.out/f'by_{axis}.csv',index=False)
    sensitivity=[]
    uncertainty=[]
    for key,g in orders.groupby(groupkeys):
        meta=dict(zip(groupkeys,key))
        uncertainty.append({**meta,**week_interval(g)})
        for symbol in sorted(set(orders.symbol)):
            remaining=g[g.symbol!=symbol].net_r.dropna()
            sensitivity.append(dict(**meta,excluded=symbol,filled=len(remaining),total_net_r=remaining.sum(),mean_net_r=remaining.mean()))
        returns=g.net_r.dropna().sort_values()
        rest=without_top_gains(returns)
        sensitivity.append(dict(**meta,excluded='TOP_5_GAINS',filled=len(rest),total_net_r=rest.sum(),mean_net_r=rest.mean()))
    pd.DataFrame(sensitivity).to_csv(args.out/'sensitivity.csv',index=False)
    pd.DataFrame(uncertainty).to_csv(args.out/'weekly_intervals.csv',index=False)
    card.update(complete=True,reconciled_parents=len(selected),reused_scenario_rows=len(orders),
                artifact_sha256={f.name:digest(f) for f in args.out.glob('*.csv')})
    run.write_text(json.dumps(card,indent=2)+'\n')
    print(pooled.to_string(index=False))
    print(pd.DataFrame(uncertainty).query('path=="OHLC" and cost_mult==1').to_string(index=False))


if __name__=='__main__': main()
