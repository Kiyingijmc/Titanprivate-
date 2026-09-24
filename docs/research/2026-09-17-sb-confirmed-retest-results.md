# Confirmation followed by a fresh midpoint LIMIT

**The delayed retest entry remains NO_ADVANCE in both windows.** It restores the original midpoint entry price, stop distance and 2R target when filled, but misses roughly half of confirmed opportunities. It does not solve the signal-frequency or return problem. No live broker calls, orders or settings changes were made.

A LIMIT becomes active only after the completed M5 confirmation. It cannot claim the earlier touch that helped establish confirmation. Its deadline remains 45 minutes after the M15 parent close, and its maximum holding period remains 180 minutes after its own fill. Gaps through the stop after submission are realized as adverse fills/stops, not retrospectively avoided.

## Comparison

Normal modeled costs; both tested OHLC paths agree. Each cell reports filled trades and mean net R. Controls are reused, hash-verified rows from the previous confirmation study; this is not new independent evidence.

| Period | New York parent window | Original midpoint | Immediate M5 confirmation | Confirmed midpoint retest |
|---|---|---:|---:|---:|
| Early, before 2025 | 10:00–11:00 | 109 / +0.0278R | 53 / +0.0557R | 26 / +0.0826R |
| Early, before 2025 | 09:30–11:00 | 148 / +0.0219R | 69 / +0.0170R | 33 / -0.0018R |
| Late, from Jan 8 2025 | 10:00–11:00 | 105 / +0.1674R | 61 / +0.0114R | 28 / +0.0354R |
| Late, from Jan 8 2025 | 09:30–11:00 | 141 / +0.1738R | 80 / +0.0353R | 39 / +0.0179R |
| Extension, Jun 25–Sep 16 2026 | 10:00–11:00 | 12 / -0.4137R | 5 / -0.0972R | 3 / -0.0873R |
| Extension, Jun 25–Sep 16 2026 | 09:30–11:00 | 17 / -0.4260R | 6 / -0.1620R | 3 / -0.0873R |

For the wider window's late period, 80 confirmations led to 80 submitted limits: 39 filled and 41 expired. The normal-cost return per fill was lower than either control. In the extension, both retest windows happened to fill the same three parents; this is not six independent observations.

On the 39 late-period parents shared with immediate confirmation, retest improved aggregate modeled return by 8.4621R using each policy's own risk scale. But it missed 41 immediate-confirmation trades worth +10.5898R, leaving a net change of -2.1278R. Using the original parent risk as a common denominator, retest totaled +0.6985 parent-R versus immediate confirmation's +3.9306 parent-R. Better prices on the trades that returned did not compensate for missed opportunities.

## Cost stress and interpretation

At 1.5x spread/commission, early/late/extension retest means were +0.2657 / +0.0881 / -0.0986R for the original window and +0.1868 / +0.0842 / -0.0986R for the wider window. These higher historical means do **not** show that higher trading costs help: stressed costs change confirmation eligibility, reject more orders at the 0.25R submission cost ceiling, and change limit fills. For example, the wider late arm rejects 11 submissions for cost and fills 34 trades under stress versus 39 normally. These are different admitted trade sets, not a fixed-cohort sensitivity analysis.

All retest samples fall below the frozen minimums of 150 early and 100 late/extension fills; extension returns remain negative; neither arm consistently improves over both controls. Shortlist requirements were left unchanged.

Returning to the midpoint solves the entry-price arithmetic but does not guarantee a favorable subsequent move. Waiting for confirmation and then another touch also narrows an already sparse strategy. The result does not support adding this sequence to live entry logic.

## Validation and reproducibility

105 tests passed, including 14 new tests for post-confirmation eligibility, unchanged expiry, remaining TTL, bid/ask fills, long/short symmetry, adverse gaps, cost rejection, uninterrupted coverage, holding deadlines and future-data independence.

The independent artifact audit passed across 12,948 scenario order rows (4,316 new retest rows and 8,632 reused controls), 72 scenario cells and 39 hashes. It checks source/data/control hashes, reused control rows, summary accounting, occupancy, executable confirmation conditions, preserved entry/risk, commission, post-confirmation fill timestamps, original expiry and paired added/lost/shared trade identities. Full study artifacts are in `data/results/sb_confirmed_retest_20260917/`.

Data periods, timestamp assumptions and gap handling are unchanged from the previous study. All periods are reused research observations, including the extension. Results use idealized bid OHLC paths with modeled spread and commission, not actual historical tick fills or a portfolio/account-return simulation. No prospective paper-trading service was started.

- [Frozen design](2026-09-17-sb-confirmed-retest-design.md)
- [Scenario summary](2026-09-17-sb-confirmed-retest-summary.csv)
- [Paired trade decomposition](2026-09-17-sb-confirmed-retest-paired.csv)
- [Entry implementation](../../src/research/sb_confirmed_retest.py)
- [Study runner](../../scripts/sb_confirmed_retest_study.py)
- [Audit script](../../scripts/audit_sb_confirmed_retest.py)

Reproduce with `.venv/bin/python scripts/sb_confirmed_retest_study.py --out <new-directory>`, then `.venv/bin/python scripts/audit_sb_confirmed_retest.py <new-directory>`. The runner refuses changed parent-study sources, data or audited artifacts.

The tested confirmation entry branch should remain frozen. Further work should first reassess the parent setup's opportunity count and stability, rather than add another entry condition to this same sparse sample.
