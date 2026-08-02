# Titan Strategy Arsenal — master index and status board

> **Doc version:** 2026-08-01 · **Scope:** every strategy ever live, built, gated, proposed, or
> mentioned in this repository, across all three taxonomies (live/v14 track, novel-arsenal track,
> audit-arsenal track, plus the separate new-bot roster). One architecture file per strategy in
> this directory. Maintained by hand; update when a gate verdict lands.

## How to read this board

**Exactly one strategy trades live.** One was built and formally gated NO-GO. One defensive
overlay was built and recorded RECORD-ONLY on a side branch. One control experiment ran and
anchored the whole programme. Everything else is specification — 9 novel-arsenal concepts,
7 audit-arsenal candidates, and a 12-item new-bot roster with zero implementing code.

Three findings bound every decision on this board:

1. **The cost gate is brutal and measured.** Median round-trip cost must be ≤ 0.25R
   (FBS spreads + $7/lot). M5/M15 ATR-stops are dead; stops must be structural/wide; H1 is the
   validation sweet spot (~18,600 bars/symbol); D1 cannot be validated without the history
   extension (P10).
2. **EXP-0 (2026-07-31, Outcome 1):** entries must earn their own edge. Placebo entries through
   the full exit engine are −0.249R (0/20 reps positive) vs real +0.109R. The ratchet/runner is
   an **amplifier** (+0.231R on real entries), not a subsidy (+0.075R on random). Candidates are
   screened on skew potential, not on inheriting the exit engine.
3. **STRAT-01 (CRITICAL, open):** the validated exit engine is an offline replay
   (`poc_sb_stops.replay_managed`); the live exit engine is different code
   (`trade_manager.sync_positions`). Live expectancy is unmeasured until the ratchet is extracted
   into one shared pure function and the study re-run (roadmap B2). Every replay number below is
   an upper bound.

## Status board

### Track 1 — live / built / gated (code exists)

| Strategy | Doc | Status | Evidence | Next action |
|---|---|---|---|---|
| **SilverBullet** | [silver-bullet.md](silver-bullet.md) | **LIVE** (demo-forward since 2026-07-28, 12 pairs, arm C) | +0.109R net pooled / +0.194R cost-screened, OOS +0.185R, EXP-0-confirmed entry value | Demo checkpoint ~2026-08-11; STRAT-01 closure |
| **Gyroscope** | [gyroscope.md](gyroscope.md) | v1 research NO-GO (2026-07-15); **v2b innovation-SPRT GO 7/7 (2026-08-01, owner-ratified calibration metric)** — still `status: research` pending the 5-step demo-canary build | v2 (6-sym trend universe, managed exits): **+0.057R net, OOS +0.033R, bootstrap 5% LB +0.003R, PF 1.13, DD 23.6R, 1.03 sig/day, 114h median gap** (v1: −0.067R, 27.1% false-entry, 11h re-fires) | Per `2026-08-01-gyroscope2b-gate-results.md`: wire live time-stop + spread gate + grade floor + config, then manifest research→demo on owner sign-off |
| **MaSlopeBaseline** | covered in [gyroscope.md](gyroscope.md) | research forever (control) — **gated 2026-08-01: NO-GO 1/7, decisively** | −0.027R pooled, PF 0.95, 9.9 sig/day, 99.7% flip rate, 0/4 sweeps positive; **Gyroscope v2 beats it by +0.084R/trade on the identical harness** (`2026-08-01-ma-slope-baseline-gate-results.md`) | Doctrine confirmed with numbers; stays the mandatory comparator (`gyro2_gate.py --strategy ma_slope`) |
| **Antibody v1** | [antibody.md](antibody.md) | **RECORD-ONLY** (branch `feat/antibody-study`, unmerged) | alert rate 0.05% (pass); SB-overlap n=1 vs required ≥30 (fail) | v2 (tick-vol/spread z) — value rises when non-session-timed strategies exist |
| **EXP-0 Coin Flip** | in [silver-bullet.md](silver-bullet.md) §2 + prereg doc | **DONE — Outcome 1** | placebo −0.249R vs real +0.109R, 0/20 | Programme proceeds; placebo-vs-ATR-state follow-up is optional |

### Track 2 — audit arsenal (2026-07-30, `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md`; no code)

Ordered by the audit's staging. Gating statement: nothing is built before remediation Stage A is
complete; nothing deploys before Stage B.

| Strategy | Doc | Concept | Stage | Hard blockers |
|---|---|---|---|---|
| **Almanac** | [almanac.md](almanac.md) | Turn-of-month index overlay — zero-parameter yardstick + integration canary | 1 — **BUILT 2026-08-01** (research/disabled; awaiting operator enable for the soak) | n=36 until P10 |
| **Coil** | [coil.md](coil.md) | H1 vol-compression breakout, two-sided STOP bracket | 2 | OCO (P2), bias-exemption policy, grading P8 |
| **Tide** | [tide.md](tide.md) | H1 overextension reversal — the diversifier | 3 | per-strategy exit profile (P7); RISK-01 now fixed |
| **Anchor** | [anchor.md](anchor.md) | H4→D1 diversified TSMOM | 4 | D1/H4 data extension (P10), portfolio backtest (P12) |
| **Ledger** | [ledger.md](ledger.md) | D1 carry/swap harvest | 4 (Step 0 **underway** on `feat/swap-survey`) | Step-0 gate: any net carry > 3% ann. |
| **Bell** | [bell.md](bell.md) | M15 index opening-range breakout | 5 | M15 CandleMaker (ENTRY-03/P1), bar-time sessions (P5), OCO (P2), P9/P12 |
| **Tether** | [tether.md](tether.md) | H1 cointegration pairs (Kalman hedge ratio) | 6 (last) | multi-leg state machine (P13), signed correlation (P4), ARCH-01 |

### Track 3 — novel arsenal (2026-07-12, `docs/research/2026-07-12-novel-arsenal-brainstorm.md`; no code beyond Wave 1)

| Strategy | Doc | Concept | Wave | Standing |
|---|---|---|---|---|
| **Aftershock** | [aftershock.md](aftershock.md) | Hawkes vol-cascade trader | 2 | NO-GO kill-screen 2026-08-02; promoted Rubicon |
| **Rubicon** | [rubicon.md](rubicon.md) | BOCPD regime-break trader | 2 | Rank #3; highest salvage value (regime clock infra) |
| **Rainflow** | [rainflow.md](rainflow.md) | Fatigue-accumulation breakout | 2 | Merge its gate with Coil (same family, two detectors) |
| **Spring** | [spring.md](spring.md) | OU half-life mean reversion | 3 | Cost screen is the expected kill point |
| **Gumbel Fade** | [gumbel-fade.md](gumbel-fade.md) | EVT exhaustion fade (H4/D1) | 3 | Blocked on P10; start background event studies |
| **Walclock** | [walclock.md](walclock.md) | Tick-volume effort-per-distance | 3 | Stage (b) doubles as FBS tick-volume audit |
| **Shannon Gate** | [shannon-gate.md](shannon-gate.md) | Entropy-deficit detector | 4 | Architect as a FeatureBus filter, not a strategy |
| **Constellation** | [constellation.md](constellation.md) | Cross-asset lead-lag network | 4 | Highest existence risk; FDR-gated existence study first |
| **Trinity** | [trinity.md](trinity.md) | HMM regime allocator (overlay) | 4 | Needs risk-multiplier seam + P12; validate as overlay only |

### Track 4 — retired / falsified (records; code removed)

See [retired-ict-family.md](retired-ict-family.md): SilverBullet-M5 original (−4.27R),
ICT_OTE canonical (−0.158R, NO-GO everywhere), **Unicorn canonical (NO-GO everywhere
2026-08-01, −0.209R)**, **CRT canonical (NO-GO everywhere 2026-08-01, −0.150R)** — the
revival gates (`2026-08-01-ict-revival-gate-results.md`) closed the ICT question: all
three retired models are now falsified in canonical, MSS-confirmed form, not merely
removed — MTF-PB (v1 PoC inconclusive-but-promising, v2 NO-GO at −0.274R pooled),
Donchian-20 D1 (wrong horizon). The graveyard is the calibration set: base rate
≈ 1 survivor in 9 attempts.

### Track 5 — new-bot roster (brainstorm-v2, separate `tradebot/` target)

See [newbot-roster.md](newbot-roster.md): T1–T4, M1–M4, TC-1/TC-2, MC-1/MC-2 — all
hypothesis-tagged, zero code, targeting the event-sourced skeleton (M0 complete), with overlap
mapping onto the Titan-track arsenal so research is not duplicated.

## Portfolio view (priors, not measurements)

The arsenal is deliberately anti-correlated by habitat: SilverBullet (session-timed
continuation) · Coil/Rainflow/Aftershock (expansion/vol-events) · Tide/Spring (reversion — the
counter-cyclical leg) · Anchor/Gumbel (multi-day trend/exhaustion) · Tether/Ledger/Almanac
(market-neutral-ish flows) · Trinity/Antibody/Shannon Gate (overlays). The audit's correlation
matrix (05-STRATEGY-ARSENAL §11) is a prior to be measured by the portfolio backtest (P12), and
its risk-budget table cuts the aggregate cap from 5% to 3% as breadth grows — adopt that
direction, not the current 5%, when a second strategy goes live.

## The funnel discipline

Every candidate passes the same pipeline (TVP): pre-registered gate committed before the run →
cost screen (stage b) → event study where applicable → backtest on the shared rig → GO/NO-GO
recorded in `docs/research/` → demo-forward before live. One candidate per research cycle.
Baselines are mandatory: MaSlopeBaseline for trend-family, Almanac (once built) as the
zero-parameter yardstick for everything. The one-pass rule forbids re-tuning on gate data.

## Cross-cutting improvements

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for the prioritized list of missing tools/elements
(ratchet extraction, spread/ask feed, per-strategy exit profiles, D1/H4 data unlock, portfolio
backtest, grading generalization, regime/anomaly FeatureBus resources) with their evidence.
