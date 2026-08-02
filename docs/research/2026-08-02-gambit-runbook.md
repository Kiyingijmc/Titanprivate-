# Gambit research runbook (Phase 1-3)

Pre-registered: spec 2026-08-02 §6. One-pass rule — any failure is a recorded
NO-GO, no re-tune. Baselines: MaSlopeBaseline; Reprise is Judas's
mechanism-vs-habitat control.

## Phase 1 — collection + kill-screen (per setup)

**Step 1 (DONE):** Collection harness completed 2026-08-02. Full run produced:
  - `data/results/gambit/trades_judas.csv` (n=100)
  - `data/results/gambit/trades_reprise.csv` (n=885)
  - Collection log: `data/results/gambit/collect.log`
  - Fixed harness commit: 15fb8a1

Proceed with kill-screen verdicts:

1. `.venv/bin/python scripts/gambit_gate.py --phase kill --setup judas`
2. `.venv/bin/python scripts/gambit_gate.py --phase kill --setup reprise`
3. Record both verdicts in docs/research/2026-08-XX-gambit-killscreen.md
   (numbers, INSUFFICIENT-N included) and add a Gambit row to
   docs/strategies/ARSENAL.md. Commit CSVs + doc.

## Phase 2 — full gate (only for setups whose kill-screen PASSED)

Sweeps (+/-30% one-at-a-time, 4 runs — pre-registered parameter pairs):
  - judas: body_min_atr 0.56/1.04, sweep_ttl_bars 8/16 (12*0.7 rounded to 8;
           12*1.3 rounded to 16)
  - reprise: body_min_atr 0.56/1.04, stop_buffer_atr 0.14/0.26

Commands:
  `.venv/bin/python scripts/poc_gambit.py --arms --override body_min_atr=0.56` (etc.)

Then: `.venv/bin/python scripts/gambit_gate.py --phase gate --setup judas \
       --sweeps <4 sweep csvs>`

Also run `--exit fixed` — the dual-exit-model gate requires the positive to
hold under BOTH exits. Record GO/NO-GO doc per setup.

## Phase 3 — demo canary (GO setups only)

- Config: gambit.enabled true + <setup>.enabled true; manifest status -> demo;
  min_stop_price/max_spread_price **re-derived against current specs** via
  `scripts/cache_specs.py` (note: US100 row currently absent from bridge specs,
  will be auto-filled on next specs refresh).
- Confirm time_exits.Gambit flat_at_ny row present. Restart per
  demo-forward-test memory (ss -tlnp PID, not pgrep). ~2-week checkpoint.
