# Frozen signal-frequency and entry experiment

Question: can the seasonal-clock M15 sweep/reclaim generate more useful
filled trades without sacrificing robustness? Written before reading results.
This is post-selection exploratory research on reused history, not a new
independent holdout. No production changes or automatic promotion.

Baseline: existing sweep/reclaim, gap midpoint LIMIT, structural stop,
10:00–11:00 NY, first cost-eligible candidate per symbol/day. Same nine
symbols, early/late split (2025-01-01 / 2025-01-08), fixed 2R target,
45-minute pending TTL, 180-minute holding limit, normal and 1.5x spread AND
commission, two M5 paths. Source-supported seasonal EET/EEST clock remains
an inference pending historical raw-epoch verification.

Seven arms, no combinations or parameter search:

1. `baseline`: unchanged reference; reproduce the previous seasonal fixed rows.
2. `two_setups`: admit up to two distinct setup timestamps per NY date, at
   least 30 minutes apart. Same session and midpoint entry. Each detector
   timestamp has its own sweep at i-2. One pending/open slot still applies;
   a candidate admitted while busy consumes the session allowance.
3. `open_window`: extend admission to 09:30–11:00 NY, first eligible per day.
   Tests whether the original one-hour window excludes useful opportunities.
4. `quarter_retest`: LIMIT 25% into the gap from its near edge, instead of
   50%. Preserve the baseline absolute stop; recompute risk, target and cost
   eligibility. More fills can also mean worse entry prices and further targets.
5. `edge_retest`: LIMIT at the near edge (0% depth), same stop treatment.
   Comparator for fill probability versus entry quality, not a market order.
6. `recent_sweep`: permit the reclaim at any of the four bars before the
   displacement candle (i-2 through i-5), rather than exactly i-2. It must
   sweep/reclaim the preceding 12-bar range. Choose the most recent qualifying
   sweep; all bars through signal must be contiguous. Stop beyond the full
   sweep-to-signal structure plus 0.1 ATR, minimum 1 ATR. Midpoint entry and
   original session/daily cap. This changes setup timing and its structural
   risk, not the displacement threshold.
7. `h1_aligned`: baseline plus completed H1 close above rising EMA20 for BUY,
   below falling EMA20 for SELL. EMA needs 20 bars and a prior EMA; reject
   neutral, missing or >60-minute-old H1 context. H1 bar close must be no
   later than signal availability. This is a quality comparator, not a
   frequency-increase claim.

All arms keep the 0.25R indicative cost ceiling. Candidates rejected by cost
or alignment do not consume session allowance. Signal generation never uses
future highs/lows. NY first-signal rules apply before occupancy. Report the
funnel (pattern, in-window, cost, alignment, cap, eligible, busy, filled,
expired), early/late fills, fill rate, mean and total net R, PF and breadth.
Do not call more emitted signals more opportunity if fills/returns deteriorate.

Preliminary advance still requires >=150 early and >=100 late fills, positive
early/late means under EVERY cost/path scenario, and positive late means for
a majority of adequately sampled symbols (>=20 fills each, at least three
such symbols). These are shortlist criteria, not proof of significance.
For frequency improvement also require more early AND late fills than baseline
under both paths and costs. Report all failures; do not combine winners now.

Deferred: market-on-confirmation and stop-entry models need explicit next-quote
fills/slippage; do not disguise them as guaranteed limit fills. M5 triggers
inside an M15 zone require a parent/child setup lifecycle and a separate study.
Longer pending TTL is not presumed better: it changes adverse selection.
Multiple testing remains a risk even with frozen experiments:
https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf .
