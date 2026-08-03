# Gyroscope (KalmanDrift + SPRT) — post-NO-GO audit

**Date:** 2026-08-01 · **Auditor:** Claude (Fable 5) · **Scope:** `src/analysis/kalman_drift.py`,
`src/strategies/models/gyroscope.py`, the Plan-07 gate (`docs/research/2026-07-14-gyroscope-gate.md`,
`docs/research/2026-07-14-gyroscope-gate-results.md`, `data/results/plan07_gyro_gate/`), unit tests.

**Purpose:** establish, from mechanism and evidence, *why* Gyroscope failed its gate
(pooled −0.067R, PF 0.91, NO-GO 2026-07-14) — as the required precursor to any redesign.
Per the one-pass rule, the NO-GO'd configuration stays NO-GO; a redesign enters as a
**new pre-registered gate**, not a re-tune.

---

## Verdict of the audit

The strategy did not fail because Kalman drift estimation is worthless — it failed because
the **decision layer's statistics are broken by construction**, the gate **scored the entry
stream under an exit model the book doesn't use**, and half the safety rails documented
around it (time-stop, spread screen, NIS suspension) are **inert or nonexistent**. The
filter itself (level+velocity Kalman, NIS-calibrated R) is sound, deterministic, well-tested
code worth keeping.

---

## Findings

### F1 — The SPRT's error guarantees are void: it tests an autocorrelated statistic (CRITICAL)

`kalman_drift.py:160-165`: the SPRT accumulates `λ += δ·z − δ²/2` where
`z = v̂/√P_vel` is the **standardized velocity state**. The module docstring itself concedes
*"alpha/beta are NOMINAL (z is autocorrelated across bars)"*. The Wald boundaries
`A = log((1−β)/α) = 2.77` price evidence as if each bar's z were independent; in reality the
velocity state carries over bar-to-bar, so once v̂ drifts slightly positive, z stays positive
for many bars and λ ratchets to the boundary **on noise**.

Measured consequences (gate results + `signals.jsonl` re-analysis, n=8,365 signals):

| Designed | Realized |
|---|---|
| α = 5% false-entry | **27.1%** (5.4× design; 2.7× the blueprint's own 2α kill-switch) |
| "episodic participation" | **~10.7 signals/day** across 9 symbols |
| decisive, rare crossings | median **11h between signals** on the same symbol; 14% within 6h |
| directional conviction | **42% of consecutive same-symbol signals flip direction** |

A drift detector that reverses its mind every other signal is a whipsaw generator. This single
defect explains most of the loss: 4,914 trades × ~0.09R round-trip cost at 33% win-rate/2R
target is almost exactly the realized −0.067R/trade.

### F2 — The documented justification for the velocity-SPRT deviation is internally inconsistent

The docstring (`kalman_drift.py:6-18`) justifies abandoning the blueprint's innovation-SPRT
because *"the NIS integrity monitor (which flags large innovations) then suspends on exactly
the drift transient the innovation-SPRT would need — the two layers fight."*

But `kalman_drift.py:83`: `nis_persist = nis_window` (50) and suspension requires the rolling
NIS **mean** to sit out-of-band for **50 consecutive bars** (`:152-156`), which the same
docstring correctly states *"a drift onset is a brief spike and never trips."* Both claims
cannot be true. Under the code as written, a drift transient **cannot** cause suspension, so
the stated reason for the deviation does not exist. The deviation traded a valid statistical
test (innovations are approximately white when NIS≈1 — the filter's own calibration target)
for an invalid one, to avoid an interaction the suspension logic already precludes.

### F3 — Post-crossing reset + 5-bar cooldown guarantees serial re-entry on one trend

After any crossing, both λ reset to 0 (`:174-176`) and the strategy blocks re-entry for only
`reentry_lockout = 5` bars (`gyroscope.py:119`). With autocorrelated z, a persistent drift
re-arms λ to the boundary in a handful of bars — hence the 11h median re-fire. The strategy
takes the same trend as **many full-risk sequential trades** instead of one position, multiplying
cost drag and stop-outs on every pullback. (3,451 further signals were skipped only because a
trade was already open — `n_skipped_busy` in `run.json`.)

### F4 — The gate scored entries under a fixed SL/TP exit the live book does not use (CRITICAL, = STRAT-01)

`2026-07-14-gyroscope-gate.md:34-42` is explicit: accounting used the rig's deterministic
first-hit `resolve_trade`; *"Reverse-SPRT/time-stop live exits … are NOT part of this offline
gate's accounting."* Meanwhile the live book's entire measured edge lives in the managed exit
engine (EXP-0: exits amplify a real entry stream +0.109R→+0.231R). Median holding time in the
gate: winners 14h, losers 8h — losers ride to −1R untouched by the BE/partials ladder that
live trades get at +0.382R/+0.618R. The gate therefore measured *"Gyroscope entries under an
exit policy nobody runs."* Its NO-GO stands for that configuration, but it tells us little
about the entry stream under the managed exit — in either direction.

### F5 — The documented time-stop/reverse-SPRT exits do not exist in the tree

The gate doc claims these exits are *"built and unit-tested."* Verified 2026-08-01:
`grep -r max_bars_in_trade src/ scripts/` → **zero hits**. The key exists only in
`config/config.yaml:158` (dead config) and the test fixture dict at
`tests/unit/test_gyroscope_strategy.py:20` (never asserted on). `run.json` corroborates:
`expired: 0` across all 4,914 trades. Either the exits were purged in the 2026-07-12 dead-code
sweep or never landed; either way the doc's claim is false against the current tree.

### F6 — The spread screen is doubly hollow

Live: `gyroscope.py:113-114` gates on `context.get('spread')`, which the controller never
populates — the check is inert. Offline: the gate doc itself admits the screen
*"passes vacuously (optimistic)."* `max_spread_atr_frac` is a comfort parameter.

### F7 — NIS suspension is a dead man's brake

Suspension needs the windowed NIS mean out of ±2.576·√(2/50) band for 50 **consecutive** bars
(two full days of H1). No plausible regime break short of a data-feed fault sustains that; the
integrity monitor almost certainly never fired during the gate. As configured it protects
against nothing the warmup guard doesn't already cover.

### F8 — The economics split cleanly by asset class, exactly as a drift model predicts

Per `run.json` / `signals.jsonl` (fill-level re-analysis):

| Class | Trades | Net | Per-trade |
|---|---|---|---|
| Trend-prone (BTCUSD, XAUUSD, US30) | 1,766 | **+70.4R** | **+0.040R** |
| FX majors+crosses (6 pairs, incl. USDJPY +20R) | 3,148 | **−400.3R** | **−0.127R** |

Per-symbol: BTCUSD +32.2R, XAUUSD +35.7R, USDJPY +20.0R, US30 +2.6R vs EURUSD −106.1R,
GBPJPY −124.1R, GBPUSD −77.5R, AUDUSD −71.8R, USDCAD −40.9R. Mean-reverting FX ranges are the
single worst habitat for a persistent-drift detector with a broken re-fire brake; the
detector detects drift where drift actually persists. (This is observed IS+OOS pooled —
any universe restriction in a redesign must be pre-registered as an *asset-class* hypothesis,
not a post-hoc pick of winners.)

### F9 — The gate itself terminated early; criteria 5–7 were never evaluated

`data/results/plan07_gyro_gate/` holds exactly one run card (the headline defaults run).
`gate_run.log` ends mid-launch of run 2 (spread ×1.5). The ±30% sweeps (criterion 5), the
MA-slope baseline comparison (criterion 6), and the ×1.5 spread stress (criterion 7) never
completed. Legitimate under early termination on a failed primary criterion — but it means
robustness/baseline evidence does not exist for this family at all.

### F10 — The grader is a poor fit for a stat strategy (context, not a defect)

The gate ran with `signal_grading.min_grade=C` overridden precisely because the grader's
components (HTF bias 30, displacement 20, PD 15, killzone 15) are SMC-centric: 49% of
Gyroscope signals graded C and would die at the default B floor. Since 2026-08-01 the
infrastructure for this exists properly: `signal_grading.per_strategy_min_grade`
(built for the Almanac canary) — no override hack needed in a future gate.

---

## What is worth keeping

- **The Kalman filter core** (`kalman_drift.py` predict/innovate/update, the 0.5
  return-variance→R correction, ATR-scaled Q): deterministic, stdlib-pure, well-unit-tested,
  NIS≈1 calibration verified. This is a good "trend with an error bar" estimator.
- **`sqrt_S_price` stops with an ATR floor**: honors the validated "tight H1 stops die" finding.
- **The idempotent carried-state feeding pattern** in `gyroscope.py` (bar-identity guard,
  bootstrap-not-traded): correct and reusable.
- **The gate discipline itself**: pre-registration, IS/OOS, run cards, honest NO-GO.

## Mechanically-motivated redesign directions (for the v2 pre-registration)

Each maps to a finding; none is a free parameter to tune:

1. **F1/F2 → SPRT on whitened innovations** `e/√S` (the original blueprint design). When
   NIS≈1 the innovation stream is approximately white, so α/β become approximately real.
   The detector fires on drift *onset* and self-quiets after the filter absorbs the new
   velocity — episodic by construction, killing the re-fire pathology (F3) at the root.
2. **F3 → keep a lockout as belt-and-braces**, but sized in days not bars, or replaced by
   "no re-entry while the filter's velocity sign is unchanged".
3. **F4 → gate accounting under the managed exit engine** (the validated
   `poc_sb_stops.replay_managed` rules), alongside the fixed-exit number for comparability.
4. **F5 → implement the time-stop for real** (TradeManager `time_exits` infrastructure from
   the Almanac build generalizes to a max-bars variant) — or delete the config key.
5. **F6 → wire `context['spread']`** from live tick data or delete the parameter; model
   spread honestly in the offline gate (the rig already charges it in costs).
6. **F7 → make suspension reachable**: decouple `nis_persist` from `nis_window`
   (e.g. 10 consecutive out-of-band bars on a 50-bar window).
7. **F8 → pre-register a trend-prone universe as an asset-class hypothesis**
   (crypto/metals/indices/energy from the passed universe screen: BTCUSD, XAUUSD, US30,
   US100, ETHUSD, XTIUSD), with FX explicitly excluded by mechanism, not by result-peeking.
8. **F10 → use `per_strategy_min_grade`** for Gyroscope instead of a global override.

A v2 must clear a **new pre-registered gate** (committed before the run, one pass, NO-GO a
valid outcome) before any status change from `research`.
