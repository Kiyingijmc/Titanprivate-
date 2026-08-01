# ICT-family revival gates — results: NO-GO everywhere, both models

**Date:** 2026-08-01 · **Pre-registration:** `2026-08-01-ict-revival-gate.md` (committed
1b817f2 before either run; frozen rule sets; OTE-cycle criteria verbatim) · **Rig:**
`scripts/poc_ict_revival.py` @ 7376f93, golden-slice hand-verified per model ·
**Raw:** `data/history/unicorn_canonical_trades.csv`, `data/history/crt_canonical_trades.csv`
(root checkout) · **One pass per model; no re-tuning.**

## Verdicts

| Model | Verdict | Pooled (MANAGED net 1×) | Classes |
|---|---|---|---|
| **Canonical Unicorn** | **NO-GO everywhere** | −0.209R, n=562, PF 0.66, win 28.5%, DD 119R, negative every year 2023–26 | 0/5 pass; 4/5 flip sign at ×1.5 |
| **Canonical CRT** | **NO-GO everywhere** | −0.150R, n=1,882, PF 0.77, win 25.3%, DD 316R, negative every year 2023–26 | 0/5 pass; 4/5 flip sign at ×1.5 |

Both fail under BOTH exit models (the dual-exit gate) — as with OTE, "the management
engine has nothing to rescue": a negative raw entry stream gets no amplification.

## Detail

**Unicorn** (H4+H1 bias → H1 leg → breaker∩FVG zone → retest + M5 MSS → 2.5R):
selective by construction (≈600 trades/3y across 10 costed symbols; the breaker∩FVG
overlap filter removed 96% of legs). Only XAUUSD positive (+0.162R managed, n=46 — inside
noise). FX-majors' test-set +0.006R managed sits on a −0.367R train and a CI spanning
zero. Cost screen: all symbols pass except XBRUSD (0.653R — structural stops on Brent are
too tight for its spread); costs are NOT the failure mode here — the signal is.

**CRT** (prev-day range → raid → close-back-inside → retest → M5 MSS → opposite-extreme
target): ~1,900 trades/3y. Win rate 24–25% against a variable RR that averages far below
what that win rate needs. US30 alone +0.053R managed (its class still fails train/test
consistency). Metals' +0.043R test rides a −0.148R train — the small-sample-optimism
signature the MTF-PB lesson warns about, correctly caught by the train-AND-test criterion.

## What this closes

With OTE canonically NO-GO'd 2026-07-11 and Unicorn + CRT canonically NO-GO'd today, **all
three retired ICT models are now falsified in their canonical, correctly-implemented,
confirmation-disciplined forms** on this broker's costs — not merely "removed." The
2026-05-29 evidence review's caveat ("that confirmation raises win rate is ICT folklore —
no independent statistic proves it; we must verify on our own data") has now been verified
three times: MSS-confirmed retest entries did not produce a positive raw edge in any of
the three models. SilverBullet remains the only ICT entry stream on this rig that clears
costs, and only via H1 scale + the managed engine.

**Re-activation: NONE.** No manifest, config, or live change. The graveyard doc is
updated; both models' entries move from "removed unvalidated" to "canonically falsified"
with these run records. Per the one-pass rule, any future revisit requires a new
mechanically-motivated design and its own pre-registration — an appeal to "try different
parameters" is not one.

Standing assets from this cycle regardless of verdict: `src/analysis/ict_structure.py`
restored (30 tests) and `src/analysis/ict_zones.py` added (12 tests) — tested MTF/zone
primitives available to any future candidate; the revival rig itself reruns either model
deterministically.
