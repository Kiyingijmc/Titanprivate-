# SilverBullet variants: frozen first research screen

Written before the new variant results. Research only; no live registration.

## Hypotheses and design

1. `edge_control`: newest candle body >= its ATR14, bullish/bearish three-bar
   gap, near-edge LIMIT, one ATR stop. Direction must match candle body.
   This is a comparator, not byte-identical to the old production collector.
2. `middle_retest`: the middle candle displaces >= its ATR14, its direction
   agrees with the gap, entry halfway through the gap, stop beyond the entire
   three-candle structure plus 0.1 current ATR, with one ATR minimum risk.
   Hypothesis: enter a retracement of genuine prior displacement rather than
   require another displacement on the last candle. This bundles entry/stop
   changes and is not an isolated attribution experiment.
3. `sweep_reclaim`: middle_retest plus the first candle sweeps and closes back
   inside the preceding 12-bar low/high. Hypothesis: rejection plus displacement
   selects better reversals. No hindsight pivots or future confirmation.

Each runs on M5, M15, M30, H1 and H2. Each has `all_hours` and `ny_am` (signal
available 10:00 <= New York time < 11:00) modes. NY mode allows only the first
cost-eligible candidate per symbol/date, even if it expires or is blocked.
H2 is a horizon comparator. No M1 claims from M5 data.

Potential later ideas, deliberately outside this screen: H1 trend-aligned M5
entries, opening-range continuation, market entry instead of missed limits,
volatility-regime filters. They require new frozen experiments, not rescue
parameter sweeps on these results.

## Shared mechanics

- Source M5 bars resample on broker midnight; discard incomplete aggregate
  bars. ATR14 uses completed true ranges. Three setup bars and the sweep
  lookback must be contiguous to avoid manufacturing gaps over market closures.
- Signals become available at their actual timeframe close, never before.
- Two exits: fixed 2R; existing idealized runner with 3-pip BE buffer. No
  runner-parameter search. Both have a 12-signal-bar wall-clock holding limit
  from fill; pending LIMIT expires after 3 signal bars, boundary excluded.
- Reject a candidate if indicative spread plus $7/lot commission exceeds
  0.25 planned R. Do not widen stops merely to pass the cost screen.
- Each symbol/model/path has independent chronological pending/position
  occupancy. BUY enters on ASK, SELL on BID; inverse sides for exits.
- M5 O-H-L-C and O-L-H-C path scenarios; neither is a guaranteed bound.
- Primary costs: fixed historical indicative spread plus $7/lot commission.
  Stress: 1.5x spread AND commission with the SAME frozen candidate population.
  No tuning to stressed eligibility. No swap/slippage beyond price gaps.
- NY uses DST-aware America/New_York and an explicit historical broker UTC+2
  assumption. Historical broker DST is unverified; NY finalists require UTC+3
  sensitivity and verified timestamps before promotion.

## Evaluation, declared before measurement

Default universe is the existing nine-symbol diagnostic universe (EURUSD,
GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, BTCUSD), unless the user
selects a different universe before the run.

60 declared model combinations (3 detectors x 2 windows x 5 timeframes x
2 exits), each evaluated under 2 paths and 2 costs. No choosing a preferred
path. Early history ends 2025-01-01; later evaluation starts 2025-01-08,
purging seven calendar days. Each segment resets occupancy and terminates
positions at its last executable close, with tails disclosed. Signal warmup
may use preceding bars, never future bars. Previously used historical data
means the later segment is NOT a virgin holdout.

Preliminary survivors need >=150 early and >=100 late fills in EVERY
path/cost scenario, positive early and late mean net R in every scenario,
and positive late per-symbol net mean in a majority of eligible symbols
(>=20 fills; at least three eligible symbols) in every scenario. This is a
research shortlist, never an automatic GO. Record all failures and counts.
Report per-symbol and pooled means, PF, costs, fill/expiry counts, and tails.
Pooled R is not portfolio performance; no pooled drawdown/Sharpe claim.

No changes based on winning cells in this run. All attempted combinations
must be reported; multiple testing makes the best historical cell unreliable
([Bailey et al.](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)).
Any survivor needs execution-tape parity, verified session time, portfolio
simulation, and independent forward data before deployment.
