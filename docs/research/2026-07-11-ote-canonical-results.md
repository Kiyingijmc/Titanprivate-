# Canonical OTE MTF — 3-Year Gate Results

**Date:** 2026-07-11 · **Rig:** `scripts/poc_ote_canonical.py`
**Data:** 3 years M5 (2023-06 → 2026-06), 11 instruments, FBS specs, costs in R
(spread ×1/×1.5 + $7/lot). **Raw:** `data/history/ote_canonical_3yr.log`,
`data/history/ote_canonical_trades.csv`
**Spec + pre-registered gate:** `docs/superpowers/specs/2026-07-11-ote-canonical-mtf-design.md`

## Verdict

**NO-GO everywhere.** Every one of the six asset classes fails the pre-registered
gate — none clears leg 1 (test-set expectancy positive under both exit models).
`FX-majors`, `FX-crosses`, `metals`, `index`, and `crypto` all have negative
MANAGED test expectancy (`energy`/XBRUSD was excluded by the a-priori cost screen
before the gate even ran). Pooled net-of-cost expectancy across all included
symbols is **−0.158R** (MANAGED, net 1×) — materially worse than MTF-PB v2's prior
NO-GO (−0.28R pooled) is *not* the comparison that matters here; the comparison
that matters is the sign, and it stayed negative. None of the three deltas this
build tested against v2 (H1-scale legs, H1-anchored stops, the v14.4
ratchet/runner engine) flipped the sign, contrary to the honest-but-hopeful prior
that they might reproduce SB's rescue (SB went −0.12R fixed → +0.11R managed on
the same management engine). The gross signal here does not survive net-of-cost
testing at any exit model, at any leg/stop scale tried across this cycle plus the
prior MTF-PB v2 cycle. OTE stays `enabled: false`.

## Verification performed

**Golden-slice (spec §5):** `--sym XAUUSD --golden --start 2026-03-02 --end
2026-03-27` produced 3 SETUP→ZONE→MSS→ENTRY sequences (funnel: legs=94,
setups=26, zone_touch=6, mss=4, entries=3). Two of the three entries were
hand-verified end-to-end against the raw `data/history/XAUUSD_M5.csv`:

- **Trade @ 2026-03-18 02:35:00 (SELL, entry 5001.10):** leg low 4973.64 found
  exactly at M5 bar 2026-03-17 17:40 (low=4973.64); leg high 5031.44 found
  exactly at M5 bar 2026-03-17 15:40 (high=5031.44) — high precedes low
  chronologically, consistent with a bearish impulse. Zone (5009.476, 5019.302)
  recomputed by hand as `leg_lo + 0.62×range` / `leg_lo + 0.79×range` (range
  57.80) — exact match. Zone-touch bar 02:05 has high=5012.13, inside the zone —
  matches the logged "ZONE touched" bar exactly. MSS-confirm bar 02:30
  (close=5001.11) independently traced to a confirmed M5 swing low at 02:00
  (low=5001.15, confirmed via the stated lookback-2 rule against neighbouring
  bars) being broken on close — matches the logged MSS bar. Entry fills at the
  next bar's open (02:35, open=5001.10), matching the log. Stop 5021.266643
  recomputed as `max(pullback_ext=5012.13, zone_hi + 0.1×ATR = 5019.302 +
  1.9646 = 5021.2666, entry + 0.5×ATR = 5010.92)` = zone-invalidation anchor,
  the most protective of the three — exact match, confirming the stop is never
  M5-tightened.
- **Trade @ 2026-03-20 06:10:00 (SELL, entry 4718.03):** leg low 4502.49 found
  exactly at M5 bar 2026-03-19 15:00; leg high 4867.03 found exactly at M5 bar
  2026-03-19 03:40 (again high-before-low). Zone (4728.5048, 4790.4766)
  recomputed by hand — exact match. Zone-touch bar 05:15 (high=4735.33 ≥
  z_lo=4728.5048) matches. MSS-confirm bar 06:05 (close=4718.04) independently
  traced to a confirmed swing low at 05:50 (low=4721.68, confirmed against
  05:35–06:00 neighbours) broken on close — matches. Entry fills at 06:10
  (open=4718.03). Stop 4795.895529 = `zone_hi + 0.1×ATR` (4790.4766 +
  5.41893 = 4795.8955) again the most protective anchor and matches exactly.
- Broader context check: resampled H1 highs/lows for XAUUSD 2026-03-09 →
  2026-03-13 show a clean structural decline (peak ~5228 on 03-10 down to
  ~5055 by 03-12 22:00, continuing sub-5000 by 03-17–03-20) — consistent with
  the sustained bearish H1/H4 structure the setups above were built on. No
  discrepancy found in any of the checked numbers.

**SB-control reconciliation (spec §5, integration-tier check):** substituted per
the task brief — the ~30–60 min `poc_sb_stops.py` rerun was skipped. The Task 5
unit goldens (`tests/unit/test_ote_rig.py`, 5/5, imports `replay_managed`/
`cost_r` directly from `scripts/poc_sb_stops.py`) already pin the shared
managed-exit replay and cost-model arithmetic to exact values (ratchet+runner
golden R value, ratchet-fixed-TP golden value, same-bar-SL-first ordering,
EURUSD cost arithmetic to 9 decimal places, 1.5× spread-stress multiplier) —
this is the same reconciliation the plan calls for, at the unit tier rather than
a full integration rerun.

## Cost screen

Section 1 (median round-trip cost at realized H1-anchored stops, exclude
> 0.25R):

| Symbol | Median cost | n | Verdict |
|---|---|---|---|
| AUDUSD | 0.142R | 178 | INCLUDED |
| BTCUSD | 0.035R | 251 | INCLUDED |
| EURUSD | 0.111R | 173 | INCLUDED |
| GBPCAD | 0.187R | 178 | INCLUDED |
| GBPJPY | 0.114R | 178 | INCLUDED |
| GBPUSD | 0.109R | 163 | INCLUDED |
| US30 | 0.026R | 161 | INCLUDED |
| USDCAD | 0.163R | 159 | INCLUDED |
| USDJPY | 0.086R | 173 | INCLUDED |
| XAUUSD | 0.030R | 162 | INCLUDED |
| XBRUSD | 0.667R | 144 | **EXCLUDED** (economic screen) |

Only XBRUSD excluded — **fewer** exclusions than the SB study's two (GBPCAD
0.26R, XBRUSD 1.00R); GBPCAD passes cleanly here at 0.187R because the
H1-anchored stop (floored at ≥0.5×ATR(H1)) is wider than SB's own stop, pushing
median risk up and cost-as-fraction-of-risk down. **No calibration flag**:
Section 1 excludes fewer symbols than the SB study's baseline, not materially
more. Spot-check of `risk / atr_h1` across all 1,920 pre-screen trades confirms
the floor is respected exactly (min = 0.500, by construction) with a median of
1.17×ATR(H1) — stops are meaningfully H1-scale, not M5-scale, so the negative
result is not an artifact of under-priced costs.

## Gate table

Per spec §3: GO requires net>0 train AND test under both exit models, n_te≥30,
1.5× spread stress holding sign, bootstrap CI excluding zero (or lower bound
> −0.02R).

| Class | n (incl.) | Model | train exp | test exp | n_te | bootCI (test) | winCI | 1.5× holds | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| FX-majors | 846 | FIXED | −0.206 | −0.103 | 254 | [−0.297, +0.099] | 25–36% | | fail |
| | | MANAGED | −0.176 | −0.173 | 254 | [−0.309, −0.033] | 25–36% | SIGN FLIP (−180.6R / −180.8R) | fail |
| **FX-majors** | | | | | | | | | **NO-GO** |
| FX-crosses | 356 | FIXED | −0.010 | −0.278 | 107 | [−0.561, +0.038] | 18–34% | | fail |
| | | MANAGED | −0.084 | −0.301 | 107 | [−0.489, −0.078] | 19–35% | SIGN FLIP (−53.2R / −74.3R) | fail |
| **FX-crosses** | | | | | | | | | **NO-GO** |
| metals (XAUUSD) | 162 | FIXED | −0.190 | +0.130 | 49 | [−0.300, +0.559] | 21–47% | | fail |
| | | MANAGED | −0.088 | −0.054 | 49 | [−0.364, +0.264] | 18–42% | SIGN FLIP (−17.8R / −15.2R) | fail |
| **metals** | | | | | | | | | **NO-GO** |
| index (US30) | 161 | FIXED | +0.026 | −0.598 | 49 | [−0.884, −0.243] | 6–24% | | fail |
| | | MANAGED | −0.062 | −0.388 | 49 | [−0.656, −0.093] | 11–34% | SIGN FLIP (−28.4R / −27.9R) | fail |
| **index** | | | | | | | | | **NO-GO** |
| crypto (BTCUSD) | 251 | FIXED | −0.379 | −0.159 | 76 | [−0.486, +0.210] | 17–36% | | fail |
| | | MANAGED | −0.252 | +0.032 | 76 | [−0.276, +0.334] | 26–47% | SIGN FLIP (−82.2R / −45.4R) | fail |
| **crypto** | | | | | | | | | **NO-GO** |
| energy (XBRUSD) | — | — | — | — | — | — | — | — | **NO-GO — no trades** (excluded by cost screen) |

No class clears train AND test AND both exit models simultaneously (metals FIXED
test and crypto MANAGED test are individually positive, but their paired exit
model fails, so the class fails on gate leg 2 regardless). Note the "1.5×
spread pooled" rows print "SIGN FLIP" whenever the 1.5× pooled sum isn't
positive — for these classes the pooled sum was already negative at 1× (not a
flip caused by the stress multiplier); the label is a rig cosmetic, not a
substantive additional failure. Every class fails independently on gate leg 1
(train/test net>0) regardless.

## Portfolio + context

Section 4, pooled across all cost-screen-included symbols (10 of 11; XBRUSD
excluded), chronological ordering:

| Slice | n | exp | totR | PF | DD | win% |
|---|---|---|---|---|---|---|
| FIXED net1× | 1,776 | −0.169R | −300.1 | 0.79 | 308R | 27.0% |
| MANAGED net1× | 1,776 | **−0.158R** | −281.5 | 0.73 | 288R | 29.9% |
| MANAGED net1.5× | 1,776 | −0.193R | −343.6 | 0.69 | 349R | 29.9% |

Per-year (MANAGED net1×): 2023 n=306 exp=−0.149R · 2024 n=584 exp=−0.079R ·
2025 n=627 exp=−0.203R · 2026 n=259 exp=−0.241R — negative in every year, with
no improving trend; if anything the most recent year is the worst.

**Comparison to the two anchors:**

| Study | Pooled net exp | PF | DD |
|---|---|---|---|
| MTF-PB v2 (2026-06-25, prior NO-GO, M15 legs/stops) | −0.28R (−0.274…−0.285R) | — | — |
| SB-H1 control (2026-07-11, adopted v14.4.2, H1+ATR10 stop+ratchet/runner) | **+0.109R** | 1.26 | 24R |
| **This study — canonical OTE (H1 legs/stops, same ratchet/runner engine)** | **−0.158R** | 0.73 | 288R |

The canonical OTE rebuild is closer to MTF-PB v2's failure than to SB's rescue,
despite reusing SB's exact stop-scale and management-engine deltas. The
management engine alone did not rescue OTE the way it rescued SB — SB's edge was
gross-positive pre-cost on every timeframe tested (+0.3…+0.45R gross); this
study's per-symbol table (Section 2 of the log) shows negative expectancy under
*both* FIXED and MANAGED models on 10 of 11 symbols, i.e. the underlying
gross signal (H4+H1 BOS bias → H1 leg → 0.62–0.79 zone → M5 MSS) does not appear
to carry a positive raw edge here the way SB's FVG-displacement signal did — the
management engine has nothing to rescue.

## Grader mirror

Section 5 (`SignalGrader` offline mirror; `candle=None` — the displacement
factor is unavailable offline, so this is an approximation, reported only, not
gated):

| Grade | n | exp |
|---|---|---|
| B | 861 | −0.151R |
| C | 915 | −0.165R |

`≥B floor`: n=861, exp=−0.151R vs ungated −0.158R — a small directional
improvement from the grade floor, consistent with the SB study's finding that
`min_grade: B` helps at the margin, but it does not come close to flipping the
sign; grading is not a rescue for a structurally negative edge.

## What happens next

**NO-GO everywhere.** OTE (`src/strategies/models/ict_ote.py`) stays
`enabled: false`; no code change, no config change, no live port — per spec §4,
the live port is executed only on a GO. This closes the OTE cycle of the
three-strategy inactive sequence (spec "Sequence: first of three inactive-
strategy cycles (OTE → Unicorn → CRT)"). Per spec §5/Phasing, the rig (bias
detection, leg/zone/MSS structure functions, cost model, dual-exit replay, gate
harness) carries forward unchanged into the **Unicorn cycle**, reusing
`src/analysis/ote_structure.py`'s shared pure functions and
`scripts/poc_sb_stops.py`'s shared cost/replay code. **One-pass rule:** this
result is final for the frozen rule set in spec §1 — no in-place re-tuning of
zone bounds, ATR multiples, or TTL on this data. Any specific,
mechanically-motivated change (e.g. a different leg-detection timeframe, a
different confirmation TF) requires its own mini-spec and a fresh pre-registered
run, not an edit to this one.
