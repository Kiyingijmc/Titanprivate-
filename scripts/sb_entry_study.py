#!/usr/bin/env python3
"""Evaluate frozen entry/frequency hypotheses against the seasonal baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.research.sb_entries import ARMS,candidates
from src.research.sb_variants import resample_complete
from src.research.sb_execution import simulate,PATHS
from src.research.costs import spread_price
from scripts.sb_variant_study import SYMBOLS,stats,ratios


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    sources=['src/research/sb_entries.py','src/research/sb_variants.py','src/research/sb_sessions.py',
             'src/research/sb_execution.py','src/research/costs.py','scripts/sb_entry_study.py',
             'scripts/sb_variant_study.py','data/specs.json',
             'docs/research/2026-09-17-sb-frequency-entry-design.md']
    card=dict(complete=False,arms=list(ARMS),purpose='post-selection exploratory screen; no live GO',
              source_sha256={f:digest(ROOT/f) for f in sources},data={},funnel=[])
    run=args.out/'run.json'
    run.write_text(json.dumps(card,indent=2)+'\n')
    specs=json.loads((ROOT/'data/specs.json').read_text())
    orders,summaries=[],[]
    for sym in SYMBOLS:
        file=ROOT/f'data/history/{sym}_M5.csv'
        source=pd.read_csv(file).rename(columns={'datetime':'time'})
        source['time']=pd.to_datetime(source.time)
        m15,h1=resample_complete(source,15),resample_complete(source,60)
        spec=specs[sym]
        spread,commission=spread_price(sym,spec['tick_size']),7*spec['tick_size']/spec['tick_value']
        card['data'][sym]=dict(sha256=digest(file),spread=spread,commission=commission)
        for arm in ARMS:
            signals,funnel=candidates(m15,arm,spread=spread,commission=commission,h1=h1)
            card['funnel'].append(dict(symbol=sym,arm=arm,**funnel))
            for period,mask in [('early',source.time<'2025-01-01'),('late',source.time>='2025-01-08')]:
                part=source[mask]
                bars={k:part[k].to_numpy() for k in ('time','open','high','low','close')}
                selected=[s for s in signals if part.time.iloc[0]<=pd.Timestamp(s['time'])+pd.Timedelta(minutes=15)<=part.time.iloc[-1]]
                for path in PATHS:
                    for mult in (1.,1.5):
                        meta=dict(symbol=sym,arm=arm,period=period,path=path,cost_mult=mult)
                        rows,skipped=simulate(selected,bars,arm='fixed',path=path,
                            spread=spread*mult,commission=commission*mult,
                            signal_minutes=15,ttl_minutes=45,max_hold_minutes=180)
                        orders.extend({**meta,**row} for row in rows)
                        summaries.append({**meta,**stats(rows,len(selected),skipped)})
        print(f'{sym}: all seven arms complete',flush=True)
    orders=pd.DataFrame(orders)
    orders.to_csv(args.out/'orders.csv',index=False)
    raw=pd.DataFrame(summaries)
    by_symbol=ratios(raw)
    by_symbol.to_csv(args.out/'by_symbol.csv',index=False)
    summary=ratios(raw.groupby(['arm','period','path','cost_mult'],as_index=False).sum(numeric_only=True))
    summary['fill_rate']=summary.filled/summary.orders.replace(0,np.nan)
    summary.to_csv(args.out/'summary.csv',index=False)
    baseline=summary[summary.arm=='baseline'].set_index(['period','path','cost_mult'])
    decisions=[]
    for arm,group in summary.groupby('arm'):
        failures=[]
        more=True
        for _,row in group.iterrows():
            label=f'{row.period}/{row.path}/{row.cost_mult}x'
            if row.filled < (150 if row.period=='early' else 100):
                failures.append(label+': insufficient fills')
            if not np.isfinite(row.mean_net_r) or row.mean_net_r<=0:
                failures.append(label+': nonpositive mean')
            if row.period=='late':
                b=by_symbol[(by_symbol.arm==arm)&(by_symbol.period=='late')&(by_symbol.path==row.path)
                            &(by_symbol.cost_mult==row.cost_mult)&(by_symbol.filled>=20)]
                if len(b)<3 or (b.mean_net_r>0).sum()<=len(b)/2:
                    failures.append(label+': insufficient positive breadth')
            more &= row.filled>baseline.loc[(row.period,row.path,row.cost_mult),'filled']
        decisions.append(dict(arm=arm,more_fills_all_scenarios=bool(more),
                              verdict='RESEARCH_SHORTLIST' if not failures else 'NO_ADVANCE',
                              failures='; '.join(failures)))
    pd.DataFrame(decisions).to_csv(args.out/'decisions.csv',index=False)
    prior=pd.read_csv(ROOT/'data/results/sb_session_validation_20260917/orders.csv')
    prior=prior[(prior.clock=='seasonal_eet')&(prior.period!='supplemental')&(prior.exit=='fixed')]
    cols=[c for c in orders if c!='arm']
    sort=['symbol','period','path','cost_mult','created']
    pd.testing.assert_frame_equal(prior[cols].sort_values(sort).reset_index(drop=True),
        orders[orders.arm=='baseline'][cols].sort_values(sort).reset_index(drop=True),
        check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    card.update(complete=True,baseline_reproduced_rows=len(prior))
    run.write_text(json.dumps(card,indent=2)+'\n')
    print(pd.DataFrame(decisions)[['arm','more_fills_all_scenarios','verdict']].to_string(index=False),flush=True)


if __name__=='__main__':
    main()
