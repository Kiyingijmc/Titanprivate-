# ICT video rules — conditioning reads, flat-RR control, liquidity-anchored target

**Date:** 2026-08-03
**Status:** design, approved for planning
**Scope:** research only. No live path, no manifest entry, no config change.

## Origin

A trading video proposes five rules. Each was checked against the tree before
design. Verified state:

| Rule | Claim | Verified state |
|---|---|---|
| 1 Directional bias | fractal vs internal bias split | `structure_bias(highs, lows, lk=3)` and `precompute_last_swings(highs, lows, lk)` exist in `src/analysis/ict_structure.py` and take `lk` — but **the SB rig calls neither**. Its `bias` column comes from `BiasEngine` → `MarketStructure.identify_swings(left_bars=5, right_bars=5)`, hardcoded at `bias_engine.py:47`. |
| 2 Time & price | session windows | `windows: [[0, 24]]` (`config/config.yaml:133`). `sb_stops_trades_H1.csv` already carries an `hour` column. |
| 3 Liquidation $ | liquidity-anchored target | Genuinely absent. `equal_high\|eqh\|liquidity_pool\|draw_on_liquidity` matches nothing in `src/` or `scripts/`. `src/analysis/liquidity.py` exists but computes premium/discount equilibrium (PDH/PDL/EQ), not pools. |
| 4 Reversal confirmation | M1 MSS | Do not build. EXP-1 ITT range **−0.451 to −0.757** (n=1889), widening to −0.488/−0.798 under 1.5× spread stress, negative in all 4 years and all 11 symbols. Also blocked: `_VALID_TIMEFRAMES = {"M5","M15","H1"}` (`manifest.py:15`) and no M1 in `data/history/`. |
| 5 OB/FVG/iFVG | inverse FVG | `bull_fvg_in_leg`/`bear_fvg_in_leg`/`opposing_candle_before` exist; iFVG does not. **Deferred — out of scope for this cycle.** |

## Rig facts that constrain the design

Four properties of `scripts/poc_sb_stops.py` and the frozen tables shape
everything below. They were discovered during design, not assumed.

**1. The `model` column is a trap.** `resolve()` writes four stop models into one
table. The rows labelled `LIVE` are the legacy 0.2×ATR stop, which the rig's own
header (`poc_sb_stops.py:7`) flags as cost-broken at ~1R+ per round trip. Config
runs `stop_atr: 1.0`, so the live strategy is the **`ATR10`** rows (n=2217) —
which is why `reach_screen.py` labels ATR10 as "LIVE". **Every read in this spec
pins `model == "ATR10"`.** Selecting `"LIVE"` silently analyses a deprecated stop.

**2. Arms are not paired.** `resolve()` sets `busy_until = exit_k` — one open
position per symbol. Changing the target changes exit timing, which changes which
subsequent signals are eligible. Population and `n` shift per arm. This is
realistic (it is what live does) but it forbids paired statistics. Every arm
reports its own `n`; arm comparisons use unpaired bootstrap.

**3. `NY_SHIFT = -7` already exists** (`poc_sb_stops.py:44`), commented
*"broker(GMT+3ish) -> NY approx; +/-1h DST wobble accepted"*. A1 does not add a
new concern; it validates or corrects a constant the rig already leans on.

**4. Research universe ≠ live universe.** `SYMS` is 11 (includes GBPCAD, XBRUSD;
missing US100, ETHUSD, XTIUSD); config `pairs` is 12. All work here runs on the
rig's 11, because the frozen tables and the `SPREADS`/`COMMISSION_USD_PER_LOT`
cost model are built on exactly that set. The delta is a stated known gap: a GO
here does not transfer to US100/ETHUSD/XTIUSD without a re-run.

## Why the flat-RR sweep exists

`data/results/reach_screen/horizon12.log`, for `ATR10`:

```
MFE from entry (R):  p25 1.29   median 1.99   p75 3.32   p90 5.33
required reach 2.11R   median/required 0.94 (FAIL)   reach 46.0% vs BE 33.3% (PASS)
```

The fixed 2.0R target sits almost exactly at the **median** of realised MFE on a
wide, right-skewed distribution. That is a strong argument for a variable target
— but it argues about **distance**, not about **liquidity**.

Those are independent variables. Running the liquidity arm against the incumbent
2.0R without first establishing the best flat RR makes a GO uninterpretable:
"liquidity beats 2.0R" could just be "1.6R beats 2.0R" wearing an ICT costume.
**The flat-RR sweep is the null model the liquidity target must beat**, and it
costs one parameterisation.

---

## Section A — conditioning reads and the control

### A1 · Session buckets (Rule 2) — pre-specified, reported

Derive the broker→UTC offset empirically rather than trusting `NY_SHIFT = -7`:
infer it from the weekend seam and the daily bar-count boundary, per symbol and
per year, and assert the result lands in GMT+2/+3. **If derivation is ambiguous
the run aborts** — it must never fall back silently to −7. Convert to
DST-aware New York time via stdlib `zoneinfo` (no new dependency; the repo
already guards Python ≥3.10).

Bucket `ATR10` trades into exactly **four** pre-declared buckets:

| Bucket | NY time, snapped to H1 opens |
|---|---|
| London KZ | 02:00–05:00 |
| NY AM | 08:00–11:00 |
| NY PM | 13:00–16:00 |
| Outside | everything else |

Canonical killzones are quoted 08:30–11:00 and 13:30–16:00; H1 bars do not align
to half-hour boundaries, so they snap to bar opens. This is an approximation the
report states rather than hides.

Report per bucket: `n`, net R/trade using per-symbol `cost_r` (not the flat 0.11
that `reach_screen.py` uses), Wilson interval on win rate, and per-year sign.

Four buckets fixed in advance. **No scanning for a best hour** — 2217 trades over
24 hours is ~92 per hour and any argmax there is noise.

**Verdict rule:** reported, not gated. A bucket is called *interesting* only if
its net R/trade separates from the pooled mean by ≥ 0.10R **and** that bucket's
own net R/trade keeps the same sign in all four years. Anything weaker is
recorded as null.

### A2 · Bias agreement (Rule 1) — reported, cannot carry a verdict

The video's split is fractal vs internal structure. Since the rig's existing
`bias` column comes from a different algorithm (`BiasEngine`, 5-bar fractal),
mixing it with `ict_structure.structure_bias` would compare two unlike things.
Instead **both levels come from one algorithm**:

- fractal — `structure_bias(highs, lows, lk=5)`
- internal — `structure_bias(highs, lows, lk=2)`

The existing `BiasEngine` column is reported alongside as context only.

Report net R/trade on the agreement subset (fractal == internal, both non-NEUTRAL)
against the pooled baseline.

**This read cannot carry a verdict and the report must say so on its face.** The
`ATR10` population is ~42% NEUTRAL at a single level; requiring agreement across
two levels lands near ~700 trades against a +0.109R base. It can motivate a
later powered test; it cannot conclude one. Recording it as gated would repeat
the EXP-0/Antibody n=1 failure.

### A3 · Flat-RR sweep — the control arm

Lift `RR` from module constant to a `resolve()` parameter. Sweep:

```
1.25  1.50  1.75  2.00  2.25  2.50  3.00
```

Report per arm: `n`, net R/trade (per-symbol `cost_r`), win%, reach%, per-year
sign, per-symbol sign.

**`RR*` is not the raw argmax.** Argmax over seven arms on one dataset is a
selection artifact. Declared rule:

> **2.0 stands as `RR*` unless a challenger beats it on net R/trade in every year
> (2023, 2024, 2025, 2026) and in ≥6 of 11 symbols. If two challengers qualify,
> `RR*` is the one nearer 2.0.**

---

## Section B — liquidity build and the experiment

### B1 · Pool primitives

New pure-stdlib module `src/analysis/liquidity_pools.py`. Deliberately **not**
`ict_zones.py`, which is scoped to a frozen Unicorn rule set (`ict_zones.py:3`)
and should not be blurred. Deliberately distinct from `src/analysis/liquidity.py`
(pandas, live path, PD arrays). Pure functions, no pandas, no I/O — matching the
established `ict_structure.py` / `ict_zones.py` split.

```
equal_level_pools(highs, lows, atr, lk=3, tol_atr=0.10, min_members=2)
    -> [(level, side, usable_from_idx), ...]

prior_day_levels(times, highs, lows)
    -> per-bar (pdh, pdl) from the previous COMPLETED day

nearest_pool_beyond(pools, entry, risk, is_long, i, floor_r=1.0, cap_r=5.0)
    -> (target_price, source) | None
```

`atr` is the per-bar ATR(14) array, not a scalar; two swing extremes are
"equal" when they lie within `tol_atr × atr[j]` of each other, evaluated at the
**later** swing's bar `j`. `side` is `"buy"` for pools resting above equal highs
and `"sell"` for pools below equal lows; a long targets the nearest `"buy"` pool
above entry, a short the nearest `"sell"` pool below.

Pre-declared parameters: `lk=3` (minor swings, matching `ict_structure`'s
default granularity; a single `lk=5` sensitivity run is reported, not gated),
`tol_atr=0.10`, `min_members=2`, `floor_r=1.0`, `cap_r=5.0`. The cap is set from
data: p90 of MFE is 5.33R, so 5.0R sits just under the 90th percentile — beyond
it a pool is effectively an unreachable target.

**The load-bearing invariant is no look-ahead.** A pool from the swing at index
`j` is usable only from bar `j+lk`; PDH/PDL only from the first bar of the
following day. `nearest_pool_beyond` takes the current bar index `i` and must
filter on `usable_from_idx <= i`. This is what the unit tests exist to pin.

### B2 · The pre-registered experiment

Single variable. **Frozen:** entry (SB FVG + `BODY_MIN_ATR` gate), `ATR10` stop,
11-symbol universe, per-symbol `cost_r`, `TTL_BARS = 12`, the one-open-per-symbol
occupancy rule.

**Varied:** target only.

| Arm | Target |
|---|---|
| CONTROL | flat `RR*` from A3 |
| LIQ | nearest opposing pool beyond entry, floored 1.0R, capped 5.0R, falling back to `RR*` when no pool is in range |

**Degeneracy diagnostics, declared before the run.** Both are reported and both
can void the arm regardless of its mean:

- **fallback share** — trades taking the `RR*` fallback. If > 50%, the arm is
  mostly CONTROL under another name.
- **floor-bind share** — trades clamped to the 1.0R floor. If > 50%, the arm is
  flat 1.0R, which A3 already tested.
- combined fallback + floor-bind > 65% → **inconclusive**.

**GO criteria — all four required:**

1. LIQ − CONTROL ≥ **+0.05R**/trade net of costs (context: SB base is +0.109R and
   the grading layer earns +0.028R, so +0.05R is a materially sized effect);
2. unpaired bootstrap 95% CI on the difference of means excludes 0;
3. the LIQ − CONTROL difference is positive in all four years and in ≥6 of 11
   symbols (sign of the difference, not of either arm's absolute return);
4. survives the 1.5× spread stress the rig already supports.

`n` reported per arm. Not paired — see rig fact 2.

### B3 · Tests

stdlib `unittest` under `tests/unit/`, per repo convention (there is no pytest).
TDD: failing case first.

- `equal_level_pools` clusters within tolerance, rejects beyond it
- `min_members=2` rejects a lone swing extreme
- **no look-ahead**: a pool at swing `j` is invisible at `j+lk-1`, visible at `j+lk`
- `prior_day_levels` rolls exactly at the day boundary and never leaks the current day
- `nearest_pool_beyond` honours floor, cap, direction, and `usable_from_idx <= i`
- returns `None` (→ fallback) when no pool sits in range

### B4 · Scope boundary

Research only. No manifest entry, no `smc_pack` registration, no `config.yaml`
change, no live path touched. If B2 gates GO, promotion follows the normal
research → demo → live ladder as a separate cycle. iFVG (Rule 5) stays out —
it serves no rule in this experiment, and "useful either way" is the
justification that left `ict_zones.py` unused after the revival gate.

## Deliverables

| File | Change |
|---|---|
| `scripts/poc_sb_stops.py` | `RR` → `resolve()` parameter |
| `src/analysis/liquidity_pools.py` | new, pure stdlib |
| `tests/unit/test_liquidity_pools.py` | new |
| `scripts/ict_video_reads.py` | new — A1 + A2 reads, empirical offset derivation |
| `scripts/exp2_liquidity_target.py` | new — A3 sweep + B2 experiment |
| `docs/research/2026-08-03-exp2-liquidity-target-preregistration.md` | pre-registration, committed **before** the B2 run |
| `docs/research/2026-08-03-ict-video-rules-results.md` | results |

## Execution order

1. A1 + A2 reads (frozen tables, plus the `structure_bias` re-run for A2)
2. B1 primitives + tests (additive, no live path)
3. A3 sweep → fixes `RR*`
4. Commit the B2 pre-registration naming `RR*`, the GO criteria, and the
   degeneracy thresholds
5. Run B2, write results

Steps 1–3 are exploratory reads on frozen data and need no gate. **Step 4 is a
hard gate: the pre-registration is committed before step 5 runs.**

## Known gaps

- H1 bars cannot represent the 08:30/13:30 killzone boundaries; buckets snap to
  bar opens.
- A2 is underpowered by construction and is recorded as such.
- Research universe is 11 symbols; a GO does not transfer to US100/ETHUSD/XTIUSD
  without a re-run.
- `SPREADS` is an indicative table, not per-bar measured spread. Unchanged from
  every prior gate on this rig, so it does not bias arm comparison — both arms
  carry the same cost model — but it caps absolute-level confidence.
