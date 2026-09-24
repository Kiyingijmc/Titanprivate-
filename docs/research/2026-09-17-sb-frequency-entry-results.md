# M15 sweep/reclaim: increasing signals and improving entry logic

## Outcome

The most useful tested frequency change is the **09:30–11:00 New York
window with the existing midpoint limit entry**. It raises later normal-cost
fills from 105 to 142 (+35.2%) and mean net R from +0.16745 to +0.18270.
Later stressed mean is +0.16057R with 140 fills. This is a research observation,
not a deployment recommendation: early stressed economics and late breadth
still fail. None of the seven arms passes every frozen advance rule.

Shallower entries improve fill rate but hurt returns on the existing trade
population. A second daily setup contributes almost nothing. Relaxing the
sweep-to-displacement timing more than doubles fills but dilutes late results.
The tested H1 EMA20 alignment filter makes this particular variant worse.

Rules were fixed before this run: [experiment design](2026-09-17-sb-frequency-entry-design.md).
All 56 model/period/path/cost cells are preserved in the
[summary CSV](2026-09-17-sb-entry-summary.csv).

## Where signals are lost

Whole-history baseline funnel, before early/late partitioning:

| Stage | Candidates |
|---|---:|
| Sweep/reclaim pattern | 4,117 |
| In 10:00–11:00 NY window | 481 |
| Rejected by cost ceiling | 10 |
| Rejected by daily cap | 19 |
| Eligible after these checks | 452 |

The early/late partitions retain 449 candidates (243 early, 206 late).
Under normal costs, 214 fill and 235 expire. Thus roughly half of session
signals never trade. The narrow session and limit-fill probability are
substantial bottlenecks; the one-per-day cap and cost filter remove relatively
few signals inside this particular M15 session. This does not negate the
earlier finding that costs reject many M5 candidates.

## Controlled results

Each arm changes one policy relative to baseline. All retain seasonal clock,
M15 signals, fixed 2R targets, 45-minute pending TTL, 180-minute holding
limit, structural protection and 0.25R indicative cost ceiling. Entry-depth
changes preserve the absolute baseline stop, recomputing risk and target.

Normal-cost pooled results are identical across the two M5 path scenarios in
this fixed-exit experiment. Stressed means below take the worse path, not
a statistical confidence bound. Values are R per fill, not account returns.

| Arm | Early fills | Early mean | Late fills | Late mean | Early stressed mean | Late stressed mean |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 109 | +0.02778 | 105 | +0.16745 | -0.01786 | +0.14720 |
| Two setups, >=30 min apart | 109 | +0.02778 | 106 | +0.15640 | -0.01786 | +0.13612 |
| 09:30–11:00 window | 148 | +0.02193 | 142 | +0.18270 | -0.01932 | +0.16057 |
| 25% gap retracement | 133 | +0.00344 | 113 | +0.11594 | -0.04020 | +0.06950 |
| Gap-edge entry | 151 | -0.04958 | 124 | +0.06515 | -0.07351 | +0.02650 |
| Sweep within preceding four bars | 292 | +0.03883 | 252 | +0.02251 | -0.00009 | +0.00348 |
| H1 EMA20 aligned | 44 | -0.29814 | 36 | +0.01630 | -0.36987 | +0.01007 |

The widened window adds early fills as well (109 to 148) but slightly reduces
early per-fill expectancy. Early stressed fills are 146, below the unchanged
150 floor. Later normal modeled total R increases from 17.5820 to 25.9440;
this is an independently scheduled per-symbol sum, not a portfolio return.

Later widened-window breadth also fails: only US30 (26 fills), XAUUSD (23)
and BTCUSD (21) meet the >=20-fill per-symbol floor, and only US30 is positive.
The other six symbols have positive means but only 8–13 fills each. Removing
gold or crypto after seeing this is not a valid rescue of the experiment.

## Entry-price trade-off

Later normal-cost filled-trade bookkeeping, matched by symbol, signal time
and direction. Each arm still runs its own admission/occupancy schedule;
this decomposition is not a paired causal-effect or significance estimate.

| Arm | Added fills | Lost baseline fills | Mean R on added fills | Change in total R on shared fills | Overall total R change |
|---|---:|---:|---:|---:|---:|
| Two setups | 1 | 0 | -1.0034 | 0 | -1.0034 |
| Wider window | 37 | 0 | +0.2260 | 0 | +8.3620 |
| 25% retracement | 8 | 0 | +0.8181 | -11.0262 | -4.4812 |
| Gap edge | 19 | 0 | +0.3772 | -16.6701 | -9.5035 |
| Recent sweep | 151 | 4 | -0.0770 | 0 | -11.9083 |
| H1 aligned | 0 | 69 | — | 0 | -16.9952 |

The shallow-entry result is particularly useful: new fills themselves are
positive later, but worsening the entry price on existing fills costs more
than they add. Near-edge entry also increases risk distance and moves a
fixed-2R target farther away. A higher fill rate does not establish a better
entry policy. Late fill rates rise from 51.0% baseline to 54.9% at quarter-gap
and 60.2% at the edge, while mean and total net R decline.

The wider window has no displaced baseline fills in this sample; that is an
observed result, not guaranteed by its first-eligible-per-day rule. Future
09:30 candidates can still preempt 10:00 candidates. The recent-sweep arm
adds many weak later fills. The H1 result rejects the tested completed-bar
EMA20 rule here, not every possible use of higher-timeframe context.

## Development consequence

For the next independent-data experiment, preserve the midpoint entry,
structural stop and fixed exit; compare 09:30–11:00 against 10:00–11:00.
Do not automatically stack shallower entries, a looser sweep and H1 filtering.
No arm has earned live enablement or a lower acceptance threshold.

A distinct later hypothesis could use an M5 trigger inside an M15 setup,
with one parent setup, explicit invalidation and no repeated firing on the
same sweep. Market-on-confirmation could also address missed limits, but
requires genuine next-quote fills, slippage and stop-distance repricing.
Neither is implemented or claimed to work by this experiment.

## Verification and limits

**79 tests passed**, including baseline detector parity, long/short entry
geometry, absolute-stop preservation, cost-before-cap ordering, expanded
session timing, distinct setups, recent-sweep continuity, prefix invariance,
and H1 availability/staleness. Existing execution/session/variant/placebo
regressions also pass.

The previous seasonal baseline reproduces 1,796 scenario order rows within
1e-12 numerical tolerance. The independent analysis checked 18 source/data
hashes, 14,948 order rows, 56 summary cells, chronological occupancy,
commission accounting, signal availability, aggregate identities and the
added/lost/shared-fill return decomposition. Four marked filled tails occur
across the repeated scenario cells; they are terminal marks, not realized P&L.

Data and modeling limitations remain: reused 2023–2026 history, post-selection
research, inferred historical broker clock, indicative fixed spreads,
idealized M5 paths, no tick slippage/volume constraints/news/portfolio
allocation, and no fresh holdout. Seven arms are seven additional attempted
models; frozen tests do not remove selection bias from the larger research
process. No conclusion that this is profitable live follows.

Implementation: `src/research/sb_entries.py`, `scripts/sb_entry_study.py`,
`scripts/sb_entry_analysis.py`, `tests/unit/test_sb_entries.py`.

```bash
.venv/bin/python -m unittest tests.unit.test_sb_entries tests.unit.test_sb_sessions \
  tests.unit.test_sb_variants tests.unit.test_sb_execution \
  tests.unit.test_sb_legacy_execution_difference tests.unit.test_sb_component_diagnostic \
  tests.unit.test_exp0_coinflip tests.unit.test_sb_overlay
.venv/bin/python scripts/sb_entry_study.py --out data/results/sb_entry_study_NEW
.venv/bin/python scripts/sb_entry_analysis.py data/results/sb_entry_study_NEW
```

Primary artifacts: `data/results/sb_entry_study_20260917/` (gitignored),
containing orders.csv, summary.csv, by_symbol.csv, decisions.csv, run.json,
incremental.csv and audit.json. A fresh output directory is required.
Summary SHA-256:
`9df74edc109e150ba756797c681bdd2a160fc0b9ce77d555b21798306e552c58`.
