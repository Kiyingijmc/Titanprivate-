# Frozen confirmation-then-retest experiment

Hypothesis: after the same M5 confirmation as the prior experiment, a fresh midpoint LIMIT may recover entry price at the cost of missed trades. This is a single new entry policy, not a parameter search or a signal-frequency claim.

Use exactly the parents and scenarios recorded in the completed `sb_confirmation_20260917` study: two New York parent windows, early/late/extension data, OHLC/OLHC paths and 1x/1.5x costs. Verify its recorded source/data hashes before use. Retain its midpoint and immediate-confirmation rows as frozen controls; report this as control reuse, not a new independent experiment. All data has already been inspected.

New policy:

1. Observe only M5 bars beginning at the M15 parent close. Require executable midpoint touch and a directional M5 close beyond the previous completed M5 high/low, exactly as in the prior confirmation study. The parent absolute stop invalidates a setup if reached before or within the confirming bar; this conservatively handles unknown intrabar order.
2. Only after that confirming M5 close, submit a new LIMIT at the original midpoint. A pre-confirmation touch cannot fill this order. Keep original absolute stop, original risk distance and 2R target.
3. Retain the parent's original exclusive 45-minute expiry. Do not grant another 45 minutes after confirmation. No market fallback, second parent, revised stop or re-entry. A confirmation at the expiry boundary is too late.
4. At submission, reject spread+commission above 0.25 of the original risk. Model BUY fills on ask and SELL fills on bid, with the existing conservative requested-price LIMIT convention. The order is considered resting before the next M5 open. Gaps through its stop after submission therefore fill and stop at the adverse executable opening quote; do not avoid these losses by using the next open to cancel retroactively.
5. Preserve the existing 180-minute holding period, fixed exit, complete 225-minute parent lifecycle coverage and per-parent occupancy. No live broker calls or live settings changes.

Report fills, no-confirmation and invalidation counts, submitted-but-expired limits, cost rejections, added/lost/shared parent results against both controls, and mean/total modeled R. Retest risk must equal midpoint risk. Use original parent-risk units as a common denominator when comparing immediate-confirmation returns.

Shortlist only if every execution scenario is positive, improves mean net R versus both controls, has at least 150 early/100 late/100 extension fills, and late plus extension each have at least three symbols with 20 fills and a majority positive. Otherwise NO_ADVANCE. Even a shortlist would require independent prospective evidence before live consideration. Do not weaken these criteria in response to results.
