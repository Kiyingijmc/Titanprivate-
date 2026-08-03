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

| OTE canonical (n=1,776) | |
|---|---|
| gross (managed) | **−0.046R** |
| mean cost | 0.113R |
| net (managed) | **−0.158R** — reproduces `2026-07-11-ote-canonical-results.md` exactly |

**Cost drag is 71% of the loss.** The geometry check closes on itself independently: win 27.1%
against 28.57% breakeven at RR 2.5 is a 1.47pp deficit; at 3.5 R-units per win that predicts
0.051R of gross deficit, against a measured gross-fixed of −0.052R. Agreement to the third
decimal.

**Unicorn** is the sharpest case: 28.5% realized against 28.57% breakeven (`RR_UNICORN = 2.5`,
`scripts/poc_ict_revival.py:43`) — a **0.07pp** deficit, ≈0.002R of gross. A zero-information
detector to two decimal places.

**Consequence:** neither OTE nor Unicorn is invertible. Flipping OTE's −0.046R gross yields
+0.046R against 0.113R of costs. Dead in both directions.

### Correction — CRT cannot be screened this way

The proposal instantiated CRT as "breakeven 25% at 3R vs 25.3% realized". **Canonical CRT has
no 3R target.** It targets the opposite range extreme — variable RR, floored at
`CRT_MIN_RR = 1.0` (`poc_ict_revival.py:44,349,421`). The fixed 3R belongs to the *deviant*
CRT deleted 2026-07-12, so that check imports a retired implementation's geometry onto the
canonical model's win rate.

It errs in CRT's favour: `2026-08-01-ict-revival-gate-results.md:29` states the variable RR
"averages far below what that win rate needs", i.e. breakeven is **above** 25.3%. CRT is
genuinely below its geometric breakeven, not sitting on it — so of the three it is the
candidate most likely to carry real negative gross. Screening it requires the per-trade
realized RR, not a nominal target.

### Reproducibility gap (open)

`unicorn_canonical_trades.csv` and `crt_canonical_trades.csv` **no longer exist**. The revival
worktree was removed and `data/history/` is gitignored, so
`2026-08-01-ict-revival-gate-results.md` cites raw artifacts that are gone. Only OTE's
survived. Verifying Unicorn/CRT gross requires re-running `scripts/poc_ict_revival.py`.
Future gate runs should copy their trade tables to `data/results/<study>/` — which is equally
gitignored but is at least the convention EXP-0/EXP-1 follow, and survives worktree removal.

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

**Caveat on the OTE figure — it is understated.** OTE's holding period has median 62 M5 bars
but p90 = 331, so a 144-bar horizon covers only **72.5%** of its trades; winners needing
longer never register. A horizon sweep is queued to replace this row with a
truncation-free number. The direction of the bias is known (OTE's true reach is higher than
22.4%), so the FAIL margin is an upper bound on OTE's deficit, not a lower one.

**Derived quantity worth keeping: `reach% − win%` = stop-out drag** — trades that reached the
target in favourable excursion but did not capture it, because the stop fired first. For
SilverBullet the 12-bar horizon gives 46.0% reach against a 35.9% realized win rate, ≈10pp of
drag. This is the one number in the screen that a backtest does not already report.

### The two diagnostics are not independent

For a **fixed-RR target over an adequate horizon**, "share reaching RR" *is* the win rate, so
`P(MFE ≥ RR) ≥ 1/(1+RR)` is algebraically the Diagnostic-1 breakeven test. Diagnostic 2
collapses into Diagnostic 1. The data shows it directly: OTE's fixed-exit win rate is 27.0% at
RR 2.5 against 28.6% breakeven — the same ~1.6pp deficit Diagnostic 1 reports from a different
direction.

This does not retire the screen; it relocates its value. Diagnostic 2 carries **independent**
information in exactly three cases:

1. **A time cap binds** — the horizon is shorter than the natural holding period, so reach and
   win rate diverge (this is the time-stop question, and the sweep measures it).
2. **The target is variable** — CRT, where there is no single RR to test breakeven against.
3. **The candidate has no trade logic yet** — no entry, no exit, therefore no win rate exists
   to compute. This is the original framing ("no entry logic, no exits, one pass") and the
   case where the screen genuinely earns its keep: it is the only one of the two that can be
   run *before* a model is built.

Practical consequence: on an already-gated model, run Diagnostic 1 — it is arithmetic on an
existing trade table and costs nothing. Reserve Diagnostic 2 for pre-design screening of
candidates, for variable-target models, and for measuring stop-out drag.

---

## How the two diagnostics combine

They can disagree, and the disagreement is informative:

| Diagnostic 1 | Diagnostic 2 | Reading |
|---|---|---|
| gross ≈ 0 | reach fails | **Harvest, don't remodel.** No information and no room. |
| gross ≈ 0 | reach passes | Information problem: the move exists, the detector doesn't find it. |
| gross < 0 meaningfully | reach fails | **Geometry remodel** — variable target at an MFE quantile, or a time stop at the MFE horizon. |
| gross < 0 meaningfully | reach passes | Legitimate remodel; convert trigger to state. |

**Time-based exits keep appearing on the winning side.** Gyroscope v2b uses time-stop exits
(`2026-08-01-gyroscope2b-gate-results.md:25,48`); Mesfin (2026, arXiv:2605.04004) reports both
positive controls exiting at a fixed bar count with 12–15 bar holds. That is cheap to test on
existing trade tables and is the natural response to a reach failure.

**Practical note on data.** `data/lake/frozen/` is **H1-only, 9 symbols, 5.8MB** — no M5, and
missing GBPCAD/XBRUSD. LTF reach screens must run off `data/history/*_M5.csv`.

## Standing consequence for EXP-1

Diagnostic 1 constrains how far `2026-08-03-exp1-mss-ablation-preregistration.md` can be read.
EXP-1 measured M5 MSS confirmation costing ≈0.47–0.67R on a *working* entry. OTE and Unicorn
do not have 0.5R of damage to explain — their gross deficits are 0.046R and ~0.002R. So MSS
confirmation **cannot be the mechanism** behind those two NO-GOs; the arithmetic has no room
for it. EXP-1 already declined to claim causation; this makes the refusal quantitative rather
than cautionary. CRT remains open, being the one of the three plausibly carrying real negative
gross.
