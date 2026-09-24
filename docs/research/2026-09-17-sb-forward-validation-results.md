# Extended-history window comparison

The wider window generated more signals but did not reproduce its earlier positive returns. Both frozen variants remain **NO_ADVANCE**. No live strategy configuration or orders were changed; no ongoing paper-trading service was started.

## Results

Nine symbols; June 25–September 16, 2026 broker-local bar dates. M15 sweep/reclaim, midpoint LIMIT, fixed exits. Normal-cost results below; OHLC and OLHC paths agreed.

| Variant, New York time | Eligible orders | Filled | Expired | Mean net R | Total modeled R | Mean net R, 1.5x costs |
|---|---:|---:|---:|---:|---:|---:|
| Baseline, 10:00–11:00 | 22 | 12 | 10 | -0.4137 | -4.9640 | -0.4264 |
| Wider window, 09:30–11:00 | 30 | 17 | 13 | -0.4260 | -7.2418 | -0.4431 |

The wider window produced 36.4% more eligible orders and 41.7% more fills, but those additional opportunities did not improve aggregate returns. Each scenario contains only 12 or 17 fills, well below the frozen 100-fill threshold. No symbol meets the 20-fill breadth threshold. These results do not establish a robust negative edge either; they do remove support for promoting the variant on the earlier attractive averages alone. R is simulated return divided by initial price risk, not an account return.

## Collection and clock evidence

Read-only MT5 bridge collection returned 161,458 M5 rows across EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30 and BTCUSD. Raw timestamps, tick volume and spread points are preserved in separate CSVs. Original history files were untouched. Existing fixed spread/commission assumptions remain in the simulation; recorded bar spread points were not substituted for executable historical quotes.

At capture, EURUSD and GBPUSD ticks were approximately 10,798 seconds ahead of UTC despite carrying UTC labels. This corroborates broker-local summer wall time (+3 hours). It is not full certification of historical timestamps. The frozen protocol described a completed UTC day; actual filtering uses broker-local dates, consistent with the existing signal implementation. The endpoint is consequently three hours earlier than UTC midnight. All analyzed session windows are earlier in the day and unaffected by that endpoint difference.

Downloaded data has gaps. Each missing M5 bar starts a separate segment, resetting indicator warmup; short segments are excluded. Daily signal caps persist across segments. Every included candidate has a fully covered 225-minute lifecycle horizon. There were zero additional horizon exclusions after candidate selection. This strict gap handling differs from the older full-history screen, so absolute signal rates across those studies are not directly comparable.

Previously inspected July–September warmup snapshots overlap this interval. This is later-period, post-selection evidence, **not an untouched holdout or prospective paper-trading result**.

## Verification and artifacts

The existing 79 research/strategy tests passed. An independent artifact audit verified 10 source/configuration hashes, nine data hashes, all 208 scenario order rows, uninterrupted lifecycle horizons, non-overlapping order occupancy, and summary totals. No marked-at-end positions or pending-at-end orders remain.

- Frozen protocol: [design](2026-09-17-sb-forward-validation-design.md).
- Reproducible collector/evaluator: [script](../../scripts/sb_forward_validation.py).
- Portable results: [summary CSV](2026-09-17-sb-forward-summary.csv).
- Full local artifacts: `data/results/sb_forward_validation_20260917/`, including collection metadata, raw data, coverage, orders, per-symbol results, decisions and audit.

Offline replay: `.venv/bin/python scripts/sb_forward_validation.py --out data/results/sb_forward_validation_20260917 --evaluate-only`.

## Decision

Keep both variants research-only. Wider trading hours address opportunity count, but have not demonstrated reliable entry quality. Preserve these frozen rules as controls. A subsequent entry experiment should test one separately specified M5 confirmation trigger against midpoint entry, with explicit missed-trade, execution-cost and stop-distance accounting; it should not tune filters to rescue this small losing sample. Any genuinely prospective evaluation must use observations collected after this study and be reported separately.
