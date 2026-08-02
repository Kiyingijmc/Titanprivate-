# Wave-2 Gate-Triage + Aftershock Kill-Screen — Design

**Date:** 2026-08-01 · **Branch:** `feat/wave2-gate-triage` · **Status:** approved (brainstorm session)
**Candidates:** Aftershock, Rubicon, Rainflow (`docs/strategies/{aftershock,rubicon,rainflow}.md`, all 2026-08-01)
**Precedents:** Gyroscope gate (`docs/research/2026-07-14-gyroscope-gate.md` — pre-registration format),
EXP-0 (`docs/research/2026-07-31-exp0-coinflip-preregistration.md` — entries must earn their own edge).

## Decision summary (owner-approved)

1. **Deliverable:** a pre-registered triage document, then build ONLY the top pick's detector and run
   its kill-screen this cycle (one candidate per research cycle, per the brainstorm's portfolio rule).
2. **Top pick: Aftershock.** Best prior of a trading GO — 5/5 cost-survival in the comparative matrix,
   underlying phenomenon (volatility clustering) is the best-replicated stylized fact in finance,
   self-contained screen with no Coil coordination.
3. **Vehicle:** hands-on this session (Antibody/EXP-0 pattern), not mig rows. mig rows are created only
   for what the verdict unlocks.
4. **Screen design: pure event study, IS-only.** No P&L simulation, no paper trading — exactly the
   stage-(b) discipline `aftershock.md` §6 mandates.

## 1. Deliverables & sequencing (pre-registration discipline)

Three strictly ordered commits on `feat/wave2-gate-triage`, so kill criteria exist in git BEFORE any
result exists (the Gyroscope-gate discipline):

1. **Triage doc** `docs/research/2026-08-01-wave2-gate-triage.md` — the ranking (§2) plus the full
   Aftershock screen pre-registration (§3–§4 below, restated as the registered protocol).
2. **Detector** `src/analysis/hawkes_intensity.py` + `tests/unit/test_hawkes_intensity.py` — TDD on
   synthetic event streams only, no market data.
3. **Screen run** `scripts/event_study_aftershock.py` → results under `data/results/aftershock_screen/`
   + a verdict appendix appended to the triage doc.

## 2. Triage ranking (content of the triage doc)

| Rank | Candidate | This cycle? | Rationale |
|---|---|---|---|
| 1 | Aftershock | **Yes — kill-screen now** | Best GO prior; self-contained; screen is cheap (event study). |
| 2 | Rubicon | Next cycle | Weakest documented hypothesis (post-break drift persistence), but highest salvage value: `BOCPD` + `regime.run_length_posterior` ship as infrastructure even on trading NO-GO — that build can become a mig row independent of its gate. |
| 3 | Rainflow (+Coil) | After, as the shared two-arm gate | One research question, two detectors; already a backlog row. |

**Contradiction to reconcile in the triage doc:** backlog row `coil-rainflow-shared-two-arm-compression`
(`docs/sessions/_BACKLOG.md:127`) says the gate "needs P2 OCO", but `docs/strategies/rainflow.md` §6
deliberately fixes **single-sided entry geometry for both arms** precisely to avoid P2. The triage doc
records single-sided as binding and drops the P2 dependency from that row.

## 3. Detector: scale-invariant excitation index (no MLE)

The continuation condition only ever compares intensity against its own IS **percentile**
(λ_lo = 20th pctile). Percentile banding is invariant to α and μ scaling, so the screen needs only an
**excitation index** `S(t) = Σ exp(−β·(t−tᵢ))` over past events with one fixed β — zero MLE fitting,
which deletes the Hawkes-fragility risk (the Gyroscope calibration-lesson analog named in
`aftershock.md` §2) from the screen entirely.

Pre-registered parameters:

- **Event:** H1 bar with `TR > q × rolling_median(TR, 200)`; **q = 2.5 primary**, q ∈ {2.0, 3.0}
  robustness cells.
- **Decay:** β from **half-life 24 H1 bars** (~1 trading day) primary; {12, 48} robustness cells.
- **Continuation-eligible event (the signal):** S(t⁻) < 20th IS percentile (fresh shock, not
  mid-cascade) AND event bar closes beyond its own midpoint in its direction AND the next bar does not
  fully retrace the event bar's range.
- Banding per symbol, percentiles computed on IS only.

`HawkesIntensity` API surface: event flagging, S(t) recursion, percentile banding, eligibility flags —
pure functions over an OHLC frame, no strategy class, no live-path code.

## 4. Event study & pre-registered kill criteria

**Data:** first 70% chronological per symbol of the frozen lake
(`data/lake/frozen/fbs/<SYM>/H1/*.parquet`, 9 symbols, ~3yr). **The OOS 30% is never read** — it is
preserved for the full backtest gate if the screen passes.

**Outcome variable:** direction-signed forward log returns at +1/+4/+8/+24 bars — forward log return
multiplied by the event direction (+1 if the event bar closed up, −1 if down), so positive = the shock
continued. **Primary horizon: +8.** All horizons reported; only +8 decides.

**Kill criteria — ALL six must pass to advance (verdict PASS); any failure is NO-GO:**

1. Pooled signed forward return at +8 > 0 with bootstrap 95% CI excluding zero (fixed seed).
2. Conditional-vs-unconditional mean difference: bootstrap 95% CI excludes zero (the "histograms must
   separate" test, in monetisable units, not a KS p-value).
3. **Session control:** regression of signed forward return on {signal dummy + session-bucket
   dummies}, where the buckets are {Asia, London, NY-overlap, NY-late} from broker-time hour (4 levels,
   not 24 hour dummies — event counts are too small for that) — the signal coefficient stays positive
   with CI excluding zero (λ-freshness must add information beyond "it's the London/NY open",
   brainstorm §2.17).
4. Per-symbol consistency: ≥6/9 symbols with positive conditional mean at +8 (the criterion Gyroscope
   failed at 4/9).
5. Sample floor: ≥150 qualifying continuation events pooled IS; below floor the verdict is
   **INSUFFICIENT-N** (recorded; not a GO; not silently re-parameterized to manufacture N).
6. Cost sanity: per-symbol median event-bar range ≥ **8× spread** (FBS spread table,
   `scripts/poc_sb_stops.py` SPREADS). A symbol failing this is cost-dead regardless of drift: its
   events are **excluded from the pooled criteria 1–3** and it **counts as a negative symbol for
   criterion 4** (so cost-dead symbols push toward NO-GO, never quietly improve the pooled cell).

Robustness cells (q × half-life variants) are computed and reported, but **the primary cell alone
decides** — no post-hoc cell selection. Exhaustion leg: out of scope entirely (v1 is
continuation-only per `aftershock.md`).

## 5. Verdict handling

- **PASS →** next session drafts the full pre-registered backtest gate mirroring
  `2026-07-14-gyroscope-gate.md` (70/30 IS/OOS, ±30% sweeps, spread stress, `MaSlopeBaseline` arm).
- **FAIL →** NO-GO recorded in `docs/research/`, statuses updated in `docs/strategies/aftershock.md` +
  `ARSENAL.md`, Rubicon promoted to next cycle's pick.
- Either way, the outcome is decomposed into mig backlog rows via `mig idea`.

## 6. Testing & reproducibility

- **TDD:** `tests/unit/test_hawkes_intensity.py` first — TR/median event flagging, decay recursion
  against closed-form values, percentile banding, eligibility flags on synthetic streams (fabricated
  OHLC with known event patterns; no market data).
- Event-study script: fixed RNG seed for all bootstrap draws; emits a run-card-style JSON
  (parameters, dataset provenance ref to `data/lake/frozen/PROVENANCE.md`, per-criterion outcomes,
  verdict) plus plain CSV tables under `data/results/aftershock_screen/`.
- Full unit suite green before each of the three commits.
- Only doc/test/analysis/script files are committed — never the live `data/db/*` or log churn from the
  running demo bot.

## Out of scope (this cycle)

- Any `AftershockStrategy` class, manifest, or config block (only earned by a screen PASS + gate PASS).
- The strategy-initiated flatten hook (shared Wave-2 plumbing) — explicitly deferred by all three
  strategy docs until a candidate clears its screen.
- Rolling-MLE Hawkes fitting, the exhaustion leg, spread-capture (P6/RISK-07), swap-cost modeling.
