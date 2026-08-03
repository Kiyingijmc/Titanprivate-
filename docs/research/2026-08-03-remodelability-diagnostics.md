# Remodelability diagnostics — is a dead model worth redesigning?

**Date:** 2026-08-03 · **Status:** methodology + first calibration run · **Scope:** the two
screens that decide whether a NO-GO'd model is worth a remodel at all, applied to the
retired ICT family.
**Origin:** external proposal (2026-08-03), audited and corrected against this tree.
**Rigs:** Diagnostic 1 is arithmetic on existing trade tables; Diagnostic 2 is
`scripts/reach_screen.py`.

Most remodel effort in this repo's history has gone into redesigning *entries* for detectors
that had no information to begin with. These two screens run before any redesign and are
cheap enough to be mandatory.

---

## Diagnostic 1 — breakeven geometry

**The screen.** At a fixed RR target, breakeven win rate is `1/(1+RR)`. Compare realized win
rate against it. A model sitting *at* its geometric breakeven is not a broken edge; it is a
**zero-information detector**, and its net loss is mostly cost drag.

**Why it matters.** It decides invertibility. If net loss ≈ cost drag then gross ≈ 0, and the
inverse of a zero-gross stream is a zero-gross stream that still pays costs. Only a
significantly negative *gross* edge is invertible.

### Result — confirmed, and exact

Computed from `data/history/ote_canonical_trades.csv` (the surviving raw table), cost-screened
to the 10 symbols the gate included:

| OTE canonical (n=1,776) | managed exits | fixed exits |
|---|---|---|
| gross | −0.046R | **−0.056R** |
| mean cost | 0.113R | 0.113R |
| net | **−0.158R** — reproduces `2026-07-11-ote-canonical-results.md` exactly | −0.169R |
| cost share of loss | 71% | 67% |

The **fixed** column is the one the breakeven test uses (see the exit-model warning below);
the managed column is quoted because it is what the gate doc reports.

**The geometry check closes on itself independently.** Fixed-exit win 27.0% against 28.6%
breakeven at RR 2.5 is a 1.6pp deficit; at 3.5 R-units per win that predicts 0.056R of gross
deficit, against a measured fixed gross of −0.056R. Agreement to the third decimal — the
arithmetic of Diagnostic 1 is exact, and this is the cleanest demonstration of it in the set.

**Unicorn** initially looked like the sharpest case — 28.5% against 28.57% breakeven — but
that used the published *managed* win rate against a *fixed*-exit breakeven. Measured
correctly it is the family's outlier, not its purest member: see the exit-model warning and
the corrected table below.

**Consequence for OTE:** not invertible. Flipping its −0.056R gross yields +0.056R against
0.113R of costs. Dead in both directions.

### CRT needs the variable-target treatment — and it is the purest case of the three

The proposal instantiated CRT as "breakeven 25% at 3R vs 25.3% realized". **Canonical CRT has
no 3R target.** It targets the opposite range extreme — variable RR, floored at
`CRT_MIN_RR = 1.0` (`poc_ict_revival.py:44,349,421`). The fixed 3R belongs to the *deviant*
CRT deleted 2026-07-12, so that check imports a retired implementation's geometry onto the
canonical model's win rate. Screening CRT requires the **per-trade realized RR**.

**Measured** (regenerated table, `data/results/reach_screen/crt_canonical_trades.csv`, n=1,882
after the XBRUSD cost screen — matching the gate record exactly):

Realized RR is wide and right-skewed — p25 2.23, **median 3.54**, p75 5.44, p90 7.95 — so no
nominal figure represents it. Mean RR **on winners** is 3.12, giving breakeven
1/(1+3.12) = **24.3%** against a realized fixed-exit win rate of **24.1%**: a **0.2pp**
deficit.

| CRT (n=1,882) | |
|---|---|
| gross (fixed) | **−0.006R** |
| mean cost | 0.106R |
| net | −0.112R |
| **cost share of the loss** | **94%** |

**Both prior readings of CRT were wrong, in opposite directions.** The proposal put it below
breakeven via the 3R substitution. An earlier revision of this document inferred from
`2026-08-01-ict-revival-gate-results.md:29` ("variable RR that averages far below what that
win rate needs") that breakeven must be *above* 25.3%, and concluded CRT was the member of the
family most likely to carry real negative gross. Measured breakeven is 24.3% — *below* the
realized win rate. That sentence in the gate doc describes a wide right-skewed RR
distribution, not a win-rate shortfall. **CRT carries the least negative gross of the three,
not the most.**

### ⚠️ The published win rates are MANAGED-exit — the breakeven test needs FIXED

The breakeven identity `1/(1+RR)` assumes **every win pays exactly RR**. That is only true
under a fixed-R exit. The managed (ratchet/runner) model banks partials, changing both the win
rate *and* the payoff per win, so a managed win rate compared against `1/(1+RR)` is a category
error. The gate docs report managed figures:

| model | managed win (published) | **fixed win (correct input)** |
|---|---|---|
| ICT_OTE | 29.9% | **27.0%** |
| Unicorn | 28.5% | **25.4%** |

Both earlier readings of this family tripped on it. The proposal screened CRT with a nominal
3R against a managed 25.3%; an earlier revision of this document screened Unicorn with the
published managed 28.5% against a fixed-exit breakeven of 28.57% and concluded a 0.07pp
deficit ≈ 0.002R of gross. **Measured on the fixed-exit basis, Unicorn's gross is −0.109R —
fifty times larger, and the largest of the three.** Always take the win rate from the same
exit model the RR refers to.

### Diagnostic 1, complete family (fixed-exit basis throughout)

Regenerated tables, cost-screened, n matching each gate record exactly:

| model | n | breakeven | fixed win | deficit | **gross** | cost | net | cost share of loss |
|---|---|---|---|---|---|---|---|---|
| **CRT** | 1,882 | 24.3% (variable) | 24.1% | −0.2pp | **−0.006R** | 0.106R | −0.112R | **94%** |
| ICT_OTE | 1,776 | 28.6% (RR 2.5) | 27.0% | −1.6pp | **−0.056R** | 0.113R | −0.169R | 67% |
| **Unicorn** | 562 | 28.6% (RR 2.5) | 25.4% | −3.1pp | **−0.109R** | 0.125R | −0.234R | **53%** |

They are **not** a homogeneous set, which is what the corrected numbers change:

- **CRT is the pure case.** Gross −0.006R is indistinguishable from a coin flip at its own
  geometry; 94% of its loss is transaction costs. It is not a bad detector, it is *not a
  detector*. → **harvest**.
- **OTE is close to it** — small negative information, two-thirds cost drag. → **harvest**.
- **Unicorn is different.** −0.109R of gross with only 53% cost drag is a real negative edge,
  not a zero. It is the one member of the family that carries genuine anti-information.

**On invertibility — the naive arithmetic does not apply.** "Flip a −0.109R gross stream to
get +0.109R" is wrong for a stop-and-target model, because inverting swaps the stop and the
target: RR 2.5 becomes RR 0.4, the win rate becomes its complement, *and* cost-in-R falls by
2.5× because the risk distance is now the old target distance. Whether Unicorn inverts to
anything viable is an empirical question requiring its own pre-registered run, not a sign
flip. Recorded as the one open remodel question in the family; the standing prior remains
poor, and the one-pass rule means it needs a fresh mechanically-motivated design.

### Reproducibility gap — closed for Unicorn and CRT

`unicorn_canonical_trades.csv` and `crt_canonical_trades.csv` had been lost: the revival
worktree was removed and `data/history/` is gitignored, so
`2026-08-01-ict-revival-gate-results.md` cited raw artifacts that no longer existed. Only
OTE's survived.

Both have been regenerated from `scripts/poc_ict_revival.py` (one pass, frozen rule sets, no
tuning — this recovers artifacts, it does **not** re-gate; the NO-GO verdicts stand) and
written to **`data/results/reach_screen/`** rather than `data/history/`. Fidelity was
confirmed before use: CRT reproduces n=1,882 post-screen and the per-symbol cost table
exactly.

**Convention for future gate runs:** write trade tables to `data/results/<study>/`. It is
equally gitignored, but it is the location EXP-0/EXP-1 already use and it survives worktree
removal — which is what destroyed these two.

---

## Diagnostic 2 — the reach screen

**The screen.** For each candidate, measure the distribution of maximum favourable excursion
(MFE) from the signal and compare against what the trade structure needs. No entry logic, no
exits, one pass. It catches the failure mode where the pattern is real but the move is too
small to pay for the structure — the SpookyQuant Silver Bullet case (raid-failure snapback
real at 69–77%, but structure needed 128–160 ticks against a ~50-tick move).

### Two corrections before it can be used

**1. The comparator was `stop_distance × (1 + RR) + cost`.** That is the *stop-to-target*
span. MFE measured from the entry needs to reach **RR**, not 1+RR — the extra unit is the
distance below entry to the stop, which the favourable excursion never has to cover. Using
1+RR against entry-anchored MFE overstates the requirement by exactly 1R.

**2. The median is the wrong statistic, and it rejects the strategy that works.** Requiring
median MFE ≥ RR requires a >50% hit rate, which no positive-expectancy asymmetric system has.
Calibration run (exit-bounded MFE, cost 0.11R):

| | median MFE | required | median test | share reaching | breakeven win |
|---|---|---|---|---|---|
| OTE (dead, −0.158R) | 0.89R | 2.61R | FAIL | 13.4% | 28.6% |
| SilverBullet (live, **+0.109R**) | 1.73R | 2.11R | **FAIL** | 35.0% | 33.3% |

The median test fails the live, profitable strategy — fatal as specified. SilverBullet is
profitable *because* 35% of trades reach 2R, not because the typical one does.

**The correct screen is exceedance against breakeven:** `P(MFE ≥ RR + cost) ≥ 1/(1+RR)`. On
that statistic OTE fails by 15pp (13.4% vs 28.6%) and SilverBullet passes by 1.7pp (35.0% vs
33.3%) — a thin margin exactly consistent with its +0.109R. Same data, same single pass,
correct threshold.

### A third correction, to this rig

The calibration above bounded MFE at each trade's exit index. That imports the stop and
target, so the measure collapses into approximately the win rate — SilverBullet's 35.0%
"share reaching" sits within noise of its 35.9% realized win rate. It was a slow way to
recompute what a backtest already reports, and it is **not a pre-backtest screen**.

The true screen measures MFE over a **fixed bar horizon** from entry with no stop and no
target — exit logic never consulted. Results below use horizon = 12 bars (the TTL both models
use; 144 M5 bars for OTE's M5-indexed fills, for equal wall-clock).

### Result — horizon-based screen

Horizon = 12 bars (144 M5 bars for OTE's M5-indexed fills, for equal wall-clock):

| | median MFE | reach % (≥ RR+cost) | breakeven | verdict |
|---|---|---|---|---|
| OTE (dead, −0.158R) | 1.17R | **22.4%** | 28.6% | FAIL by 6.2pp |
| SilverBullet (live, +0.109R) | 1.99R | **46.0%** | 33.3% | **PASS by 12.7pp** |

The exceedance test discriminates correctly, and separates slightly better than the
exit-bounded version (18.9pp vs 16.9pp). The median test still fails both models
(0.45 and 0.94 of required) — the median is the wrong statistic regardless of how MFE is
bounded.

**⚠️ The table above does not survive the horizon sweep. See the correction below — the
apparent discrimination is an artifact of the horizon choice, and the row should not be
cited.**

**Derived quantity worth keeping: `reach% − win%` = stop-out drag** — trades that reached the
target in favourable excursion but did not capture it, because the stop fired first. For
SilverBullet the 12-bar horizon gives 46.0% reach against a 35.9% realized win rate, ≈10pp of
drag. This is the one number in the screen that a backtest does not already report.

### CORRECTION (same day, horizon sweep) — the screen does not discriminate

An earlier revision of this document claimed that (a) reach collapses into the win rate for a
fixed-RR target, and (b) the 12-bar screen separated OTE from SilverBullet. **The horizon
sweep (`scripts/reach_sweep.py`) refutes both.** Both claims were merged to main in `5ac5a20`
and are corrected here rather than deleted.

| horizon | OTE reach (BE 28.6%) | | horizon | SilverBullet reach (BE 33.3%) |
|---|---|---|---|---|
| 144 M5 (covers 72.5% of trades) | 22.4% **FAIL** | | 12 H1 | 46.0% PASS |
| 288 M5 (87.4%) | 35.9% **PASS** | | 24 H1 | 60.2% PASS |
| 576 M5 (95.7%) | 49.7% **PASS** | | 48 H1 | 70.5% PASS |
| unbounded | **94.0%** PASS | | unbounded | **97.4%** PASS |

**OTE's verdict flips from FAIL to PASS between 144 and 288 bars.** The apparent
discrimination in the previous revision was an artifact: 144 M5 bars truncated 27.5% of OTE's
trades while 12 H1 bars truncated far less of SilverBullet's. Equal nominal wall-clock was not
equal effective coverage.

**Why (a) was wrong.** Reach measured without a stop is *not* the win rate, because a win
requires reaching the target **before** the stop fires. MFE-without-stop ignores path
entirely. The gap is enormous, not marginal: unbounded reach 94.0% against a 27.0% realized
win rate for OTE (**+67.0pp**), and 97.4% against 36.1% for SilverBullet (**+61.3pp**). Far
from collapsing into Diagnostic 1, the two measure different things — and the "stop-out drag"
quantity defined above is the whole difference, which makes it the dominant term, not a
footnote.

**Why unbounded reach is vacuous.** Median unbounded MFE is 34.1R (OTE) and 47.9R
(SilverBullet). Over unlimited time and with no stop, price wanders arbitrarily far in both
directions; the screen degenerates into "does this instrument move at all", and everything
passes. Any reach number is therefore a statement about its horizon, never about the model
alone.

### What the screen is actually for

The screen has a domain, and OTE/Unicorn/CRT are outside it. All three are **stop-and-target
models with no time limit** — the trade runs until SL or TP, so the "intended horizon" is
unbounded and the binding constraint is *stop survival*, i.e. path, which reach cannot see.
For that family, Diagnostic 1 is the correct tool and Diagnostic 2 adds nothing trustworthy.

Diagnostic 2's domain is **time-bounded exits**, where a real horizon exists and can be
plugged in non-arbitrarily. That is exactly the family it was drawn from — SpookyQuant's
intraday model, Mesfin's two positive controls (fixed bar-count exits, 12–15 bar holds), and
Gyroscope v2b's time stop. It is also usable, with the same caveat, on a candidate that has no
trade logic yet, provided the horizon is set by the intended holding period rather than
convenience.

**Rules of use, revised:**

1. Never quote a reach number without its horizon, and never use an unbounded one.
2. Set the horizon from the intended holding period. If the model has no time limit, the reach
   screen does not apply — use Diagnostic 1.
3. Match effective *coverage*, not nominal wall-clock, when comparing two models.
4. Reach is at best **necessary, never sufficient**: failing at the intended horizon kills a
   structure, but passing says nothing about whether the stop lets you collect.

---

## How the two diagnostics combine

**Only when Diagnostic 2 is in its domain** (a time-bounded exit, horizon set by the intended
holding period). For a stop-and-target model with no time limit, read Diagnostic 1 alone — the
reach column below is not computable in a way that means anything.

| Diagnostic 1 | Diagnostic 2 @ intended horizon | Reading |
|---|---|---|
| gross ≈ 0 | reach fails | **Harvest, don't remodel.** No information and no room. |
| gross ≈ 0 | reach passes | Information problem: the move exists, the detector doesn't find it. |
| gross < 0 meaningfully | reach fails | **Geometry remodel** — variable target at an MFE quantile, or a time stop at the MFE horizon. |
| gross < 0 meaningfully | reach passes | Candidate remodel — but confirm stop survival first; reach is blind to path. |

For the three retired ICT models specifically, this table does **not** apply: all are
stop-and-target with no time limit, so the decision rests on Diagnostic 1 — which splits
them: **CRT and OTE** land in the top row, **harvest** (gross −0.006R / −0.056R, 94% / 67%
cost drag, nothing to invert). **Unicorn** lands in the third row, real negative gross
(−0.109R, 53% cost drag) — the only remodel question the family leaves open.

**Time-based exits keep appearing on the winning side.** Gyroscope v2b uses time-stop exits
(`2026-08-01-gyroscope2b-gate-results.md:25,48`); Mesfin (2026, arXiv:2605.04004) reports both
positive controls exiting at a fixed bar count with 12–15 bar holds. That is cheap to test on
existing trade tables and is the natural response to a reach failure.

**Practical note on data.** `data/lake/frozen/` is **H1-only, 9 symbols, 5.8MB** — no M5, and
missing GBPCAD/XBRUSD. LTF reach screens must run off `data/history/*_M5.csv`.

## Standing consequence for EXP-1

Diagnostic 1 constrains how far `2026-08-03-exp1-mss-ablation-preregistration.md` can be read.
EXP-1 measured M5 MSS confirmation costing ≈0.47–0.67R on a *working* entry. The three models'
gross deficits are **−0.006R (CRT), −0.056R (OTE), −0.109R (Unicorn)** — between 4× and 100×
too small for a 0.5R mechanism to be what sank them.

So MSS confirmation **cannot be the mechanism** behind any of the three NO-GOs; the arithmetic
leaves no room. EXP-1's finding is real about SilverBullet and says nothing causal about the
retired family.

This is worth stating plainly because it cuts against the hypothesis EXP-1 was built to test.
The component-isolation result stands on its own — confirmation costs ~0.5R on an entry that
works — but the shared-component story that motivated it ("one component falsified three
times") is **not** supported. Two of the three (CRT, OTE) failed by never having had an edge
to lose. Unicorn is the only one with real anti-information, and at −0.109R it is still 4×
short of the effect EXP-1 measured — and it is also the model whose zone primitive
(breaker∩FVG overlap, 96% of legs filtered) differs most from the others, which points at zone
definition rather than a shared trigger.
