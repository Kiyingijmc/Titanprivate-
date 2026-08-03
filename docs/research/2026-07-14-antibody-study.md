# Antibody v1 — Pre-Registered Counterfactual Study (adoption criteria frozen)

**Date:** 2026-07-14 (committed BEFORE any run — falsification discipline).
**Spec:** docs/superpowers/specs/2026-07-14-antibody-v1-study-design.md (commit 14064ab, user-approved).
**Plan:** docs/superpowers/plans/2026-07-14-antibody-v1-study.md.
**Branch:** feat/antibody-study (worktree Titan_antibody).

## Question (one, pre-registered)

Over the frozen 3-year 9-symbol H1 dataset, would blocking *new* SilverBullet
entries during Antibody ALERT windows have improved SB's expectancy?

## Method (frozen)

- **Scorer:** `src/analysis/antibody.py`. Four OHLC features per H1 bar
  (ATR(14)-normalized range, body/range, ATR-normalized gap, prev-bar overlap);
  Mahalanobis distance vs a trailing self-model; ALERT threshold = q99 of the
  fit window's own scores. State machine PATROL->ALERT (score>q99 for 2 bars)->
  PATROL (score<=q99 for 3 bars).
- **Walk-forward:** fit on a trailing **6000** H1 bars (~1 yr), score forward
  **1500** bars (~1 quarter), roll and refit. Every scored bar uses only past
  data. State carried across refits. Score regions tile the post-warmup range
  with no overlap (each bar scored once).
- **SB trades:** ONE pooled `research_run`, all 9 symbols, `--tf H1 --split 0.7`,
  **SB live config (min_grade B — the config default, NOT the gate's C floor)**,
  `--spread-mult 1.0`. Only FILLED trades (entered the market) are classified.
- **Overlay:** a trade is *inside-alert* iff its entry-bar timestamp falls within
  any ALERT window for its symbol (window = first ALERT bar through last ALERT
  bar before ALL-CLEAR). Report expectancy (mean net R over TP/SL), n, PF for
  inside vs outside, per-symbol + pooled; alert-rate per-symbol + pooled;
  top-10 alert episodes by peak score.

## Adoption criteria (ALL must hold to advance to a wiring plan)

1. Pooled alert rate **< 2%** of scored bars.
2. **n >= 30** SB trades entered inside alert windows (else: insufficient sample —
   record only, no adoption).
3. Inside-alert expectancy is **negative** AND at least **0.15 R/trade worse**
   than outside-alert expectancy.

Descriptive (non-gating): the top-10 episode catalogue should read as real
events (flash moves, liquidity holes), not artifacts.

**No post-hoc adjustment.** Criteria are frozen here; the run is executed once;
the verdict is mechanical. The values above are the `CRITERIA` dict and the
`DEFAULT_FIT_BARS`/`DEFAULT_STEP_BARS`/`_QUANTILE` constants in the committed
code — the code is the registration.

## Honest limitations (recorded up front)

- **OHLC-only.** The frozen data has no tick volume (`tick_volume=1` filler) and
  no spread history, so feed-pathology detection is weaker than v2 will be. Tick-
  vol z and spread z are the pre-registered v2 extension once live journaling
  accumulates them.
- **q99 is in-sample to each fit window** (non-parametric, no chi-square
  assumption); the ~1% design alert rate is a property of the fit window,
  validated out-of-sample by criterion 1.
- The first ~6000 bars per symbol are unscored (warmup); state resets are avoided
  across quarterly refits (one scorer, state carried).
- **Degeneracy diagnostic:** the fixed ε=1e-9 covariance ridge is scale-blind, so
  a near-constant feature dimension in a real fit window would dominate the
  Mahalanobis distance and distort q99. The study-card records per-symbol
  `fit_diag` (min per-feature variance, worst covariance condition number); the
  results doc sanity-checks that no symbol's windows are pathologically
  ill-conditioned. This does not alter the pre-registered ε — it makes the risk
  empirical, not assumed.
- This is a **counterfactual overlay**, not a live A/B: it measures whether ALERT
  windows coincided with worse SB entries, not the causal effect of blocking.
