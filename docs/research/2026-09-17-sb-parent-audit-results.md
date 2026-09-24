# Parent setup: opportunity and stability audit

**Keep this parent research-only and stop adding confirmation filters to it.** Its main frequency bottleneck is the narrow sweep/reclaim pattern and session requirement, not the daily cap. Its positive late-period result is distributed across several symbols, but fails to persist across earlier and newer periods. This diagnostic changes no trading rules and establishes no new profitable strategy.

## Where opportunities disappear

The table follows the wider 09:30–11:00 New York window through the unchanged M15 parent pipeline. Before the session stage, counts cover all hours. Stages are cumulative; “displacement/geometry” also requires valid midpoint and stop geometry. Counts pool nine symbols and must not be interpreted as independent observations.

| Stage | Early: before 2025 | Late: from Jan 8 2025 | Extension: Jun 25–Sep 16 2026 |
|---|---:|---:|---:|
| M15 closes after required warmup | 187,516 | 176,187 | 28,739 |
| Directional FVG | 39,766 | 37,016 | 5,967 |
| Middle-bar displacement and valid geometry | 12,757 | 12,440 | 1,991 |
| Exact sweep/reclaim | 1,130 | 1,143 | 168 |
| Inside parent window | 349 | 292 | 37 |
| Normal-cost eligible | 333 | 282 | 30 |
| After one-parent daily cap | 314 | 275 | 30 |
| Complete execution horizon | 311 | 271 | 30 |
| Midpoint LIMIT fills | 148 | 141 | 17 |

In the late period, the exact sweep/reclaim requirement removes 90.8% of displacement/geometry candidates; the session requirement then removes 74.5% of those remaining. The daily cap removes just seven cost-eligible parents, or 2.5%. Another four fail uninterrupted lifecycle coverage. The midpoint fills 52.0% of covered parents.

These counts locate scarcity; they do **not** demonstrate that removing the sweep or session conditions would improve returns. The earlier “recent sweep” experiment already increased fills while substantially weakening late-period mean return. Relaxing constraints is not a substitute for establishing predictive value.

The wider window has 3,659 / 3,436 / 559 observed eligible symbol-session days in the three periods. Normal-cost fills per 100 such days are approximately 4.04 / 4.10 / 3.04. A day is counted if the local data contains at least one sufficiently warmed M15 close inside the window. This denominator measures observed data coverage, not complete exchange-calendar coverage. The nine symbols, and the two overlapping windows, are not independent samples.

## Does one symbol explain the result?

For the wider window at normal modeled costs:

| Period | Symbols with positive mean / symbols with fills | Mean after removing any one symbol |
|---|---:|---:|
| Early | 3 / 9 | -0.0538R to +0.0701R |
| Late | 7 / 9 | +0.1248R to +0.2445R |
| Extension | 1 / 6 | -0.7412R to -0.3403R |

The late result is not explained by a single winning symbol. Conversely, excluding any one symbol does not rescue the extension. Early performance is fragile: removing BTCUSD makes the pooled early mean negative. Choosing a symbol list from these observations would be another fitted strategy, not validation.

Only three late-period wider-window symbols have at least 20 fills: US30 (26, positive), XAUUSD (23, negative), and BTCUSD (21, negative). Thus the apparently broad 7-of-9 positivity comes mostly from small per-symbol samples and still fails the previously frozen breadth requirement.

## Stability through time and uncertainty

Normal-cost wider-window quarter means during the late historical period were +0.2653R, +0.2498R, +0.2346R and +0.1410R in 2025 Q1–Q4, then +0.2386R in 2026 Q1 and -0.1622R in the available portion of 2026 Q2. The extension's 2026 Q3 observations averaged -0.4668R across 16 fills. These are differently sized, partially covered quarters; the sequence suggests instability but does not prove a specific market-regime cause.

Both BUY and SELL were positive in the late wider-window period (+0.1995R and +0.1518R). Both were negative in the extension (-0.2326R and -0.5979R). A simple direction switch is therefore not supported by this audit.

The diagnostic resamples complete New York calendar weeks jointly across symbols, using 2,000 resamples and a fixed seed. Unfilled parents do not dilute the per-fill denominator; zero-trade calendar weeks between the first and last parent are retained.

| Wider window | Mean net R | Descriptive 95% weekly-bootstrap interval |
|---|---:|---:|
| Early, normal costs | +0.0219R | -0.1552R to +0.1867R |
| Late, normal costs | +0.1738R | +0.0122R to +0.3358R |
| Extension, normal costs | -0.4260R | -0.9260R to +0.0517R |
| Late, 1.5x costs | +0.1521R | -0.0094R to +0.3194R |

The late normal-cost interval is above zero in this descriptive calculation; the stressed interval crosses zero. These intervals do not correct for the many hypotheses already examined, do not establish independence between weeks, and do not validate a selected strategy. The extension is too small to establish a reliable negative edge either. No live promotion follows from these intervals.

## Recommendation

1. Preserve the original midpoint parent and all tested variants as frozen research controls. No tested confirmation branch has earned promotion.
2. If retaining this parent, evaluate it on genuinely prospective observations with the existing execution and breadth gates. Do not count these reused historical partitions as new validation.
3. If designing a replacement parent, specify a separate hypothesis about the liquidity event and subsequent displacement before computing returns. Merely moving the sweep farther back or adding entry filters has already failed to establish a stable improvement here. Keep any new hypothesis and its evaluation distinct from this parent.

The actionable finding is to move research effort from entry mechanics to the parent hypothesis and independent evidence. Raising a daily cap is unlikely to materially improve frequency for this particular parent.

## Verification and artifacts

110 tests passed, including five diagnostic tests for frozen date boundaries, weekly grouping of correlated symbols, non-dilution by unfilled orders, empty-fill uncertainty handling, and removing gains without accidentally removing losses.

The final diagnostic reconstructs 1,079 unique parent rows and reconciles their symbol, window, period, time, direction, entry and risk against the frozen controls. It reuses 4,316 midpoint scenario rows across costs and intrabar paths. The accounting audit checks the funnel, subgroup totals, sensitivity calculations, source/data hashes and artifact integrity.

- [Frozen diagnostic plan](2026-09-17-sb-parent-audit-design.md)
- [Opportunity funnel](2026-09-17-sb-parent-funnel.csv)
- [Symbol results](2026-09-17-sb-parent-by-symbol.csv)
- [Quarter results](2026-09-17-sb-parent-by-quarter.csv)
- [Weekly intervals](2026-09-17-sb-parent-weekly-intervals.csv)
- [Diagnostic runner](../../scripts/sb_parent_audit.py)
- [Accounting audit](../../scripts/audit_sb_parent_results.py)

Final artifacts: `data/results/sb_parent_audit_20260917_final/`. An initial diagnostic directory is explicitly marked superseded after correcting gain-removal handling. No existing strategy/research engine or live configuration was modified.

Reproduce with `.venv/bin/python scripts/sb_parent_audit.py --out <new-directory>`, then `.venv/bin/python scripts/audit_sb_parent_results.py <new-directory>`.
