# Owner Ratification Record — Human Decision Sheet (pass8-synthesis.md §5)

**Date:** 2026-07-18. **Decided by:** project owner, ratifying the board's recommendations wholesale ("approved all your recommendations"). Where the board offered no recommendation, the item remains OPEN and is marked so below.

| Item | Decision | Status |
|---|---|---|
| **H1** — F-002 account posture + netting default | Posture **A**: seek a hedging account where the choice exists. Shipped behavior: auto-engage **degraded mode B** (one child per instrument, reduce-only guard) on netting accounts with one-time acknowledgment. Synthetic tranches (C) rejected for v1. | **DECIDED** — F-002 RESOLVED |
| **H2** — F-016 platform topology | **(b) Linux core + Windows MT5 bridge over WireGuard** (Titan `bridge/` prior art). Infra seat's cost objection noted and accepted (~$40–70/mo, two boxes). | **DECIDED** — F-016 RESOLVED |
| **H3** — Sentinel auto-flatten arming | Ship **OFF** (alert-only + operator-commanded flatten). Revisit after one clean quarter of Sentinel drills and ≥1 real deadman event handled manually. | **DECIDED** (arming question intentionally stays on this sheet for that future revisit) |
| **H4** — `accounting.tax_lot_policy` + balance-op pre-registration | **OPEN** — the board deliberately recommends nothing ("ask your accountant"); a blanket approval cannot ratify it. Exports continue to refuse to run until set. Blocks tax exports only. | **OPEN** |
| **H5** — Quiet-hours confirmation default | Ratified: per-child `{deliver: silent, timeout_action: unchanged}` with mandatory eyes-open notice at child setup. | **DECIDED** |
| **H6** — Graduation thresholds (CAL-09) | Ratified: ≥30 human decisions, \|decision-value\| < 0.03 R/trade; CAL-09 CI-derived per-child n ∈ [20, 60] replaces the flat 30 when computed. | **DECIDED** |
| **H7** — CAL-01 viability pair | Ratified: disable < 1.5 / re-enable ≥ 1.8, governing every child (dossier-local pairs superseded per pass8 §1.9). First Threshold-Lab review may move it with a sweep artifact. | **DECIDED** |
| **H8** — CAL-02 gap-k | Ratified: fx major 1.3 · fx cross 1.5 · metal 2.0 · index CFD 3.0 · crypto 1.0/1.5; annual recalibration from lake + live gap tags. | **DECIDED** |
| **H9** — CAL-08 CUSUM parameters | Ratified: κ=0.5, WARN h=2.5, ACTION h=4.0 (sustain 2 blocks), ARL₀ ≥ 40/200, ARL₁ ≤ 8; per-child simulation calibration before any Stage-L arming regardless. | **DECIDED** |
| **H10** — Threshold Lab cadence | Ratified: threshold changes rate-limited to one per item per quarter absent a CRITICAL, each citing a sweep artifact. | **DECIDED** |
| **H11** — Broker tier | Ratified: **RAW-spread + commission, hedging-mode** (consistent with H1), demo first, and the same demo broker carries through G2/G3 (switching brokers between gates invalidates execution-profile continuity, pass4 §4.9-6). Consequence accepted: STD-only pricing would have shrunk the roster to ≈ T1 + TC-2 + M2. | **DECIDED** |

## Consequences

- **Findings close-out update:** F-002 and F-016 move from OPEN-FOR-HUMAN to **RESOLVED (ratified per this record)** — all 42 summit findings are now closed.
- **Decision register update:** the 7 OPEN-FOR-HUMAN entries in pass8 §2 that map to H1–H3/H5–H11 are now FINAL; only the H4-linked entry remains open.
- **Nothing blocks the build through M6** except real-world account actions: opening the hedging RAW-tier demo (M6) and live (M7) accounts are operator errands, now with their parameters fixed.
- The pending real-world errand list: (1) choose/provision the Linux VPS + Windows MT5 box per H2; (2) open the RAW hedging demo account per H11/H1; (3) ask an accountant about H4 before the first tax export.
