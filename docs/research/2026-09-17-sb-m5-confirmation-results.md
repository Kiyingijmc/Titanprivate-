# M5 confirmation entry: results

**Neither confirmation variant passes the frozen research criteria.** Confirmation removes losing setups, but next-open entry after the confirming move gives up enough price advantage to reduce historical late-period returns. It also reduces fills rather than increasing them. No live settings or orders were changed.

The experiment implemented one frozen entry rule: after the original M15 sweep/reclaim setup closes, require an executable midpoint touch and a directional M5 close beyond the previous M5 high/low; enter at the next open before the parent's 45-minute expiry. Retain the original absolute stop, recalculate the 2R target from actual entry, and exit after at most 180 minutes. A stop touch before confirmation invalidates the setup.

## Paired results

Normal modeled costs, OHLC path. OLHC produced identical results. Each pair uses identical parent setups and data-coverage exclusions.

| Period | NY parent window | Midpoint fills | Midpoint mean net R | Confirmation fills | Confirmation mean net R |
|---|---|---:|---:|---:|---:|
| Early, before 2025 | 10:00–11:00 | 109 | +0.0278 | 53 | +0.0557 |
| Early, before 2025 | 09:30–11:00 | 148 | +0.0219 | 69 | +0.0170 |
| Late, from Jan 8 2025 | 10:00–11:00 | 105 | +0.1674 | 61 | +0.0114 |
| Late, from Jan 8 2025 | 09:30–11:00 | 141 | +0.1738 | 80 | +0.0353 |
| Extension, Jun 25–Sep 16 2026 | 10:00–11:00 | 12 | -0.4137 | 5 | -0.0972 |
| Extension, Jun 25–Sep 16 2026 | 09:30–11:00 | 17 | -0.4260 | 6 | -0.1620 |

At 1.5x spread/commission, confirmation's early/late/extension mean net R was +0.0308 / -0.0138 / -0.1072 for the original window and +0.0100 / +0.0150 / -0.1722 for the wider window. All confirmation samples are below their preregistered minimums, and the extension remains negative. The controls' source periods are reused research data, not untouched holdouts.

## Why waiting did not solve entry quality

For the wider window's late-period normal-cost case:

- Both methods received 271 parents. Midpoint filled 141; confirmation filled 80. Confirmation did not add any new filled parent.
- Confirmation missed 61 midpoint trades with aggregate midpoint return of -20.4655R. This was useful selection in this sample.
- On the 80 shared filled parents, later entry reduced aggregate return by 42.1462R using each method's own risk denominator. The net aggregate change was -21.6807R.
- Confirmation's initial stop distance averaged 1.493 times the midpoint stop distance. With a fixed original stop, later entries require more price movement to reach their recalculated 2R targets.
- To check denominator effects, confirmation returns were also expressed in units of each original parent's risk. Total return was +3.9306 parent-R versus midpoint's +24.5069 parent-R. The deterioration therefore persists under this common scale. These pooled R totals are not account returns or a portfolio simulation.

On the extension's wider window, confirmation skipped 11 filled midpoint parents and reduced aggregate losses, but its six fills still averaged -0.1620R. Six observations cannot establish a reliable improvement.

This decomposition is descriptive accounting, not proof that the confirmation condition has a stable predictive edge. A confirmation observable only after a price move cannot be used to retrospectively select a midpoint fill at an earlier price.

## Integrity and limitations

- 91 tests passed, including 12 new tests for confirmation timing, executable bid/ask handling, long/short symmetry, no reuse of confirmation-bar extrema, expiry, gap rejection, cost gates and future-data independence.
- The independent audit checks 8,632 scenario order rows, 48 scenario cells, 31 source/data hashes, availability times, order occupancy, unchanged absolute stops, risk ratios, commissions, source-bar lifecycle coverage, actual next-open entry prices, summary totals and paired return identities.
- All 208 extension control order rows reproduce the prior frozen comparison to numerical tolerance.
- Every missing M5 bar splits the history. Indicator warmup restarts; daily caps persist across segments. Full 225-minute parent lifecycle coverage is required. This stricter coverage removes one late wider-window midpoint fill relative to the earlier frequency study (141 versus 142), so compare against the controls in this study.
- Market entry assumes next-open execution with modeled spread but no extra latency/slippage. Bid OHLC paths do not reconstruct actual ticks. Both paths agreeing does not remove those limitations.
- Seasonal broker-local timestamps are retained. The extension's observed +3-hour summer tick offset supports that interpretation; historical clock mapping is not independently certified for every bar.
- No marked-at-end or pending-at-end outcomes occur. The original midpoint execution engine was left unchanged.

## Decision and artifacts

Keep the midpoint controls and this confirmation alternative frozen as research references. Do not promote confirmation as either a frequency improvement or a proven entry-quality improvement. A further hypothesis would need its own specification and test; simply weakening this confirmation after seeing these results would add selection bias.

- [Frozen design](2026-09-17-sb-m5-confirmation-design.md)
- [Portable scenario results](2026-09-17-sb-confirmation-summary.csv)
- [Portable paired decomposition](2026-09-17-sb-confirmation-paired.csv)
- [Entry implementation](../../src/research/sb_confirmation.py)
- [Study runner](../../scripts/sb_confirmation_study.py)
- [Independent audit](../../scripts/audit_sb_confirmation.py)

Full artifacts: `data/results/sb_confirmation_20260917/`. Reproduce offline with `.venv/bin/python scripts/sb_confirmation_study.py --out <new-directory>` and audit using `.venv/bin/python scripts/audit_sb_confirmation.py <new-directory>`.
