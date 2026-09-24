# Risk and position-management corrections

Implemented against the existing working tree; unrelated edits were preserved.

## Changes

- Ratchets persist desired SL, TP and remaining volume atomically before dispatch. Stages advance only when broker state satisfies the intent. Lost sends, broker rejection, partial execution and Python restart retain the same target for reconciliation.
- Partial events immediately update the controller's position volume. L2 closes 30% of its starting volume; L3 closes 50% of the remaining volume, subject to broker lot steps.
- Targeted partials use the new `CLOSE_TO_VOLUME` command. The gateway calculates the difference from live position volume and persists an in-flight guard in MT5 terminal globals. A previous accepted order must become terminal and its execution must be visible in position volume before another close can be sent. Definitive rejection permits retry; ambiguous results remain guarded.
- Runner updates always request TP zero, including when the stop is already sufficiently tight. The gateway also prevents stale modifications from loosening an existing stop.
- Sizing always includes configured commission. Sizing, partial calculations and gateway volume snapshots preserve the broker's volume-step precision.
- Exposure and arbiter count checks include pending and in-flight orders. Duplicate tickets appearing in both broker and database snapshots count once.
- Short ratchets and trails use ask. The gateway streams ask-only changes. Missing ask suppresses price-based short management; emergency and time exits remain available.
- Pending-order expiry and news sweeps use a monotonic 60-second deadline instead of a narrow wall-clock window.
- Managed stop notifications wait for confirmation. Partial profit notifications require an observed exit deal.

## Compatibility and rollout

Compile and attach the updated `mql5_bridge/Experts/Titan_Gateway.mq5` before enabling the updated Python process. Its heartbeat advertises `mgmt_protocol: 2`. Python refuses targeted partials through an older gateway and retains the intent for later reconciliation. The database adds a nullable `management_intent` column automatically.

Old records that already advanced their ratchet optimistically have missing stops repaired. An old outstanding partial request without a durable volume target cannot safely be reconstructed: it is logged for broker reconciliation and further partial progression remains blocked. No live database records were rewritten by this task.

An ambiguous broker close response with neither a known order nor a conclusive later transaction remains guarded. Inspect the broker's order/deal history before resolving such an outcome; clearing an unresolved in-flight guard could duplicate a close. This follows the distinction between acceptance and execution in the [MQL5 OrderSend documentation](https://www.mql5.com/en/docs/trading/ordersend).

## Validation

Final targeted run: **375 tests passed** (72.989 seconds). Whitespace validation passed with CRLF-aware Git settings.

Regression coverage includes rejected/lost sends, restart recovery, partial fills, lost deal events, stale position volume, stale runner TP, short bid/ask differences, commission-dominated stops, fractional volume steps, committed-book counting, cleanup scheduling and protocol compatibility.

`test_gateway_close_guard.py` executes the actual MQL retry-guard helpers through a C++ harness with stubbed MT5 state. It covers active orders, unknown outcomes, missing history, delayed position updates, IOC partial fills and rejection. This is not a full EA compile.

MetaEditor/MT5 is unavailable in this workspace. Full gateway compilation and a demo-account lifecycle check remain deployment validation: trigger L1/L2/L3, reject a modification, disconnect/reconnect Python, verify a partial is never repeated, and verify TP remains zero while the runner trails. No live trades or deployment were performed.
