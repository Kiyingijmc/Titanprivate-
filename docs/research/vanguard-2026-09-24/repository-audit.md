# B. Repository audit

Static source inspection at `8d6ab8d2863d294125df89243ca2a384c8c815fe`. “Current” below means checked-in source/configuration, not verified running-process or broker state. Line numbers refer to this revision. Older document status labels are not authoritative.

## Architecture map

| Area | Verified implementation | Reuse / VANGUARD consequence |
|---|---|---|
| Runtime | `main.py` bootstraps `src/core/system_controller.py`; controller owns data, strategy routing, risk, execution and reconciliation | Keep one orchestrator and execution path |
| Strategy contract | [BaseStrategy](../../../src/strategies/base_strategy.py), line 18; async `on_new_candle(df, context)` returns a dictionary | Thin VANGUARD adapter; pure research functions should own signal math |
| Registry | [registry.py](../../../src/strategies/registry.py), lines 43, 88, 107: imports manifests, validates feature requirements, activates eligible demo/live configurations; explicit research override exists | Research status plus disabled config; do not mistake manifest status for economic validation |
| Manifests | [manifest.py](../../../src/strategies/manifest.py), line 16 accepts M5/M15/H1; priority and `honors_htf_bias` supported | H4 not currently accepted as a routed strategy timeframe; context horizons can be derived after causal validation |
| Features | [feature_bus.py](../../../src/features/feature_bus.py), resources cached by caller-supplied tokens; [SMC pack](../../../src/features/packs/smc_pack.py) wraps SMC and H1 bias | Reuse cache and dependency mechanism; current controller still explicitly evaluates SMC enrichment even for raw-price strategies |
| Analysis | `atr_simple`, `kalman_drift`, `market_structure`, `ict_structure`, `ict_zones`, `bias_engine`, `signal_grader`, `structure_management`; antibody/Hawkes modules also exist | Reuse ATR and causal resampling patterns; do not assume every analysis module is active alpha |
| Market storage | [data_store.py](../../../src/core/data_store.py), line 23 creates M5 and H1 makers only | Manifest M15 support is not feed support |
| Candles | [candle_maker.py](../../../src/core/candle_maker.py), line 103 uses BID, closes on first tick in next bucket, UTC epoch conversion | Native bars are quote-side-specific, delayed at quiet boundaries, and not a complete tick tape |
| Configuration | [config.yaml](../../../config/config.yaml), [GUI config layer](../../../src/ops/web/config_layer.py), [settings](../../../src/ops/web/settings.py) | Preserve runtime settings conventions; freeze strategy structural/research settings per position |
| Risk | [risk_manager.py](../../../src/risk/risk_manager.py), lines 262, 373, 409: broker-spec volume sizing, daily breaker, costs, hard lot caps, aggregate committed risk | Reuse final sizing and global veto; a requested account-currency budget seam is missing |
| Exposure | [exposure.py](../../../src/risk/exposure.py), lines 31 and 70 onward: aggregate cap, count, same-symbol veto, currency overlap and correlation | Campaigns require a reviewed capability change here as well as in arbiter |
| Correlation | [correlation.py](../../../src/risk/correlation.py): last 100 H1 timestamp rows, pairwise returns correlation, minimum 30 overlaps, hourly wall-clock cache, absolute 0.8 veto | Not signed factor budgeting; missing matrix/symbol passes. Do not advertise as comprehensive portfolio protection |
| Arbiter | [arbiter.py](../../../src/arbiter/arbiter.py), line 80: grade/priority sorting, thesis dedup, same-symbol/direction dedup, opposition, position caps | Reuse deterministic ordering. Resolves per symbol/timeframe invocation, not a cross-market simultaneous opportunity auction |
| Intent | [intent.py](../../../src/arbiter/intent.py), line 18: immutable fields, optional thesis key | No campaign, trade, allocation or durable command identity. Controller currently does not populate strategy-supplied thesis IDs |
| Execution | [bridge_zmq.py](../../../src/execution/bridge_zmq.py), line 83: boolean reliable-send result; [Gateway](../../../mql5_bridge/Experts/Titan_Gateway.mq5), line 124 onward | Entry acknowledgement is insufficient fill/accounting evidence |
| Management | [trade_manager.py](../../../src/execution/trade_manager.py), lines 173–378: emergency guard, time exits, durable intent reconciliation, legacy ratchet or opt-in structure profile, runner trail | Extend policy dispatch here after approval; do not create a competing adaptive manager |
| State | [state_manager.py](../../../src/core/state_manager.py), lines 38, 340, 359: WAL SQLite active/history rows, risk anchor, deal dedup, management profile/intent persistence | Extend existing transactional persistence; current schema is not a campaign event store |
| Research | [kernel_replay.py](../../../src/research/kernel_replay.py), line 66 shares strategy routing but stubs execution; `scripts/research_run.py`, `gyro2_gate.py`, `gambit_gate.py`, SB studies | Useful components, not complete live risk/execution parity |
| Execution simulator | [sb_execution.py](../../../src/research/sb_execution.py), lines 74, 121; [structure_execution.py](../../../src/research/structure_execution.py) | Reuse executable-side/gap sequencing; adapt limitations explicitly rather than declaring exact parity |
| Historical data | [lake.py](../../../src/data/lake.py): validated/quarantined Parquet partitions, manifest and frozen datasets; HTTP exporters/history snapshots | Research lake is explicitly separate from live in-memory storage; no automatic as-observed revision history |
| Observability | [events.py](../../../src/core/events.py), [bus.py](../../../src/core/bus.py), [event_journal.py](../../../src/ops/event_journal.py), JSON logs, equity recorder, Telegram, web views | Reuse structured events, but sampled ticks and possible log drops cannot serve as complete critical replay evidence |
| HTTP broker | `bridge/app/mt5_client.py`, `bridge/app/main.py`, `src/execution/broker/mt5_http.py` | Existing read/data and isolated execution adapter; controller trading remains ZMQ. Do not open a second execution route |
| New runtime skeleton | `tradebot/core/{event_log,projection,recovery,sta,clock}.py`, `tradebot/config/schema.py` | `pyproject.toml` explicitly calls it independent of `src/`; no `tradebot` references found in `src/` or `main.py`. Useful design precedent, not already integrated safety infrastructure |

## Existing strategies and research doctrine

The checked-in manifests/config show SilverBullet H1 enabled/live status, Gyroscope H1 enabled/demo status, Almanac H1 enabled/demo status, MA-slope research/disabled, Gambit research/disabled. This differs from older CLAUDE/arsenal prose. No assertion is made about which process is actually running.

**Gyroscope:** `models/gyroscope.py:21` wraps `analysis/kalman_drift.py:75`. Carried filter, last processed time and cooldown are in-memory per symbol. Historical warmup is replayed, only the newest crossing may signal. Configured v2 uses innovation-SPRT, velocity confirmation, NIS guard, ATR stop floor and spread check. It emits MARKET/SL/TP, not a managed trend campaign. The [v2b report](../2026-08-01-gyroscope2b-gate-results.md) records +0.057R pooled versus [MA slope](../2026-08-01-ma-slope-baseline-gate-results.md) −0.027R under common harness assumptions. This is evidence of incremental value on that experiment, not an independent live replication. The v2b calibration criterion was ratified after the earlier data were seen; the report discloses that fact.

**MA slope:** `models/ma_slope_baseline.py:12` trades changes in the sign of a 24-bar SMA slope with ATR protection. It is an unusually weak whipsaw-prone baseline; beating it does not excuse comparison with stable breakout, normalized momentum and slower trend rules. Its recorded NO-GO remains a result, not something to retune until it passes.

**Almanac:** `models/almanac.py:26` is a calendar canary, uses completed daily ATR derived from H1, records one emitted attempt per month in memory, and uses a distant 10R TP to avoid normal ratchet interference. Weekday rather than exchange-holiday calendar is explicit. Its architecture is reusable; its canary role is not validated investment alpha.

**Gambit:** `models/gambit.py:21` owns sessions, spread/cost floors and one emitted intent per session; `gambit_setups.py` holds pure detectors. Exit sessions use the shared TradeManager hook. Judas had insufficient N and Reprise failed its preregistered confidence-interval gate. This is a good model for isolating acquisition families, not evidence for those setups.

**SilverBullet:** `models/silver_bullet.py:17` implements closed-candle displacement/FVG limits. Current source explicitly warns that execution-sensitive results supersede its earlier profitability claim. The September diagnostics and prospective observation failures must take precedence over old arsenal headlines.

**Other research:** MTF-PB v2 failed; structural exits have mixed initial results; Coil/Rainflow, Anchor, Rubicon, Shannon Gate and Trinity overlap VANGUARD's compression, slower trend, change-point, entropy and allocation ideas at the document level. They are not additional active strategy implementations in `src/strategies/models`. Reuse the research questions/trial history; do not count renamed mechanisms as independent discoveries.

The repository's strongest research norm is preregister → freeze → one pass → record GO/NO-GO/insufficient evidence → do not rescue a failed result by changing the metric. VANGUARD should strengthen this with synchronized portfolio replay and recorded data observability.

## End-to-end trace: Gyroscope

1. **Ingestion:** Gateway sends HISTORY specs/bars and TICK bid/ask. Controller `1561` ingests history and specs; TICK handling `1665` updates quote caches and calls `MultiTimeframeStore.process_tick`.
2. **Candle close:** M5/H1 makers produce windows. Controller routes only matching timeframe/symbol strategies at `_run_strategies`, line `1840`.
3. **Features:** controller line `1851` evaluates SMC enrichment and H1 bias; context includes symbol, bias, liquidity, wall-clock NY string and latest spread. Gyroscope itself uses raw close and ATR, with its own trend estimate. No general M15/H1 feature bundle is handed to it.
4. **Strategy:** newest H1 data update the carried Kalman/SPRT; a crossing passing cooldown, volatility and spread guards returns a MARKET dictionary with stop and TP.
5. **Intent and grading:** controller lines `1939–1984` applies manifest bias policy and grader, then constructs `Intent`. Gyroscope bypasses HTF direction filtering via manifest but the sizing function still receives `bias_str`; its NEUTRAL half-risk behavior is a separate effect.
6. **Arbitration:** `resolve()` sorts and applies dedup/opposition/count limits against committed positions. **Actual order is arbiter before final sizing/global exposure checks**, contrary to the brainstorm's diagram.
7. **Final risk/execution:** `_execute_signal`, line `957`, checks news, optionally refreshes broker-universe specs, normalizes prices, calculates lots, checks exposure and aggregate risk including pending orders/reservations, and sends through ZMQ REQ.
8. **Registration:** success stores symbol-keyed `pending_signal_meta` and reservation. EXECUTION OPENED uses metadata to register ACTIVE MARKET or PENDING LIMIT/STOP. HEARTBEAT corrects market fill price once and backfills observed positions. An accepted pending order is not a filled position.
9. **Management:** on ticks, `TradeManager.sync_positions` applies emergency/time exits before normal policy. For ordinary trades it requires nonzero initial entry and TP, restores durable requests, and proposes monotonic SL/target-volume commands. `_dispatch_mgmt_command`, line `1487`, sends management over PUSH. Broker observations confirm effects.
10. **Exit:** Gateway `OnTradeTransaction`, line `435`, reports exit deals/remaining volume. Controller records partials without archiving a live remainder; full closure archives PnL plus prior realized partials and emits notifications.
11. **Reconciliation:** `_perform_reconciliation`, line `667`, compares broker positions and pending orders with SQLite, with grace handling. This repairs some missing observations but is not reconstruction of Gyroscope filter state, campaign state or every missed deal.
12. **Research/telemetry:** core bus feeds JSONL/structured logs, strategy/intent/close events and equity reporting. Kernel replay exercises strategy routing but captures rather than executes `_execute_signal`; separate historical resolvers estimate outcomes. Therefore signal parity is established more narrowly than whole-trade parity.

## Material gaps and exact implications

| Gap | Evidence / implication | Required before |
|---|---|---|
| Incomplete/stale/duplicate warmup bars | Gateway `CopyRates(...,0,...)` at line 271 includes current bar; setter at `candle_maker.py:81` copies all records without close cutoff, sort or dedup. Historical/realtime overlap can enter the window | Any causal VANGUARD performance claim |
| Out-of-order ticks | `process_tick` updates current candle when bucket is not greater; no explicit older-bucket rejection | Faithful live bar policy |
| H4 bucketing | minute-only flooring in `CandleMaker` is not a generic 240-minute calendar algorithm | H4 live context unless built by validated closed-bar resampling |
| M15 feed gap | Store contains only M5/H1; Gateway history mapping has no explicit M15 branch | M15 routing; existing `m15_context` is a management helper, not full routing |
| Same-symbol veto twice | Arbiter default cap 1 AND unconditional ExposureManager duplicate veto | Any simultaneous addition |
| Identity loss | Intent thesis not forwarded by controller; entry payload lacks durable command key; metadata/reservations keyed by symbol | Reliable campaign entries, restart retries |
| Ambiguous sends | boolean send timeout; reservation only after success; time-based expiry releases unresolved reservations | Fail-safe pending-send accounting |
| Risk semantics | `_row_risk` uses `abs(entry-sl)`; stop at entry yields zero sentinel/unknown; profitable stop still consumes positive cap | Any claimed stop-funded risk release |
| No-TP management | `TradeManager:218` skips ordinary management when initial TP is zero; structure policy also expects original TP | True no-TP V1 live management; far TP is not equivalent |
| Fill semantics | market backfill is corrected once; pending LIMIT/STOP comments assume fill at intended price | Gap/slippage-aware trade R and sizing attribution |
| Partial entry handling | Gateway successful entry branch handles DONE/PLACED, not DONE_PARTIAL explicitly | Venues/fill policies with partial entry fills |
| Limited replay tape | sampled tick events contain bid; complete arrival/ask/critical state history not guaranteed | Exact execution-state reconstruction |
| Reservation/management durability | partial target persistence exists; in-flight entry budget and trend state do not have equivalent durability | Stateful campaign restart |
| Missing exit accounting | Controller `_perform_reconciliation:667` archives an absent nonpending ticket with `pnl=0.0`; this establishes disappearance, not recovered final deal PnL | Realized-profit recycling, campaign loss limits and trustworthy recovery attribution |
| Portfolio model limits | absolute correlation, direction-free currency overlap, no full stressed factor/margin budget in this path | Native portfolio-aware risk claims |

These are static findings and scope constraints, not changes authorized by this report. In particular, old comments claiming broker pending stops are absent are outdated: current Gateway heartbeat includes ORDER_SL and the controller includes unknown broker pending rows in aggregate risk.

## Reuse decision

Keep BaseStrategy, registry, FeatureBus, controller, arbiter, RiskManager, TradeManager, StateManager, broker boundary, lake and telemetry. Add only (after approval) pure VANGUARD policies, a versioned per-position management profile, typed allocation/identity metadata, and durable reservation/state extensions. Do not add an independent `adaptive_trade_manager`, broker client, event bus, optimizer or risk database.

Focused verification and its limits are recorded in [research-protocol.md](research-protocol.md). No live bridge was queried or commanded during this audit.
