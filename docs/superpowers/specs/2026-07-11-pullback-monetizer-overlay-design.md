# Pullback Monetizer Overlay — Design

**Date:** 2026-07-11 · **Status:** Approved design, pending rig validation
**Depends on:** v14.4.2 validated SilverBullet H1 config (`docs/research/2026-07-11-silverbullet-h1-stop-study.md`)

## Problem

The validated SilverBullet H1 config (+0.109R/trade net, PF 1.26) carries a ~24R max
drawdown, largely from **runner give-back**: the post-88.6% tail trails 0.268×range
behind price, so every pullback surrenders open profit before the trail fires or the
run resumes. The user's intent — "hold the buy day trade but scalp the sells on
pullbacks" — is to monetize those pullbacks instead of donating them.

## Non-goals

- No standalone scalp strategy (M5/M15 scalping is cost-dead on this account:
  best case +0.415R gross → −1.32R net; see the stop study).
- No opposite-direction ("true hedge") tickets. On a netting basis, a counter-scalp
  against an open position is economically identical to a partial close + re-add,
  and the partial-close route reuses existing infrastructure.
- No recovery/martingale behavior of any kind.

## Approach (chosen: A — scale-out/scale-in overlay)

A management overlay on open trades, active **only in the runner phase**
(`r_level ≥ 3`: 80% banked, TP released, trail active, trade risk-free).

- **Bank ("the sell scalp"):** on a pullback signal, partially close fraction `f`
  of the remaining tail near the local high.
- **Re-add:** when resumption is proven, re-enter that size in the trade
  direction and rejoin the trend. (All logic is direction-symmetric; a short
  core banks on upward pullbacks and re-adds short.)
- If the core trails out during the pullback, the bank was simply a better exit —
  **no re-add into a dead trade**.

Alternatives considered: (B) true hedge tickets — same economics, much larger
state/reconciliation surface, rejected; (C) trail tightening only — zero added
cost, retained as a mandatory comparison arm in validation (if C beats A net,
ship C and never build the re-add machinery).

## Strategy-agnostic requirement

The overlay is a property of the **management engine**, not of SilverBullet:

- It keys exclusively off management state (`r_level`, trail level, HWM,
  remaining volume) and market data — never off strategy internals.
- Enablement is **per-strategy opt-in** in `config.yaml` (e.g.
  `trade_management.overlay.enabled_strategies: [silver_bullet]`).
- SilverBullet H1 is the only strategy enabled at launch. Any future strategy
  must pass its own offline rig validation before being added to the list.

## Pullback signal — two candidates, the rig decides

Both computable from data the bot already holds:

1. **Give-back trigger (signal-free):** track the runner-leg high-water mark
   (HWM); bank when price retraces `g` × trail-distance from HWM
   (test `g ∈ {0.5, 0.75}`); re-add when price sets a new HWM.
2. **M15 counter-displacement:** reuse SilverBullet's displacement primitive —
   an opposing displacement candle banks; a with-trend displacement or HWM
   reclaim re-adds.

Adopt whichever validates net of costs; if neither does, the feature dies in
the rig.

## Sizing & caps

- Bank fraction `f` of the remaining tail — test `f ∈ {50%, 100%}`.
- **Hard cap: 2 bank/re-add cycles per trade** — chop cannot bleed spread
  indefinitely. Each cycle costs ≈ one extra round-trip (~0.1–0.25R × f on the
  cost-screened universe).
- Volumes snap to broker `volume_step` via the existing partial-volume logic;
  if the tail is below min lot, the overlay stands down.

## Validation plan (gate — nothing ships without this)

Extend the offline managed-exit replay in `scripts/poc_sb_stops.py`: same 3-year
M5 data, same FBS cost model (`data/specs.json`, spread ×1/×1.5/×2 + $7/lot),
overlay simulated on the exact validated config (H1, ATR10, ratchet+runner,
9-symbol universe).

- **Grid:** signal {give-back, counter-displacement} × f {50%, 100%} × g {0.5, 0.75}.
- **Arms per cell:** Control (current ratchet+runner baseline) · Overlay (A) ·
  Trail-tighten (C: same signal, tighten trail to 0.10×range, no re-add).
- **Rigor:** 70/30 chronological OOS split, per-year breakdown, spread stress.

**Pre-registered success criteria (in order):**

1. Max DD meaningfully below 24R (target ≤ 18R).
2. PF ≥ 1.26.
3. Total net R ≥ 90% of control.
4. Holds OOS and at ×1.5 spread stress.

## Live plumbing (built only after a rig win)

- **State:** per-trade overlay fields — `hwm`, `overlay_state`
  (ARMED / BANKED / DONE), `banked_volume`, `cycles_used` — persisted via
  StateManager so a restart cannot double-bank. HEARTBEAT remains the source of
  truth for actual volume.
- **Bank:** existing partial-close path (`CLOSE_POS` + volume, fire-and-forget
  PUSH, outcome verified from HEARTBEAT). No new EA surface.
- **Re-add:** `TRADE MARKET` over REQ (existing reliable path). On the hedging
  account this creates a **second same-direction ticket**, registered as a
  **child trade** linked to the parent: `initial_entry` = fill price,
  `initial_tp` = parent's runner HWM (real and non-zero — respects the
  no-`tp=0` rule), SL = parent's current trail level. The child is trail-managed
  only (enters at `r_level 3`; no ratchet stages of its own); both tickets trail
  together. **At most one child ticket open at a time**: a second-cycle bank
  closes child volume before parent volume, so cycle 2's re-add never coexists
  with cycle 1's child.
- **Risk/reconciliation:** ExposureManager counts the child against the position
  cap (conservative, no exemption). Reconciliation treats the child like any
  tracked order — ghost-close detection unchanged.
- **Telemetry:** `overlay_bank` / `overlay_readd` Telegram notifications via the
  existing builders; all overlay decisions journaled alongside the
  signal-grading journal.
- **No EA changes** — both commands already exist in `Titan_Gateway.mq5`; no
  Windows recompile required.

## Failure handling

- Re-add REQ timeout → mark cycle DONE, no retry (a missed re-add costs
  opportunity, never money).
- Tail closed externally mid-pullback → reconciliation clears overlay state
  with the trade.
- Specs/volume-step missing for a symbol → overlay stands down (consistent with
  the fail-safe sizing convention).

## Testing

- Unit tests (stdlib unittest, TDD): overlay state machine transitions, cycle
  cap, volume snapping/min-lot stand-down, no-re-add-after-trail-out,
  restart-safe persistence (no double bank), child-trade registration fields.
- Rig replay is the integration test; demo-forward-test before live, per house
  rule.
