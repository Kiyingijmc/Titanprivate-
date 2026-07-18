# Brainstorm v2 — Expert Board Design Summit (INDEX)

Eight-pass simulated 10-seat board summit over the baseline design docs (`../00-overview.md` … `../05-interfaces-validation-ops-learning.md`). The baseline docs are the **input**; where a pass supersedes a baseline section, the pass file is authoritative (supersessions are recorded in `pass8-synthesis.md` §1). Completed 2026-07-18.

## Read in this order

| Order | File | Pass | One-line summary | ~Words |
|---|---|---|---|---|
| **1st** | `pass8-synthesis.md` | 8 — Synthesis & roadmap | Contradiction sweep (14 rulings), final decision register D-001…D-056, findings close-out, milestones M0–M8, **the human decision sheet (H1–H11)**, abandon criteria, board sign-off | 11,002 |
| 2 | `pass1-audit.md` | 1 — Adversarial audit | Findings register F-001…F-039 over the baseline docs; 5 CRITICAL (orphan fills, netting, viability math, event-log integrity, missing margin limits) | ~7,000 |
| 3 | `pass2-research.md` | 2 — Research & theory | Dossiers for all 8 children (thesis, evidence class, falsification criterion), regime-engine verdicts, 4 new child candidates, portfolio view (effective bets ≈ 2.3, not 8) | ~8,600 |
| 4 | `pass3-systems.md` | 3 — Systems deep design | Event schemas + hash-chained log, five state machines, exactly-once order semantics, feature-DAG rebuild plan, backtester, repo tree w/ Titan BORROW/ADAPT/REBUILD, testing pyramid, CI/CD + security | 11,446 |
| 5 | `pass4-execution.md` | 4 — Execution reality | Broker-behavior stress book (news, rollover, gaps, requotes), SL-in-entry-request ruling, intent→mechanism matrix v2, OCO machine, **the execution simulator spec (resolves F-012)** | 10,023 |
| 6 | `pass5-interfaces.md` | 5 — Interfaces & human factors | Confirmation-card spec (cost-of-being-wrong first; "if you do nothing" line), Hold-as-claim amendment, version-pinned approvals, WS contracts, GUI IA, Titan GUI verdicts | 8,343 |
| 7 | `pass6-accounting.md` | 6 — Money truth | Integer-micro-unit double-entry ledger, two-truths cost decomposition, three-book netting/hedging design, reconciliation tolerances, audit invariants I1–I10, tax exports | 7,772 |
| 8 | `pass7-innovation.md` | 7 — Innovation + calibration | 6 winning innovations (shadow stage, Threshold Lab, health cards, exec A/B, Stop Sentinel, broker scorecard), 4 graveyarded, calibration register CAL-01…23, gate-control suite | 10,808 |

Start with `pass8-synthesis.md` because it is the reconciliation layer: it adjudicated every cross-pass conflict, so any statement elsewhere that conflicts with it is superseded.

## Headline counts

- **Findings:** F-001…F-042 (39 from the audit + 3 born in Pass 7). Final status: **42 RESOLVED, zero open** — F-002 and F-016 were ratified by the owner on 2026-07-18 (see `DECISIONS.md`).
- **Decisions:** D-001…D-056 — all FINAL except the H4-linked tax-lot-policy entry (see `DECISIONS.md`).
- **Human decision sheet:** 11 items (H1–H11) — **10 ratified per the board's recommendations on 2026-07-18 (`DECISIONS.md`); only H4 (tax lot policy — "ask your accountant") remains open**, blocking tax exports only. Sheet of record: `pass8-synthesis.md` §5.
- **Calibration register:** CAL-01…CAL-23 (`pass7-innovation.md` §4 + CAL-23 in `pass8-synthesis.md` §1), every deferred number with a starting hypothesis, procedure, and acceptance band.
- **Milestones:** M0 (trustworthy skeleton) → M8 (roster growth); critical path M0→M1→M2→M3→M4→M6→M7. First admissible G1 verdict is gated behind the gate-control suite ("constitution rule"). First real money is M7 at 25% risk.

## Standing invariants (violating any of these re-opens a finding)

1. Corrected viability math (F-003): tick units + per-trade expectancy; threshold pair CAL-01 (1.5 disable / 1.8 re-enable) — the old "4" is void.
2. Hash-chained, snapshot-backed event log (F-004); core process is the sole DB writer (F-015).
3. Every exposure carries risk-at-stop **and** gap-stressed **and** margin/notional columns (F-005/F-011).
4. SL rides the entry request; attach-on-fill is fallback only. Exits and safety-class stop modifies are never blocked by any gate.
5. No per-trade expectation cones anywhere; block evaluation + CUSUM (CAL-08) is the only live-performance judge (F-013).
6. Backtest evidence is inadmissible without: run-card, both fill models, a balancing SimAccount posting stream, and green gate controls.
7. Shadow/counterfactual numbers are analytics-grade — never mixed with ledger money.
8. No online self-modification of entry logic. The learning loop touches execution, costs, throttles, and on/off states only.

## Abandon criteria (pre-committed, board-unanimous — `pass8-synthesis.md` §6)

(1) T1 **and** TC-2 both fail pre-registered Stage-R at full costs; (2) ≥2 quarters live net-negative with clean books and a confirmed cost model; (3) recurring money-integrity CRITICALs surviving two remediation cycles; (4) the gate-control suite certifies a planted lie twice. Trend droughts, single-family deaths, and in-boundary drawdowns are pre-committed **non**-triggers.
