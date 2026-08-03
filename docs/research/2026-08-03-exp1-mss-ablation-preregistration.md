# EXP-1 "MSS Ablation" — pre-registration

**Date:** 2026-08-03 · **Status:** PRE-REGISTERED (committed before any run; one pass;
every outcome below is a valid, recordable result)
**Provenance:** external critique (2026-08-03) proposing that M5 MSS confirmation is a
single falsified *component* shared by all three canonically-gated ICT failures, with
SilverBullet as the accidental control; plus the in-session audit of that critique against
this tree.
**Rig:** `scripts/exp1_mss_ablation.py` (to be written), built on `scripts/poc_sb_stops.py`
machinery (`collect_signals` → `stop_price` → `resolve` → `replay_managed` → `cost_r`) and
`src/analysis/ict_structure.py` (`precompute_last_swings`, `mss_confirm`). No change to
either module; the new script imports both.

---

## Hypothesis under test

Three canonically-implemented ICT models were gated NO-GO on this rig, all three sharing
one component — **zone → retest → M5 MSS → market entry**:

| Model | Pooled MANAGED net 1× | n | Verdict |
|---|---|---|---|
| ICT_OTE (2026-07-11) | −0.158R | 1,776 | NO-GO, 6/6 classes |
| Canonical Unicorn (2026-08-01) | −0.209R | 562 | NO-GO, 0/5 classes |
| Canonical CRT (2026-08-01) | −0.150R | 1,882 | NO-GO, 0/5 classes |

The one survivor, SilverBullet, does not use that component: it rests a LIMIT at the FVG
edge of a displacement candle with no post-retest confirmation step
(`src/strategies/models/silver_bullet.py`).

**H1 (directional):** M5 MSS confirmation on a retest *subtracts* net expectancy from an
entry stream that is otherwise positive, by (a) surrendering the first leg of the move —
worse realized RR against a fixed target — and (b) conditioning on "price already moved",
which at M5 resolution is largely noise autocorrelation.

**H0:** MSS confirmation is expectancy-neutral or positive on a working zone. The three
failures above were then driven by their *zone/entry primitive* (structural interpretation:
swing legs, breaker∩FVG overlap, prior-day range) rather than by their trigger.

### What this experiment does and does not establish

- **It measures** the incremental effect of the confirmation component on a baseline whose
  entry is known to carry a gross edge.
- **It does not prove** MSS caused the three NO-GOs. Those are separate claims about
  separate rule sets. A confirmed H1 raises the posterior; it is not a retro-verdict.
- **It is not a portfolio simulation.** See "Occupancy" below — the treated arm is a
  per-trade counterfactual, not a tradeable variant. A GO-shaped result requires its own
  portfolio-level gate with a fresh pre-registration.

---

## Priors, stated honestly

- **The component-level claim already exists in this repo's prose.**
  `docs/research/2026-08-01-ict-revival-gate-results.md:39-43` records that
  "MSS-confirmed retest entries did not produce a positive raw edge in any of the three
  models," and names SilverBullet as the survivor in the following sentence. What has
  never been done is treating SilverBullet as a **control** and measuring the component
  directly. That gap is what EXP-1 closes.
- **SilverBullet is not a "widen the stop and it works" baseline, and this correction is
  load-bearing.** `2026-07-11-silverbullet-h1-stop-study.md:48-52`: at H1/ATR10 the fixed-2R
  exit is **−0.122R**. Positivity arrives only with the ratchet (+0.087R) and
  ratchet+runner (+0.109R). The control arm is therefore *negative under one of the two
  registered exit models*, which is why the gate below reads Δ (the paired difference) and
  never the level.
- **Costs were not the failure mode for the three models.** OTE median round-trip cost per
  symbol ran 0.026R–0.187R with only XBRUSD screened out and risk floored at 0.500×ATR(H1)
  by construction; the Unicorn results doc states it outright ("costs are NOT the failure
  mode here — the signal is"). EXP-1 therefore tests signal geometry, not friction.
- **EXP-0 bounds what the exit engine can do here.** Random entries through the full engine
  are −0.249R over 20/20 reps; the engine amplifies (+0.231R on real entries) rather than
  subsidises (+0.075R on random). A Δ measured through the same replay in both arms is a
  component measurement, not an exit-engine artifact.
- **A null is the modal outcome and is fully acceptable.** The correspondent's own causal
  claim was assessed at 30–40% confidence by the models that reviewed it, on n=3
  under-identified observations. Outcome B below closes the question just as usefully as
  Outcome A.

---

## Control arm (A) — frozen, unchanged

The adopted v14.4.2 configuration, reproduced by the existing rig with no modification:

- SilverBullet signal: displacement candle, `body ≥ 0.8 × ATR`, FVG present; entry = the
  near FVG edge (`fvg_top` for BUY, `fvg_bottom` for SELL).
- Timeframe **H1**, stop model **ATR10** (`entry ± 1.0 × ATR(H1)`), **RR 2.0**,
  **TTL 12** H1 bars, one open trade per symbol.
- Fill: the LIMIT fills when an H1 bar's range touches `entry` on bars `i+1 … i+12`.
- Costs: indicative FBS spread table + $7/lot commission, `cost_R = (spread + comm)/risk`,
  at 1× (primary) and 1.5× (stress).

**Rig fidelity check, registered as a pass/fail precondition:** arm A must reproduce
n=2,217, FIXED −0.122R, RATCHET +0.087R, RATCHET+RUNNER +0.109R to the third decimal on
the 11-symbol universe, exactly as EXP-0 did. If it does not, the run is void and no
verdict is issued.

---

## Treated arm (B) — the only thing that changes

For each arm-A trade, the counterfactual: **wait for an M5 MSS after the zone touch, then
enter MARKET at the next M5 open.**

1. **Touch bar.** Resolve arm A's H1 fill bar down to M5: the first M5 bar within the H1
   fill bar whose range contains `entry`.
2. **Confirmation window.** From the touch bar (inclusive) to the close of H1 bar `i+12`
   (arm A's TTL horizon), whichever is earlier. No MSS in window → **no arm-B trade for
   this pair** (handled below; it is an absent observation, not R=0).
3. **MSS.** `mss_confirm(m5_high, m5_low, m5_close, k, bias, last_swh, last_swl)` with
   `precompute_last_swings(..., LK_M5)` and **`LK_M5 = 2`** — the identical definition and
   lookback used by the OTE, Unicorn and CRT gates (`scripts/poc_ict_revival.py:47`).
   `bias` is the arm-A signal direction. Unchanged code, unchanged constant.
4. **Entry.** MARKET at the **next M5 bar's open** after the confirming bar — the same
   execution convention hand-verified in the OTE golden slice.
5. **Resolution.** Same H1 bar path, same pessimistic same-bar-SL-first rule, same
   `replay_managed` ratchet/runner, same cost function.

### The anchoring problem, and why two variants are registered

Adding a confirmation step **moves the entry price**, which moves risk distance, which
moves the R denominator, which moves realized RR against a fixed target. Entry mechanics
and target geometry cannot both be held fixed. Rather than pick one and call the design
"identical", both are registered and both are reported:

| Variant | Frozen | Floats | Rationale |
|---|---|---|---|
| **B1 — stop-anchored** | SL *price* = arm A's `stop_price(sig, "ATR10")` | entry, risk, TP (= entry ± 2.0 × risk_B) | Preserves the economically meaningful level (zone invalidation). Risk widens → cost/R **falls**, so B1 hands the treated arm a friction advantage. |
| **B2 — R-anchored** | risk distance = 1.0 × ATR(H1) from the *new* entry | SL price, TP price | Preserves cost/R and RR exactly; isolates timing from geometry. |

B1 and B2 bracket the design space. A component claim that survives only one of them is
not a component claim — see the gate.

### Occupancy — registered decision

Arm B **inherits arm A's signal selection verbatim**. The `busy_until` one-open-per-symbol
state machine is *not* re-run on arm B's later entries. This is deliberate: re-running it
would change which signals are taken, destroying the pairing and turning a component
measurement into a portfolio comparison with two moving parts. Registered consequence:
arm B is a per-trade counterfactual and its pooled expectancy is **not** a tradeable
result.

### Missing-observation handling — both readings registered

- **Primary — paired-on-both-traded.** Drop pairs where no MSS fires in the window. This
  answers the hypothesis as stated: *does the component subtract value from a trade?*
- **Secondary — intent-to-treat.** A no-MSS pair contributes R = 0, cost 0 to arm B (the
  variant would simply not have traded). Reported, not gated: a costless option to skip
  flatters arm B, so it cannot carry the verdict.

---

## Registered parameters

| Parameter | Value |
|---|---|
| Timeframe / stop model | H1 / ATR10 |
| Universe | the study's 11 symbols (`poc_sb_stops.SYMS`); US100/ETHUSD/XTIUSD excluded pending STRAT-04 cost coverage |
| Data | `data/history/{SYM}_M5.csv`, 3y (2023-06 → 2026-06), unchanged |
| MSS lookback | `LK_M5 = 2` |
| Exit models | FIXED 2R **and** RATCHET+RUNNER (dual-exit gate, falsification principle #3) |
| Anchoring variants | B1 stop-anchored, B2 R-anchored |
| Costs | 1× primary, 1.5× stress |
| Primary metric | Δ = mean(R_B − R_A) over paired trades, net 1× |
| Uncertainty | 10,000-resample **paired** bootstrap CI on Δ |
| Determinism | bootstrap seed 11; no other stochastic element |

---

## Power floor — registered before looking

Arm B's n is unknown a priori and is **not** 1,837–2,217: only pairs where an MSS actually
prints in the window are analysable. (Precedent for aggressive attrition: canonical
Unicorn's overlap+MSS funnel removed 96% of legs.)

Assuming sd of the paired difference ≈ 1.3R, 80% power at α = 0.05 two-sided needs
≈ 590 pairs to detect Δ = 0.15R, ≈ 330 for Δ = 0.20R.

| n_paired | Standing |
|---|---|
| ≥ 500 | Confirmatory. Verdict bands below apply. |
| 300 – 499 | Directional only. Report Δ and CI; **no permanent verdict**, no graveyard entry, no arsenal-doctrine change. |
| < 300 | **INCONCLUSIVE.** Report the funnel and stop. Do not re-tune the window to manufacture n — that is the one-pass rule. |

Realized sd of the paired difference is a **required** reported figure; if it lands far
from 1.3R the power statement is restated in the results doc rather than the bands moved.

---

## Registered gate

Read on Δ (pooled, net 1×, paired-on-both-traded). All four cells — {FIXED, RATCHET+RUNNER}
× {B1, B2} — must agree for any permanent verdict.

| Band | Requirement | Verdict |
|---|---|---|
| **Outcome A — component confirmed costly** | Δ ≤ −0.05R **and** bootstrap upper bound < 0, in **all four cells**; sign holds at ×1.5 spread | MSS confirmation subtracts value from a working displacement-limit entry. The arsenal screens LTF candidates on **entry trigger**; the confirmation branch is closed absent a new mechanically-motivated design with its own pre-registration. |
| **Outcome B — component neutral** | \|Δ\| < 0.05R, **or** the CI spans zero in any cell | **H1 is dead.** MSS is not the toxin; the three NO-GOs were about zone quality / entry primitive. The arsenal screens on **entry primitive** (zone information source), not trigger. |
| **Outcome C — component adds value** | Δ ≥ +0.05R **and** bootstrap lower bound > 0, in **all four cells** | Hypothesis inverted. Confirmation is additive on a good zone; the three failures were entirely zone-driven. Justifies a separate portfolio-level gate on an SB+MSS variant — new pre-registration, not an extension of this one. |
| **Disagreement across cells** | any mixed sign or a band met in some cells only | **INCONCLUSIVE.** Report the disagreement verbatim and make no claim. This is the MTF-PB v2 lesson: a result that holds under one exit model and fails the other is model dependence, not a finding. |

**Reported, not gated:** MSS fire-rate (share of arm-A trades with any MSS in window);
median bars from touch to confirmation; **"first-leg cost"** — the price distance from
zone touch to arm-B entry, expressed in arm-A R (the direct measurement of the mechanism
in H1(a)); win rate and realized RR per arm; per-year and per-symbol Δ; the ITT reading;
×1.5 spread stress.

---

## Known limitations (registered up front)

1. **Already-seen data.** SilverBullet's stop model and exit variant were selected on this
   exact dataset (the stop study's own integrity caveat). The MSS component has never been
   tuned on it, and Δ is a paired difference in which the baseline's selection bias largely
   cancels — but this is not out-of-sample, and the results doc must say so in these words.
2. **STRAT-01.** The validated exit engine is the offline `poc_sb_stops.replay_managed`,
   not the live `trade_manager.sync_positions`. Every level here is an upper bound. Because
   both arms run through the *same* replay, the bias largely cancels in Δ — which is a
   positive argument for this design over any absolute comparison, and the reason no live
   change can follow from this run.
3. **Not a tradeable variant.** See "Occupancy". Arm B's pooled expectancy must never be
   quoted as a strategy result.
4. **Replay conventions** (pessimistic same-bar SL-first; partials filled at the fib level;
   no slippage, no swap) are inherited and symmetric across arms.
5. **Execution asymmetry is real and unmodelled.** Arm A pays the spread on a resting limit
   with no maker rebate — this is already how `cost_r` charges it, so no correction is
   owed. Arm B's market entry additionally suffers slippage that the rig does not model,
   biasing Δ *upward* (in arm B's favour). An Outcome-A result is therefore conservative;
   an Outcome-C result is not.
6. **One instrument family, one broker.** FBS CFDs, 11 symbols, 3 years.

---

## Verification tier (before the gate run)

1. Arm-A fidelity check must pass to the third decimal (above).
2. **Golden slice:** one symbol / one month in verbose mode; hand-verify on raw M5 data for
   at least two pairs — the touch bar, the confirmed swing that MSS breaks, the confirming
   close, arm-B's fill open, and both anchorings' SL/TP arithmetic. Precedent: the OTE
   canonical golden slice.
3. Unit tests for the new pairing/window code (touch-bar resolution, window boundary at
   H1 `i+12`, missing-MSS handling, B1/B2 arithmetic) in `tests/unit`.

---

## Results

*(To be completed after the run. Registered fields: rig commit, funnel counts, n_paired,
realized sd, the four Δ cells with CIs, the reported-not-gated table, verdict against the
bands above, and any post-hoc observation explicitly labelled as post-hoc.)*
