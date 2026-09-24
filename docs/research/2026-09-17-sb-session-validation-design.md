# M15 sweep/reclaim: frozen session validation

This follow-up keeps the first screen's M15 sweep_reclaim detector, 10–11
a.m. NY admission, cost filter, three-bar pending TTL, twelve-bar holding
deadline, fixed/runner exits, two execution paths and normal/1.5x costs.
No detector thresholds or sample floors change. Selecting this hypothesis
after inspecting the 60-model screen makes this post-selection research.

Before measuring new returns, compare exactly three clock interpretations:
fixed UTC+2 (baseline reproduction), fixed UTC+3 (sensitivity), and seasonal
EET/EEST via Europe/Helsinki (source-supported candidate correction).
Ambiguous/nonexistent broker-local times are rejected, never guessed. NY
conversion uses America/New_York, including the weeks when US and European
DST transitions differ. Select on signal CLOSE time, first eligible per NY day.

Evidence for seasonal time: FBS documents GMT+3 from the last Sunday in March
and GMT+2 from the last Sunday in October:
https://fbs.com/trading/trading-hours?lang=en . Its trading conditions also
say platform time is generally GMT+2/GMT+3 and may change. This is evidence
for a model, not complete historical server/account timestamp certification.
Local EURUSD warmup snapshot last-bar timestamps are ~2.94–2.98 hours ahead
of UTC-stamped snapshot directory names on July 28, August 7 and September 16.

Historical evaluation keeps the previous early/late split and nine symbols.
Report every clock, path, cost and exit; never choose the most profitable clock.
Verify fixed+2 reproduces the previous M15/session/sweep schedule exactly.

Also inventory and test unused post-history M5 warmup snapshots (July–September
2026). These are a limited supplemental dataset, not continuous new market
history or a pristine independent source. Copy completed bars only using the
capture directory's UTC timestamp and source-supported seasonal broker clock.
Drop ambiguous times. Remove exact duplicate candles; discard any timestamp
whose OHLC conflicts across snapshots. Never fabricate missing candles.

Split at EVERY missing M5 interval. Each continuous segment bootstraps anew
(50 complete M15 bars minimum before a signal); its final unclosed positions
are marked and reported separately. Exclude marked returns from the
closed-trade supplemental mean and disclose both. Use seasonal clock only
on this summer supplemental set; do not select a clock by its returns.
The documented first-eligible-per-day rule applies across all segments of a
symbol, including candidates skipped by occupancy. No journal-tick reconstruction:
the journal samples ticks and cannot certify complete execution paths.

No promotion based on this follow-up. A candidate still needs positive,
sufficiently sampled early/late stress and breadth evidence, then verified
execution and forward observation. A timing correction cannot waive the
original sample/economics failures. No live strategy changes.
