# Prospective shadow deployment

Implemented and started a separate GET-only recorder for the two frozen candidates. The localhost dashboard is http://127.0.0.1:8772 and the tmux session is `sb-shadow-20260918`.

Cohort start UTC: 2026-09-18T15:20:09.032275+00:00. Data lives in `data/shadow/sb_prospective_20260918/`, excluded from version control. No trading-controller integration or broker-order endpoint is used.

Validation: 151 unit/research tests passed. Focused adapter and dashboard tests passed after the final daily-cap and feed-health changes. The live HTML page, JSON state endpoint and CSV export returned HTTP 200. Thirteen frozen source/spec/protocol hashes matched the database manifest. Quote counts increased across repeated checks, with all nine latest quotes valid. There were no hypothetical trades at the verification point, so there are no prospective performance conclusions.

The initial smoke check was interrupted by connection errors. A separate retry ingested 16,193 bars but rejected quotes roughly 61–64 seconds behind receipt time. The persistent cohort subsequently received fresh quotes on all nine symbols; USDCAD and GBPJPY candle history remained stale/revised and those snapshots were withheld. These smoke runs are not part of prospective results.

Sampling, timing, observed-cost gates, source-clock assumptions, censored outcomes and WAL durability limits are explicitly documented in the [frozen protocol](2026-09-18-sb-prospective-protocol.md). The [runbook](../runbooks/sb-shadow.md) explains operation, exports, shutdown and restart. The service is a quote-sampled observer, not a complete tick capture or proof of broker fills.
