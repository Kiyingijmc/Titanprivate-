# Passive-Entry Layer — design

**Date:** 2026-07-29
**Status:** design approved, implementation plan pending
**Scope:** execution-quality layer for pending-order entries. No new alpha, no strategy file changes.

---

## 1 · Motivation

Cost is the binding constraint on this system, and the repo has the receipts:

- M5 SilverBullet nets **≈ −4.3R/trade after spreads** (`docs/research/2026-07-11-silverbullet-h1-stop-study.md`).
- GBPCAD and XBRUSD are excluded from the live universe purely on spread.
- XTIUSD needed a dedicated liquid-hours spread re-measure before adoption.

SilverBullet already enters on `LIMIT`, so resting orders are the normal state of the book. What does *not*
exist is any management of those orders' **lifecycle** or any measurement of their **fill quality**. This design
adds both, as a reusable layer, without touching strategy logic.

### 1.1 Where the savings actually come from

Working through the mechanics produced one correction worth stating up front.

**"Rest deeper to get a better price" is an alpha claim, not an execution claim.** Pushing the entry deeper into
the FVG forces a choice, and both branches are problems:

- Re-anchor the SL to preserve the validated 1.0-ATR stop distance → the trade is now a *different* setup at a
  *different* level, and needs the full gate treatment as new alpha.
- Leave the SL fixed and move only the entry → the stop distance silently shrinks, which is precisely what made
  M5 cost-dead. `CLAUDE.md` is explicit: *"Do not lower without re-running the cost study."*

The provable execution savings are these three, in descending order of expected value:

**(a) Stop converting limits into market orders.** `src/core/system_controller.py:405` converts a LIMIT to
MARKET when the limit price is within `0.0002 × bid` of the bid. On EURUSD that is a **2-pip band** — a wide net,
and every capture pays the full spread instead of resting. Pure cost, zero alpha content. Expected to be the
largest single win. Its current magnitude is **unmeasurable today** because non-fills are not recorded (see §4.2).

**(b) A dynamic spread gate.** Refuse to place when `spread > max_spread_atr_frac × ATR`. The universe screen
already gates spread *statically, per symbol, on median*; a per-placement gate catches rollover and news
blowouts that a median averages away. Costs trades, saves cost.

**(c) Ask-correct placement.** A BUY LIMIT fills on `ask ≤ price`, so a limit resting at `fvg_top` produces a fill
whose *bid* is `fvg_top − spread`. Titan currently places bid-space prices into an ask-space trigger. This is a
correctness fix, not a discount.

The deeper-resting offset **remains in the design as a knob, pre-registered at `0.0`** — available to a future
gated study, inert on ship. That keeps this work an execution change that can be proven in isolation.

---

## 2 · Prerequisite facts established against the live tree

Verified 2026-07-29 against `main` @ `e3b1975`. Each of these changes what the work costs, so they are recorded
rather than assumed.

| Fact | Location | Consequence |
|---|---|---|
| EA **already sends ask** in every TICK (`{"type":"TICK","s":…,"b":…,"a":…}`) | `mql5_bridge/Experts/Titan_Gateway.mq5:88` | Live spread needs **no EA change**. Python discards `a` today. |
| Python keeps bid only (`live_prices[symbol] = float(msg.get('b', 0))`) | `src/core/system_controller.py:717` region | Add `live_asks`; no protocol change. |
| EA supports `CANCEL` (`TRADE_ACTION_REMOVE` on `req.order`) | `Titan_Gateway.mq5:317-323` | Cancel-replace works with **no MetaEditor recompile**. |
| EA `MODIFY` is `TRADE_ACTION_SLTP` on `req.position` — positions only | `Titan_Gateway.mq5:299-311` | A pending order **cannot** be re-priced in place. Replace = CANCEL + fresh LIMIT. |
| Pending orders are placed GTC (`req.expiration = 0`) | `Titan_Gateway.mq5:137,144` | Python's TTL cleanup is the only expiry. |
| TTL cleanup **hard-deletes** unfilled orders | `src/core/state_manager.py:244` (`delete_order`) | **No record of any non-fill exists.** Live fill rate is currently unknowable. |
| Backtest LIMIT fill is a direction-blind bid-OHLC touch | `tests/backtest/backtest_engine.py:53-59` | Over-fills buy limits by exactly one spread — the marginal region this work operates in. |
| `check_exposure` and Arbiter `max_positions_per_symbol` both count **open positions only** | `system_controller.py:419`; `config/config.yaml:78` | A resting LIMIT is invisible to both count gates. |
| Arbiter thesis key is `symbol:direction:price:sl` | `src/arbiter/intent.py:31` | A re-emitted setup at a *moved* level is a **new** thesis, passes dedup, and **adds** a second order. |
| EA pushes a TICK only when **bid** changes | `Titan_Gateway.mq5:84` | Spread reading can be one tick stale. Acceptable for an ATR-fraction gate; not acceptable as a sole defence. |

---

## 3 · Architecture

Approach chosen: a **separate entry-model layer**. Rejected alternatives:

- *Fold into SilverBullet* — welds execution policy to one strategy, is not reusable, and moves
  `decision['price']`, a recorded field in the kernel-replay parity golden. Invalidating the parity fixture to
  ship an execution change is the wrong trade.
- *Push re-pricing into the EA* (`TRADE_ACTION_MODIFY` on `req.order`) — reacts tick-by-tick, but puts a policy
  we intend to tune repeatedly into MQL5: manual Windows-side recompile per iteration, untestable by the unit
  suite.

### 3.1 Components

**`src/execution/passive_entry.py`** — one pure class, no I/O, no broker, no DB:

```text
PassiveEntryModel.placement(intent, *, bid, ask, atr) -> Placement

Placement = {action: "PLACE" | "SKIP", kind: "LIMIT" | "MARKET", price: float, reason: str}
```

Deterministic function of its arguments. `reason` is a short audit string journaled on **every** call, so a SKIP
is never silent.

**`src/execution/pending_manager.py`**:

```text
PendingOrderManager.sync(pending_rows, *, bid, ask, atr, bias, now) -> list[dict]
```

Returns commands in the same shape `TradeManager.sync_positions` already returns (`CANCEL`, `REPLACE`), so they
ride the existing `SystemController._dispatch_mgmt_command` seam rather than a new path.

### 3.2 Wiring

- `_execute_signal` gains an `atr` kwarg, threaded from `enriched_df.iloc[-1]['ATR']` which `_run_strategies`
  already holds. Default `0.0` means "unknown" and forces full pass-through, so the `__new__`-built legacy
  fixtures keep working untouched.
- Ask captured into `live_asks[symbol]` from the TICK message that already carries it.
- Config block `passive_entry:` ships `enabled: false`. Disabled means **byte-identical placement** — same
  discipline as `risk.drawdown_throttle` and the Arbiter rollout.

No strategy file is modified. `decision['price']` is unchanged, so the kernel-replay parity golden stays valid.

---

## 4 · Order lifecycle

### 4.1 Bounding resting orders per symbol

Nothing today limits how many limits rest on one symbol: both count gates see open positions only, and the
Arbiter's price-keyed thesis lets a re-emitted setup at a moved level add a *second* order. The only bound is the
5% total-risk cap. Tolerable when limits are incidental; not when they are the primary instrument.

**Rule: `max_resting_per_symbol: 1`, and a re-price is a replace, never an add.**

### 4.2 State machine

```text
PLACE ──fill─────────────────> ACTIVE   (existing heartbeat backfill flips PENDING→ACTIVE)
      ├──stop-through void───> CANCEL   (archived VOID)
      ├──bias flip──────────-> CANCEL   (archived VOID)
      ├──level moved────────-> REPLACE  (archived REPLACED)
      └──TTL (existing)─────-> CANCEL   (archived EXPIRED)
```

**Stop-through void** is the rule with real teeth. An unfilled BUY LIMIT whose `initial_sl` has already been
traded through is a setup that has *already failed*, yet today it stays resting for up to 12 bars and can still
fill on a retrace — buying into a broken thesis. Evaluated on bar close against the bar's low/high; costs nothing.

**Bias flip** makes the existing filter symmetric. `_run_strategies` refuses to *create* a signal against HTF
bias but never retracts a resting one. The per-H1-bar cached `BiasEngine` value is already at hand.

**Level drift** (`max_drift_atr`, default generous) is the weakest of the three — the TTL largely covers it — but
it exists so nobody reaches for a shorter TTL to get the same effect.

Terminal rows are archived to `trade_history` with `pnl = 0.0` and a terminal status, **not** left in
`active_orders`. Leaving them would make `get_pending_orders()` count a dead order's risk forever and block every
symbol via the fail-closed book-wide rule — the RS013 failure mode in reverse. This gets its own test.

### 4.3 Re-pricing safely

`REPLACE` is `CANCEL` + a fresh LIMIT (the EA cannot re-price a pending — §2). Two hazards, both handled with
machinery that already exists:

**Socket ordering.** `CANCEL` is fire-and-forget on PUSH; the replacement goes over the REQ handshake. Different
sockets, no ordering guarantee — the replacement can land before the cancel, briefly doubling the position.
*Fix:* **sequence through the heartbeat.** Dispatch the cancel; place the replacement only once the ticket has
disappeared from the heartbeat's `orders` list. This is the pattern `CLAUDE.md` already prescribes for management
commands ("outcomes are verified from HEARTBEAT state"), and on H1 bars the added latency is irrelevant.

**Risk-cap blind spot.** Between cancel and replace the DB row is gone, so `get_pending_orders()` under-reports
and a concurrent signal could slip past the 5% cap. *Fix:* `_reserve_risk(symbol, row_risk)` before the cancel,
released by the replacement's `EXECUTION:OPENED` via the existing `_release_reserved_risk`.
`RESERVED_RISK_TTL_S` already guarantees the reservation cannot leak if the replacement never opens.

Churn is bounded by `min_reprice_atr_frac` (ignore trivial moves) and `max_replaces_per_thesis: 3` (each replace
is a broker round trip plus a REQ handshake). The existing TTL cleanup remains the final backstop.

---

## 5 · Risk, safety, failure modes

Controlling principle: **every unknown fails toward today's behaviour; every unknown touching risk fails closed.**

### 5.1 Pass-through conditions (behave exactly as v14.4.2)

`PassiveEntryModel` returns the intent untouched when `passive_entry.enabled: false`, when `ask` is missing or
`≤ bid`, or when `atr ≤ 0`. Because the EA pushes a TICK only on bid change, a symbol whose ask moved alone
carries a one-tick-stale spread; acceptable for an ATR-fraction gate, but it means the dynamic gate is **additive
to**, never a replacement for, the static per-symbol universe screen, which stays exactly as it is.

### 5.2 Sizing and the cap

With the offset pre-registered at `0.0`, `abs(price − sl)` is unchanged, so `calculate_lot_size` returns an
identical lot and the `$` cap sees identical risk. The layer changes *whether* an order rests and *at what
trigger price* — never how big it is. Should the offset ever be activated by a future study, the SL re-anchors to
preserve the 1.0-ATR distance, so sizing stays invariant by construction. Stated explicitly because
"better fill = free R" — shrinking the stop to bank the improvement — is the tempting wrong turn here and is
forbidden by the stop study.

### 5.3 Failure modes

| Failure | Consequence | Handling |
|---|---|---|
| `CANCEL` lost on PUSH | Order rests; replacement withheld by the heartbeat gate | Retry next bar close; TTL is the final backstop |
| Replacement handshake fails | No resting order for that thesis | Reservation expires via TTL; thesis re-enters normally next bar |
| Fill races the cancel | Order becomes a position mid-replace | Heartbeat `PENDING→ACTIVE` backfill wins; manager sees no pending row and stops; ratchet takes over |
| Spread gate flaps at threshold | Place/skip churn | Gate applies at placement only; `max_replaces_per_thesis` bounds it |
| Ask feed dies entirely | Every placement passes through | Degrades to exactly today's behaviour, plus one Telegram per symbol per session |

The last row is the escape hatch: if the new inputs vanish, Titan is v14.4.2 again — not a bot with a broken new
organ.

### 5.4 Out of scope

No OCO, no ladders, no partial-fill accounting, no EA recompile, no change to `TradeManager`'s ratchet, no change
to `decision['price']`, no change to any strategy file, no change to the static universe screen.

---

## 6 · Measurement and validation

### 6.1 Prerequisite: fix the backtest fill model

`tests/backtest/backtest_engine.py:53-59` tests `b["low"] <= entry <= b["high"]` — **direction-blind**, on
bid-based OHLC. Correct triggers, given bid OHLC and one-way spread `s` **expressed in price units**
(`s = spread_points × tick_size`, since the `SPREADS` table is denominated in price-ticks):

| Order | MT5 trigger | Bid-OHLC test |
|---|---|---|
| SELL LIMIT | `bid ≥ price` | `high >= entry` — unchanged |
| BUY LIMIT | `ask ≤ price` | `low <= entry - s` — **spread haircut** |
| BUY STOP | `ask ≥ price` | `high >= entry - s` — fills *easier* |
| SELL STOP | `bid ≤ price` | `low <= entry` — unchanged |

The asymmetry is the point: today buy limits fill `s` too easily, in exactly the marginal region a passive-entry
policy operates in. Any "beat the spread" result from the uncorrected engine is partly self-confirming.

**Cost side needs no change.** `spread_cost = spread_points * tick_value * lots` (`backtest_engine.py:168`)
charges one crossing regardless of entry type, and that is correct. In bid-space OHLC accounting every trade pays
exactly `s`, whatever the entry type: a long market entry buys at `ask = B + s` while SL/TP resolve against bid; a
long limit at `P` fills at `ask = P` when `bid = P − s`, so its bid-space entry is `s` worse than its nominal
price; a short sells at bid (free at entry) and buys back at `ask` on exit. The apparent "market orders cross
twice" is already absorbed by working in bid space, and charging the entry leg separately would double-count the
same `s` the corrected fill trigger already accounts for. **Only the trigger side changes.**

Separately, the spread tables need the three newest pairs. There are two, and they are duplicated:
`scripts/poc_sb_stops.py:43` (`SPREADS`, imported by `scripts/research_run.py:46` as `FBS_SPREADS` — the
authoritative table for the 3yr study) and `tests/backtest/backtest_engine.py:410` (a copy used only by the legacy
`Backtester.run` path). Neither has `US100`, `ETHUSD`, or `XTIUSD`. The consequences differ: `research_run.py`
in pooled mode **hard-errors** on a symbol absent from `FBS_SPREADS` (`research_run.py:390-393`), so those three
pairs **cannot currently be studied at all**, while `backtest_engine.SPREADS` silently defaults them to 20 ticks.
All three get measured values before any study runs, and the duplication is collapsed to one table.

**Consequence to be stated plainly in the results:** the headline `+0.19R/trade, PF 1.53` for the validated
v14.4.2 config was produced on the over-filling model. Correcting it may move that number, possibly down. Both
arms of the comparison are re-run on the corrected model. If the baseline shifts, that is a finding about the
current live config — not a reason to keep the old model.

### 6.2 Making non-fills visible

Replace the TTL path's hard `delete_order` with an archive to `trade_history` (`pnl = 0.0`, terminal status
`EXPIRED` / `VOID` / `REPLACED`), and add a placement-journal row per `PassiveEntryModel` call carrying intent
price, chosen price, bid, ask, spread, ATR, action, and `reason`. Live fill rate then becomes a query, and every
SKIP is auditable.

### 6.3 The metric

Cost saving is measured **per signal, not per fill** — otherwise the trades we failed to get vanish from the
numerator and adverse selection reads as a win:

```text
saving_R = mean over ALL signals of ( R_passive − R_market_counterfactual )
```

A skipped or expired signal contributes `R_passive = 0` against whatever the market-order arm actually returned.
A policy that dodges losers earns credit; one that dodges winners pays for it.

### 6.4 Pre-registered gate

Fixed before the study runs (Gyroscope-style — see `docs/research/2026-07-14-gyroscope-gate.md`):

1. `saving_R > 0` on the corrected fill model, 3yr H1, all 12 live pairs, both arms re-run.
2. Sign consistent across the same 70/30 chronological split the SilverBullet study used.
3. The passive arm's **count of filled trades** ≥ 60% of the market arm's count of filled trades, over the same
   signal set. Below that we have changed the strategy's frequency, not its cost. (Distinct from *fill rate*,
   which is reported separately under criterion 5.)
4. No individual pair's net R/trade degrades by more than 0.05R.
5. Reported alongside the verdict: fill rate, median spread at placement, and SKIP counts broken out by reason.

**Failing the gate is a legitimate outcome.** The §6.1–6.2 prerequisite fixes and the §4 lifecycle rules land on
their own merits regardless of the verdict, because each closes a real defect: phantom backtest fills,
unrecorded non-fills, unbounded resting orders per symbol, and void setups filling on a retrace.

### 6.5 Test plan (TDD, `tests/unit`, stdlib unittest)

`PassiveEntryModel` and `PendingOrderManager` are pure and get direct table-driven tests. The cases that must
actually bite — per the standing lesson that a green suite hides exactly this class of defect:

- Disabled config produces a **byte-identical** payload to today (parity guard).
- Missing ask, `ask <= bid`, and `atr = 0` each fall through to today's behaviour.
- A stop-through void order is cancelled **and archived**, and `get_pending_orders()` no longer counts its risk —
  asserted on the aggregate, not on the cancel call having been made.
- A replace holds risk across the cancel/place gap: a concurrent signal is capped correctly *while* no pending
  row exists.
- A replacement is not dispatched until the ticket leaves the heartbeat's `orders` list — asserted on what was
  sent, never on elapsed wall-clock time.
- A second resting order on the same symbol is refused.
- Corrected fill model: a bar whose low touches `entry` but not `entry − s` does **not** fill a BUY LIMIT, and
  does fill a SELL LIMIT at the mirrored price.

Verification bar: full unit suite green via
`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.

---

## 7 · Config surface

```yaml
passive_entry:
  enabled: false              # ships OFF; disabled == byte-identical placement
  max_spread_atr_frac: 0.10   # dynamic spread gate (name mirrors gyroscope's knob)
  offset_atr_frac: 0.0        # deeper-resting offset — PRE-REGISTERED AT ZERO, inert on ship
  no_market_conversion: true  # supersedes the 0.0002-of-bid LIMIT->MARKET capture
  max_resting_per_symbol: 1
  max_drift_atr: 3.0
  min_reprice_atr_frac: 0.25
  max_replaces_per_thesis: 3
  cancel_on_bias_flip: true
  cancel_on_stop_through: true
```

`enabled: false` short-circuits **every** sub-knob — none of them has any effect while the layer is disabled, so
the shipped default is one decision, not nine.

`offset_atr_frac` is the only knob whose activation requires a fresh gated study; the rest are execution-quality
settings validated by §6.4. Of those, `max_spread_atr_frac` mirrors gyroscope's existing pre-registered value and
`max_resting_per_symbol`/`max_replaces_per_thesis` are structural bounds. `max_drift_atr: 3.0` and
`min_reprice_atr_frac: 0.25` are **initial values chosen for plausibility, not measured** — they are tuning
surface, and the spec makes no claim about them beyond "does not churn".

---

## 8 · Sequencing

This is more than one mig session's worth of work. It decomposes into four, each independently shippable and
each leaving the tree green:

| # | Session | Delivers | Depends on |
|---|---|---|---|
| 1 | Fill-model correction | §6.1 — direction-aware LIMIT/STOP triggers, explicit `STOP` handling (`resolve_trade` currently resolves any non-`MARKET` cmd with LIMIT semantics, so a future STOP signal would be silently mis-filled), one deduplicated spread table with measured values for US100/ETHUSD/XTIUSD. Re-baseline the v14.4.2 study and report whether `+0.19R` moves. Cost model unchanged. | — |
| 2 | Non-fill observability | §6.2 — archive `EXPIRED`/`VOID`/`REPLACED` instead of hard-delete, plus the placement journal. Answers "how often do our limits fill, and how often do we convert to market?" from live data. | — |
| 3 | Lifecycle rules | §4 — `PendingOrderManager`, `max_resting_per_symbol`, stop-through void, bias-flip cancel, heartbeat-sequenced replace. | 2 (needs archive statuses) |
| 4 | Placement policy + gate | §3, §5, §6.3-6.4 — `PassiveEntryModel`, ask capture, spread gate, `no_market_conversion`, then run the pre-registered study. | 1, 2, 3 |

Sessions 1 and 2 are pure defect fixes and are worth landing whether or not the gate in session 4 passes.
Session 2's live data should run for at least a few sessions of the demo-forward-test before session 4's study,
so the offline fill model can be sanity-checked against observed live fill rates.

---

## 9 · Open questions

None blocking. Two deferred by design:

- Whether `offset_atr_frac` has positive expectancy — a separate pre-registered study, explicitly out of scope.
- Whether a corrected fill model changes the v14.4.2 adoption decision. Session 1 produces the number; the
  interpretation is the owner's call, not this spec's.
