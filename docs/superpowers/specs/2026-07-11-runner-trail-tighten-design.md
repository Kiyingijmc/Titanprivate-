# Runner-Trail Tighten (Arm C) — Design

**Date:** 2026-07-11 · **Status:** Approved design, pending implementation
**Depends on:** v14.4.2 validated SilverBullet H1 runner config; rig verdict
`docs/research/2026-07-11-pullback-monetizer-overlay-results.md`

## Problem

The validated runner config gives back open profit on every pullback: the tail
trails a fixed `0.268 × range` behind price. The 3-year overlay study
(`data/history/sb_overlay_H1.log`) showed that **tightening that trail once, when a
pullback gives back ≥ 0.75× the trail distance from the runner high-water mark**, is a
zero-cost Pareto improvement over the live baseline: expectancy +0.109R → +0.130R,
PF 1.26 → 1.32, max DD 24R → 21R, holding out-of-sample and under 1.5× spread. The
study also killed the costlier "bank + re-add" variant (dominated on every cell), so
only this trail-tighten ("arm C") gets built.

## Non-goals

- No bank/re-add, no child tickets, no counter-direction positions (rejected: the
  rig showed arm C dominates arm A everywhere).
- No StateManager schema change, no new bridge command type, no EA change.
- No per-strategy gating (the runner this rides on is already a single global flag).

## Behavior

All logic lives inside the existing runner-trail block in
`TradeManager.sync_positions` (`src/execution/trade_manager.py`, currently lines
135–146), reached only at `r_level ≥ 3` with runner enabled — after every ratchet
stage and both partials, when the core trade is already risk-free.

On each heartbeat, for a runner-phase position:

1. **Update HWM.** `runner_hwm[ticket] = max(prev, curr_price)` for a long,
   `min(prev, curr_price)` for a short. First sight seeds HWM = `curr_price`.
2. `base_trail = range_size × (L3_FIB − L2_FIB) = range_size × 0.268` (unchanged).
3. **Give-back trigger.** If `tighten_on_giveback` is enabled and `ticket` is not yet
   in `tightened`: compute give-back = `hwm − curr_price` (long) / `curr_price − hwm`
   (short); if give-back `≥ giveback_frac × base_trail`, add `ticket` to `tightened`.
   This is one-way (mirrors the rig's DONE state).
4. `trail_dist = range_size × tight_trail_frac` if `ticket in tightened`, else
   `base_trail`.
5. The existing candidate / `tighter` / `MODIFY` logic runs unchanged with that
   `trail_dist`.

**State growth:** `runner_hwm`/`tightened` are not pruned inside `sync_positions`.
The live controller calls `sync_positions` **per-symbol** (only that symbol's
positions), so the passed list is never the full open-ticket universe — pruning
against it would wipe other symbols' runner state every tick and break the one-way
guarantee. Instead the dicts follow the existing `command_cooldowns` precedent: they
grow by at most one entry per ticket ever seen (bounded by lifetime trade count,
harmless since MT5 tickets are never reused) and are cleared on restart.

**Live vs rig detection:** the rig measured give-back from intra-bar highs/lows; live
detection uses discrete heartbeat `curr_price` snapshots — a slightly coarser but
honest analog. The demo-forward-test confirms live behavior before go-live.

## State

In-memory on `TradeManager`, alongside `command_cooldowns` (chosen over SQLite
persistence: the runner phase is short and restarts are rare; a mid-runner restart
merely re-seeds HWM to current price, whose worst case is one extra tighten
opportunity on an already-risk-free trade):

- `self.runner_hwm: dict[int, float]` — ticket → best price in trade direction.
- `self.tightened: set[int]` — tickets whose trail has been tightened (one-way).

## Config

Additive under `trade_management.runner` (defaults baked into `__init__`, so a config
without these keys behaves exactly as today):

- `tighten_on_giveback: false` — master switch. Ships **off**; flipped on for the demo
  run and, after that passes, for live.
- `giveback_frac: 0.75` — retrace fraction of `base_trail` from HWM that triggers.
- `tight_trail_frac: 0.10` — tightened trail distance as a fraction of range.

## Safety

- Executes only at `r_level ≥ 3` with runner on — the trade is already risk-free
  (80% banked, SL at L2). Tightening can only improve the exit; worst case it trails
  out slightly earlier on a deep pullback, which is the give-back being monetized.
- The existing `tighter` guard means a tightened trail only ever moves SL favorably;
  it never loosens a stop.
- The 2s per-ticket cooldown and the emergency risk-guard path are untouched.
- `normalize_price` still snaps the candidate to the broker tick grid.

## Testing

Unit tests (stdlib `unittest`, TDD, new `tests/unit/test_trade_manager_tighten.py`),
each driving `sync_positions` with a fake position list + prices and a stub
StateManager returning `r_level = 3`:

- **Disabled = unchanged:** flag off → trail stays `0.268×range` on every path.
- **Below threshold:** give-back < `0.75×base_trail` → not tightened, trail `0.268`.
- **Trigger:** give-back ≥ `0.75×base_trail` → ticket in `tightened`; emitted MODIFY SL
  reflects the `0.10×range` distance.
- **One-way:** after tightening, a new HWM keeps the trail at `0.10` (never reverts).
- **Short symmetry:** a short runner tightens on an upward give-back, correct HWM
  (`min`) and SL direction.
- **HWM seeding:** first sight seeds HWM = curr_price, give-back 0, no trigger.
- **Pruning:** a ticket absent from the position list is dropped from `runner_hwm` and
  `tightened`.

Then: full unit suite green, and — because this is live-trading code — a
**demo-forward-test** on FBS demo with the flag enabled before go-live (house rule).
