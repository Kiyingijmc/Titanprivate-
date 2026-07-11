# Titan v15 Program Roadmap — Sanitize → Trading OS → Backend → Novel Arsenal

> **For agentic workers:** This is the PROGRAM roadmap, not an executable plan. Execute the
> numbered sub-plans in order; each sub-plan is (or will be) a full bite-sized plan in
> `docs/superpowers/plans/`. Only Plan 01 exists in detail today — later sub-plans are
> written when their predecessor completes, because their exact content depends on
> predecessor outcomes (kernel interfaces, gate results).

**Goal:** Transform Titan from a 4-strategy SMC monolith into the Trading OS platform
hosting SilverBullet plus the 11 novel strategies, per the three blueprints of 2026-07-12.

**Architecture:** Three blueprint documents govern this program:
- `docs/research/2026-07-12-novel-arsenal-brainstorm.md` (Phase I — the 11 strategies)
- `docs/research/2026-07-12-trading-os-blueprint.md` (Phase II — kernel: FeatureBus, registry, arbiter)
- `docs/research/2026-07-12-backend-infrastructure-blueprint.md` (Phase III — backend: bus, lake, control plane, ops)

**Tech Stack:** Python 3.11/asyncio, SQLite WAL, Parquet/pyarrow, FastAPI, stdlib unittest, ZMQ bridge (live), systemd.

## Global Constraints

- **Approved-strategy policy:** SilverBullet (H1, v14.4.2 config) is the only strategy that
  trades live today. All 11 novel strategies join the arsenal as plugins with
  `status: research`; flipping any to `demo`/`live` requires its pre-registered gate to
  pass (Phase I §14.7 pattern). Gates can NO-GO; a NO-GO'd plugin stays in the repo,
  disabled, with its result recorded in `docs/research/`.
- **Sanitization policy:** delete unapproved strategy models (Unicorn, ICT_OTE, CRT),
  NO-GO'd research rigs (OTE canonical, MTF-PB v1/v2, trend-H4), and the CLAUDE.md dead-code
  list. KEEP: everything SilverBullet consumes (SMCAnalyzer, market_structure, liquidity,
  bias_engine, FVG columns), `poc_sb_stops.py` + SB tests (validated study), signal grader,
  and all `docs/research/` result records (history is never deleted).
- Tests: stdlib unittest only (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`). No pytest.
- No new dependencies without asking (exceptions pre-approved by blueprints: `pyarrow`,
  `fastapi`, `uvicorn`, `pydantic` — introduced only in the sub-plan that needs them).
- Work on feature branches; `main` holds the inherited baseline. Frequent small commits.
- Live-loop determinism: single asyncio loop, single writer; resources pure; no wall-clock
  TTLs on the hot path (Phase II §4.2).
- The full unit suite must pass at the end of every task of every sub-plan.

---

## Sub-plan sequence

| # | Plan | Delivers | Depends on | Blueprint § | Est. |
|---|------|----------|-----------|-------------|------|
| **01** | **Sanitization** (detailed — `2026-07-12-plan-01-sanitization.md`) | SB-only codebase, dead code gone, suite green, CLAUDE.md updated | — | user directive | 0.5–1 d |
| 02 | Backend B0 — Foundations | typed event bus + event journal (golden tape), structured JSON logging, `/healthz`+`/readyz` probe module, systemd unit files (live+demo) | 01 | III §5, §9, §11 | 2–3 d |
| 03 | Kernel v15.0 — FeatureBus | FeatureBus core (DAG, event-keyed cache, metrics counters), `core.*` pack, `smc.*` pack wrapping SMCAnalyzer/BiasEngine; SilverBullet running via adapter; **golden-tape regression: identical signals pre/post** | 02 | II §3–4 | 3–4 d |
| 04 | Kernel v15.1 — Registry + lifecycle | manifests, registry (SQLite), lifecycle FSM, ResourceView grant enforcement, Telegram enable/disable | 03 | II §5–7 | 2–3 d |
| 05 | Kernel v15.2 — Arbiter + Risk extensions | Intent type, dedup/opposition/exposure/correlation-bucket rules, allocator scaffold, drawdown throttle; `_execute_signal` retired | 04 | II §8–9 | 3–4 d |
| 06 | Backend B1+B5 — Lake + research runners | Parquet lake + manifest + import CLI + retention; replay router; backtest/walk-forward CLI on the same kernel | 03 | III §7, B5 | 3–4 d |
| 07 | Arsenal Wave 1 — defense + first alpha | **Antibody** (defense sentinel, ships active as lockout module) + **Gyroscope** (`stat.*` pack: KalmanDrift + SPRT; pre-registered gate doc; backtest via 06). Extensibility acceptance test: zero diffs in `src/core/`+`src/execution/` for Gyroscope | 05, 06 | I §1, §10, §14 | 4–5 d |
| 08 | Arsenal Wave 2 — event/regime engines | **Aftershock** (`physics.*`: event stream + Hawkes) + **Rubicon** (`stat.bocpd_posterior`) + **Rainflow** (physics pack extension). Each: plugin + unit tests + gate doc + backtest | 07 | I §2–4 | 5–7 d |
| 09 | Arsenal Wave 3 — reversion/exhaustion | **Spring** (OU fit) + **Gumbel Fade** (EVT, H4/D1) + **Walclock** (tick-volume channel; doubles as FBS tick-volume audit) | 07 | I §5, §7, §11 | 4–6 d |
| 10 | Arsenal Wave 4 — cross-asset + overlays | **Constellation** (`net.*` pack + barrier scheduling) + **Shannon Gate** (entropy filter) + **Trinity** (HMM allocator overlay, consumes registry weights) | 05, 08 | I §6, §8–9 | 5–7 d |
| 11 | Backend B2–B4 — control plane + config + ops | FastAPI control plane + auth/principals + audit chain; layered config revisions; restic backups + outbox + circuit breakers + runbooks | 04 | III §2.1, §4, §8, §12 | 6–8 d |
| 12 | Backend B6 — cockpit integration | dashboards over metrics/WS per Phase-1 GUI design | 11 | III B6 | per GUI plan |

Sequencing rules:
1. 01 → 02 → 03 are strictly serial (each is the next one's foundation).
2. 06 can run parallel to 04/05 (touches `src/data/` + `src/research/` only).
3. Arsenal waves (07–10) are the priority queue after 05+06; backend 11–12 slots between
   waves per the "kernel work only between research cycles" rule (II §15).
4. Wave composition may change: a gate NO-GO in wave N does not block wave N+1; Trinity
   (10) is last because it allocates across strategies that must exist first.
5. **Before each sub-plan executes, write its detailed plan** (this roadmap's row + the
   blueprint section = its spec) via superpowers:writing-plans, then execute via
   subagent-driven-development or executing-plans.

## Program-level definition of done

- Sanitized: no Unicorn/OTE/CRT/MTF-PB artifacts; CLAUDE.md dead-code section empty.
- Kernel: SilverBullet + 11 plugins registered; golden-tape parity proven at v15.0;
  Gyroscope landed with zero kernel diffs (extensibility test).
- Backend: trader under systemd with watchdog; event journal replayable; backups drilled.
- Arsenal: every plugin has unit tests, a manifest, a pre-registered gate doc, and a
  recorded gate outcome (GO → demo, or NO-GO → documented, disabled).
