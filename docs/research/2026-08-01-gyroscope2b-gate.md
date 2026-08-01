# Gyroscope v2b — fresh pre-registered gate with the ratified calibration metric

**Date:** 2026-08-01 · **Status:** PRE-REGISTERED (committed before the run; one pass;
NO-GO a valid outcome) · **Owner ratification:** 2026-08-01, in-session — the owner chose
disposition option 2 of `2026-08-01-gyroscope2-gate-results.md` ("ratify the corrected
calibration metric and run the fresh gate").

## What changes vs the v2 gate — and what does not

**Only criterion 7 changes.** The v2 flip-rate sub-metric (≤25% direction flips between
consecutive same-symbol signals) was mis-specified: with independent drift episodes a
median ~5 days apart, ~50% flips is the expected signature of episode independence, and a
low flip rate is produced by serial same-direction re-firing — the exact v1 pathology
(11h re-fires, audit F1/F3). The corrected criterion measures episodicity directly:

> **7 (calibration, ratified):** pooled signal rate ≤ 2.0/day across the 6 symbols,
> **and** median gap between consecutive same-symbol signals ≥ 48 h.
> Flip-rate is still *reported*, non-binding.

**Frozen, byte-identical to `2026-08-01-gyroscope2-gate.md`:** all strategy/filter
parameters (`sprt_on=innovation, z_confirm=1.0, α=0.05, β=0.20, δ=0.40, warmup 200,
q_atr_frac 0.05, r_frac 1.0, nis_window 50, nis_persist 10, k_sl 3.0, sl_atr_floor 0.8,
rr_target 2.0, reentry_lockout 12, max_bars_in_trade 48`), the 6-symbol universe, data
files, spreads/commission, managed-exit accounting, split 70/30, criteria 1–6, sweep set,
bootstrap spec, and the all-criteria pass rule.

## Transparency note

The v2 run's data already exists and the registrant has seen it; under the ratified
metric that run read 1.03 signals/day and 118 h median gap. This registration is
therefore not blind. Its legitimacy rests on (a) the owner ratifying the metric before it
is scored, (b) the metric being justified by mechanism (episode independence), not by the
observed value, and (c) every other criterion and parameter being frozen at the v2
values. The gate still executes as a fresh single pass and its run card is the record.

**Verdict rule:** all 7 → GO — propose to the owner a demo-status canary (which requires,
before any enablement: live TradeManager wiring of the 48-bar time-stop, wiring
`context['spread']` for the live spread gate, and a `per_strategy_min_grade` entry). Any
failure → NO-GO, recorded, no re-tune.
