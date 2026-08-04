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

### Gate-input filters (pre-registered)

`scripts/gambit_gate.py` applies two filters to every collected CSV (main
df AND each sweep df) BEFORE any criterion runs, both pre-registered here so
they are on record before any kill-screen/gate verdict is read:

- **Gate universe (MF-1).** The kill-screen and gate criteria evaluate only
  `GATE_SYMS = ["US30", "US100", "XAUUSD", "BTCUSD"]` — the 4 symbols the
  spec defines the symbol-majority/breadth checks over. `ETHUSD`/`XTIUSD`
  are collected as an informational arm (mechanism-generality check, not
  part of the verdict) and are reported separately as
  `out["arms_excluded"] = {"n": ..., "per_sym": {...}}`; they never enter
  `evaluate_kill`/`evaluate_gate`.
- **Live-cost floor (MF-2).** A row whose recorded `risk` is below the live
  chassis's cost floor is dropped before evaluation — live would have
  refused to fire it, so it is not a trade the gate should be scored on.
  Floor formula (same specs machinery as `_cost_r`, and definitionally the
  same formula Task 6 used to derive config `min_stop_price`):
  `floor_price = COST_FLOOR_MULT * (SPREADS[sym] * tick_size +
  (COMMISSION_USD_PER_LOT / tick_value) * tick_size)`, with
  `COST_FLOOR_MULT = 4` a pre-registered module constant (never CLI-tunable).
  Dropped-row count is reported as `out["floor_excluded"]`.

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
- Verify FBS server UTC offset seasonally before enabling — live
  `broker_gmt_offset` is fixed at 2 but FBS runs UTC+3 in summer; a wrong
  offset shifts the session windows ~1h off true NY (final-review finding).
