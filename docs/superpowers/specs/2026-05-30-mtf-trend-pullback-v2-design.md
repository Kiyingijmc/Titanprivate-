# Spec: MTF Trend-Pullback v2 ("MTF-PB v2") — 2026-05-30

Status: approved (brainstorming). Branch: `harden/normalize-price-crash`.
Supersedes the v1 PoC design (`docs/superpowers/specs/2026-05-30-mtf-trend-pullback-poc-design.md`)
as the **forward** design. The v1 PoC and its code (`scripts/poc_mtf_pb.py`) stay untouched as the
baseline to compare against.

## Purpose

Rework the MTF trend-pullback strategy **from the mechanics up**, keeping only the core thesis
(*"align the higher-TF trend, enter on a pullback in the trend direction"*) and redesigning every
mechanical layer beneath it. Then **validate whether it has a net-of-cost edge** on the existing
offline harness — *before* any live or management code.

This responds to the v1 verdict (`docs/research/2026-05-30-mtf-pb-poc-results.md`): the v1 rules
were net-negative on every asset class except metals (XAUUSD), which was the lone OOS survivor but
on a thin ~3-month sample — "promising, not validated." v2 keeps the discipline (a-priori params,
net-of-cost, OOS, significance) and reworks the trend filter, pullback definition, entry trigger,
and risk geometry that were the weak points.

## What changed from v1 (at a glance)

| Layer | v1 | v2 |
|---|---|---|
| Trend bias | 50-EMA close-cross, H4+H1 agree | **Market-structure BOS**, H4+H1 agree |
| Pullback | fib 0.5–0.705 of a 5-bar M5 leg | **OTE 0.62–0.79 of an M15 impulse leg** (must have broken prior swing) |
| Confirmation | M5 resumption candle close | **liquidity sweep → M5 MSS → entry-TF pressure (FVG or micro-BOS+displacement) → OTE∩HTF-POI confluence** |
| Entry order | market at next M5 open | **two models: market-on-confirm AND limit-at-FVG** |
| Stop | 1.0×ATR(H1) | **conditional M5-structure stop** (see table) |
| Exit | fixed-2.5R; partial-at-1R + BE + 2.0×ATR trail | **managed: TP1 internal liq → 33% + BE → trail M5 HL/LH → TP2 external liq**; comparator: fixed-2.5R |
| Entry granularity | M5 only; 1–2m deferred to live | **M5 (Tier 1) + M1/M2 refinement quantified offline (Tier 2)** |

## Hard rules (non-negotiable)

- **Structural stops only** (never sub-pip/tight — the SilverBullet spread lesson). Exact anchor
  is conditional (see Stop-loss).
- **Validate net-of-cost in R** AND **out-of-sample** (chronological train/test) AND
  **significance** (Wilson CI + bootstrap; flag `n<30`). A frictionless R result means nothing.
- **No parameter sweeping.** All parameters are a-priori, committed below *before* running. Choose
  rules from market-structure reasoning, run **once** through the gate. Overfitting is the #1
  verified risk; v2 adds *two* sample-hungry filters, which makes this rule more important, not less.
- **No look-ahead.** Every HTF read uses **closed bars only** (last-closed-bar indexer); fib/pivot
  from past bars only; entry at the **next** bar open after a confirmation close.
- **Conservative entry gates the verdict.** With two entry models, the GO/NO-GO uses the
  conservative market-on-confirmation entry; limit-at-FVG is reported as potential *uplift* only.

## Data reality (constraints that shaped the design)

- The strategy as actually traded is finer than M5: **entries on M1/M2**, with **M5 as the
  market-structure-shift confirmation** in the trend direction (opposite the pullback).
- **M1 deep history is not viable** for a credible gate (≈20k M1 bars ≈ 2 weeks). The EA exports
  M5/H1 only today; M1 needs an export extension and even then is thin.
- **Key insight that resolves this:** the signal *fully forms at the M5 MSS*. M1/M2 only change the
  **entry price and stop tightness**, not *whether the trade fires*. So we validate in two tiers
  (below) — the core edge at M5 fidelity on the longest M5 history we can pull, and the M1/M2 entry
  refinement separately and subordinately.
- H4/H1/M15 are **resampled from M5** (the harness already does this). The first build action is to
  pull the **maximum M5 history** FBS returns (raise `--count`) and record the real span; v1 had
  only ~3 months.
- Two stacked quality filters (sweep + HTF-POI confluence) **shrink trade count hard**. We mitigate
  with a setup **funnel report** (survivors per stage) and an **unfiltered core-thesis baseline**
  run alongside — both informational, neither selected on — so a starvation-driven low `n` is
  visible rather than mistaken for "no edge."

## The strategy (one rule set; short is the mirror of long)

All timeframes resampled from M5. All HTF reads use **closed bars only**. Long is described; short
is the exact mirror.

### Setup (signal) — top-down

| Layer | Rule (long) | A-priori parameter |
|---|---|---|
| **H4 bias** | last *confirmed* H4 swing sequence is higher-high + higher-low (bullish BOS) | pivot = **3 bars** each side |
| **H1 bias** | same BOS test on H1; must **agree** with H4, else stand aside | pivot = **3 bars** each side |
| **M15 impulse leg** | most recent M15 swing leg in bias direction that **broke the prior M15 swing** (a real displacement, not a wiggle) | pivot = **2 bars** each side |
| **OTE pullback** | price retraces into **[0.62, 0.79]** of that leg (low→high); sweet spot 0.705. Invalidate if price closes beyond the leg origin before confirmation | fib band fixed **[0.62, 0.79]** |
| **Liquidity sweep** | the pullback must **take out a prior swing low** (sell-side liquidity grab) before the MSS | prior minor swing (M5/M15) |
| **M5 MSS** | an M5 **close back above the most recent M5 lower-high** (CHoCH in the trend direction) while armed | — |
| **Entry-TF pressure** | **displacement FVG** (imbalance *left behind* by the resumption impulse off the zone, in the trend direction) *OR* (**micro-BOS** + **displacement candle**) | displacement = body ≥ **60%** of range AND range ≥ **1.0×** median range of last **20** bars; FVG = 3-candle imbalance (c1.high < c3.low) |
| **HTF-POI confluence** | the OTE zone must **overlap an H1 or H4 POI** (order block *or* FVG *or* prior structural swing level) | H1/H4 OB/FVG/level |

**Two distinct FVGs — do not conflate:**
- **OTE-leg FVG** (used by the **stop logic** only): an FVG *within the M15 impulse leg* whose body
  is **≥30% inside the golden zone (0.62–0.79)**, *or* lies **entirely within** it. This is the
  imbalance price pulls *back into*; the stop depends on whether the pullback swept it.
- **Displacement FVG** (used by the **pressure test** only): an FVG *left behind by the resumption
  impulse off the zone*, in the trend direction, on the confirmation/entry timeframe. This is
  evidence of aggressive displacement at entry, not a retracement target.

**Per-tier resolution of the pressure test:** evaluated on **M5 in Tier 1** (where the "micro-BOS"
is effectively the M5 MSS itself, so the test reduces to *MSS candle is a displacement candle, or
the resumption impulse leaves an M5 FVG*) and on **M1/M2 in Tier 2** (true entry-TF pressure).

Trade only longs when H4 & H1 both bullish; only shorts when both bearish; else stand aside.
**Not session/time-bound.** One open position per symbol at a time.

### Entry orders — two parallel models (reported side-by-side)

- **A. Market-on-confirmation** — MARKET at the close of the confirming bar / next-bar open.
  Conservative fill (pays spread, enters into displacement). **This model gates the verdict.**
- **B. Limit-at-FVG/OB** — rest a LIMIT at the discount FVG midpoint / order-block edge left by the
  displacement, expecting a retrace. Better fill + logical invalidation; some setups never retrace
  (model **fill rate** + a **TTL**). Reported as potential uplift, not gated.

(The EA places **MARKET and LIMIT only — no stop orders**; both models respect this. `MODIFY`
enables BE/trailing and `CLOSE_POS` enables partials at the live stage; out of scope for the PoC.)

### Stop-loss — conditional on the OTE-leg FVG (M5 structure)

| Condition | Stop placed… |
|---|---|
| Qualifying FVG present, pullback **did not fully sweep** it | below the **OTE leg origin** |
| Qualifying FVG present, pullback **fully swept** it | below the **swept extreme** (sweep low) |
| **No** qualifying FVG in the leg | below the **M5 MSS swing** |

"Fully swept" = price traded through the **far edge** of the qualifying FVG; "not fully swept" =
price reacted before clearing it. The **same M5 stop level is used in both validation tiers** — the
M1/M2 entry never moves the stop, it only changes the entry price.

### Exit — two parallel models (reported side-by-side)

- **Managed (primary, the real strategy):**
  - **TP1 = nearest internal liquidity** (nearest opposing minor swing above entry). On TP1: book
    **33%** and move the runner stop to **breakeven**.
  - **Runner (67%)** trails each new **M5 higher-low** (bull) / **lower-high** (bear), activated
    **after TP1**, with final target **TP2 = external liquidity** (the M15/H1 leg high / next swing
    the trend reaches for). Runner closes at the **trail-stop or TP2, whichever comes first**.
- **Comparator:** fixed **2.5R**, full position, no management (for comparability with v1 and to
  isolate whether the managed model actually adds anything).

**Total parameter budget (committed a-priori, never swept):** H4/H1 pivot 3, M15 pivot 2, fib band
[0.62, 0.79], qualifying-FVG zone overlap 30%, displacement body 60% / range 1.0× / median window
20, partial 33% at TP1, fixed comparator 2.5R.

## Architecture

One new script: `scripts/poc_mtf_pb2.py`, mirroring `scripts/poc_mtf_pb.py`'s shape. v1 stays
untouched.

**Reused from the harness** (`tests/backtest/backtest_engine.py`): `simulate_signals`,
`resolve_trade`, `aggregate_metrics`, `split_trades`, `win_rate_ci`.
**Reused from `poc_trend_h4.py`**: `resample` (M5→HTF), `atr_series`, `net_r_after_costs`, `_net`,
`SPREAD` map + `data/specs.json` loading, the per-instrument report pattern.

**New pure functions (TDD-first, each independently testable):**

- `resample_tf(m5_df, rule)` — M5 → '15min'/'1h'/'4h' (closed bars).
- `swing_pivots(df, n)` → confirmed swing highs/lows (N-bar fractal, past bars only).
- `structure_bias(htf_df, n)` → BULLISH/BEARISH/NEUTRAL per closed HTF bar (BOS logic).
- `mtf_bias_at(ts, bias_4h, bias_1h)` → combined bias for an M5 timestamp, last-closed bars only.
- `impulse_leg(m15_window, pivot)` → (origin, extreme) of the most recent leg that broke the prior
  M15 swing; `ote_zone(leg)` → [0.62, 0.79] band; plus invalidation test.
- `find_fvg(window)` (generic 3-candle imbalance); `qualifying_fvg(leg, zone, fvgs)` → the
  **OTE-leg FVG** (≥30% body in zone or entirely within) for the stop logic.
- `swept_liquidity(window, leg)` → did the pullback take out a prior swing low, and the sweep low.
- `mss_confirm(m5_window, bias)` → M5 CHoCH back in trend direction while armed.
- `is_displacement(bar, median_range)`, `micro_bos(window, bias)`, `pressure_ok(...)` →
  (**displacement FVG** left by the resumption impulse) OR (micro-BOS + displacement candle).
- `htf_poi_overlap(zone, h1_df, h4_df)` → OTE ∩ H1/H4 OB/FVG/level.
- `conditional_stop(leg, zone, fvg, sweep, mss_swing)` → the stop per the table above.
- `build_signals(...)` → composes all of the above (no look-ahead); emits, per setup, entry dicts
  for **both** entry models, the stop, TP1/TP2 levels, and the funnel stage it reached.
- `simulate_managed(signals, bars)` → custom exit loop: TP1 → 33% + BE → M5-swing trail → TP2.
- `mae_mfe(trade, bars)` → max adverse / favorable excursion per trade.
- Tier-2: `m1_refined_entry(...)` + `entry_uplift(...)` → R-uplift and cost-in-R vs the M5 entry.

Fixed-2.5R comparator builds `resolve_trade`-style signal dicts and goes **straight through
`simulate_signals`** — no new exit code. Only the managed model needs the custom loop.

## Validation protocol (the go/no-go gate)

Every reported number is **net of cost**: `net_r = r − 2·spread/stop − commission_R`, **plus** a
slippage add on market entries and a killzone spread-widening assumption (see Diagnostics).

### Tier 1 — core edge at M5 fidelity (the GO/NO-GO)

1. **Data:** maximum M5 history pulled per symbol (record the real span). All 11 instruments.
2. **Out-of-sample:** 70/30 chronological train/test (`split_trades`) **per symbol**. Edge must
   survive in TEST. Single-instrument classes are chronologically clean; for pooled multi-symbol
   classes the documented intermixing caveat stands.
3. **Significance:** Wilson CI on win rate **plus bootstrap/MC CIs** on expectancy and a max-DD
   distribution. Flag `n<30` loudly.
4. **Per asset class** (FX-majors, FX-crosses, metals, index, crypto, energy), per-instrument, and
   pooled — under **both exit models**, using the **conservative market-on-confirmation entry**.
5. **Funnel + baseline:** report setups surviving each filter stage, and an **unfiltered
   core-thesis** run (bias→OTE→MSS, no sweep/confluence) alongside — informational only.

**GO (per class):** net-of-cost expectancy **positive in BOTH train and test**, sample **n≥30**,
under **BOTH exit models**, on the **market-on-confirmation entry**. A single class passing on its
own counts (per-class gate). Limit-at-FVG entry is reported as uplift, not part of the gate.

**NO-GO:** anything less → iterate the (few, a-priori) rules or shelve. If samples remain too thin,
the honest output is **"inconclusive on this data — need more history,"** stated plainly.

### Tier 2 — M1/M2 entry refinement (subordinate, informational)

- Extend the export to **M1** (`export_history.py` `--tf` + verify the EA passes `PERIOD_M1`);
  resample M1→M2. Pull the max M1 available (explicitly a short window).
- On the overlap window, for setups Tier 1 already flagged, take the refined M1/M2 entry against
  the **same M5 stop** and measure the **net** effect: (1) **R-uplift** (better entry, same stop →
  more R to the same target), minus (2) **added cost-in-R** (risk-in-price shrinks → spread is a
  bigger fraction), recomputed at the refined risk. Stop-out rate is unchanged (same stop level).
- **Output:** a single honest verdict — *"M1/M2 entry changes net expectancy by X R vs M5 entry,
  after costs"* — clearly caveated as thin-sample. It may be **negative**; that is a real finding.
- **Gating:** Tier 2 **never overrides** Tier 1. If Tier 1 is NO-GO, Tier 2 is informational only.
  Tier 2 can **downgrade** an otherwise-passing class if the refined entry destroys the edge on
  cost.

## Diagnostics & realism (low/no overfit cost)

- **MAE/MFE** per trade — diagnoses whether the M5 stop is too tight/wide and whether the targets
  leave money on the table; also quantifies the Tier-2 entry uplift directly.
- **Bootstrap / Monte-Carlo CIs** — resample the trade sequence for expectancy CI and a max-DD
  distribution; honest significance on small `n`.
- **Slippage + spread-widening** — a slippage add on market entries (entering into displacement
  fills worse than mid) and a killzone spread bump; makes the cost picture honest rather than rosy.
- **Funnel + unfiltered baseline** — described above.

## Risks designed against

- **Sample starvation (biggest):** two stacked quality filters on thin data. Mitigated by the
  funnel + unfiltered baseline; treat `n<30` as *non-evidence*, not negative evidence.
- **Overfitting:** fixed a-priori params, no sweep, single pass; two exit models + two entry models
  as robustness cross-checks (not selection knobs — the gate is pinned to the conservative combo).
- **Multiple comparisons:** per-class gate across 6 classes × 2 exit models inflates false-positive
  risk; a single surviving class is a **lead**, not proof (same caution as v1).
- **Cost-in-R with tight structural stops:** could be the edge-killer; reported explicitly per
  symbol (median stop size in price + cost-in-R), and re-measured at the Tier-2 refined risk.
- **Look-ahead in MTF:** closed-bar-only reads; fib/pivot/sweep from past bars; entry at next open.
- **Tier-2 operational dependency:** M1 export needs live MT5 + Gateway EA up with `main.py`
  stopped (shared ZMQ ports) — a manual step by the user; the rest is offline.

## Out of scope (this PoC)

Live execution, and **all** management layers (order, risk, account, compounding, bookkeeping,
accounting/auditing) and **ML** — those come *only after* a validated edge, in the stated order,
ML last. (`MODIFY`/`CLOSE_POS` feasibility for live BE/trail/partial is noted but not built here.)

## Sequence after a validated edge

order management → risk management → account management → compounding → bookkeeping →
accounting/auditing → ML (last).
