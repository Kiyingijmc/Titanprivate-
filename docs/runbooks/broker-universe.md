# Broker-wide instrument support

The bot can discover the connected account's broker catalog and resolve a
strategy's symbol list from that catalog at startup. Exact broker names are
retained, including suffixes such as EURUSD.pro; no guessed alias is traded.
Discovery and operational eligibility are separate from strategy enablement
and from evidence that a strategy is profitable on an instrument.

## Strategy scope

| Strategy | Broker-universe behavior |
|---|---|
| SilverBullet | Can evaluate any eligible positive-price instrument supporting LIMIT, SL and TP orders. |
| Gyroscope | Can evaluate eligible positive-price instruments supporting MARKET, SL and TP orders. Its historical trend-universe validation does not transfer automatically to new assets. |
| Almanac | Still restricted to the exact `pairs` list and buy-capable instruments. A month-end index rule is not extended automatically to FX, stocks or commodities. |
| Gambit | Each instrument also needs `symbol_sessions`, a positive `min_stop_price`, and a positive `max_spread_price`. Existing session/setup logic and disabled research status remain. |
| MA-slope baseline | Mechanically supports broker-selected instruments; remains disabled/research according to existing config/manifest. |

The registry still controls research/demo/live status. Universe selection
does not promote a strategy or override `enabled: false`.

## Broker metadata and order checks

The Python HTTP adapter now exposes `list_symbols()`. The Windows bridge's
symbol response carries order-type permissions, minimum stop distances and
freeze levels in addition to trade mode, tick size/value, contract size,
volume limits and currencies. The controller still sends actual orders and
receives live feeds through the existing ZMQ gateway.

For broker-universe symbols, every new order refreshes symbol specifications
and quotes through HTTP. Failed reads, quotes older than 60 seconds or more
than five seconds ahead, unknown permissions, disabled/close-only symbols,
invalid specifications and unsupported order directions/types block entries.
The risk manager must accept the fresh tick specifications before sizing.
Quotes/prices must be finite and positive; negative-price trading is not
supported by the current strategies.

Prices use tick-size normalization. New orders check SL/TP geometry and
broker minimum stop distances. Volume is capped at the broker maximum and
rounded down to its lot step; below-minimum trades are skipped. Existing
daily drawdown, portfolio-risk, news and position-count gates still run.
Broker mode preserves LIMIT orders instead of using the legacy near-price
LIMIT-to-MARKET conversion. This is a behavior difference to account for in
research comparisons.

Explicit news currency mappings take precedence; otherwise exact-name
mappings are derived from broker base/profit currencies. Unknown symbol names
are not silently treated as standard forex pairs. In-trade management still
uses the existing InstrumentHelper break-even convention and broker feedback.

Trade/order permissions can change, hence the refresh before each entry.
See [MetaQuotes symbol permissions](https://www.mql5.com/en/book/automation/symbols/symbols_trade_mode)
and [symbol specifications](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).

## Inventory before activation

Deploy/restart the updated **Windows HTTP bridge** from `bridge/` using its
normal deployment procedure. It must connect to the same account/terminal
as the ZMQ trading gateway. This implementation does not independently
cross-check the identities of those two connections.

An older bridge can still serve existing fixed-pair clients, but its missing
permission metadata makes instruments ineligible for broker-wide selection.
The controller does not invent permissive defaults.

```bash
.venv/bin/python scripts/broker_catalog.py --out data/broker_catalog.json
```

The command loads the existing `.env` connection configuration, reads symbols
and specifications with at most four concurrent requests, and writes an
inventory plus per-strategy eligibility previews and rejection reasons. It
does not enable strategies, subscribe feeds, or place orders. Use a new output
filename for each capture; existing files are not overwritten.

An instrument may be listed by the broker yet lack usable specifications
until the terminal has loaded it. Such instruments appear as unavailable;
the tool does not guess their contract parameters.

## Configuration

`config/examples/broker-universe.yaml` is a ready-to-review override fragment,
**not an automatically loaded configuration**. After inventory verification,
merge the desired entries into `config/overrides.yaml` and restart the bot:

```yaml
broker_universe:
  max_symbols: 128
strategies:
  silver_bullet:
    universe:
      source: broker
      include: ["*"]
      exclude: []
  gyroscope:
    universe:
      source: broker
      include: ["*"]
      exclude: []
```

Include/exclude patterns are case-sensitive shell-style patterns matched to
the **exact broker symbol**; they do not match asset-class labels. For example,
`include: ["EUR*.pro", "US30*"]`. Exclusions win. An empty resolved list means
that strategy trades nothing, never that it can run on every other strategy's
symbols. Omitting `universe` retains the existing configured-pairs behavior.

The default feed budget is 128 total enabled-strategy symbols. Exceeding it
stops boot with an explicit error rather than silently truncating the catalog.
Set a larger budget only after checking feed, memory and broker capacity;
there is no rotating scanner in this change. History responses are drained
while the expanded universe subscribes. Existing per-strategy data validation
continues to require enough bars before signals can form.

Universe discovery is startup-only. Newly listed instruments require a bot
restart to enter the selected universe; entry permissions are refreshed on
every proposed order. Existing open-position management is unchanged.

## Verification and present deployment state

Focused Python tests cover catalog validation, suffix/special-name handling,
eligibility, empty-scope safety, capacity limits, unchanged enablement, news
mapping, fresh permissions/quotes, volume rounding and live-controller gates,
plus existing broker, routing, registry, sizing and exposure behavior.

The actual broker inventory could not be verified in this session: the
sandboxed request failed to connect, and the approved outside-sandbox retry
timed out reading `/symbols`. No inventory report or active configuration
change was produced. The example configuration remains unapplied.

This makes broad instrument support available in source; it does **not**
establish that every strategy should trade every listed instrument. Session
calendars, liquidity, commissions, swaps, exchange-specific constraints,
nonlinear contract valuation and strategy performance still need validation
for new markets. Broker-side margin, session, freeze and aggregate-volume
checks remain authoritative; those constraints are not fully replicated
client-side. The earlier SilverBullet execution-diagnostic losses are not
resolved by expanding its instrument list.
