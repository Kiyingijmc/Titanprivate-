# 02 — Risk Management & Signal Lifecycle / Operating Modes

## PART A — Risk & money management (Topic 2)

The risk manager is a mandatory pipeline stage in every mode. A manually confirmed trade still gets sized, capped, and circuit-checked. No bypass path exists in the codebase.

### A1. Position sizing (universal, asset-agnostic)

```
risk_amount   = equity × risk_pct_per_trade          (default 0.5%, per-child configurable, hard cap 1%)
stop_ticks    = stop_distance_price / tick_size
value_per_lot = tick_value × stop_ticks               (in account currency — broker adapter provides tick_value already converted)
lots_raw      = risk_amount / value_per_lot
lots          = clamp(round_to_lot_step(lots_raw), min_lot, max_lot_child, max_lot_broker)
```

- Works identically for EURUSD, XAUUSD, NAS100, BTCUSD — no pip math anywhere.
- If `lots < broker min_lot` → signal rejected with reason `POSITION_TOO_SMALL` (never round up — rounding up silently doubles risk on small accounts).
- Volatility targeting overlay (optional, on for T3): scale risk_pct by (target_vol / realized_vol) with bounds [0.5×, 1.5×].

### A2. Exposure limits (checked in order, first failure rejects)

| Limit | Default | Notes |
|---|---|---|
| Per-trade risk | 0.5% equity | hard cap 1.0% |
| Per-instrument open risk | 1.5% | all children combined |
| Per-child open risk | 2.0% | across its instruments |
| Per-asset-class open risk | 4.0% | fx / metals / indices / crypto |
| Per-correlation-group risk | 4.0% | see A3 |
| Account total open risk | 8.0% | sum of all live risk-to-stop |
| Max positions | 12 | sanity backstop |

"Open risk" = distance to current stop × size, i.e. what you actually lose if every stop hits now. Positions moved to breakeven free up budget automatically — a nice emergent property.

### A3. Correlation awareness

- Static correlation groups v1 (config-defined): `usd_bloc` (EURUSD, GBPUSD, AUDUSD…), `risk_on` (indices, AUD, NZD), `safe_haven` (JPY, CHF, gold), `crypto`.
- Signed exposure: long EURUSD + long gold + long NAS100 all count against the short-dollar/risk-on budget.
- v2: rolling 60-day return correlation matrix computed in the feature store; dynamic clustering replaces static groups; alert when static and dynamic groups diverge.

### A4. Circuit breakers (state machine, auto-triggered, Telegram-notified)

| Breaker | Trigger (defaults) | Action | Reset |
|---|---|---|---|
| Daily loss | −2.0% equity from day start | no new signals until next trading day | automatic |
| Weekly loss | −5.0% | flat-only mode; existing positions managed to exit | manual ack via Telegram |
| Loss streak (child) | 6 consecutive losses | that child → paused, flagged for review | manual |
| Drawdown (account) | −12% from HWM | everything → manual mode + risk_pct halved | manual |
| Anomaly | loss velocity > 3σ of backtest expectation | global pause + alert | manual |
| Data integrity | stale feed > 2× candle period | no new entries; exits still allowed | automatic on feed recovery |

Design point: breakers **restrict new risk, never block exits**. The kill path (flatten everything) is always available and is the only operation exempt from every check.

### A5. Stop philosophy

- Every position has a broker-side hard stop from the moment of fill (server-side, survives bot crash). Trailing/managed exits adjust it — never remove it.
- Family defaults: Trend = wide initial (1.5–2.5 ATR) + trail after +1R; MeanRev = tight (1.2–1.5 ATR) + fixed TP + time-stop.
- Weekend rule (config): reduce/flatten CFDs before Friday close (gap risk), leave crypto (24/7) untouched.

---

## PART B — Signal lifecycle & the three modes (Topic 3)

### B1. The signal object (schema v1)

```json
{
  "signal_id": "uuid",
  "child_id": "meanrev.asian_bb_v1",
  "instrument": "EURUSD",            // canonical name; adapter translates
  "direction": "long",
  "intent_type": "LIMIT_AT",         // BREAKOUT_AT | LIMIT_AT | IMMEDIATE
  "level": 1.08420,                  // null for IMMEDIATE
  "urgency": "passive",              // passive | normal | urgent → execution behavior
  "valid_until": "2026-07-17T06:00:00Z",   // session-derived, never 'forever'
  "risk": { "stop_price": 1.08290, "tp_prices": [1.08560], "time_stop_bars": 16 },
  "snapshot": {                      // frozen 'why' — audit + confirmation UI + learning loop
    "regime": "RANGING", "regime_conf": 0.81,
    "features": { "BB_lower": 1.08425, "ATR14": 0.00108, "RSI2": 4.1,
                  "spread_now": 0.00006, "spread_session_norm": 0.00007 }
  },
  "state": "GENERATED"
}
```

### B2. State machine

```
GENERATED → RISK_APPROVED → ROUTED ─┬→ (auto)   EXECUTING → WORKING/FILLED
                                    ├→ (hybrid) AWAITING_CONFIRM → CONFIRMED → EXECUTING
                                    │                            └→ REJECTED_BY_HUMAN
                                    └→ (manual) AWAITING_CONFIRM (no timeout-execute possible)
Any state → EXPIRED (valid_until passed) | INVALIDATED (thesis died) | REJECTED_BY_RISK
FILLED → MANAGED → CLOSED (all transitions persisted to the event log)
```

Every transition is an immutable event row. The event log IS the source of truth; in-memory state is a projection of it (crash recovery = replay).

### B3. The three modes, precisely

| | Full auto | Hybrid | Manual |
|---|---|---|---|
| Who decides | bot | bot proposes, human can veto | human must approve |
| Timeout behavior | n/a | configurable per child: `execute` (default for trend children — signal quality already regime-gated) or `skip` (default for meanrev) | always `skip` |
| Timeout length | n/a | e.g. 10 min or 25% of validity window, whichever is shorter | until valid_until |
| Passive limits | placed immediately | placed immediately, cancelled on veto ("confirm-while-resting") | placed only after approval |
| Breakout stops | placed immediately | placed after timeout/confirm | placed after approval |
| Exits & stop management | ALWAYS automatic in every mode | ← | ← |

The last row is a deliberate safety decision: humans confirm **entries**; the bot always manages **exits**. A human who is asleep must never be the reason a stop didn't trail or a time-stop didn't fire.

### B4. Mode assignment & hot switching

- Mode is a per-child config key: `children.meanrev.asian_bb_v1.mode = hybrid`.
- Runtime switch via GUI/Telegram (`/mode meanrev.asian_bb_v1 auto`) → config event on the bus → router updates instantly. Signals already AWAITING_CONFIRM keep their original mode contract (no rug-pulls mid-decision).
- Global overrides: `/pause all`, breaker-forced manual mode (A4) — overrides stack, most restrictive wins.

### B5. Confirmation store (shared by GUI + Telegram)

- Single table of pending confirmations keyed by signal_id, with resolved_by (gui|telegram|timeout), resolved_at.
- Both interfaces subscribe to it. Approve on Telegram → GUI card resolves live, and vice versa. Double-resolution is impossible (atomic compare-and-set on state).
- Confirmation card content comes entirely from the frozen snapshot — zero recomputation: instrument, direction, level, size (already risk-computed), stop/TP, the 'why' features, spread status, and remaining validity countdown.

### B6. Position management lifecycle

After FILL, ownership transfers to the child's `manage_position()` evaluated on its timeframe events: breakeven moves, ATR trails, partial TPs, time-stops. Manual close from GUI/Telegram is always allowed and logs `closed_by=human`. The learning loop later compares human-closed vs bot-closed outcomes — data on whether interventions help or hurt.
