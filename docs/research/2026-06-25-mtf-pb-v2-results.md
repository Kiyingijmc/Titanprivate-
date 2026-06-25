# MTF-PB v2 — 3-Year Validation Results & GO/NO-GO Verdict — 2026-06-25

**Verdict: NO-GO.** On ~3 years of M5 (2023-06 → 2026-06, all 11 symbols, ~2.45M bars), **no
asset class clears the dual-model out-of-sample gate.** The promising 3-month leads (metals +
crypto) were small-sample optimism — they collapsed toward zero on the larger sample.

Raw output: `data/history/mtf_pb2_poc_3yr.txt`. Supersedes the interim
`docs/research/2026-05-31-mtf-pb-v2-interim-results.md` (which was explicitly thin-sample/promising).
Data obtained via the new HTTP bridge (Phase 1), which revealed FBS retains ~3 years of M5 — the
old ~3-month limit was the EA/ZMQ export cap, not the broker.

## Gate (per spec)
Positive net-of-cost expectancy in **both train AND test**, **n ≥ 30**, under **both exit models**,
on the **conservative MARKET entry**. (n is no longer a constraint — all candidate classes have
n = 760–1253, test subsamples 220–380; significance is solid. The edges are simply ~0.)

## MARKET entry — the gated path

| Class | MANAGED exp (tr / te), bootCI | FIXED exp (tr / te), bootCI | Gate |
|---|---|---|---|
| metals (XAUUSD) | +0.024 (−0.001 / +0.080) [−0.01,+0.06] | +0.101 (+0.051 / +0.218) [+0.02,+0.18] | ❌ managed train ≈0-neg |
| index (US30) | +0.041 (+0.009 / +0.115) [+0.01,+0.07] | +0.017 (+0.027 / −0.006) [−0.06,+0.10] | ❌ fixed test negative |
| crypto (BTCUSD) | +0.030 (+0.007 / +0.083) [−0.01,+0.06] | −0.121 (−0.212 / +0.091) [−0.20,−0.04] | ❌ fixed train negative |
| energy (XBRUSD) | −0.103 | −0.081 | ❌ |
| FX-majors | −0.359 | −0.368 | ❌ |
| FX-crosses | −0.585 | −0.579 | ❌ |
| **POOLED-ALL** | −0.274 (n=11533) | −0.285 (n=8536) | ❌ basket loses |

Each apparent winner passes exactly **one** exit model and fails the other — the model-dependence
the dual-model rule is designed to reject.

## The collapse vs. the 3-month interim (why NO-GO is the right call)

| managed exp | 3-month (interim) | 3-year (this run) | ratio |
|---|---|---|---|
| metals | +0.192R | +0.024R | ÷8 |
| index | +0.158R | +0.041R | ÷4 |
| crypto | +0.096R | +0.030R | ÷3 |

The positives shrank 3–8× toward zero as n grew from a few hundred to ~1,000+. This is the classic
small-sample-optimism signature. Removing the data wall did its job: it converted a false "promising"
into an honest "no robust edge."

## What is real vs. noise
- **Faint, model-dependent signal (not a GO):** metals/FIXED-2.5R is the single most robust result
  — +0.101R, n=760, train +0.051 / test +0.218, bootstrap CI [+0.02,+0.18] excludes zero. But it
  dies under the managed model (+0.024R, train ≈ −0.001), so by the anti-overfit dual-model rule it
  does not pass. A single-asset single-model +0.10R is thin and high-overfit-risk.
- **FX strongly negative** under both models (−0.36 to −0.59R) — consistent with the thesis that
  trend-pullback works worst on FX; a good sanity check that the pipeline isn't just noise.
- **Cost drag dominates the managed model:** managed per-trade R for the "winners" is +0.02–0.04,
  barely above the cost+slippage deduction — the edge, if any, is eaten by frictions.
- **Confluence filter is dead weight at scale:** FILTERED pressure 23,738 → confluence 23,484
  (~1% removed); BASELINE pressure == confluence (29,714 == 29,714). The HTF-POI confluence filter
  as implemented (FVG gaps + all swing-candle ranges) is so permissive it discriminates ~nothing.
- **MSS is the real filter:** sweep 146,071 → mss 37,420 (~74% cut) — the M5 CHoCH gate does the work.
- **LIMIT/MANAGED is unusable:** index +6.58R (test +20.4R, CI [+0.70,+15.31]), energy +2.06R —
  tiny-risk-denominator artifacts + optimistic single-bar limit fills. Not evidence of anything;
  quantifying the real fine-entry effect is Tier 2 (deferred), which must model fill realism.

## Implications / next step
- **Do NOT build the management layers** (order/risk/account/…/ML) — there is no validated edge to
  manage. This is the same discipline that (correctly) shelved the ICT strategies.
- The trend-pullback thesis has now been tested twice (v1, v2) and does not clear costs robustly on
  FBS intraday. The accumulating evidence weighs against more mechanic-tweaking of the same thesis.
- If iterating anyway: (1) drop the confluence filter (confirmed non-binding); (2) the metals/FIXED
  result is the only thread worth pulling, but treat a single-asset/single-model +0.10R with extreme
  suspicion (multiple comparisons across 6 classes × 2 models); (3) Tier 2 (M1/M2 entry) was the
  hypothesised R-booster, but the LIMIT numbers here are artifacts — it would need an honest,
  fill-realistic study before any claim.
- **Infrastructure win stands regardless:** the HTTP bridge (Phase 1) + 3-year data pull + the ~18×
  pipeline optimization are durable assets for whatever strategy comes next.

## Reproduce
`.venv/bin/python scripts/poc_mtf_pb2.py` (reads `data/history/*_M5.csv`; no bridge needed). Same
a-priori params, no sweeping. Deterministic (bootstrap seeded).
