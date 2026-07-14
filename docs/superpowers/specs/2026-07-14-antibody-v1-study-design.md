# Antibody v1 — OHLC anomaly sentinel + counterfactual study (design spec)

**Date:** 2026-07-14 (design approved by user in-session)
**Branch:** `feat/antibody-study`, worktree `/home/kiyingijmc/projects/Titan_antibody`, forked from `342820f` (Plan-07 HEAD incl. all its tooling). Merges into `feat/trade-mgmt-pipeline` ONLY after Plan 07's gate completes and its final review closes.
**Blueprint source:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §10 (Antibody).
**Suite baseline entering:** 377 OK (`.venv` lives ONLY in the main checkout: `/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python`).

## 1. Goal & framing

Antibody is the arsenal's **defensive sentinel**: learn "normal market microbehavior" per symbol, score each bar's abnormality, and — eventually — block new entries during sustained anomalies. This plan delivers the **validated study only** (user decision: study-first): a pure scoring module + a walk-forward counterfactual study answering ONE pre-registered question — *would blocking new entries during ALERT windows have improved SilverBullet's expectancy over 3 years?* Live lockout wiring is a separate follow-up plan, gated on this study's pre-registered criteria.

## 2. Decisions locked during brainstorm (user-approved)

1. **OHLC-only v1.** The 3-yr research CSVs/frozen parquet have NO tick volume (frozen `tick_volume=1` is filler) and NO spread history. v1 uses the four price-geometry features below. Tick-vol z + spread z are the **pre-registered v2 extension** once live journaling accumulates them (B0 tape records ticks; spread arrives with HEARTBEAT). Honest limitation recorded: feed-pathology detection is weaker without spread.
2. **Study first, wire after.** No `src/core`/`src/execution` diffs in this plan. Wiring (ALERT → block entries, config-gated) happens only if the study passes.
3. **Mahalanobis scorer** (deterministic once fit; numpy only — already a dependency; isolation forest would need sklearn = new dep, rejected).
4. **SB trades via `research_run`** (reuse mandate): one pooled run at SB's LIVE config, never a parallel replay implementation.
5. **Compute courtesy:** the study's one heavy replay launches only AFTER the Gyroscope gate's 11 runs finish (gate log: `/home/kiyingijmc/projects/Titan_plan07/data/results/gate_run.log`, detached PID in `gate_run.pid` beside it). Building + unit-testing everything can proceed immediately.

## 3. The scorer (`src/analysis/antibody.py` — pure, stdlib + numpy)

- **Features per H1 bar (4-vector):**
  1. range/ATR z-score (rolling ATR(14) via the existing `src/analysis/atr_simple.last_atr` convention);
  2. |body|/range ratio (0 when range 0);
  3. ATR-normalized gap: |open − prev close| / ATR;
  4. bar-overlap ratio: intersection of [low,high] with prev bar's [low,high] / prev range (0 when prev range 0).
- **SELF-MODEL fit:** feature mean vector + 4×4 covariance over a trailing fit window (regularize: add εI, ε=1e-9, before inversion; refuse to score if covariance is singular after regularization — fail LOUD).
- **Score:** Mahalanobis distance vs the fitted model. **ALERT threshold = q99 of the fit window's own scores** (non-parametric — no χ² assumption).
- **State machine:** `PATROL → ALERT (score > q99 for 2+ consecutive bars) → ALL-CLEAR (score ≤ q99 for 3 consecutive bars) → PATROL`. Deterministic; no wall-clock; no randomness.
- Interface (one object per symbol, mirrors KalmanDrift's shape): `AntibodyScorer(fit_features) → .score(feature_vec) → Reading{score, threshold, state, alert}` plus a pure `compute_features(df) → list[vec]` helper. Exact signatures fixed at plan time.

## 4. The study (`scripts/antibody_study.py` — walk-forward, no lookahead)

- Data: the frozen 9-symbol H1 dataset (`data/lake/frozen/fbs/<SYM>/H1/`, loads via the Lake frozen-glob fallback; 170,856 bars total; provenance sidecar committed).
- **Walk-forward:** fit on trailing ~6,000 H1 bars (≈1 year), score forward one quarter (~1,500 bars), roll, refit — the offline analogue of the brief's quarterly refit. Every scored bar uses only past data.
- **SB trade list:** one pooled `research_run` invocation, all 9 symbols, `--tf H1 --split 0.7`, SB's live config (default min_grade B — NOT the gate's C floor), per-symbol SPREADS costing (spread-mult 1.0). Trades read from the run's `signals.jsonl` + `run.json`.
- **Overlay:** for each SB trade, classify inside-alert if its entry bar timestamp falls within any ALERT window for its symbol (window = first ALERT bar through last bar before ALL-CLEAR). Report expectancy (net R/trade), n, PF for inside vs outside; per-symbol + pooled; plus alert-rate per symbol and pooled; plus a catalogue of the top-10 largest alert episodes (start/end/duration/peak score) for the sanity check.
- Output: a results JSON (study-card, mirroring run-card discipline: git_sha, data sha256s, fit params, thresholds) + printed report. Results land in `data/results/` (gitignored); the results DOC is committed.

## 5. Pre-registered adoption criteria (frozen in the study doc BEFORE the run)

Adopt (→ wiring plan) only if ALL of:
1. Pooled alert rate **< 2%** of bars (brief's rarity bound).
2. **n ≥ 30** SB trades entered inside alert windows (else: "insufficient sample — no adoption, record only").
3. SB expectancy inside alerts is **negative** AND at least **0.15 R/trade worse** than outside-alert expectancy.

Descriptive (non-gating): top-10 episode catalogue reads as real events (flash moves, holes), not artifacts. Same falsification discipline as the Gyroscope gate: criteria committed first, run second; no post-hoc threshold adjustment.

## 6. Hard rules (inherited)

- FROZEN: `scripts/capture_parity_golden.py`, `tests/backtest/fixtures/*`, `tests/unit/test_signal_parity.py`. Parity green at every task gate.
- Zero diffs under `src/core`/`src/execution` (this plan is additive: `src/analysis`, `scripts`, `tests`, `docs`).
- Validated math imported, never duplicated. NEVER stage: `data/specs.json`, `data/history` (symlink), user's bridge files. Stdlib unittest; full suite green per task; commits end `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. No remote, never push, never touch `main`.
- **Do not commit anything to `feat/trade-mgmt-pipeline` while the Gyroscope gate runs** (mid-gate git_sha drift corrupts run-card provenance).

## 7. Task sketch (for writing-plans)

1. `AntibodyScorer` + `compute_features` + synthetic-data unit tests (planted single-bar anomaly → ALERT after 2 bars; benign vol expansion → alert rate stays ~1%; determinism pin; singular-covariance loud failure).
2. Walk-forward study CLI + small-fixture tests (window roll arithmetic; overlay classification; study-card schema).
3. Pre-registered adoption doc (`docs/research/2026-07-14-antibody-study.md`) — committed BEFORE the run.
4. Run the study (SB pooled replay AFTER the gate finishes) + results doc + verdict vs the frozen criteria.

Execution: superpowers:writing-plans → superpowers:subagent-driven-development, same reviewer discipline as Plan 07 (sonnet implementers + reviewers, fix loops to Approved, opus final review, ledger entries in `.superpowers/sdd/progress.md`).
