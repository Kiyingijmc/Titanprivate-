# RETIRED / FALSIFIED — the ICT family graveyard

> **Status:** falsification record (retired/removed strategies) · **Scope:** SilverBullet-M5-original,
> ICT_OTE canonical, Unicorn, CRT, MTF-PB v1/v2, Donchian-20 D1 · **Doc version:** 2026-08-01

This document is the falsification record for every strategy variant tested and killed (or removed
unvalidated) on this repo's rig, plus the two ICT trend-pullback cycles and the one non-ICT trend
test that preceded the current arsenal work. It exists so the next candidate does not re-litigate
ground already covered. `src/strategies/models/silver_bullet.py` is the sole survivor and is
documented separately in `docs/strategies/silver-bullet.md` — it is not "retired," it is the
incumbent, rescued by a different exit model than the one tested here.

**EXP-0 implication (2026-07-31):** none of the strategies below were tested against the coin-flip
control, because EXP-0 postdates all of them. But EXP-0's finding — the ratchet/runner exit engine
amplifies a real entry edge (+0.231R) and does not manufacture one from noise (+0.075R on random
entries) — retroactively explains why "the management engine has nothing to rescue" (§2 below) is
not a coincidence: an entry with no gross edge gets none of the amplification, because there is
nothing to amplify.

---

## 1. SilverBullet-M5-original — the sub-pip stop that started the cost discipline

**What it was:** the inherited live configuration — session-timed FVG-displacement continuation
entry (unchanged from today's SilverBullet), but with a fixed **0.2×ATR** stop buffer past the FVG
edge on **M5**, i.e. risk ≈ 1 pip on a typical EURUSD bar.

**Why it died — with numbers:** `docs/research/2026-07-11-silverbullet-h1-stop-study.md` §1: at the
live 0.2×ATR/M5 config, **net expectancy = −4.271R/trade**, despite a real gross edge (+0.067R
gross on the same config — the signal concept is not the problem). The audit's worked cost table
(`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:37`) makes the arithmetic explicit: a 0.2×ATR(M5)
stop on EURUSD is ~0.5 pips, against a round-trip cost of ~1.5 pips (8-tick spread + $7/lot
commission) — **cost ≈ 3.0R at that stop.** The strategy was not marginally unprofitable; it paid
roughly three units of risk in transaction costs for every unit of risk it staked, before the
market had any chance to move in its favour.

**What the graveyard teaches the next candidate:** this is the origin of the repo's hardest
constraint — the cost gate (`docs/strategies/ARSENAL.md` §"How to read this board" item 1; median
round-trip cost ≤ 0.25R). On M15 and below, stops must be structural/wide (a range width, a swing
extreme), never a small ATR multiple; M5/M15 ATR-multiple stops are dead by construction on this
broker at any reasonable multiple (the same 2026-07-11 study found ATR05/M5 at +0.415R gross but
**−1.318R net** — even a 2.5× wider stop than the live config still failed by more than a full R).
The fix that actually worked was not tightening the pattern; it was moving to H1 with an
ATR-anchored stop wide enough to keep cost under the 0.25R gate (see `docs/strategies/silver-bullet.md`).

---

## 2. ICT_OTE canonical — the canonical-rewrite cycle's first and decisive test

**What it was:** a from-scratch rebuild of ICT's Optimal Trade Entry model per the canonical
definition verified in `docs/research/2026-05-29-ict-edge-research.md` (fib zone 0.62–0.79,
0.705 centre, entry confirmed by an LTF market-structure-shift, never a bare limit at the level) —
H4/H1 bias → H1 leg → M5 MSS confirmation, reusing SilverBullet's exact H1 stop-scale and the same
ratchet/runner management engine.

**Why it died — with numbers:** `docs/research/2026-07-11-ote-canonical-results.md`. **NO-GO
everywhere** — all six asset classes (FX-majors, FX-crosses, metals, index, crypto, energy) failed
the pre-registered gate on leg 1 alone (test-set expectancy positive under both exit models).
Pooled net-of-cost expectancy across all cost-screen-included symbols: **−0.158R** (MANAGED, net
1×, n=1,776, PF 0.73), negative in every year 2023–2026 with no improving trend. Per-symbol,
**10 of 11 instruments showed negative expectancy under both the FIXED and the MANAGED exit
model**, from which the study concludes the underlying signal carries no positive raw edge — the
underlying H4+H1 bias → H1 leg → 0.62–0.79 zone → M5 MSS signal did not carry a positive raw edge
the way SilverBullet's FVG-displacement signal did, so, in the study's own words, **"the management
engine has nothing to rescue."** The rebuild was hand-verified end-to-end on two golden trades
against raw M5 data (zone math, MSS detection, stop placement all matched exactly) — this was not
an implementation bug; the canonical rules, correctly implemented, do not clear costs here.

**What the graveyard teaches the next candidate:** confirmation isn't the fix retail ICT education
implies it is. The 2026-05-29 evidence review already flagged that "entering confirmed by
LTF MSS" is an *unproven* discipline, not an independently validated one — this study measured it
directly and it did not rescue the signal. It also demonstrates that a validated exit engine
(the same one that turns SilverBullet's entry into +0.109R) is not a general-purpose profitability
patch; it inherits whatever the entry's raw edge is, and OTE's is negative under both exit models
on 10/11 symbols. This closed the first of the three-strategy canonical-rewrite sequence
(OTE → Unicorn → CRT, `docs/research/2026-07-11-ote-canonical-results.md` "What happens next").

---

## 3. Unicorn — removed unvalidated, the canonical-rewrite sequence terminated early

**What it was:** ICT's Breaker+FVG overlap model with a structural-shift confirmation requirement
(canonical definition: mandatory retest of the zone, never chase —
`docs/research/2026-05-29-ict-edge-research.md`). The as-implemented pre-rewrite version deviated
materially from canon: FVG+breaker overlap with a crude sweep detector and a **passive LIMIT at a
historical breaker level**, with no structural-shift confirmation — exactly the "bare level, no
confirmation" antipattern the evidence review flagged as the top mistake across all four ICT
models.

**Why it died — with numbers:** the original, pre-canonical-rewrite implementation was
net-negative after costs alongside the other three original ICT strategies
(`docs/RESUME.md:9`: "All four ICT strategies (Unicorn, CRT, OTE, SilverBullet) are net-negative
after costs. Deep research found ICT/SMC has no independent evidence of edge."). Unlike OTE (which
got a full canonical rewrite and its own decisive pre-registered NO-GO), Unicorn never received
that treatment: the three-strategy canonical-rewrite sequence (OTE → Unicorn → CRT) was terminated
after OTE's NO-GO, on the reasoning that a third consecutive canonical-rewrite cycle against the
same evidence base and the same rig was unlikely to reverse the pattern. Unicorn was deleted
unvalidated in its canonical form on 2026-07-12 (commit `b4450f8`, "remove unapproved strategies
(Unicorn, ICT_OTE, CRT); SilverBullet-only arsenal" —
`docs/superpowers/plans/2026-07-12-plan-01-sanitization.md`).

**2026-08-01 UPDATE — canonical form now falsified.** The pre-registered gate this section
called for was run (`docs/research/2026-08-01-ict-revival-gate-results.md`): canonical
Unicorn (H4+H1 bias → H1 leg → breaker∩FVG zone → retest + M5 MSS, hand-verified rig) is
**NO-GO everywhere** — pooled −0.209R managed (n=562, PF 0.66), negative every year
2023–26, 0/5 classes pass, under both exit models. Status upgraded from "unvalidated" to
**canonically falsified**.

---

## 4. CRT (Candle Range Theory) — removed unvalidated, never the canonical model

**What it was:** ICT's CRT model, canonically an HTF-range (D/H4/H1) → LTF (M5/M15) liquidity-raid
model: grab the prior high/low, close back inside, confirm an LTF market-structure shift, enter on
a retest into the FVG/order block, target the opposite range extreme
(`docs/research/2026-05-29-ict-edge-research.md`). The as-implemented version was, in the evidence
review's own words, "the biggest deviation" of the four: a **simplified M5 PDH/PDL sweep** with
single-candle rejection, entering at the close of the rejection candle (long side implemented as a
limit-at-close), fixed 3R target — **no HTF range structure, no MSS, no retest, and the target was
not the opposite range extreme.**

**Why it died — with numbers:** same original-implementation falsification as Unicorn —
`docs/RESUME.md:9` covers all four original ICT strategies including CRT as net-negative after
costs. CRT also never received a canonical rewrite; it was removed unvalidated on 2026-07-12
(commit `b4450f8`), in the same sanitization pass and for the same reasoning as Unicorn: the
canonical-rewrite sequence was terminated after OTE's decisive NO-GO before reaching CRT.

**2026-08-01 UPDATE — canonical form now falsified.** The canonical HTF-range → raid →
close-back-inside → retest → M5 MSS → opposite-extreme model was built from scratch and
gated exactly as OTE was (`docs/research/2026-08-01-ict-revival-gate-results.md`):
**NO-GO everywhere** — pooled −0.150R managed (n=1,882, PF 0.77), negative every year,
0/5 classes, both exit models. With OTE (07-11) and Unicorn (08-01), all three retired
ICT models are now falsified in canonical, confirmation-disciplined form on this broker.

---

## 5. MTF-PB v1/v2 — the trend-pullback thesis, tested twice, and the small-sample-optimism signature

**What it was:** a multi-timeframe trend-pullback system — H4/H1 bias, M15 trend confirmation, M5
ICT-OTE-style pullback entry, executed on a 1-2 minute chart — designed against the same evidence
review (`docs/research/2026-05-29-ict-edge-research.md`, `docs/research/RESEARCH_QUESTION_mtf.md`).
Not part of the four "original ICT strategies" line but tested twice as a distinct research cycle.

**Why it died — with numbers:** `docs/research/2026-06-25-mtf-pb-v2-results.md`. On a 3-month
interim sample, metals/index/crypto looked promising (managed exp +0.192R / +0.158R / +0.096R). On
the full 3-year sample (~2.45M M5 bars, obtained once the HTTP bridge revealed FBS retains ~3 years
of history, not the ~3-month EA/ZMQ export cap previously assumed), **every one of those positives
collapsed 3–8× toward zero**: metals +0.024R (÷8), index +0.041R (÷4), crypto +0.030R (÷3) — the
textbook small-sample-optimism signature. **Pooled net expectancy across all classes: −0.274R**
(n=11,533 MANAGED / n=8,536 FIXED). No class cleared the dual-exit-model gate; each apparent
"winner" passed exactly one of the two exit models and failed the other. FX majors and crosses were
strongly negative under both models (−0.36 to −0.59R) throughout. This was the thesis's **second**
research cycle: the v1 screening PoC (`docs/research/2026-05-30-mtf-pb-poc-results.md`) was *not* a
NO-GO — its recorded verdict was **"inconclusive-but-promising; need more commodity history"**, with
only metals (XAUUSD) clearing the gate on a 3-month sample (n_test 35/37). v2 is what converted that
provisional positive into a decisive NO-GO once the full 3-year history was available.

**What the graveyard teaches the next candidate:** the collapse pattern is the single most
important methodological lesson in this repo's research history — **a 3-month "promising" result on
n≈100s of trades is not evidence; re-test at n≈1,000+ before believing any positive.** The dual-
exit-model gate (a positive result must hold under both FIXED and MANAGED, not just whichever one
happens to look good) exists specifically because this cycle showed model-dependence disguising a
non-result as a result. MTF-PB also independently confirmed the OTE finding above: trend-pullback
on FX majors is strongly and consistently negative net-of-cost on this broker across two unrelated
studies (MTF-PB and canonical OTE).

---

## 6. Donchian-20 D1 — the wrong-horizon lesson that motivates Anchor

**What it was:** a short trend-following system, 20-day Donchian channel breakout on D1, tested
across 8 instruments over ~5 years (`docs/RESUME.md:11`; referenced in
`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:234`).

**Why it died — with numbers:** net-negative, **−0.1 to −0.25R**, and explicitly **not** a
cost-driven failure — the study confirmed cost-robust structure (wide stops) held; the signal
itself was the problem. The audit's diagnosis: "too fast, weak."

**What the graveyard teaches the next candidate:** this is a wrong-horizon result, not a
wrong-thesis result, and the distinction matters. Twenty days is short-term reversal territory, not
the 3–12 month horizon the time-series-momentum literature documents (Moskowitz–Ooi–Pedersen 2012;
Hurst–Ooi–Pedersen); the audit's own words: "you tested the wrong horizon and correctly diagnosed
it" (`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:234`). This is precisely the reasoning behind
the `Anchor` candidate (63-bar H4 / 126-day D1 lookback with EMA(50) confirmation,
`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §7, and the `TC-2` long-horizon-TSMOM child in the
separate new-bot track, `docs/strategies/newbot-roster.md`) — **not** evidence that momentum works
at the right horizon, since that has never been tested on this data, but evidence that this
specific short-horizon variant does not, and that the failure mode was mechanically diagnosable
rather than a blanket indictment of trend-following. D1 sample size is also a live constraint here:
`data/lake/frozen/` gives only ~775 D1 bars/symbol over 3 years — not enough to validate a 6-month
signal; a data-extension project (MT5 D1 history runs 15–25 years via `GET_HISTORY`) is a
prerequisite before Anchor can be gated at all.

---

## Standing falsification-log principles

The discipline that produced every verdict above, and that binds every future candidate on this
rig:

1. **Pre-registration.** The gate criteria (thresholds, splits, cost model, sweep ranges) are
   committed to git *before* the first run. Every study cited in this document has a pre-
   registration doc predating its results doc (e.g. `2026-07-14-gyroscope-gate.md` committed at
   `30ee17e`/`342820f` before `2026-07-14-gyroscope-gate-results.md`).
2. **One-pass rule.** No in-place re-tuning on the same data after a verdict. A specific,
   mechanically-motivated change (a different leg-detection timeframe, a different stop model)
   requires its own mini-spec and a fresh pre-registered run — this document records final verdicts
   for the frozen rule sets tested, not open invitations to retune.
3. **Dual-exit-model gate.** A positive result must hold under both a FIXED-R exit model and the
   live-mirroring MANAGED (ratchet/runner) model. MTF-PB v2 is the canonical example of why: every
   apparent winner there passed exactly one model and failed the other.
4. **NO-GO is a valid, recordable outcome.** Five of the six lines above ended NO-GO or unvalidated-
   removal, and each is treated as a completed research cycle with durable lessons, not a failure to
   hide. The infrastructure built along the way (cost model, bootstrap CI, chronological OOS split,
   the rig itself) is a standing asset regardless of verdict.

**MaSlopeBaseline** (`ma_slope_baseline`, referenced in `docs/research/2026-07-14-gyroscope-gate.md`)
is a permanent **research-only control**, not a candidate: a zero/low-parameter moving-average-slope
yardstick every new momentum-family candidate should be run against on identical data, cost model
and exit model, so that a candidate's added complexity has to earn its keep against the simplest
possible baseline. It has never been proposed for live trading.
