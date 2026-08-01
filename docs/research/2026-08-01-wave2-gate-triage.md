# Wave-2 Gate-Triage — Pre-Registered (Aftershock kill-screen)

Registered BEFORE the detector is built or any market data is read (this
file's commit precedes src/analysis/hawkes_intensity.py in git history —
the same discipline as docs/research/2026-07-14-gyroscope-gate.md).

## Triage ranking (owner-ratified 2026-08-01)

| Rank | Candidate | This cycle? | Rationale |
|---|---|---|---|
| 1 | Aftershock | Yes — kill-screen below | Best GO prior: 5/5 cost-survival (brainstorm §12), volatility clustering is the best-replicated stylized fact in finance; screen is self-contained. |
| 2 | Rubicon | Next cycle | Weakest documented hypothesis (post-break drift persistence), highest salvage value — BOCPD + regime.run_length_posterior ship as infrastructure even on trading NO-GO. |
| 3 | Rainflow (+Coil) | After — shared two-arm gate | One research question, two detectors (docs/strategies/rainflow.md §6); single-sided entry geometry is BINDING for both arms, which drops the P2/OCO dependency previously claimed by the backlog row. |

## Aftershock screen — registered protocol

Dataset: data/lake/frozen/fbs/<SYM>/H1/*.parquet, 9 symbols (EURUSD,
GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY, XAUUSD, US30, BTCUSD). Per
symbol: concatenate year files, sort by `time`, drop duplicate
timestamps (keep first), then keep ONLY the first floor(0.7·N) bars
(IS). The OOS remainder is never read by this study.

Definitions (verbatim contract for src/analysis/hawkes_intensity.py):
- TR_t = max(high_t, close_{t-1}) − min(low_t, close_{t-1}); TR_0 = high_0 − low_0.
- tr_med_t = median of TR over the previous 200 bars, EXCLUDING bar t
  (pandas: tr.shift(1).rolling(200).median()). Bars with index < 200
  are never events (warmup).
- Event: TR_t > q × tr_med_t, q = 2.5 primary.
- event_dir_t = +1 if close_t > open_t, −1 if close_t < open_t, else 0
  (0 → never eligible).
- closes_beyond_mid: up events close_t > (high_t+low_t)/2; down events
  close_t < (high_t+low_t)/2.
- Excitation (scale-invariant, no MLE): decay = exp(−ln 2 / half_life),
  half_life = 24 bars primary; S⁻_0 = 0;
  S⁻_t = (S⁻_{t−1} + 1{event at t−1}) × decay.
  S⁻ is the excitation JUST BEFORE bar t and never includes bar t's own
  event.
- s_lo = 20th percentile of S⁻ over all IS bars with index ≥ 200, per
  symbol, per parameter cell.
- Eligible (continuation signal) at t: event_t AND event_dir_t ≠ 0 AND
  closes_beyond_mid_t AND S⁻_t < s_lo AND confirm at t+1, where confirm
  means close_{t+1} > mid_t for up events / close_{t+1} < mid_t for
  down events (mid_t = (high_t+low_t)/2).
- Signal time = t+1 (the confirm bar). Signed forward log return at
  horizon h ∈ {1,4,8,24}: y = event_dir_t × (ln close_{t+1+h} − ln
  close_{t+1}). Rows where t+1+h exceeds the IS slice are dropped.
- Control population (for criteria 2–3): ALL IS bars b with index ≥ 200,
  dir_b ≠ 0, and b+1+h inside IS: y = dir_b × (ln close_{b+1+h} − ln
  close_{b+1}) — "any bar's naive continuation", no event/confirm
  conditions. Signal rows are a subset of control rows by construction;
  they are EXCLUDED from the control cell.
- Session buckets from broker-time hour of bar t: Asia [0,8), London
  [8,15), NY-overlap [15,19), NY-late [19,24).
- Spread (price units) for symbol s: SPREADS[s] ticks (scripts/
  poc_sb_stops.py table) × tick_size from data/specs.json.

Kill criteria — ALL six must pass at the PRIMARY cell (q=2.5,
half_life=24, horizon +8) for verdict PASS; any failure → NO-GO;
criterion 5 below floor → INSUFFICIENT-N:
1. Pooled (cost-alive symbols) mean signed forward return at +8 > 0,
   bootstrap 95% CI (5000 draws, seed 20260801) excludes 0.
2. Mean difference (signal cell − control cell), bootstrap 95% CI
   (5000 draws, independent resampling per cell) excludes 0 and is
   positive.
3. OLS of y on {1, signal_dummy, london, ny_overlap, ny_late} over
   control ∪ signal rows (Asia is the dropped reference bucket; numpy
   lstsq): signal coefficient > 0 with case-resampling bootstrap 95% CI
   (2000 refits) excluding 0.
4. ≥6/9 symbols with per-symbol mean signed forward return at +8 > 0.
   Cost-dead symbols (criterion 6) count as NEGATIVE here.
5. Pooled eligible-event count (cost-alive symbols) ≥ 150, else
   INSUFFICIENT-N.
6. Cost sanity per symbol: median (high−low) of that symbol's eligible
   event bars ≥ 8 × spread. Failing symbols are excluded from pooled
   criteria 1–3 and count negative in criterion 4.

Robustness: all 9 (q × half_life) cells reported (pooled +8 mean, CI,
N); the primary cell ALONE decides. Horizons +1/+4/+24 reported,
never deciding. Exhaustion leg: out of scope (continuation-only v1).

## Verdict handling (registered dispositions)
- PASS → draft the full backtest gate mirroring
  docs/research/2026-07-14-gyroscope-gate.md (separate session).
- NO-GO / INSUFFICIENT-N → record in this doc's appendix, update
  docs/strategies/aftershock.md + ARSENAL.md standing, promote Rubicon.
