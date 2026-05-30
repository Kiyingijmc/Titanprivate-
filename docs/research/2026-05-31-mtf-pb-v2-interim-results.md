# MTF-PB v2 — Interim Results (thin 3-month sample) — 2026-05-31

**Status: INTERIM / NOT THE VALIDATED VERDICT.** This is the first end-to-end run of the
reworked v2 pipeline (`scripts/poc_mtf_pb2.py`) on the **existing ~3-month M5 data** (20,000 bars
per symbol). The spec's GO/NO-GO gate is reported here, but the headline verdict must wait for the
**max-M5 export** (see "Next step"). Treat anything positive below as a *lead*, not proof.

Raw output: `data/history/mtf_pb2_poc.txt`. Spec:
`docs/superpowers/specs/2026-05-30-mtf-trend-pullback-v2-design.md`.

## Run configuration

- **Strategy:** H4+H1 BOS bias → M15 OTE 0.62–0.79 pullback → liquidity sweep → M5 MSS →
  entry-TF pressure (displacement FVG *or* micro-BOS+displacement) → OTE∩HTF-POI confluence.
- **Stop:** conditional M5-structure (FVG-not-swept → leg origin; FVG-swept → swept extreme;
  no FVG → MSS swing).
- **Entry models:** MARKET-on-confirm (gates the verdict) and LIMIT-at-FVG (uplift, not gated).
- **Exit models:** MANAGED (TP1 internal liq → 33% + BE → M5-swing trail → TP2 external liq) and
  FIXED-2.5R comparator.
- **Costs:** 2× spread + commission (per-symbol specs) **+ 0.05R slippage** on every resolved trade.
- **OOS:** chronological 70/30 train/test per symbol. **Significance:** Wilson CI on win rate +
  percentile bootstrap CI on expectancy.
- **Data span:** ~3 months M5 per symbol (the binding caveat).

## GO/NO-GO gate (per asset class)

> Positive net-of-cost expectancy in **BOTH train AND test**, **n ≥ 30**, under **BOTH exit
> models**, on the **MARKET (conservative) entry**. A single class passing counts (per-class gate).
> LIMIT entry is reported as upside only.

## Headline (MARKET entry — the gated path)

| Class | MANAGED exp (tr / te) | FIXED exp (tr / te) | n (mgd/fix) | Gate |
|---|---|---|---|---|
| **metals (XAUUSD)** | **+0.192** (+0.217 / +0.136) | **+0.124** (+0.084 / +0.215) | 118 / 88 | ✅ **PASS** |
| **crypto (BTCUSD)** | **+0.096** (+0.075 / +0.144) | **+0.077** (+0.053 / +0.130) | 85 / 67 | ✅ **PASS** |
| index (US30) | +0.158 (+0.128 / +0.227) | −0.015 (−0.011 / −0.025) | 59 / 46 | ⚠️ managed-only |
| energy (XBRUSD) | +0.047 (+0.074 / **−0.014**) | −0.170 | 78 / 60 | ❌ |
| FX-majors | −0.278 | −0.356 | 356 / 265 | ❌ |
| FX-crosses | −0.632 | −0.718 | 179 / 138 | ❌ |
| **POOLED-ALL** | −0.192 | −0.283 | 875 / 664 | ❌ (basket loses) |

**Two classes pass the strict dual-model gate on this sample: metals and crypto.** Both are
positive in train *and* test under *both* exit models with n ≥ 30. Index is OOS-positive but only
under the managed model (its fixed-2.5R variant is flat-negative), so it fails the dual-model gate.
Everything FX is strongly negative — exactly as the trend-pullback thesis predicts. The pooled
basket loses money (FX dominates the count), so this is a **per-class edge, not a basket edge**.

### Significance / fragility notes
- **metals** — strongest. Managed bootstrap CI **[+0.12, +0.25]** excludes zero; win 89.8% (managed)
  / 64.8% (fixed); PF 3.89 / 1.38; max-DD 2R / 9R. The fixed model's bootstrap CI **[−0.08, +0.34]**
  *includes zero* → the fixed edge is not significant on its own.
- **crypto** — managed bootstrap CI **[+0.01, +0.17]** barely excludes zero; fixed CI
  **[−0.14, +0.30]** includes zero. Genuinely marginal.
- Test subsamples are small (metals te n=36/27; crypto te n=26/21) — within the "promising not
  proven" zone.

## Setup funnel (attrition; bar-passes, not distinct setups)

```
FILTERED  : bias 37307 = leg 37307 → armed 14812 → sweep 11827 → mss 2835 → pressure 1779 = confluence 1779 = emitted 1779
BASELINE  : bias 37307 = leg 37307 → armed 14812 → sweep 14812 → mss 3548 → pressure 2239 = confluence 2239 = emitted 2239
```

Two findings worth carrying forward:
1. **MSS is the dominant filter.** The M5 market-structure-shift gate cuts ~80% of armed-and-swept
   setups (11827 → 2835 filtered). This is where most candidates die.
2. **The HTF-POI confluence filter is currently NON-BINDING** — `pressure == confluence` in both
   modes (1779 = 1779; 2239 = 2239). Every pressure-passing setup already overlaps some H1/H4 POI,
   because the POI set includes *every confirmed swing-candle range*, which is dense enough to
   almost always intersect the zone. **Action for next iteration:** tighten the POI definition
   (e.g. only unmitigated order blocks / FVGs in the trend direction, drop raw swing ranges) so the
   filter actually discriminates — or drop it as ineffective. The "sweep" filter, by contrast, does
   bite (14812 → 11827, ~20%).

## LIMIT entry (uplift — NOT gated, and currently UNRELIABLE)

- **LIMIT / FIXED-2.5R:** strongly negative across every class (pooled −1.211R). The resting limit
  at the FVG fills, then the fixed 2.5R target is rarely reached before reversal. After the
  unresolved-trade accounting fix, n dropped (EXPIRED fills no longer mis-counted) but the sign is
  unchanged: this exit pairing does not work.
- **LIMIT / MANAGED:** prints implausibly large positives (metals +1.096R, index +2.864R,
  crypto +4.805R) with **enormous, unstable bootstrap CIs** (e.g. crypto [+1.18, +11.39]). This is
  almost certainly an **artifact of the tiny risk denominator** — the limit fills very close to the
  M5 stop, so the same price move maps to a huge R multiple — compounded by an optimistic single-
  bar limit-fill assumption. **Do not trust these numbers.** Quantifying the *real* limit/M1-M2
  entry uplift against the same M5 stop is exactly the job of Tier 2 (deferred), which must model
  fill realism and recompute cost-in-R at the tighter risk.

## What this is NOT

- **Not validated.** ~3 months of M5 is thin; metals/crypto test samples are small; the fixed-model
  bootstrap CIs for both include zero.
- **Multiple comparisons.** 6 classes × 2 exit models = 12 looks; two survivors can arise by chance.
  metals + crypto are **leads**, not confirmed edges.
- **Not a basket.** Pooled expectancy is negative; only specific classes show signal.

## Next step (unblocks the real verdict)

With the live MT5 + Gateway EA up and `main.py` stopped, pull the maximum M5 history FBS returns:

```bash
for S in EURUSD GBPUSD USDJPY AUDUSD USDCAD GBPCAD GBPJPY XAUUSD US30 BTCUSD XBRUSD; do
  .venv/bin/python scripts/export_history.py --symbol "$S" --tf M5 --count 200000 \
    --out "data/history/${S}_M5.csv"
done
```

Then re-run `.venv/bin/python scripts/poc_mtf_pb2.py` and write the final verdict doc
(`docs/research/<date>-mtf-pb-v2-results.md`) with the **same a-priori params** (no sweeping). If
metals/crypto hold positive in train+test under both models at n ≥ 100+, that is a GO for those
classes → proceed to Tier 2 (M1/M2 entry refinement) and then the management layers.
