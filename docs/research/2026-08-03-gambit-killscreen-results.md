# Gambit Phase-1 kill-screen results — Judas & Reprise

**Date:** 2026-08-03 (run 2026-08-02 ~23:00 EAT)
**Pre-registration:** spec `docs/superpowers/specs/2026-08-02-gambit-m5-playbook-design.md` §6;
runbook `docs/research/2026-08-02-gambit-runbook.md` (incl. the gate-input filters
paragraph, committed before these verdicts were read).
**One-pass rule applies: these are single-run verdicts, no re-tune.**

## Provenance

- Collection: `scripts/poc_gambit.py --arms` at harness commit `15fb8a1`
  (post dedup-parity fix), 3y M5, 6 symbols. Log: `data/results/gambit/collect.log`.
- Evaluation: `scripts/gambit_gate.py --phase kill` at commit `ba20e52`
  (gate-input filters: universe = US30/US100/XAUUSD/BTCUSD, arms informational;
  live-cost-floor filter `risk >= 4×(spread+commission)` in price units).
- Exit model: MANAGED (v14.4 ratchet+runner replay, session-capped).
  Suite state at evaluation: `Ran 1041 tests / OK`.

## Verdicts

### Gambit-J (Judas sweep-reversal) — **INSUFFICIENT-N**

```json
{"n": 69, "exit_model": "managed", "verdict": "INSUFFICIENT-N",
 "arms_excluded": {"n": 28, "per_sym": {"ETHUSD": 18, "XTIUSD": 10}},
 "floor_excluded": 3}
```

69 filled gate-universe trades over 3 years vs the pre-registered floor of 150.
The setup as specified (strict sweep of the pre-session range + displacement
back inside + H1-bias agreement + FVG limit fill inside the session window)
does not generate enough fills to power the test on this data. Per the
wave2-triage doctrine this is a recorded non-verdict, not a falsification —
but under one-pass there is no re-tune to raise N. Diagnostic color (from the
Task-8 review instrumentation, US30 tail): the detection funnel is not the
bottleneck alone — limit fills are (2 intents → 0 fills on that sample; entry
at the FVG edge of the displacement candle rarely retraces within TTL after a
genuine sweep-reversal).

### Gambit-R (SilverBullet-M5 Reprise) — **FAIL**

```json
{"n": 525, "exit_model": "managed",
 "mean": 0.0355, "ci_lo": -0.0462, "ci_hi": 0.1190,
 "syms_pos": 4, "syms_total": 4, "median_cost": 0.0785,
 "verdict": "FAIL",
 "arms_excluded": {"n": 294, "per_sym": {"ETHUSD": 236, "XTIUSD": 58}},
 "floor_excluded": 66}
```

Failed criterion: bootstrap 95% CI on per-trade net must exclude 0 upward;
`ci_lo = −0.046R` straddles it. The other two kill criteria passed: 4/4
symbols positive, median round-trip cost 0.078R (≤ 0.25R — **the habitat fix
worked**: the cost problem that killed the original M5 SilverBullet at
−1.3R…−4.3R net is gone). Mean +0.036R at n=525 is a real but statistically
unresolvable edge on this sample; the pre-registered screen requires the CI
to clear zero, it does not, so **NO-GO** is recorded. No re-tune.

## Interpretation vs the design's control structure

The spec set Reprise as Judas's mechanism-vs-habitat control. Outcome: the
habitat relocation (high-vol universe + structural stops + session caps)
solved the *cost* side decisively (0.078R median vs "hopeless" on FX M5) but
the remaining gross edge at M5, after the exit engine, is too thin to clear a
95% CI at 3 years of data. Judas's doctrine could not even be powered. The
graveyard base rate (≈1 survivor in 9) holds: 0 of 2 setups advance.

## Disposition

- Neither setup is enabled. `gambit.enabled: false` and both
  `setups.*.enabled: false` remain; manifest stays `status: research`.
- The chassis, `flat_at_ny` plumbing, harness, and gate evaluator remain on
  the tree as reusable infrastructure (a third setup — e.g. ORB after Bell's
  M15 blockers clear — is a new detector class + config block + its own
  pre-registered gate).
- Phase 2/3 of the runbook are moot for these two setups.
- Artifacts committed: `data/results/gambit/trades_judas.csv` (n=100 raw),
  `trades_reprise.csv` (n=885 raw), `collect.log` (force-added; data/ is
  gitignored, matching the plan07 artifact convention).
