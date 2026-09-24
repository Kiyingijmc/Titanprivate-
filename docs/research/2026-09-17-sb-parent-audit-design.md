# Parent-setup diagnostic plan

This diagnostic changes no strategy parameters and tests no new trading arm. Use the frozen midpoint controls from `sb_confirmation_20260917` and verify their source/data/artifact hashes. Reconstruct the same gap-separated M15 data and independently reconcile selected parents by symbol/time/direction.

Measure cumulative opportunity counts: sufficiently warmed M15 closes, directional FVG, middle-bar displacement with valid geometry, exact sweep/reclaim parent, New York window, normal-cost eligibility, daily cap, full lifecycle coverage, LIMIT fill. Report both parent windows and all three historical partitions. Daily cap precedes lifecycle exclusion, as in the frozen study. Never count the two windows as independent samples. Report observed eligible session days as a data-coverage denominator, not an exchange-calendar completeness claim.

For unchanged midpoint outcomes, report symbol and calendar-quarter returns, buy/sell breakdowns, leave-one-symbol-out means, and mean after removing the five largest individual gains. Preserve both intrabar paths and both modeled cost scenarios. No symbol exclusions or new filters will be selected based on these summaries.

Calculate descriptive 95% percentile intervals for mean net R using 2,000 calendar-week cluster resamples with seed 17092026. Aggregate all symbols in the same New York parent-signal week and resample whole weeks jointly; include zero-trade calendar weeks between the first and last candidate. This preserves within-week cross-symbol co-movement, but does not establish independence across weeks or correct for repeated strategy selection. These are exploratory uncertainty estimates, not proof of an edge or formal promotion criteria.

End with a recommendation on whether to continue tuning this parent, collect independent prospective observations, or formulate a separately specified parent hypothesis. Do not relax prior promotion gates or claim historical subgroup selection is validation.
