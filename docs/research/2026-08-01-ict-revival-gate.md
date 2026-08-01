# ICT-family revival — audit + pre-registered gates for canonical Unicorn and CRT

**Date:** 2026-08-01 · **Status:** PRE-REGISTERED (committed before any run; one pass per
model; NO-GO a valid outcome) · **Requested:** owner, in-session ("re-activate the smc/ict
strategies and do the same as before for them") · **Precedent:** the OTE canonical cycle
(`docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md` +
`docs/research/2026-07-11-ote-canonical-results.md`), whose rig this build resumes — the
sequence OTE → Unicorn → CRT was designed to carry "~80% of the rig" forward and was
terminated early after OTE's NO-GO.

## Audit of the retired family (what may be tested, what may not)

Full falsification record: `docs/strategies/retired-ict-family.md`. Summary of standing:

| Strategy | Status | Consequence for this cycle |
|---|---|---|
| **ICT_OTE** | **Canonically falsified** 2026-07-11: pre-registered NO-GO everywhere, −0.158R pooled managed, 10/11 symbols negative under BOTH exit models, golden trades hand-verified (not an implementation bug) | **Stays retired.** Audit of its gate found no mechanical defect (dual-exit, H1 stops, pre-registration, cost screen, hand-verified detection all sound — unlike Gyroscope v1's F1). The one-pass rule bars re-gating the same rule set; no mechanically-motivated delta has been identified. Re-activation would be re-tuning. |
| **Unicorn** | Removed **unvalidated** (deviant pre-canon implementation was net-negative; canonical form never tested) | **Gate it now** — the graveyard doc explicitly prescribes "its own pre-registered gate from the canonical definition." |
| **CRT** | Removed **unvalidated** (the deployed version "was never actually a test of the CRT model") | **Gate it now**, canonical HTF-range → raid → LTF-MSS → retest structure built from scratch. |

Audit of the deviant implementations (recovered from `b4450f8^` for the record): old
Unicorn = passive LIMIT at a historical breaker level, no structural confirmation (the
exact "bare level" antipattern); old CRT = M5 PDH/PDL sweep + single-candle rejection,
fixed 3R, no HTF range/MSS/retest. Neither resembles what is gated below; their old
numbers bind nothing here.

**Priors, stated honestly:** the FX prior is strongly bearish (OTE −0.158R, MTF-PB v2
−0.274R, both on overlapping machinery); SilverBullet is the only ICT entry stream that
ever cleared costs here, and only via H1 scale + the managed engine. Both models below
inherit every cost-discipline lesson (H1-anchored structural stops, MSS-confirmed retest
entries — never passive limits, dual-exit gate). A double NO-GO is a plausible and
acceptable outcome; it would close the ICT revival question with evidence.

## Shared machinery (frozen)

- `src/analysis/ict_structure.py` — restored verbatim from the OTE chain (`6de8edb^`,
  30 unit tests green): swings, BOS bias, impulse legs, MSS confirm, setup state
  machine, H1-anchored `stop_anchor` (most-protective of pullback extreme / zone
  invalidation + 0.1×ATR / 0.5×ATR floor). The M5 confirmation never tightens the stop.
- Rig: `scripts/poc_ict_revival.py`, same family as `poc_ote_canonical.py`; managed
  replay + cost model imported from `scripts/poc_sb_stops.py` (the validated engine).
- Data: 3y M5 (2023-06→2026-07), same 11 instruments as the OTE gate (FX-majors
  EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD, FX-crosses GBPCAD/GBPJPY, XAUUSD, US30, BTCUSD,
  XBRUSD), FBS measured spreads + $7/lot.
- Entry: MARKET at next M5 open after confirmation. One open trade per symbol.
- Exits: dual model — FIXED (2.5R for Unicorn; the canonical opposite-extreme target for
  CRT) AND the v14.4.2 managed ratchet/runner replay on the same entries.

## Canonical Unicorn — frozen rule set (one pass; no tuning)

Bullish case (bearish mirrored):
1. **Bias:** H1 `structure_bias` BULLISH and H4 agrees (both from closed bars only).
2. **Leg:** most recent H1 impulse leg in the bias direction that broke structure
   (`impulse_leg`).
3. **Breaker:** the last bearish H1 candle at/≤3 bars before the leg-origin swing low
   (close < open); breaker zone = that candle's [low, high]. None → no setup.
4. **FVG:** a bullish H1 FVG inside the leg (3-candle rule: `low[k] > high[k-2]` →
   zone `[high[k-2], low[k]]`, first one after the leg origin).
5. **Unicorn zone = overlap(breaker, FVG)**; empty overlap → no setup.
6. **Entry:** price retraces into the zone (touch) → **M5 MSS** in the bias direction →
   MARKET at next M5 open ("mandatory retest, never chase" + the unifying refinement).
7. **Stop:** `stop_anchor` (pullback extreme / breaker-side zone invalidation + 0.1×ATR(H1)
   / 0.5×ATR(H1) floor). **TP:** 2.5R. **TTL:** 12 H1 bars from setup creation; setup dies
   if price breaches the breaker's far side first.

## Canonical CRT — frozen rule set (one pass; no tuning)

Bullish case (bearish mirrored):
1. **Range:** the previous **broker-day (D1)** candle's high/low.
2. **Raid:** an M5 bar trades below the prior-day low, and an M5 bar (same or later)
   **closes back inside** the range. Raid extreme = lowest low of the excursion.
3. **Retest zone = [raid extreme, prior-day low]** — after the close-back-inside, price
   must trade back INTO this band (touch; "never chase").
4. **Confirmation:** **M5 MSS** bullish after the touch → MARKET at next M5 open.
5. **Stop:** below raid extreme − 0.1×ATR(H1), floored at 0.5×ATR(H1) from entry.
   **Target:** the **opposite range extreme** (prior-day high — canonical). Entries with
   target < 1.0R at fill are skipped (degenerate top-of-range entries).
6. **Lifecycle:** one setup per day per side (first raid arms it; re-raids do not re-arm);
   the setup expires at the end of the raid's broker day.

## Pre-registered gate (both models; identical to the OTE-cycle gate)

A-priori cost screen: median round-trip cost at realized stops ≤ 0.25R per symbol
(excluded symbols reported). **GO for an asset class requires ALL of:**
1. Net-of-cost expectancy positive in **train AND test** (70/30 chronological), 1× spread.
2. Positive under **BOTH exit models** (managed AND fixed).
3. **n ≥ 30** test trades for the class.
4. **×1.5 spread stress** does not flip the pooled sign.
5. Bootstrap CI on test expectancy excludes zero, or lower bound > −0.02R.

Reported, not gated: pooled metrics, per-symbol/per-year tables, funnel counts,
signal-rate/episodicity stats. **One-pass rule** per model. Verdict per class:
GO → propose demo canary (manifest/config/live wiring, owner sign-off — same path as
Gyroscope v2b); NO-GO everywhere → the model joins the graveyard with its numbers and the
ICT-revival question is closed for that model.

Verification tier before either gate run: golden-slice verbose mode on one symbol/month
per model with hand-checked setups (the OTE precedent), plus unit tests for the new
detection primitives (breaker, FVG, overlap, raid/close-back-inside).
