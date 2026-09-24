# Completed-session range parent: development results

**Verdict: NO_ADVANCE.** The completed-session range parent improved early-period average return but reduced fills by about half and underperformed the existing wider-window parent in the late period. The extension remained slightly negative at normal costs and clearly negative under cost stress. No live configuration or orders changed, and no prospective paper service was started.

## New parent hypothesis

Freeze the complete 00:00–09:30 New York bid-price range. Observe its first sweep/reclaim between 09:30 and 10:30, then allow up to 60 minutes for a subsequent directional displacement/FVG, with the parent closing before 11:00. A close back beyond the swept boundary invalidates the event; a later sweep does not reset it. Both-boundary bars abandon the day.

The entry remains a midpoint LIMIT with a structural stop covering event through signal, at least one ATR away, and a fixed 2R target. No extra M5 confirmation entry layer was added. Pending TTL is 45 minutes and maximum holding is 180 minutes. Rules and advancement gates were frozen before returns were computed.

## Results

Normal modeled costs. OHLC and OLHC paths agreed; agreement does not establish actual tick-level execution accuracy. Control is the unchanged 09:30–11:00 rolling sweep/reclaim midpoint variant, reused from the previously audited study.

| Period | Control fills | Control mean net R | Session-range fills | Session-range mean net R | Session-range mean at 1.5x costs |
|---|---:|---:|---:|---:|---:|
| Early, before 2025 | 148 | +0.0219R | 72 | +0.0469R | +0.0219R (72 fills) |
| Late, from Jan 8 2025 | 141 | +0.1738R | 72 | +0.1134R | +0.0928R (70 fills) |
| Extension, Jun 25–Sep 16 2026 | 17 | -0.4260R | 10 | -0.0008R | -0.1377R (9 fills) |

The new parent generated 161 / 137 / 15 covered orders across these periods, versus 311 / 271 / 30 for the control. It did not meet the user's frequency objective. Normal-cost historical returns are positive in both earlier partitions, but that alone is insufficient: the late mean falls below the control, every period misses the preregistered fill minimum, and no late symbol has 20 fills. The largest late symbol sample is BTCUSD with 17 fills and a negative mean.

The extension's near-zero normal-cost mean comes from only ten trades. The stressed scenario has a different filled set, because a wider spread can prevent a limit fill. It is not a fixed-cohort cost-only comparison. Neither scenario supplies independent evidence of an edge.

## What constrained this version

| Funnel | Early | Late | Extension |
|---|---:|---:|---:|
| Observed symbol-days in event window | 3,702 | 3,439 | 560 |
| Complete overnight ranges | 3,657 | 3,433 | 559 |
| First sweep/reclaim events | 1,538 | 1,313 | 192 |
| Events invalidated by a later close | 683 | 601 | 65 |
| Eligible parents | 162 | 139 | 15 |
| Parents with full execution coverage | 161 | 137 | 15 |
| Normal-cost fills | 72 | 72 | 10 |

Range coverage was high, so missing overnight bars did not explain most of the scarcity. In the late period, 1,313 first events produced only 139 eligible parents; 601 events were invalidated before an entry parent. The fixed event sequence and subsequent displacement/FVG requirement remain selective. The funnel is diagnostic, not evidence that loosening invalidation or expiry would help.

Ambiguous bars abandoning the day were recorded separately (28 early, 30 late, 10 extension), and can occur before or after the first event. Cost rejection counts are rejected FVG opportunities, not unique rejected days. Do not subtract all these columns as if they were mutually exclusive outcomes.

## Validation and limitations

125 tests passed, including 15 session-range tests covering complete-reference geometry, buy/sell symmetry, missing range bars, ambiguous sweeps, event invalidation, strict breaches, delayed FVG eligibility, gaps, causal prefixes, one-parent selection, costs, unchanged event age and timing limits.

The independent audit passed across 316 detected parents (313 with full lifecycle coverage), 1,252 new scenario rows, 2,448 reused control rows, 24 scenario cells and 37 source/data hashes. It independently reconstructs reference extrema and causal price context, checks displacement ATR and structural risk, verifies uninterrupted execution horizons, and reconciles controls, commissions, occupancy and result totals. No pending-at-end or marked-at-end trades remain.

All periods are **reused development data**. The extension overlaps previously examined observations; it is not independent validation. Clock interpretation remains seasonal broker-local time, supported by earlier bridge observations but not separately certified for every historical bar. Results use bid OHLC paths with fixed modeled spread/commission, not full historical quotes or a portfolio return calculation.

## Decision

Keep this parent as a documented research hypothesis, not a live improvement. It does not justify relaxing the preset gates or deploying it to increase signals. No parameter or symbol was adjusted after seeing results. Independent validation was not performed, and these developmental results do not warrant presenting it as completed.

- [Frozen specification](2026-09-18-sb-session-range-design.md)
- [Scenario summary](2026-09-18-sb-session-range-summary.csv)
- [Opportunity funnel](2026-09-18-sb-session-range-funnel.csv)
- [Detector](../../src/research/sb_session_range.py)
- [Study runner](../../scripts/sb_session_range_study.py)
- [Independent accounting audit](../../scripts/audit_sb_session_range.py)

Full artifacts: `data/results/sb_session_range_20260918/`. Reproduce with `.venv/bin/python scripts/sb_session_range_study.py --out <new-directory>`, then `.venv/bin/python scripts/audit_sb_session_range.py <new-directory>`.
