# Plan 07 — Gyroscope Gate Study (design spec)

**Date:** 2026-07-14
**Branch:** `feat/trade-mgmt-pipeline` (shared; do NOT auto-merge/rebase)
**Program:** Titan v15, roadmap row 07 (`docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md`)
**Predecessors:** Plans 01–06 DONE (span 87267c9..d2ce672). Suite baseline entering: **337 OK**.
**Blueprint sources:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §1 (Gyroscope concept) and §14 (Gyroscope production blueprint); `docs/research/2026-07-12-trading-os-blueprint.md`.

---

## 1. Goal & framing

Gyroscope — the first alpha strategy of the novel arsenal — enters Titan as a
`status: research` manifest plugin and receives a **pre-registered gate study**
through the Plan-06 research pipeline (`research_run` → `kernel_replay` → imported
`backtest_engine` math → run-card). The plan proves the arsenal-onboarding workflow
end-to-end for a signal-emitting strategy, and lands two one-time, parity-neutral
kernel generalizations that let every *subsequent* non-SMC strategy plug in with zero
further kernel diffs.

**Antibody is explicitly OUT of this plan.** It emits no trades; its validation is a
counterfactual on member-strategy P&L inside/outside ALERT windows, which needs a
bespoke harness rather than `research_run`. It gets its own follow-on plan.

**Gate policy (unchanged, user-set):** the strategy enters `status: research` and does
not trade live. A live flip requires the pre-registered gate (thresholds fixed BEFORE
the run: net-of-cost, OOS split, ×1.5 spread stress, beat-baseline) to pass. A NO-GO
keeps the plugin in the repo, disabled, with its result recorded in `docs/research/`.

## 2. Non-goals / out of scope

- Antibody (own plan).
- Flipping Gyroscope to demo/live (gate decision is the user's, post-run).
- The arbiter `_bar_index` per-timeframe aging fix (advisory C) — inert here because
  Gyroscope is H1; documented as a required pre-live-flip fix (see §7).
- Cross-symbol total cap (advisory A → Plan 10).
- Any Optuna / REST API / bridge-direct lake import (Plan 06 deferrals).
- Real M1/M2 fill modelling; the study uses next-H1-open MARKET fills like the existing rigs.

## 3. Hard rules (inherited from Plans 01–06)

- **FROZEN, never modify:** `scripts/capture_parity_golden.py`, `tests/backtest/fixtures/*`,
  `tests/unit/test_signal_parity.py`. Parity must be green at every task.
- **Live bot untouched except the two parity-gated controller touches in §6.** No other
  diffs under `src/core` / `src/execution`. Both touches are parity-neutral for the live
  SilverBullet config and are test-locked.
- **NEVER stage** the user's in-flight bridge work: `mql5_bridge/Experts/Titan_Gateway.mq5`,
  `scripts/check_bridge.py`, `data/specs.json`, `tests/unit/test_check_bridge_ip.py`.
- **Validated math is IMPORTED from `tests/backtest/backtest_engine.py`** (`resolve_trade`,
  `trade_dollars`, `split_trades`, `aggregate_metrics`) — never duplicated. Research runs
  go through `scripts/research_run.py`; run-cards land in `data/results/` (gitignored).
- Tests: stdlib `unittest` only
  (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`). No pytest.
- Full suite green at the end of every task. Commits end with
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- No git remote — never push. `main` holds the baseline — never merge to it.

## 4. Deliverables

| # | Deliverable | Files | Kind |
|---|-------------|-------|------|
| D1 | `Lake.load` `frozen/` disk-glob fallback | `src/data/lake.py`, `tests/unit/test_lake.py` | additive, test-locked |
| D2 | Frozen 9-symbol H1 gate dataset | `data/lake/frozen/fbs/<SYM>/H1/*.parquet` | data commit |
| D3 | `KalmanDrift` filter + SPRT + NIS | `src/analysis/kalman_drift.py`, `tests/unit/test_kalman_drift.py` | pure module |
| D4 | `GyroscopeStrategy` + manifest + config block | `src/strategies/models/gyroscope.py`, `config/manifests/gyroscope.yaml`, `config/config.yaml`, `tests/unit/test_gyroscope_strategy.py` | plugin |
| D5 | `MaSlopeBaseline` + manifest + config block | `src/strategies/models/ma_slope_baseline.py`, `config/manifests/ma_slope_baseline.yaml`, `config/config.yaml`, `tests/unit/test_ma_slope_baseline.py` | plugin |
| D6 | Controller: advisory-B priority + bias-filter exemption | `src/core/system_controller.py`, `src/strategies/manifest.py`, tests | parity-gated |
| D7 | `research_run` multi-symbol pooled mode | `scripts/research_run.py`, `tests/unit/test_research_run.py` | CLI extension |
| D8 | Pre-registered gate doc | `docs/research/2026-07-14-gyroscope-gate.md` | doc (BEFORE run) |
| D9 | Gate run + recorded verdict | `docs/research/2026-07-14-gyroscope-gate-results.md` | doc (AFTER run) |

## 5. Gyroscope math & module architecture

### 5.1 `KalmanDrift` (`src/analysis/kalman_drift.py`)

A small **stateful** object, one instance per symbol, carried across bars. Constructor
takes the config params (warmup, q_atr_frac, r_frac, sprt α/β/δ, nis_window). Public
surface:

- `.update(log_close: float, atr: float) -> Reading` — one O(1) step per H1 close.
- `.warmed -> bool`, `.suspended -> bool`, `.state -> str` (state-machine label).
- `Reading` (frozen dataclass or dict): `velocity`, `S` (innovation variance),
  `sqrt_S_price` (price-space uncertainty for the stop), `nis_mean`, `lam_long`,
  `lam_short`, `crossed` (`"LONG"` / `"SHORT"` / `None`), `state`.

Math (blueprint §14.2), on `y = ln(close)`:

```
Predict:  x̂ = F x,      P = F P Fᵀ + Q          F=[[1,1],[0,1]]
Innovate: ε = y − H x̂,  S = H P Hᵀ + R           H=[1,0]
Update:   K = P Hᵀ / S;  x̂ += K ε;  P = (I−KH) P
```

- `R` = rolling variance of 1-bar log returns × `r_frac`; `Q` scaled to ATR ×
  `q_atr_frac`. Both refreshed each bar from the same rolling window — no free
  per-symbol constants.
- **Integrity monitor:** rolling mean of `NIS = ε²/S` over `nis_window` bars must sit
  inside the χ²₁ confidence band; sustained violation ⇒ `SUSPENDED` (no new entries) and
  re-warm.
- **SPRT** on the whitened stream `u = ε/√S` (unit-variance by construction):
  `Λ += ln f(u|drift=+δ) − ln f(u|drift=0)` for the long test (short mirrors with −δ);
  enter long when `Λ_long ≥ A = ln((1−β)/α)`; reset a test at `Λ ≤ B = ln(β/(1−α))`.
  δ in whitened units (default 0.40), α 0.05, β 0.20. Both tests run concurrently;
  first crossing wins; the opposite test crossing while in a trade is the reversal exit.

**Why stateful (not recompute-per-window):** the SPRT statistic Λ *accumulates* across
bars and cannot be restarted at a sliding-window edge; the Kalman filter must run
continuously from a fixed anchor. This is faithful in both execution paths — live
delivers each closed bar once, in order (`CandleMaker` appends only closed bars);
`kernel_replay.replay()` slides one-new-bar-per-call, in order. An idempotency guard
(`self._last_ts[symbol]`, see §5.2) makes a re-seen bar a no-op. **This does not touch
the frozen parity gate**, which is SilverBullet-only; Gyroscope is not in that fixture.

**Purity for tests:** the filter/SPRT arithmetic is deterministic (no wall-clock, no
randomness). Unit tests drive synthetic series and assert:
1. pure-drift series → recovered velocity ≈ known slope within tolerance;
2. pure-noise series → SPRT stays inside boundaries (few/no crossings);
3. drift-with-break → NIS violation trips `SUSPENDED`;
4. simulated α/β → realized false-entry / miss rates track the designed budget
   (distributional check, generous tolerance; seeded deterministic synthetic input,
   no `random` in the module itself).

### 5.2 `GyroscopeStrategy` (`src/strategies/models/gyroscope.py`)

- Subclasses `BaseStrategy`; `__init__(self, config, logger)` →
  `super().__init__("Gyroscope", config, logger)` (matches SilverBullet; the registry
  calls `cls(params, logger)`).
- `timeframe = 'H1'`. `on_new_candle` calls `self.validate_data(df, min_length=warmup,
  check_smc=False)` — **needs no SMC columns**, consumes raw OHLC + ATR only.
- Holds `self._filters: dict[symbol, KalmanDrift]` and `self._last_ts: dict[symbol, ts]`
  and `self._cooldown: dict[symbol, int]`. Per call: identify the newest closed bar for
  `context['symbol']`; if its timestamp ≤ `self._last_ts[symbol]`, return `None`
  (idempotent no-op); else feed it and record the timestamp.
- **Entry (ENTRY state):** Λ crosses `A` **and** validation — spread ≤
  `max_spread_atr_frac`·ATR (spread from context when present; if absent in offline
  replay, treat as pass and let the gate's cost model + ×1.5 stress carry cost), ATR in
  `[vol_floor, vol_ceil]` if configured, no open position for the symbol (offline: the
  strategy is stateless about fills; the arbiter/rig enforce one-position-per-symbol),
  not in cooldown, not `SUSPENDED`. Returns
  `{signal: "BUY"|"SELL", type: "MARKET", price: <next open proxy = last close>,
   sl, tp}`.
- **Stops/targets (blueprint §14.4):** `sl = entry ∓ k_sl·sqrt_S_price`, floored so
  `|entry − sl| ≥ sl_atr_floor·ATR` (never undercuts the SB finding that tight H1 stops
  die); `tp = entry ± rr_target·|entry − sl|`. `initial_entry`/`initial_tp` metadata
  flows through the existing send-time pipeline so `trade_manager` BE/partials/ratchet
  engage in live (inert in the offline gate, which uses the rig's exit model).
- **Exit signalling:** reverse-SPRT crossing, `max_bars_in_trade` time-stop, cooldown
  (`reentry_lockout` bars with Λ reset), `SUSPENDED` on NIS violation. In live these
  route through the established mgmt path (`_dispatch_mgmt_command` → `CLOSE_POS` on
  PUSH), never the REQ socket. **In the offline gate, exits are the rig's deterministic
  first-hit model** (SL/TP via `resolve_trade`) — the study measures entry quality under
  a fixed exit, exactly like the SB/OTE studies. Reverse-SPRT/time-stop live exits are
  built and unit-tested but are not part of the offline gate's exit accounting; the gate
  doc states this explicitly.

### 5.3 Config block (`config/config.yaml`, defaults = pre-registered values, §14.5)

```yaml
strategies:
  gyroscope:
    enabled: false          # research first; flips only on a GO gate
    timeframe: H1
    warmup_bars: 200
    q_atr_frac: 0.05
    r_frac: 1.0
    sprt: { alpha: 0.05, beta: 0.20, delta: 0.40 }
    nis_window: 50
    k_sl: 3.0
    sl_atr_floor: 0.8
    rr_target: 2.0
    max_bars_in_trade: 48
    reentry_lockout: 5
    max_spread_atr_frac: 0.10
```

### 5.4 `MaSlopeBaseline` (`src/strategies/models/ma_slope_baseline.py`)

The §14.7 baseline Gyroscope must beat "on identical exits". A minimal `BaseStrategy`
plugin (`timeframe H1`, `check_smc=False`): entry on the sign of an N-bar moving-average
slope (config `ma_window`), **identical stop/target construction** as Gyroscope
(`k_sl·sqrt_S_price` is Gyroscope-specific, so the baseline uses the same
`sl_atr_floor`/`rr_target` geometry anchored on ATR — the gate doc pins the exact
baseline stop definition so the comparison is apples-to-apples on exits). Runs through
the identical `research_run` pipeline and cost model. Manifest `status: research`,
`honors_htf_bias: false`, config block with its own defaults. Its only job is to be the
"beat the baseline, not just zero" reference in the gate.

## 6. Two parity-gated controller touches (§6 = the only `src/core` diffs)

The roadmap's "zero `src/core`+`src/execution` diffs for Gyroscope" is the aspiration
for the *second* strategy of a family. The first non-SMC arsenal entry legitimately
requires two one-time, parity-neutral kernel generalizations (the blueprint §14.1 itself
calls for the bias exemption). Both are additive, test-locked, and **byte-identical in
behaviour for the live SilverBullet config → parity fixture unchanged.**

### 6.1 Advisory-B: manifest priority plumbing

Replace the hardcoded `priority=50` at `system_controller.py:700` with the manifest
priority. The `registry` is already looked up one line above
(`strategy_id = registry.id_of(strat)`); add a registry accessor
`priority_of(strategy_id) -> int` (reads `self._by_id[sid].priority`, default 50 when
unknown/no registry). SilverBullet's manifest is `priority: 50`, so the constructed
Intent is byte-identical → parity green.

- Test-lock: two manifests with differing priorities; assert the emitted Intent carries
  the manifest priority (not the hardcode); assert the no-registry fallback still yields 50.

### 6.2 HTF-bias-filter exemption

The unconditional bias filter at `system_controller.py:669-671` drops signals opposing
the SMC HTF bias. That corrupts a drift strategy (its own drift *is* its bias). Make the
filter manifest-driven:

- Add an optional manifest field `honors_htf_bias: bool = True` (default true) to
  `StrategyManifest` + `load_manifest` (validated as bool). SilverBullet omits it →
  defaults true → still filtered → **parity green**.
- In `_run_strategies`, gate the bias-filter `continue` on the strategy honoring bias:
  look up the manifest via the registry (`registry.honors_htf_bias(strategy_id)`,
  default true when no registry / unknown id, so `__new__`-built fixtures are unaffected).
  Gyroscope's and MaSlopeBaseline's manifests set `honors_htf_bias: false`.
- Test-lock: an exempt strategy's counter-bias signal survives to submission; a
  bias-honoring strategy's counter-bias signal is still dropped (discriminating RED vs
  the old unconditional filter).

**Parity gate for §6:** `tests/unit/test_signal_parity.py` must be green after this
task; the frozen fixture is untouched. Both changes must be shown parity-neutral by
re-running parity in the task review.

**Extensibility acceptance test (roadmap DoD):** after §6, adding a further non-SMC
strategy of an already-generalized shape requires **zero** additional `src/core` /
`src/execution` diffs — demonstrated by MaSlopeBaseline (D5) reusing the same exemption
+ priority plumbing with no controller edits of its own.

## 7. Gate mechanics & pre-registered thresholds (D7, D8)

### 7.1 `research_run` multi-symbol pooled mode (D7)

Extend `scripts/research_run.py`:

- New source option `--lake-symbols SYM1,SYM2,…` (and/or `--frozen-all` to enumerate the
  frozen H1 symbols on disk) alongside the existing single `--lake-symbol` / `--csv`.
- For each symbol: load H1 (frozen partitions via D1 glob-fallback, or lake M5→H1
  resample per the existing T5 fallback), run `replay(...)`, resolve trades. Pool ALL
  resolved trades across symbols in R-units, then call the imported
  `split_trades`/`aggregate_metrics` ONCE for pooled IS/OOS. Retain per-symbol metrics in
  the run-card. Validated math still imported, never duplicated.
- The pooled run-card records: git_sha, config_hash, per-symbol data sha256 + resolved
  tick spec + spec_source (existing provenance), cost model (`trade_dollars`),
  `--spread-pips`, IS/OOS split, per-symbol and pooled metrics, symbol list.
- Preserve single-symbol behaviour exactly (regression test).
- **MARKET-entry check:** `research_run`'s note (lines ~178-182) flags that a MARKET-order
  strategy may need a `SignalRecord` field. Verify Gyroscope's MARKET decisions resolve
  correctly through `resolve_trade`; add the field if genuinely required (test-locked,
  and confirm SilverBullet's existing records are unchanged).

### 7.2 Pre-registered gate doc (D8) — thresholds fixed BEFORE the run

`docs/research/2026-07-14-gyroscope-gate.md`, mirroring the OTE / poc_sb_stops gate
style. Fixed inputs: 3-yr H1, **9 symbols** (the exact list pinned in the doc, from the
committed frozen dataset), FBS `trade_dollars` cost model, IS/OOS split = final 30% OOS.

**GO requires ALL of:**
1. Pooled net **≥ +0.10 R/trade**.
2. **≥ 150** pooled trades.
3. **≥ 6/9** symbols non-negative net.
4. **OOS (final 30%) sign-consistent** with IS (pooled net positive OOS).
5. **±30% sweeps** on (α, β, δ, q_atr_frac) do **not flip** the pooled sign.
6. **Beats the MaSlopeBaseline** pooled net on identical exits/cost.
7. **×1.5 spread stress** keeps pooled net positive.

**Diagnostics (reported, not gating):** realized false-entry rate ≈ α on OOS; favorable
excursion after boundary crossings vs 2× spread; NIS-suspend frequency.

**Advisory-C note (required in the doc):** Gyroscope is H1, so the arbiter `_bar_index`
single-counter M5-aging bug (Plan-05 advisory C) is inert for this study. The doc records
that the per-timeframe aging fix is a **required precondition before any live flip** and
before any M5-timeframe arsenal strategy activates.

### 7.3 Gate run + verdict (D9)

Run the pooled gate + the ±30% sweeps + baseline + ×1.5 stress via `research_run`.
Record the outcome canonically in `docs/research/2026-07-14-gyroscope-gate-results.md`
(GO → recommend demo-forward, still the user's flip; NO-GO → keep the plugin disabled,
result recorded). Run-cards live in gitignored `data/results/`; the results doc
summarizes with the run-card sha256s for provenance.

## 8. Frozen dataset & P06 pre-req (D1, D2)

- **D1 — `Lake.load` `frozen/` glob-fallback:** when
  `manifest[broker][symbol][tf]` is empty, before raising `LakeError`, look for
  `<root>/frozen/<broker>/<symbol>/<tf>/*.parquet` on disk; if present, load those year
  files (sorted, same concat/sort/slice as the manifest path). This makes committed
  frozen datasets loadable from a clean clone without a committed manifest — the durable
  general fix for all future frozen data. The manifest path is unchanged (regression
  test). New tests: frozen partition with no manifest entry loads via glob; a
  manifest-backed symbol still loads via the manifest path; frozen glob-miss still raises
  the clear `LakeError`. `.gitignore` already permits `data/lake/frozen/**`.
- **D2 — freeze the gate dataset:** import the 9 symbols' `data/history/<SYM>_M5.csv`
  → resample H1 (existing `load_h1_from_m5` helper, byte-identical to `engine.h1_df`) →
  write year-partitioned parquet under `data/lake/frozen/fbs/<SYM>/H1/<year>.parquet`
  and commit. ~9 symbols × ~4 year-partitions ≈ a few MB. **The exact 9-symbol list is
  chosen by the plan author to match the validated SilverBullet study universe
  ([[silverbullet-timing-edge]], "9 syms") for cross-strategy comparability, and is
  pinned in the gate doc (D8) before the run.** Any symbol with prior cost-exclusion
  (e.g. crypto/oil outliers from the OTE study) is excluded and that exclusion recorded.

## 9. Testing strategy & task order

TDD throughout (failing test first, then minimal change). Full unit suite green at the
end of every task; parity green at every task; subagents run tests in the **foreground**
(Bash timeout 600000). Suite baseline entering: **337 OK**.

Proposed task order:

1. **D1** Lake `frozen/` glob-fallback (test-locked; no market data).
2. **D2** Freeze the 9-symbol H1 gate dataset (commit parquet).
3. **D3** `KalmanDrift` + synthetic-series tests (pure math, no market data).
4. **D4** `GyroscopeStrategy` + manifest + config block + contract tests.
5. **D5** `MaSlopeBaseline` + manifest + config block + tests.
6. **D6** Controller touches (advisory-B priority + bias exemption) — **parity-gated**,
   test-locked.
7. **D7** `research_run` multi-symbol pooled mode + MARKET-entry check.
8. **D8** Pre-registered gate doc (written BEFORE D9's run).
9. **D9** Run the gate + record the verdict.

Execution: `superpowers:writing-plans` → `superpowers:subagent-driven-development` with
the same reviewer discipline the ledger shows (sonnet implementers, sonnet task-review
gates, fix loops until Approved, opus final whole-plan review, one ledger entry per task
in `.superpowers/sdd/progress.md`).

## 10. Open risks / notes for the plan author

- **Spread in offline replay:** the FeatureBus/replay context may not carry a live spread
  at signal time; the entry spread screen degrades to "pass" offline and cost is applied
  by the gate's `trade_dollars` model + ×1.5 stress. The plan must state this and ensure
  the ×1.5 stress is the binding cost-robustness check (mirrors the SB/OTE studies).
- **Baseline exit parity:** the gate doc must pin the MaSlopeBaseline stop/target
  geometry precisely so "identical exits" is literally true for the comparison.
- **Stateful filter fidelity:** the idempotency guard (`_last_ts`) is the only thing
  standing between live and replay faithfulness for a carried-state strategy; it must be
  unit-tested (double-fed bar = no-op; out-of-order bar rejected).
- **Suite timing:** the multi-symbol gate run is a script invocation, not a unit test;
  keep any kernel-replay unit tests small (single symbol, short windows) so the suite
  stays in the ~8–13 min band.
