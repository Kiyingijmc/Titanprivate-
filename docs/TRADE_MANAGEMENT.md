# Titan v14.4 — Signal Grading & Trade Management Pipeline

This documents the full lifecycle of a trade, the v14.4 repairs that made the
in-trade management engine actually work end-to-end, and the knobs that
control it.

> **DEPLOYMENT NOTE:** v14.4 changed `mql5_bridge/Experts/Titan_Gateway.mq5`
> (partial close, STOP orders, MODIFY-ack guard). The EA must be **recompiled
> in MetaEditor on the Windows/MT5 side** and reattached before the Python
> changes are fully effective. Without the recompile, everything still runs,
> but partial closes fall back to being ignored by the old EA.

## Lifecycle of a trade

1. **Signal generation** — on each M5 candle close, `SystemController._run_strategies`
   enriches data (`SMCAnalyzer`), derives HTF bias (`BiasEngine` on H1), and asks
   each enabled strategy (`silver_bullet`, `unicorn`, `ict_ote`, `crt`) for a
   decision `{signal, type, price, sl, tp}`. Non-CRT signals against HTF bias
   are discarded.
2. **Grading** — `SignalGrader` scores every surviving signal 0–100:
   | Factor | Max | Notes |
   |---|---|---|
   | HTF bias alignment | 30 | aligned 30 / neutral 10 / counter 0 |
   | Risk:Reward | 20 | ≥3R 20 / ≥2R 15 / ≥1.5R 8 |
   | Displacement | 20 | signal-candle body vs ATR |
   | PD array | 15 | buy in DISCOUNT / sell in PREMIUM |
   | Killzone | 15 | London 02–05, NY AM 07–11, NY PM 13–16 (NY time) |

   Grades: **A++ ≥90, A+ ≥80, A ≥70, B ≥55, C below**. Every signal (taken or
   skipped) is journaled to the audit log with its factor breakdown. Only
   grades ≥ `signal_grading.min_grade` execute. A degenerate signal
   (entry == SL) grades C unconditionally.
3. **Sizing & guards** — `RiskManager.calculate_lot_size` (broker-spec driven,
   fails safe without specs), `ExposureManager` (max positions, per-symbol
   duplicates, currency saturation, correlation), daily drawdown circuit
   breaker (3% vs **today's** starting equity — re-anchored at the 23:45
   Kampala report, not the boot balance).
4. **Execution** — reliable REQ/REP handshake to the EA. Order types: `MARKET`,
   `LIMIT`, and (new in v14.4) `STOP` pending orders. LIMIT orders within
   0.02% of market are converted to MARKET. On success the controller stores
   the full context (entry/SL/TP/lots/grade) and journals it when the EA's
   `EXECUTION:OPENED` arrives; LIMIT placements register as `PENDING`, market
   fills as `ACTIVE`. Stale pending orders are auto-cancelled (1h SilverBullet
   / 2h others).
5. **In-trade management** — on every tick, `TradeManager.sync_positions` runs
   the Fibonacci ratchet against progress toward the original TP:
   | Stage | Progress | Action |
   |---|---|---|
   | L1 | 38.2% | SL → break-even + 3-pip buffer |
   | L2 | 61.8% | SL → L1 price, bank 30% (partial close) |
   | L3 | 88.6% | SL → L2 price, bank 50% |
   | Runner (opt-in) | ≥ L3 | TP removed at L3, tail trails behind price by ~0.27×range |

   Partial volumes are dust-guarded (remainder always ≥ broker min lot, else
   full close). An emergency kill-switch flattens any position whose floating
   loss exceeds 1.5× the per-trade risk budget.
6. **Close & record** — `EXECUTION:CLOSED` archives the trade to
   `trade_history` with entry/SL/TP/lots/grade/PnL. Ghost trades closed
   externally are reconciled every 60s. Daily performance report goes to
   Telegram at 23:45 Kampala time.

## v14.4 pipeline repairs (why management works now)

Before v14.4 the ratchet **never fired in live trading** due to four
independent breaks:

1. `MODIFY` was pushed on the fire-and-forget socket with `action="MODIFY"`,
   which the pre-v14.4 EA's command handler didn't understand — silently
   dropped. v14.4.1 keeps the fire-and-forget PUSH route but adds a real
   `MODIFY` branch to the EA's `HandleCommand`, with the outcome verified
   from the next HEARTBEAT's SL/TP rather than a synchronous ack. (An interim
   v14.4 attempt to route MODIFY over the REQ handshake socket was reverted:
   a slow SLTP round-trip left the EA's REP socket wedged — it never serviced
   another request until the EA was reattached. The REQ socket is reserved
   for order entry.)
2. The EA had no partial-close handler. `CLOSE_PARTIAL` is now translated to
   `CLOSE_POS` with an explicit `volume`, and the EA honours it.
3. Trades were registered with `entry=0, tp=0` (the EA's OPENED message has no
   prices), so the ratchet skipped every trade. Registration now uses the
   metadata captured at send time, and a heartbeat backfill
   (`StateManager.backfill_position_state`) fills anything still missing and
   flips `PENDING → ACTIVE` on limit fills.
4. Stale-limit cleanup registered everything `ACTIVE` (so the `PENDING` query
   matched nothing) and sent cancels as `action="TRADE"` (dropped by the EA).
   Both fixed.

## Configuration (config/config.yaml)

```yaml
signal_grading:
  enabled: true       # false = grade + journal but never block
  min_grade: "B"      # quality floor: C | B | A | A+ | A++

trade_management:
  runner:
    enabled: false    # opt-in: let the last tail run without a TP after L3
```

Raise `min_grade` to `"A"` to trade only high-confluence setups once the
grade distribution in the audit log has been reviewed (query:
`SELECT message FROM audit_log WHERE event_type='SIGNAL'`).

**Runner mode ships OFF.** It changes the live edge (SilverBullet was
validated with fixed 2R TPs); enable only after a backtest shows the trailing
tail beats the fixed target on your data.

## Record keeping

- `data/db/trade_state.db` → `trade_history`: full journal per closed ticket
  (entry, SL, TP, lots, grade, PnL, strategy, close time).
- `data/db/titan_core.db` → `audit_log`: every event including every graded
  signal with factor breakdown (JSON payload).
- Export the journal to CSV:
  `.venv/bin/python scripts/export_journal.py --out data/journal.csv`

## Strategy ↔ market-condition mapping

Four strategies exist for distinct conditions; enable per `config.yaml`
(`strategies.<name>.enabled` + `pairs`):

- **SilverBullet** — FVG displacement, **H1, 1.0-ATR stop, runner on, 9-symbol
  cost-viable universe** (v14.4.2 validated: +0.19R/trade net, PF 1.53, OOS-
  consistent — `docs/research/2026-07-11-silverbullet-h1-stop-study.md`). The
  old M5/0.2-ATR configuration nets ≈ −4.3R/trade after costs; never revert.
- **UnicornModel** — breaker + FVG + liquidity sweep (trending, post-sweep).
- **ICT_OTE** — 0.705 fib retracement (established trends).
- **CRT** — previous-day high/low fade (ranging/mean-reversion; exempt from
  the HTF-bias filter, graded lower by design when counter-trend).

They stay disabled deliberately: enabling is a research decision, not a
config toggle — backtest first (`tests/backtest/backtest_engine.py`).
