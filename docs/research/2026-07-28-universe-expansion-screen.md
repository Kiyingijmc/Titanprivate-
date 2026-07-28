# SilverBullet universe-expansion screen — 8 FBS candidates (2026-07-28)

**Question:** can the validated v14.4.2 SilverBullet universe (9 symbols,
docs/research/2026-07-11-silverbullet-h1-stop-study.md) be widened, and which
FBS symbols earn a slot?

**Method:** identical pipeline to the 2026-07-11 stop study, reusing
`scripts/poc_sb_stops.py` unchanged (H1 signals, ATR10 stop, RR 2.0, TTL 12,
one-open-per-symbol, ratchet+runner replay, spread+commission cost model).
Data: fresh 3y M5 exports over the Phase-1 HTTP bridge (2023-07-31 →
2026-07-28, ~210–315k bars/symbol). Spreads: measured live over the bridge
(median of 6 samples, 2026-07-28 evening session) in broker points; the
harness stresses ×1.5/×2. Screen rule is the study's a-priori economic gate:
median round-trip cost ≤ 0.25R. Harness + raw outputs:
`data/results/universe_screen_20260728/`.

**Reproduction check:** the wrapper re-run on EURUSD gives +0.195R net 1×,
PF 1.49, OOS +0.147 — matching the study's adopted pooled figures (+0.19R,
PF 1.53). The pipeline is faithful.

## Results (managed = ratchet+runner, net of costs)

| sym | n | med cost R | screen | exp 1× | exp 1.5× | exp 2× | PF 1× | OOS exp | yearly |
|---|---|---|---|---|---|---|---|---|---|
| USDCHF | 208 | 0.156 | PASS | +0.063 | +0.015 | −0.033 | 1.15 | +0.256 | mixed (−2024, −2025) |
| NZDUSD | 177 | 0.199 | PASS | +0.097 | +0.033 | −0.031 | 1.27 | +0.241 | mixed (−2026) |
| EURJPY | 182 | 0.115 | PASS | +0.048 | +0.016 | −0.016 | 1.11 | +0.046 | thin |
| EURGBP | 202 | 0.261 | **FAIL** | +0.121 | +0.031 | −0.060 | 1.30 | −0.032 | — |
| XAGUSD | 167 | 0.250 | PASS (at limit) | +0.007 | −0.116 | −0.238 | 1.01 | −0.011 | dead |
| **US100** | 236 | 0.055 | PASS | **+0.285** | +0.263 | +0.241 | 1.75 | +0.386 | all 4 years + |
| **ETHUSD** | 235 | 0.118 | PASS | **+0.261** | +0.205 | +0.149 | 1.85 | +0.264 | all 4 years + |
| **XTIUSD** | 238 | 0.098 | PASS | **+0.421** | +0.386 | +0.351 | 2.42 | +0.310 | all 4 years + |

## Read

- **US100, ETHUSD, XTIUSD** clear every adoption criterion the original study
  used: cost screen, positive at 2× spread stress, OOS-consistent
  (train≈test), and positive every calendar year. These are stronger
  per-symbol than most of the incumbent 9.
- **XTIUSD caveat:** its spread was measured at only 2 points in a quiet
  evening session — suspiciously tight. Sensitivity: at a 5-point spread the
  1× expectancy is still ≈ +0.31R, so the verdict is robust to plausible
  mismeasurement, but re-measure during the London/NY overlap before going
  live on it.
- **EURGBP** fails the cost gate outright (0.261R — same failure mode as
  GBPCAD's 0.26 in the original study). **XAGUSD** scrapes the cost gate at
  exactly 0.250 but has no edge (+0.007R, PF 1.01, OOS negative) and
  collapses under stress. **USDCHF / NZDUSD / EURJPY** are cost-viable but
  thin at 1× and negative at 2× — adding them mostly adds variance, not
  expectancy.
- Same model caveats as the parent study: same-bar SL-first pessimistic,
  partials-at-level optimistic, slippage beyond spread not modeled,
  indicative single-session spreads.

## Recommendation (pending owner ratification)

Add **US100, ETHUSD, XTIUSD** to `strategies.silver_bullet.pairs`; reject the
other five. Re-measure XTIUSD spread in liquid hours first. Because the FBS
demo-forward-test of the incumbent 9 started 2026-07-28, tag the additions as
a second cohort in the journal (or hold them to the 2-week checkpoint) so
realized-vs-modeled cost comparison for the original universe stays clean.
