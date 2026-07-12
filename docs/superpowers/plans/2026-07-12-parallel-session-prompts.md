# Parallel-Session Prompts — safe to run alongside Plan 01 (feat/v15-sanitize)

Plan 01's tasks are serial on one branch (shared files, a moving test-count baseline, and
git-index races make intra-plan parallelism a net loss). What IS safe to parallelize is
roadmap work that touches no Plan-01 file. Each prompt below is copy-paste for a fresh
Claude Code session in this repo. All three are doc-only or worktree-isolated.

---

## Prompt A — Write Plan 02 (Backend B0 — Foundations) in detail

> Read `docs/superpowers/plans/2026-07-12-titan-v15-program-roadmap.md` (row Plan 02) and
> the spec sections it cites: `docs/research/2026-07-12-backend-infrastructure-blueprint.md`
> §5 (event bus + journal), §9 (systemd deployment), §11 (observability: structured JSON
> logging, /healthz + /readyz probes). Using the superpowers:writing-plans skill, write the
> full bite-sized implementation plan for Plan 02 to
> `docs/superpowers/plans/2026-07-12-plan-02-backend-b0.md`. Constraints: stdlib unittest
> (no pytest); no new dependencies beyond what the blueprint pre-approves; the bus is a NEW
> module `src/core/bus.py` (the old `src/core/event_bus.py` is being deleted by Plan 01 —
> do not reference it); the event journal must be replayable (it becomes the golden tape
> for kernel v15.0); pure planning, DO NOT touch any source file, and do not modify
> anything under `src/`, `tests/`, `scripts/`, `config/`, or `CLAUDE.md` (a sanitization
> plan is executing there in another session). Commit only the new plan file.

Why safe: writes exactly one new file in `docs/superpowers/plans/`.

---

## Prompt B — Draft the Gyroscope pre-registered gate document

> Read `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §1 (Gyroscope) and §14.7
> (validation sequence), plus the gate-format precedent in
> `docs/research/2026-07-11-ote-canonical-results.md` and the shared validation protocol
> ("TVP", §0 of the brainstorm doc). Write the pre-registered gate document for the
> Gyroscope research cycle to `docs/research/2026-07-12-gyroscope-gate.md`, BEFORE any
> backtest exists (that is the point — the gate must be frozen first). It must specify,
> with exact numbers, all criteria already fixed in §14.7: 3-yr H1, 9 live symbols, FBS
> cost model, GO requires pooled net ≥ +0.10R/trade, ≥ 150 trades, ≥ 6/9 symbols
> non-negative, OOS = final 30% chronological and sign-consistent, ±30% sweeps on
> (alpha, beta, delta, q_atr_frac) not flipping the pooled sign, and a mandatory MA-slope
> baseline comparison on identical exits. Also pre-register the parameter defaults from
> §14.5. Doc only — no code. Commit only the new gate doc.

Why safe: one new file in `docs/research/`.

---

## Prompt C — KalmanDrift research spike (worktree-isolated code)

> Using the superpowers:using-git-worktrees skill, create a worktree on a new branch
> `spike/kalman-drift` (based on main). In it, implement `src/analysis/kalman_drift.py`
> per the spec in `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §14.2: a `KalmanDrift` class
> (state [level, velocity], F=[[1,1],[0,1]], H=[1,0], Q scaled to ATR, R from rolling
> return variance) plus twin SPRT accumulators on innovation-whitened returns with
> boundaries A=ln((1-beta)/alpha), B=ln(beta/(1-alpha)), and a rolling-NIS chi-square
> integrity check. TDD with stdlib unittest in `tests/unit/test_kalman_drift.py`, synthetic
> series only (pure noise -> no boundary crossings at ~alpha rate; known constant drift ->
> velocity recovered within tolerance and correct boundary hit; drift-with-break ->
> reverse test fires). Pure math module: numpy+pandas only, no imports from src/ outside
> the new file, no strategy/plugin wiring (that lands with the kernel later). This is a
> spike for early validation of the Phase-I §14.7 step-1 math; it will be re-based onto
> the Trading OS plugin API when kernel v15.3 arrives.

Why safe: worktree + own branch; zero contact with feat/v15-sanitize.

---

## Coordination rules

1. Do not run any of these against branch `feat/v15-sanitize` — Prompts A/B commit doc
   files on a branch of your choosing (e.g. `docs/plan-02`, `docs/gyroscope-gate`) or on
   `feat/v15-sanitize` ONLY AFTER Plan 01's Task 7 completes; Prompt C uses its own
   worktree/branch by construction.
2. Never run two of these prompts in the same session; one session per prompt.
3. Live-bot rule stands: none of these touch the ZMQ ports, so they can run while the bot
   is up, but do not run `scripts/` bridge tools from these sessions.
