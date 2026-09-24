# Frozen extended-history comparison

Compare only baseline (10:00–11:00 New York) and open_window (09:30–11:00), using the existing M15 sweep/reclaim midpoint LIMIT implementation unchanged. One eligible setup per symbol/day; fixed 2R target; 45-minute pending expiry; 180-minute maximum holding period. Retain existing spread and commission assumptions, both OHLC paths, and 1x/1.5x execution costs.

Request M5 history from 2026-06-25 through the completed UTC day 2026-09-16, with June 24 warmup. Keep original CSVs untouched. Preserve bridge timestamps and tick clock observations. The bridge labels rate timestamps UTC; evaluate seasonal broker wall time only if current liquid-symbol ticks corroborate the expected +3-hour offset. Otherwise stop evaluation pending reconciliation. This is a clock plausibility check, not historical clock certification.

Split at every missing five-minute bar. Resample and construct candidates separately per uninterrupted segment; retain the daily cap across segments. Reject candidate lifecycles that could cross a gap or the data endpoint, conservatively requiring the full 45+180 minute horizon to remain covered. Report missing data and exclusions. No fills may depend on fabricated bars.

This period includes previously inspected warmup snapshots and is post-selection evidence, not an untouched holdout. No live promotion from this run. A research shortlist requires each execution scenario to have at least 100 completed fills, positive mean net R, and at least three symbols with 20 fills each, a majority of those symbols positive. Failure means NO_ADVANCE. Future truly prospective observation must begin after the frozen comparison and remain separately labelled.
