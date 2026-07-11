# Pullback Monetizer Overlay — 3-Year Gate Results

**Date:** 2026-07-11 · **Rig:** `scripts/poc_sb_stops.py` Section 6 (overlay replay)
**Data:** 3 years M5 (2023-06 → 2026-06), 11 instruments resampled to H1, FBS specs
(`data/specs.json`), costs charged in R (indicative FBS spread ×1/×1.5 + $7/lot).
**Raw output:** `data/history/sb_overlay_H1.log`
**Spec:** `docs/superpowers/specs/2026-07-11-pullback-monetizer-overlay-design.md`

## Question

Does a runner-phase pullback overlay on the validated SilverBullet H1 config reduce
the ~24R drawdown from runner give-back without giving back the edge? Two arms were
tested against the frozen Control: **A** = bank fraction `f` of the tail on a pullback
signal and re-add on resumption (the "sell scalp / re-buy" the user described); **C** =
the zero-cost comparison — tighten the runner trail on the same signal, take no extra
trades. The spec pre-registered: *if C beats A net, ship C and never build the re-add
machinery.*

## Control baseline reproduced

Section 6 Control (chronological, all 11 symbols, net 1× costs): **n=2217, exp=+0.109R,
totR=+242.4, PF=1.26, DD=24R** — matches the stop study's headline
(+0.109R / PF 1.26 / 24R) exactly. (Section 4's RATCHET+RUNNER prints DD=129R because
`block()` orders trades symbol-by-symbol; Section 6 orders chronologically across the
portfolio, which is the correct equity-curve DD and the number the study published.
Overlay DD figures below are the same chronological basis — apples-to-apples.)

## Results (net 1× costs; OOS = last 30% chronological; 1.5× = spread stress)

| cell | exp | totR | PF | DD | OOS exp | 1.5× exp | gate |
|------|-----|------|----|----|---------|----------|------|
| **CONTROL** | +0.109R | +242.4 | 1.26 | 24R | — | — | — |
| giveback f0.5 g0.5 **A** | +0.114 | +252.9 | 1.28 | 23R | +0.112 | +0.035 | fail |
| giveback f0.5 g0.5 **C** | **+0.130** | **+288.5** | **1.32** | 22R | +0.125 | +0.051 | fail |
| giveback f0.5 g0.75 **A** | +0.109 | +241.2 | 1.26 | 24R | +0.107 | +0.030 | fail |
| giveback f0.5 g0.75 **C** | **+0.130** | **+288.8** | **1.32** | **21R** | +0.125 | +0.052 | fail |
| giveback f1.0 g0.5 **A** | +0.119 | +263.5 | 1.29 | 22R | +0.115 | +0.040 | fail |
| giveback f1.0 g0.5 **C** | +0.130 | +288.5 | 1.32 | 22R | +0.125 | +0.051 | fail |
| giveback f1.0 g0.75 **A** | +0.108 | +240.0 | 1.26 | 23R | +0.105 | +0.029 | fail |
| giveback f1.0 g0.75 **C** | +0.130 | +288.8 | 1.32 | **21R** | +0.125 | +0.052 | fail |
| m15disp f0.5 **A** | +0.111 | +245.9 | 1.27 | 24R | +0.109 | +0.032 | fail |
| m15disp f0.5 **C** | +0.113 | +251.6 | 1.27 | 23R | +0.111 | +0.035 | fail |
| m15disp f1.0 **A** | +0.112 | +249.4 | 1.27 | 23R | +0.110 | +0.034 | fail |
| m15disp f1.0 **C** | +0.113 | +251.6 | 1.27 | 23R | +0.111 | +0.035 | fail |

## Reading the table

Three findings, in order of importance:

1. **Every cell fails on exactly one criterion: DD ≤ 18R.** No configuration got the
   drawdown to the pre-registered target; the best (giveback g0.75, arm C) reached 21R.
   PF ≥ 1.26, totR ≥ 90% of Control, OOS > 0, and 1.5× > 0 all pass comfortably for the
   arm-C cells. So by the strict pre-registered gate, the answer is **NO-GO**.

2. **Arm C dominates arm A on every single cell.** Trail-tighten — which adds *no
   trades and no cost* — beats bank-and-re-add on expectancy, totR, PF, DD, OOS, and
   spread stress in all four give-back cells (+0.130R vs A's +0.108…+0.119R). The
   re-add machinery pays spread for a worse result. This is precisely the outcome the
   spec's arm-C control was built to detect, and it fired unambiguously: **the child-
   ticket / bank-and-re-add design (arm A) should not be built.**

3. **The give-back signal beats the M15 counter-displacement signal.** Give-back arm C
   (+0.130R, PF 1.32) clearly outperforms m15disp arm C (+0.113R, PF 1.27). The simple,
   signal-free give-back trigger is the better and cheaper detector; M15 displacement
   adds complexity for less.

## What arm C actually is, and why it's interesting despite the "fail"

Give-back arm C is a **strict Pareto improvement over the live Control, for free**:
expectancy +0.109R → +0.130R (+19%), totR +242 → +289 (+19%), PF 1.26 → 1.32,
DD 24R → 21R (−12%), and it holds OOS (+0.125R) and under 1.5× spread (+0.052R). It
requires **no re-add, no child tickets, no new StateManager fields** — just: while in
the runner phase, when price retraces ≥ 0.75×trail from the high-water mark, tighten
the runner trail from 0.268×range to 0.10×range. That is a few lines in
`TradeManager`, not the multi-position live-plumbing plan the spec gated.

The gate said NO-GO because the pre-registered DD target (≤18R) was chosen to justify
building the **costly** re-add machinery. Arm C clears a much lower bar — "improve
risk-adjusted return without adding cost" — decisively. The DD target being missed by
3R does not change that arm C is free money on every other axis.

## Verdict

- **Arm A (bank + re-add / child tickets): NO-GO — do not build.** Dominated by arm C
  everywhere; the spec's own kill-switch fired. The live-plumbing plan (child tickets,
  StateManager overlay state, ExposureManager, Telegram re-add events) is cancelled.
- **Arm C (trail-tighten only): the pre-registered gate is a formal NO-GO (DD 21R > 18R
  target), but arm C is a robust, zero-cost Pareto improvement and its live change is
  trivial.** This is the decision point for the user (the GO/NO-GO was always theirs):
  ship the tiny arm-C trail-tighten as a follow-up, or hold at the validated v14.4.2
  Control. Recommendation: **ship arm C** — give-back signal, g=0.75, tighten to
  0.10×range — as a small `TradeManager` change with its own demo-forward-test, since
  it improves every metric at no added cost and needs none of the shelved plumbing.

Durable artifacts regardless of the decision: the overlay replay + gate rig
(`replay_overlay`, `metrics`, Section 6) is now part of `poc_sb_stops.py` and can
re-validate any future management tweak against costs, OOS, and spread stress.
