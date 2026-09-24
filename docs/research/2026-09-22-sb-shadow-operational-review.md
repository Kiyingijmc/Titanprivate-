# SilverBullet shadow operational review — 2026-09-22

## Decision

The prospective cohort does not support a strategy-performance conclusion. Restore and verify observation coverage before changing signal frequency or entry rules. Keep the existing strategy and cohort manifest frozen.

## Observations

Read-only inspection of `data/shadow/sb_prospective_20260918/shadow.sqlite3` found:

- Recorder metadata reported RUNNING, with a heartbeat approximately 60 seconds old at inspection.
- Zero hypothetical trade rows and only 154 decision rows: each candidate had 75 OUTSIDE_WINDOW decisions; session_range had two NO_SESSION_SWEEP decisions and wider_midpoint had two NO_FVG decisions.
- 19,673 stored bars. Recent events repeatedly reported BAR_REVISION across symbols.
- Latest inspected quotes were rejected as STALE_QUOTE, approximately 57,450 seconds (16 hours) behind receipt time.
- A subsequent fresh bridge diagnostic failed with BrokerConnectionError for EURUSD, GBPJPY and BTCUSD. Output: `data/results/sb_shadow_review_20260922/feed_diagnosis.json`.

These are observations taken during the review, not an atomic final cohort export. A RUNNING heartbeat establishes process activity, not a healthy feed.

## Recorder limitation

The current adapter rejects an entire incoming candle snapshot when any overlapping bar differs from its immutable stored OHLC values. This can suppress future evaluation while the conflicting historical bar remains in the snapshot. Existing BAR_REVISION events identify the symbol but do not preserve the conflicting values, so they cannot establish whether the cause was a genuine correction, provisional data, or numeric representation.

The new read-only diagnostic compares fresh bridge bars against the stored originals and reports conflict timestamps and values. Connection failures prevented that comparison in this review. No tolerance adjustment or correction policy is justified by the available evidence yet.

## Recovery sequence

1. Establish fresh, advancing bridge quotes and completed candles during market activity. Repeat the diagnostic to capture actual conflicting OHLC values.
2. Use those examples to test a correction-handling policy, including rejection of stale/forming data and preservation of the information available at each decision. Do not retroactively generate trades during missing coverage.
3. If recorder source or observation policy changes, stop and preserve this cohort, then start a separately named cohort with a new manifest after verification. Never resume this directory with changed hashes.
4. Assess strategy results only after adequate valid prospective observations under the frozen protocol. Zero trades during this collection failure is not evidence of low signal frequency or poor expectancy.

No strategy rules or recorder source were changed during this review. The diagnostic uses the existing GET-only feed wrapper and a read-only SQLite connection; no orders were submitted by this review.
