# EXP-0 "Coin Flip" — pre-registration

**Date:** 2026-07-31 (registered before the first full run)
**Source:** `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §2, sequenced with STRAT-01
per `07-VERIFICATION-AGAINST-LIVE-TREE.md` §4.
**Rig:** `scripts/exp0_coinflip.py` on `scripts/poc_sb_stops.py` machinery
(`collect_signals` → `resolve` → `replay_managed` → `cost_r`), unchanged except an
additive `bars` schema extension (`atr`, `times`).

## Hypothesis under test

The stop study attributes the entire edge to the exit engine: SilverBullet is
−0.122R with fixed 2R exits and +0.109R with ratchet+runner (same entries, same
costs). If the management layer contributes +0.316R on *any* entry stream with
the right marginals, then random entries plus the ratchet should also be
positive — and the strategy-arsenal programme would be the wrong plan.

## Design

Per symbol, one placebo entry per real SilverBullet signal, matched on:

| Marginal | Mechanism |
|---|---|
| Candidate count | 1:1 with real signals |
| Hour-of-day (broker) | placebo bar sampled uniformly from bars in the same hour |
| Direction balance | the real signals' directions, shuffled (exact multiset) |
| Limit placement | real signal's entry fraction of its bar range, applied to the placebo bar |
| Stop geometry | same `stop_price()` model on the placebo bar's local ATR / structure |

Everything downstream is the study's own code: limit fill within TTL 12 bars,
one open per symbol, pessimistic same-bar SL-first, v14.4 ratchet
(BE 38.2 / bank 61.8 / bank 88.6 + runner trail), costs = indicative FBS
spread + $7/lot commission at 1× spread.

**What is deliberately NOT matched:** the displacement/FVG context. That is the
point — the placebo has SilverBullet's shape with none of its information.

## Registered parameters

- Timeframe **H1**, stop model **ATR10** (the adopted v14.4.2 configuration).
- Universe: the study's 11 symbols (`poc_sb_stops.SYMS`). US100/ETHUSD/XTIUSD
  excluded until the cost table covers them (STRAT-04).
- **reps = 20**, seeds 11…30 (`--seed 11`), deterministic.
- Metric: pooled net expectancy per rep, per arm (FIXED 2R / RATCHET /
  RATCHET+RUNNER), plus the real SilverBullet arms on the same data.

## Registered interpretation bands (RATCHET+RUNNER placebo arm, mean over reps μ)

| Band | Verdict |
|---|---|
| μ ≤ −0.05R | **Outcome 1** — the ratchet needs a real signal; the entry does genuine work. Proceed with the arsenal. |
| −0.05R < μ < +0.05R | **Outcome 2** — the ratchet neutralises costs, no alpha alone; entry carries the edge. Healthy. |
| μ ≥ +0.05R **and** p5 > 0 | **Outcome 3** — entries are decoration. Pivot the research programme to exit-engine parameterisation. |
| μ ≥ +0.05R, p5 ≤ 0 | Inconclusive — raise reps, slice by year, do not claim outcome 3. |

Secondary read: the share of placebo reps with expectancy ≥ the real
SilverBullet figure is a permutation-style p-value for "the entry adds nothing
beyond random" — registered as supporting evidence, not a gate.

## Known limitations (registered up front)

- Offline replay only: inherits the study's optimistic-partials /
  pessimistic-SL conventions and models no slippage or swap (STRAT-03/06).
  Symmetric across real and placebo arms, so the *comparison* stands.
- The real ratchet live is different code (STRAT-01). EXP-0 says nothing about
  live transfer; it separates entry-alpha from exit-alpha inside the replay.
- Hour-matching approximates session/regime placement; it does not match
  volatility state at entry. A placebo conditioned on compressed/expanded ATR
  states is a follow-up, not this experiment.

## Results

*(appended after the registered run — nothing above this line changes)*
