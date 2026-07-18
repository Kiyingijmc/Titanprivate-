# 03 — Execution Intelligence & Broker Auto-Discovery / Multi-Asset

## PART A — Execution intelligence (Topic 4)

Strategies emit intents; this layer chooses mechanisms. It is the only module that knows order types exist.

### A1. Intent → mechanism decision matrix

| Intent | Default mechanism | Adaptive fallback (from broker profile) |
|---|---|---|
| BREAKOUT_AT | broker-side stop order at level | synthetic stop (bot watches price, fires market order) if broker's measured stop-slippage > threshold or stop_level restriction blocks placement |
| LIMIT_AT (passive) | broker-side limit at level | limit at level ± offset if fill-rate stats show consistent near-misses |
| IMMEDIATE | market order with max-deviation cap | delay-and-retry up to N seconds if spread gate fails |

### A2. Spread gate (runs before every entry order)

```
gate_ratio = spread_now / spread_session_norm(instrument, session)   # both from feature store
if gate_ratio > 3.0        → HOLD (retry loop until valid_until, then EXPIRED)
if spread_now > k × expected_edge_ticks (per-child k, default 0.25) → REJECT_COST
```

The second line is the per-trade version of the viability gate: a meanrev child whose TP is 12 ticks refuses to pay a 4-tick spread.

### A3. Pending-order lifecycle manager

Every working order carries its parent signal's contract:
1. **Expiry:** broker-side expiration set to valid_until when supported; bot-side timer as belt-and-braces (brokers differ — discovery records which expiry modes the broker honors).
2. **Invalidation watch:** on each feature event, the owning child's `invalidation()` runs (regime flipped? band migrated past level? opposing signal?). True → cancel + event `INVALIDATED(reason)`.
3. **Repricing:** reversion limits trail their band with a min-reprice-distance (avoid modify-spam; brokers rate-limit modifies — discovery measures tolerance).
4. **OCO straddles:** implemented bot-side (many brokers lack native OCO): fill event on one leg → immediate cancel of twin; cancel-failure → alert + auto-flatten the unwanted fill if twin also fills within grace window (the "double-fill" hazard, handled explicitly).
5. **Partial fills:** remainder policy per urgency: passive → leave working; urgent → convert remainder to market if spread gate passes, else cancel.

### A4. Execution telemetry (feeds the learning loop)

Per order: mechanism, requested vs filled price (signed slippage in ticks), latency ms, requotes/rejections, spread at send, session. Aggregated per (broker, instrument, mechanism, session) into the **execution profile** — consumed by A1 fallbacks and by the backtester's cost model. This is how the bot "learns its broker."

---

## PART B — Broker intelligence & multi-asset (Topic 5)

### B1. Discovery pass (on connect + every 24h + on spec-change suspicion)

From MT5 account_info() / symbols_get() / symbol_info():
- Account: leverage, currency, netting|hedging, margin call & stop-out levels, trade-allowed flags.
- Per symbol: contract_size, volume_min/max/step, tick_size, tick_value (account-currency), digits, spread, stops_level, freeze_level, swap_long/short + swap rollover day (triple-swap Wednesday for fx), margin_initial, filling modes (FOK/IOC/Return), expiration modes, sessions/quote hours.
- Persisted as a versioned **broker profile document**; diffs between versions raise a `SPEC_CHANGED` event (brokers change specs silently — the bot notices).

### B2. Canonical instrument registry + resolution

- Registry of canonical instruments (`EUR/USD`, `XAU/USD`, `NAS100`, `BTC/USD`…) with match patterns.
- Resolution order: exact match → strip known suffixes (`.m`, `.raw`, `.pro`, `_ecn`…) → alias table (`GOLD→XAU/USD`, `US100/USTEC/NAS100`) → currency-pair regex. Confidence < 1.0 → surfaced in GUI for one-click confirmation, then cached. Unresolvable symbols are still discovered + tagged, tradable by explicitly-configured children only.

### B3. Capability tagging (the multi-asset unlock)

Each discovered symbol gets tags computed from specs + sampled data:

```
asset_class: fx_major | fx_cross | fx_exotic | metal | index_cfd | commodity | crypto | stock_cfd
session: fx_24_5 | exchange_hours | crypto_24_7
vol_tier: low | mid | high | extreme          (ATR% of price, rolling percentile)
spread_ratio: tight | normal | wide            (median spread / ATR)
liquidity_proxy: from spread stability + quote frequency
```

Children declare `tags_required`; the intersection auto-enables instruments. New symbol appears at the broker → discovered → tagged → eligible children pick it up (subject to a config allowlist mode for the cautious: `auto_enable: propose` = suggest in GUI instead of enabling silently — recommended default).

### B4. Viability gating (strategy × instrument × broker)

```
cost_per_round_trip = median_spread + commission_ticks + expected_slippage(mechanism)
edge_estimate       = child's backtested avg win distance on this instrument tier
viability           = edge_estimate / cost_per_round_trip
viability < 4       → child auto-disabled on that instrument at this broker (event + GUI badge)
```

Re-evaluated continuously as spread sampling updates. This single rule prevents the classic failure of running a scalpy strategy on a marked-up broker.

### B5. Broker adapter interface (swap-ready)

```python
class BrokerAdapter(ABC):
    def discover(self) -> BrokerProfile
    def resolve(self, canonical: str) -> BrokerSymbol
    def stream(self, symbols, timeframes) -> AsyncIterator[MarketEvent]
    def place(self, order: CanonicalOrder) -> OrderResult      # handles lot rounding,
    def modify(self, ...) / cancel(...) / flatten_all()        # stop-level compliance,
    def positions(self) / working_orders(self) / account(self) # filling-mode choice
```

Everything above this interface speaks canonical language. v1 implementation: MT5. Later: OANDA REST/stream, ccxt for native crypto — no changes above the line.

### B6. Multi-asset correctness checklist (the hardcoding killers)

- [ ] No "pip" outside the display layer; core uses ticks + ATR multiples.
- [ ] Sizing purely from tick_value (B1) — works for gold/indices/crypto unchanged.
- [ ] Per-instrument calendars drive session children; exchange-hours instruments get open/close/gap handling; crypto children handle weekends existing.
- [ ] Netting vs hedging accounts handled in the adapter (opposing child positions on a netting account are netted with bookkeeping preserved per child tranche).
- [ ] Swap-aware: carry cost per night in the position P&L projection; triple-swap day known; long-hold children (T3) include swap in edge math.
- [ ] Account-currency conversion uses live rates from the feed, never hardcoded USD.
