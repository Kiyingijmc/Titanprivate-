# OTE Canonical MTF Rebuild — Design & Pre-Registered Validation Gate

**Date:** 2026-07-11 · **Status:** approved design, pre-implementation
**Sequence:** first of three inactive-strategy cycles (OTE → Unicorn → CRT)
**Approach chosen:** B — full canonical MTF rebuild (H4 bias → H1 leg → M5 MSS),
validated on 3 years before any live activation.

## Context & priors (read before questioning the design)

- All three inactive strategies (`ict_ote`, `unicorn_model`, `crt`) run on M5 with
  M5-scale stops. The 2026-07-11 SB stop study proved M5 is **cost-dead at any stop
  width** on FBS costs; SB was rescued only by H1 + 1.0×ATR stop + the v14.4
  ratchet/runner engine (−0.12R fixed → **+0.11R managed**, PF 1.26).
- The 2026-05-29 research audit found the current `ict_ote.py` implements the exact
  documented antipattern: a **bare 0.705 limit with no confirmation** — wicked
  through, rarely fills.
- **MTF-PB v2 (2026-06-25) already tested something very close to canonical OTE +
  M5 MSS** — H4+H1 structural bias, OTE zone, M5 MSS confirm, MARKET entries,
  M15-leg / M5-structure stops, managed exits — and got a clean **NO-GO** on 3
  years (FX −0.36…−0.59R net; other classes ≈0 and exit-model-dependent).
- Therefore this build's *only* live thesis is the three deltas v2 never tested:
  1. **Leg scale M15 → H1** (H1-scale risk unit → round-trip costs ≤0.25R);
  2. **Stop anchored to H1 structure, never the M5 confirmation**;
  3. **The exact v14.4 ratchet/runner engine** as the managed-exit model (the
     component that flipped SB's sign).
- Honest expectation: the FX prior is bearish. A clean NO-GO is a valid, useful
  outcome — the rig carries ~80% into the Unicorn cycle.

## 1. Canonical rule set (frozen a-priori — no tuning grid)

All values fixed from the canonical prescriptions (2026-05-29 research) before the
rig runs. One rule set, one pass through the gate.

| Element | Rule |
| --- | --- |
| **Bias** | Market-structure BOS/HH-HL on **H4 and H1, both must agree** (reuse MTF-PB v2's structural-BOS definition). Longs only in dual-bullish, shorts mirror. No session/time gate. |
| **Impulse leg** | Most recent **H1** swing-to-swing move in the bias direction, displacement ≥ **2.0×ATR(H1)** (`min_swing_atr` convention). Leg defines the fib range. |
| **OTE zone** | **0.62–0.79** retracement of the leg (0.705 centre). A zone, not a line. |
| **Confirmation** | Price trades **into the zone**, then an **M5 MSS in the trend direction**: M5 close breaking the most recent M5 swing high (longs) / low (shorts) formed during the pullback (reuse v2's `mss_confirm`). |
| **Entry** | **MARKET at next M5 open** after the confirm close (pessimistic). Never a resting limit — kills the wicked/expired-order antipattern by construction. |
| **Stop** | **H1-anchored, non-negotiable**: beyond the pullback extreme (longs: lowest low printed since the leg high; shorts mirror), **floored at ≥0.5×ATR(H1)** from entry, and never tighter than zone invalidation (the 0.79 level + 0.1×ATR(H1) buffer). The M5 confirmation must never set or tighten the stop. |
| **Setup TTL** | Leg/zone expires if unconfirmed within **12 H1 bars** (SB TTL convention). |
| **Exits (dual-model)** | (i) **v14.4 ratchet/runner** (BE @38.2%, bank 30% @61.8%, bank 50% @88.6%, runner trail); (ii) **fixed 2.5R** comparator. The gate requires both to pass. |
| **Concurrency** | One open trade per symbol (live exposure rule). |

## 2. Backtest rig & data

- **Script:** `scripts/poc_ote_canonical.py`, patterned on `poc_sb_stops.py` and the
  MTF-PB v2 rig; reuses `resample` (M5→H1/H4), `atr_series`, the FBS cost model
  (`data/specs.json` spreads + $7/lot, charged in R), and the v14.4 managed-exit
  replay used by the SB stop study and the overlay study.
- **Data:** existing 3-year M5 exports (2023-06 → 2026-06, 11 instruments) in
  `data/history/`. H1/H4 resampled from M5. No new export required.
- **Replay conventions (pessimistic, identical to prior studies):**
  - Bias/legs computed only on **closed** H4/H1 bars (no lookahead).
  - Zone-touch, MSS, entry, stops, management replay at **M5 resolution**.
  - Same-bar-SL-first; partials fill at the fib level.
  - One trade per symbol; **chronological portfolio ordering** for equity-curve/DD
    (the overlay-study Section-6 lesson).
- **Outputs:** `data/history/ote_canonical_*.{csv,log}` (per-symbol + per-class
  trades and summary), results doc `docs/research/2026-07-XX-ote-canonical-results.md`.
- **Calibration pre-pass (not a gate):** print the distribution of detected H1 legs
  and realized stop distances per symbol; apply the SB **a-priori cost screen** —
  exclude symbols whose median round-trip cost at the realized stop is > 0.25R
  (economic viability, not performance selection).

## 3. Validation gate (pre-registered)

**GO for an asset class requires ALL of:**

1. Net-of-cost expectancy **positive in train AND test** (70/30 chronological OOS),
   at 1× spread.
2. Positive under **BOTH exit models** (ratchet/runner AND fixed 2.5R).
3. **n ≥ 30** trades in the test subsample for the class.
4. **Spread ×1.5 stress does not flip the sign** of pooled expectancy.
5. Bootstrap CI on test expectancy excludes zero, or lower bound > −0.02R
   (Wilson CIs on win rate reported alongside).

**Reported, not gated:** pooled expectancy/PF/DD (chronological basis), per-year
stability, per-symbol table, `SignalGrader` offline-mirror impact.

**One-pass rule (overfitting firewall):** Section-1 parameters are frozen. If the
run fails and a specific mechanically-motivated change is believed to fix it, that
change gets its own mini-spec and a fresh pre-registered run. No in-place iteration
on the same data.

**Decision matrix:**

- **GO (per class):** that class enters the live `pairs`; proceed to Section 4.
- **NO-GO everywhere:** OTE stays `enabled: false`; findings documented in the
  results doc; sequence advances to the Unicorn cycle reusing the rig (bias, legs,
  MSS, replay, cost model, gate).

## 4. Live port (executed only on a GO)

- **Rewrite `src/strategies/models/ict_ote.py`** to the canonical spec; the current
  bare-limit logic is deleted, not kept alongside.
- Registers `timeframe: "M5"` (controller calls it on M5 closes, where confirmation
  lives). H1 via `market_data[symbol].get_data("H1")` (same path as `BiasEngine`);
  **H4 resampled from H1 in-strategy** (avoids touching the data store).
- Per-symbol in-memory state: current leg, zone, TTL countdown, zone-entered flag.
  Restart mid-pullback ⇒ wait for the next leg (accepted, simple — CRT-style state).
- Decision contract unchanged: `{signal, type: 'MARKET', price, sl, tp}` —
  **no EA changes, no MetaEditor recompile**. TP is for grader/journal; the v14.4
  trade manager owns real exits, exactly as for SB.
- Controller's HTF-bias veto (`system_controller.py` `_run_strategies`) stays —
  redundant with the strategy's own H4+H1 gate but never contradicts it.
- **Config** (`ict_ote` block): `ote_zone: [0.62, 0.79]`, `min_swing_atr: 2.0`,
  `stop_floor_atr: 0.5`, `ttl_h1_bars: 12`; `pairs` = GO classes only;
  `enabled: true` last, in its own commit, with a comment pointing at the results
  doc (SB v14.4.2 adoption pattern).
- **Rollout:** demo-forward-test before live risk; verify live fills/costs match
  rig assumptions.
- Signals flow through `SignalGrader` like every strategy; the rig's grader mirror
  (Section 3) predicts whether the `min_grade` floor helps or starves it.

## 5. Testing

- **Rig verification before trusting the 3-year run:**
  - Golden-slice test: a few weeks of one symbol, hand-verify detected
    legs/zones/MSS confirms against raw candles.
  - Regression anchor: the rig's cost model + managed-exit replay must reproduce
    the SB study's Control numbers (n=2217, +0.109R, PF 1.26, DD 24R) when pointed
    at SB signals — the overlay study proved this reconciliation pattern.
- **Unit tests** (`tests/unit/test_ote_canonical.py`, stdlib `unittest`, TDD,
  synthetic-candle fixtures): leg detection (right swing pair; rejects <2×ATR),
  zone math (0.62/0.79 boundaries, long/short mirror), MSS detection (only after
  zone entry; correct swing broken), stop anchoring (0.5×ATR(H1) floor; never
  M5-tightened; respects zone invalidation), TTL expiry, restart-mid-pullback
  (no signal until a fresh leg).
- **Shared-code rule:** detection logic (legs, zone, MSS, stop) lives in **pure
  functions** — module-level in the strategy file, or `src/analysis/ote_structure.py`
  if it crowds it — imported by BOTH the rig and the live strategy. One
  implementation kills the rig-vs-live drift bug class (a targeted improvement over
  the SB rig's offline re-implementation).

## Phasing

1. **Phase 1 — structure functions + unit tests** (pure functions, TDD).
2. **Phase 2 — rig** (`poc_ote_canonical.py`), golden-slice + SB-control
   reconciliation, calibration pre-pass + cost screen.
3. **Phase 3 — the 3-year run**, results doc, GO/NO-GO verdict per class.
4. **Phase 4 (GO only) — live port**, config adoption, demo-forward-test.
5. **Phase 5 — next cycle:** carry the rig into Unicorn (then CRT) regardless of
   verdict.

## Out of scope

- Unicorn and CRT rewrites (next cycles; each gets its own spec).
- Any EA/MQL5 change (MARKET-only entries make it unnecessary).
- Re-tuning SB or the management engine's fib levels.
- Grid searches over zone bounds, ATR multiples, or TTL — the one-pass rule.
