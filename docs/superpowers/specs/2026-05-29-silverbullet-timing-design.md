# Spec: SilverBullet Timing-Discovery Experiment

- **Date:** 2026-05-29
- **Status:** Approved (design); pending spec review → plan
- **Context:** Phase-1 validation ([../../../data/history/VALIDATED_REPORT.md]) showed SilverBullet is the only positive-expectancy strategy (+0.15R, 38.5% win, PF 1.25) but on a tiny sample (65 trades, gated to one NY hour). The other strategies lose. Decision: pause the others, freeze SB's entry logic, and treat **timing as the only variable** to discover — empirically and robustly — whether a *single shared* time-of-day rule gives SB a durable edge.

## Goal
Find one shared set of trading-hour windows that maximizes SilverBullet's out-of-sample edge, by generalizing its timing to a configurable multi-window gate and sweeping candidate windows on the Phase-1 harness with strict overfitting guards — **or honestly conclude no robust timing edge exists.**

## Decisions (locked)
| Decision | Choice |
|---|---|
| Strategies active | **SilverBullet only** (others paused) |
| Entry logic | **Frozen** — FVG + 0.8×ATR displacement + limit-at-FVG-edge + 0.2-ATR-wick SL + 2R TP unchanged |
| Timing variable | A configurable **list of hour-windows** (was a single `session_ny`) |
| Timezone basis | **Broker server time** (what CSVs *and* live ticks already use → zero DST/offset conversion). Sweep runs with `--shift 0` so bar hour = broker hour |
| Window scope | **One shared rule** across instruments (fewest knobs) |
| Discovery | Run SB un-gated (all hours), bucket trades by entry hour, evaluate candidate windows post-hoc; **confirm the winner via a full gated re-run** |
| Adoption bar | Positive in **train AND test**, test **n ≥ 30**, win-rate CI lower-bound near/above ~25% breakeven, survives Monte-Carlo. Else: "no robust window — do not deploy." |

## Components

### 1. Generalize SilverBullet timing (logic frozen) — `src/strategies/models/silver_bullet.py`
Add support for a `windows` config: a list of `[start_hour, end_hour]` pairs (broker-time, end exclusive). The time gate passes if the bar's hour is in **any** window. Backward-compatible: if `windows` is absent, fall back to the existing single `session_ny` window. Nothing else in the strategy changes.

### 2. Pause the other strategies
- **Backtest/sweep:** add a `--only <StrategyName>` filter to the backtester so it instantiates and runs a single strategy.
- **Live config** (`config/config.yaml`): set `unicorn_model/ict_ote/crt` `enabled: false` (instantiated but inert via `BaseStrategy.active`). Keep `silver_bullet` enabled.

### 3. Sweep + analysis tool — `scripts/sweep_silverbullet.py` (analysis, not a bot change)
For each of the 11 instruments: run the backtester `--only SilverBullet --shift 0` with SB `windows=[[0,24]]` (all hours) → a trades CSV tagged with each trade's entry hour (derived from `time`). Then a **pure analyzer**:
- Bucket resolved (TP/SL) trades by entry hour, **pooled across instruments**.
- Evaluate candidate windows: each single hour `[h,h+1]`, each 2-hour block, and the canonical NY set (mapped to broker time). For each: train/test win-rate, expectancy, total R, PF, Wilson CI, n.
- Print the **full ranked table of all candidate windows** (no cherry-picking) + a per-hour edge profile.

### 4. Confirm the winner
Take the best window(s) that clear the adoption bar, set them as SB `windows`, and re-run the **full gated** backtester (`--only SilverBullet`) per instrument to get the honest, concurrency-correct metrics (train/test + dollars + significance). Post-hoc bucketing ignores the small one-open-per-symbol concurrency difference; this re-run resolves it.

## Testing (TDD)
- **SB window gate (pure-ish):** a multi-window config admits bars whose hour is in any window and blocks others; single-`session_ny` config still works (backward compat). Construct minimal df + context with a given `ny_time` hour and assert signal/None.
- **Window-bucket analyzer (pure):** given trades with `hour`/`outcome`/`r`, the per-window aggregation returns correct win-rate/expectancy/n for a chosen window (incl. multi-hour windows and the empty-window case).
- Full existing suite stays green; `--only` filter doesn't change multi-strategy runs when unused.

## Out of scope
- SB entry-logic changes; the other strategies; live deployment (decided only **after** a robust window is found and confirmed). Per-instrument/per-asset windows (we chose one shared rule). Minute-level window granularity (hour blocks only — YAGNI).

## Risks / caveats
- **Overfitting is the central risk** (research's #1 warning): sweeping ~24 single-hour windows × pooled data will surface chance winners. Mitigation: train/test split, report all windows, require OOS consistency + significance, prefer session-plausible hours.
- SB's sample is small; even pooled, some windows will be `n<30` → flagged insufficient, not adopted.
- Broker-time windows must be mapped to the live feed's clock identically when/if we deploy (noted for the deployment step; not in this experiment).
- A real possible outcome: **no window clears the bar.** That ends the SB thread honestly rather than shipping a curve-fit.
