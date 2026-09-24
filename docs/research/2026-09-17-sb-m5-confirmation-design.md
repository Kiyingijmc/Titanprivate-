# Frozen M5 confirmation experiment

Before computing returns, freeze one alternative to the midpoint LIMIT: use the same first eligible M15 sweep/reclaim parent per symbol/New York day, then require a completed M5 rejection and local break before entering at the following M5 open. Compare separately within the 10:00–11:00 and 09:30–11:00 parent windows. No parameter grid or outcome-driven retuning.

Confirmation rules:
1. Start observing at the M15 parent's close. Its original midpoint and absolute structural stop remain fixed.
2. Within the parent's exclusive 45-minute deadline, executable price must touch the midpoint (BUY: M5 bid low + spread <= midpoint; SELL: bid high >= midpoint).
3. On that bar or a later completed M5 bar, a BUY must close above its open, midpoint, and previous completed M5 high. A SELL must close below its open, midpoint, and previous M5 low. Strict inequalities apply to closes. The previous M5 bar is already closed; no future pivot identification.
4. Invalidate if any observed bar reaches the original executable stop before confirmation, including the confirmation bar. This conservatively rejects ambiguous intrabar sequences. Enter only at the next M5 open strictly before the deadline. BUY pays ask, SELL receives bid. Do not reuse the confirmation bar's extrema for trade exits.
5. Preserve the parent's absolute stop. Recompute risk and the 2R target using actual modeled entry. Reject invalid/nonpositive geometry and total spread+commission exceeding 0.25R at entry. No second parent if confirmation fails; parent selection and daily caps are identical to control.
6. Maximum holding period remains 180 minutes from entry. Test OHLC/OLHC exit paths and existing 1x/1.5x spread/commission assumptions. Market fills assume no additional latency/slippage beyond spread; results are not tick-execution proof.

Use the existing historical early (<2025-01-01), late (>=2025-01-08), and collected extension (2026-06-25 through 2026-09-16 broker dates) separately. These are reused, post-selection research data, not untouched holdouts. Split at every M5 gap, restart indicators, carry the per-day cap across segments, and require complete 225-minute parent lifecycle coverage. Apply this same coverage rule to controls. Reproduce the extension control against the prior frozen run.

Report parent count, fills, absent confirmations, invalidations, entry-cost rejections, expired controls, stop-distance change, net mean R, paired added/lost/shared parent outcomes and symbol breadth. Confirmation is not assumed to increase signal counts; this experiment tests entry quality and missed opportunities.

Shortlist only if every path/cost scenario has positive mean R, at least 150 early/100 late/100 extension fills, and late plus extension each have at least three symbols with 20 fills and a majority positive. Additionally require confirmation to improve mean R versus its paired control in every period/scenario. Passing remains a research shortlist, never automatic live authorization.
