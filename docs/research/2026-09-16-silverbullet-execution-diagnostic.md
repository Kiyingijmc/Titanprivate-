# SilverBullet execution-consistent diagnostic

Date: 2026-09-16. Research-only simulator; no live trading settings or previous
research engines are changed.

## Run specification (written before measurement)

Use the previous component diagnostic's nine symbols, H1 candidates, ATR10
stop, initial 2R target, four admission filters and four exit models. Keep
the historical collector's bias window and grading clock fixed. This tests
execution assumptions, not a new signal or a fresh holdout.

Replay the original M5 BID bars beneath each H1 signal on both O-H-L-C and
O-L-H-C continuous paths. These are sensitivity scenarios, **not guaranteed
upper/lower bounds**. Their event ordering is explicit, but actual tick paths
can cross levels repeatedly and behave differently from both scenarios.

Execution specification:

- Signals become available at H1 close; never trade in the signal's own bar.
- BUY LIMIT fills when ASK reaches entry; SELL LIMIT when BID reaches entry.
  ASK is modeled as BID plus a fixed indicative spread. Gap-through limits
  fill at the requested price with no favorable improvement.
- Long SL/TP and management use BID; short SL/TP and management use ASK.
  Stops crossed at a new bar's open execute at that quote, allowing losses
  beyond 1R. TP gaps receive the target price, with no favorable improvement.
- For a jump at a bar open, resting broker SL/TP acts before software
  management. Along continuous segments, crossed events act in price order.
  Pre-fill extremes cannot trigger post-fill exits.
- Each exit arm schedules its own single pending/open position per symbol.
  A slot releases at the end of its exit M5 bar, so a new H1 signal at that
  close can be admitted. Pending orders expire at 12 wall-clock hours, with
  the expiry boundary excluded from fills, including across session gaps.
- Ratchet stages: 0.764R, 1.236R, 1.772R. Partial closes are 30% of current
  volume, then 50% of the remainder. Runner removes TP at stage 3, trails
  by 0.536R, and tightens to 0.2R after 0.402R giveback from its high-water
  mark in the tight-runner arm. Stops never loosen.
- Primary run uses the live helper's 3-pip break-even buffer. An attempted
  BE stop beyond the current quote is rejected and counted. Broker-specific
  minimum stop distance and price/lot rounding remain unmodeled.
- R denominator is the planned entry-to-stop distance. Prices already
  incorporate spread: subtract **commission only**, $7 per round-turn lot.
  Charging the old flat spread deduction too would double-charge spread.
- Unclosed filled positions are marked at the final executable close and
  tagged MARKED_AT_END; pending orders are tagged separately. Terminal marks
  include the full exit commission reserve and are not called realized P&L.
- Zero latency, instantaneous acknowledgments and fractional-volume partials
  remain idealizations. No swap, news, portfolio caps, risk sizing or competing
  strategies are simulated. Do not interpret pooled R as account performance.

Default run: 1x indicative spread, live BE buffer, both paths, all nine symbols.
No threshold optimization or GO/NO-GO verdict. Any additional run must be
labeled a sensitivity; comparing this model with the old H1 replay changes
several execution assumptions simultaneously and cannot isolate one defect's
individual effect.

Runner: `scripts/sb_execution_diagnostic.py`; core: `src/research/sb_execution.py`.
The legacy `poc_sb_stops.py`, `sb_component_diagnostic.py` and generic backtest
resolver are preserved for historical reproducibility.

## Results

Primary run completed across all nine symbols and 32 filter/exit/path arms
(288 separate symbol schedules). **Every pooled arm is negative under both
M5 orderings.** The prior positive managed-exit headline does not reproduce
under this execution model.

| Filter | Exit | O-H-L-C mean net R | O-L-H-C mean net R | Filled trades O-H-L-C / O-L-H-C |
|---|---|---:|---:|---:|
| Raw | Fixed 2R | -0.1415 | -0.1253 | 1,846 / 1,846 |
| Raw | Ratchet | -0.1196 | -0.0958 | 1,856 / 1,856 |
| Raw | Runner | -0.1189 | -0.0933 | 1,854 / 1,856 |
| Raw | Tight runner | -0.1164 | -0.0933 | 1,856 / 1,856 |
| Bias | Fixed 2R | -0.1422 | -0.1244 | 1,354 / 1,354 |
| Bias | Ratchet | -0.1258 | -0.0922 | 1,358 / 1,358 |
| Bias | Runner | -0.1266 | -0.0890 | 1,356 / 1,358 |
| Bias | Tight runner | -0.1241 | -0.0896 | 1,358 / 1,358 |
| Grade | Fixed 2R | -0.1539 | -0.1321 | 1,374 / 1,374 |
| Grade | Ratchet | -0.1397 | -0.1017 | 1,380 / 1,379 |
| Grade | Runner | -0.1411 | -0.0994 | 1,379 / 1,379 |
| Grade | Tight runner | -0.1378 | -0.0997 | 1,380 / 1,379 |
| Bias + grade | Fixed 2R | -0.1538 | -0.1335 | 1,183 / 1,183 |
| Bias + grade | Ratchet | -0.1403 | -0.1045 | 1,186 / 1,186 |
| Bias + grade | Runner | -0.1432 | -0.1020 | 1,185 / 1,186 |
| Bias + grade | Tight runner | -0.1398 | -0.1025 | 1,186 / 1,186 |

R is per filled trade at the planned stop distance, net of commission with
spread represented through executable prices. None of these arms left a
filled trade open at data end, so marked-tail treatment did not affect these
figures. Each pooled arm has two pending orders at data end. No attempted
BE stop was rejected by the simulator's current-quote check.

The combined-filter tight runner has PF 0.718 / 0.789 and total -165.8R /
-121.6R. Eight of nine symbols are negative under both paths in that arm;
gold is negative under O-H-L-C and positive under O-L-H-C. This does not
justify selecting gold or changing the symbol universe post hoc.

The old component diagnostic gave +0.2434R for bias+grade+runner; the new
model gives -0.1432R / -0.1020R. This difference combines fill eligibility,
intrabar sequencing, management timing, occupancy, expiry, executable-price
accounting and BE-buffer changes. **It cannot all be attributed to the fill
trigger alone.** The ratchet's apparent large benefit in the old H1 replay
also largely disappears. No new strategy profitability claim is supported.

## Audited trades explaining concrete old-model errors

Both examples below use EURUSD raw fixed exits and stop out under **both**
M5 orderings. Times are the historical CSV's broker timestamps.

### 2023-09-29 10:00 signal: a BID touch was not an ASK fill

- Planned BUY entry 1.05880, stop 1.0578157143, target 1.0607685714.
- The old 15:00 H1 bar has high 1.06105 and low 1.05879. The old resolver
  calls that a same-hour fill and target win, +1.8476R net.
- At spread 0.00008, ASK's lowest value that hour is 1.05887, **above the
  limit**. The limit cannot have filled during that hour under this spread.
- The new first fill is 16:25, when BID reaches 1.05862. The stop is reached
  at 16:50. New result: -1.0711R net (including commission).

### 2023-10-31 09:00 signal: the target preceded the entry

- Planned BUY entry 1.06034, stop 1.0594757143, target 1.0620685714.
- The old 15:00 H1 bar opens at 1.06237, reaches 1.06256, then falls as low
  as 1.06012. The old resolver credits a fill and target in that hour,
  +1.8264R net, using the whole bar's high after recognizing the low touch.
- M5 shows the first fill at 15:50: high 1.06094, low 1.06012, close 1.06021.
  The 15:55 high is only 1.06050. Neither post-fill M5 bar reaches the target.
- At 16:00 BID falls to 1.05947, crossing the stop. New result: -1.0810R net.

Across 1,812 matched raw fixed candidate/order rows under O-H-L-C, 96 old
positive returns become negative and six old negative returns become positive.
This matched subset is explanatory only: the new execution schedule also
changes the admitted population and whether some orders fill.

## Verification and reproducibility

```bash
.venv/bin/python -m unittest tests.unit.test_sb_execution \
  tests.unit.test_sb_component_diagnostic tests.unit.test_exp0_coinflip \
  tests.unit.test_sb_overlay
.venv/bin/python scripts/sb_execution_diagnostic.py \
  --out data/results/sb_execution_diagnostic_20260916
```

**38 focused tests passed.** Cases cover ask-only BUY eligibility, short ASK
exits, no double spread deduction, gap-through fills/stops, signal-bar exclusion,
pre-fill extremes, both same-bar orderings, wall-clock TTL, partial conservation,
same-bar raised stops, persistent tightening, longer and shorter managed
occupancy, slot release at bar close, broker TP precedence at gaps,
executable-price long/short symmetry, and malformed input.

Post-run checks verified all source SHA-256 hashes against the run card,
all 32 pooled summary accounting identities, filled-order/P&L correspondence,
and **no overlapping positions in any of the 288 separate schedules**.

Artifacts in the output directory: `orders.csv` (all admitted orders, including
unfilled), `summary.csv`, `run.json` (source/input hashes, assumptions, per-symbol
data bounds, costs and admission counts). The directory is gitignored; the
aggregate result and hand-audited examples are preserved here. The runner
refuses to overwrite prior output; choose a fresh path for reproduction.

## Interpretation and remaining limits

The earlier positive estimate is not dependable evidence for live strategy
profitability. This more detailed model reverses its sign, and concrete
pre-entry/fill errors explain part of why. That warrants correcting the
research baseline before strategy tuning.

This is still a **model result**, not proof that the live account loses at
these rates. Actual tick paths, variable spreads, latency, broker constraints,
partial acknowledgments, swaps and live filter context remain unmodeled.
The H1 signal collector retains its historical bias window and fixed grading
clock, so the combined-filter arm is not an exact live-kernel replay. Results
cover the historical nine-symbol universe, not today's full twelve-symbol
configuration, and no new holdout was introduced.

The next validation step is execution-tape or tick-data reconciliation on
known filled trades, followed by an independent data period using the aligned
live context. There is no basis here to optimize entry thresholds, promote
strategies, or change trading configuration. This work changes only offline
research code and documentation.
