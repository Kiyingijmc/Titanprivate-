# Experimental M15 structure management

Implemented as an opt-in alternative to the Fibonacci ratchet. Live configuration has not been changed. See [example configuration](../../config/examples/structure-management.yaml) and [initial diagnostic](../research/2026-09-22-structure-exits.md).

## Rules

“Start at 50%” is interpreted as reaching halfway from actual entry to the original take-profit, **not** automatically closing half the position. For entry 100 and original TP 110, the first partial becomes eligible at 105. Short progress uses ask; long progress uses bid.

The first partial closes a fraction of the current position:

| Context | Fraction |
|---|---:|
| ATR(14) exceeds 1.5 times the median of the preceding 20 ATR readings, or recent directional efficiency is zero/negative | 50% |
| Directional efficiency is at least 0.55, without the volatility condition above | 25% |
| Otherwise | 35% |

Efficiency is the signed net change divided by total absolute change over six completed M15 close-to-close changes, oriented to the trade direction. Volatility takes precedence over trend strength. These thresholds are hypotheses, not optimized estimates.

The second partial closes 25% of the remaining volume once price reaches the later of 75% of original target distance or 0.75 M15 ATR beyond the first trigger. There are no repeated partial stages. Fractions are rounded down to the broker volume step. If closing would violate minimum volume or leave dust, that stage skips the partial and preserves the runner.

After the first stage is broker-confirmed, buy stops follow the latest confirmed higher swing low; sell stops follow the latest confirmed lower swing high. A swing requires two completed M15 candles on each side. This means confirmation arrives 30 minutes after the pivot candle closes. The pivot must form after the trade is first observed by this manager. Reversal pivots and pre-entry structure do not move the stop.

The buffer is the largest of 0.15 M15 ATR, 1.5 current spreads, or two broker ticks. Sell swing highs are translated from bid into ask space before adding the buffer. Stops must improve existing protection, remain behind the executable quote, and be at least one tick beyond entry. Prices are normalized to broker ticks.

The original TP is removed only when a qualifying profitable structural stop is proposed in the same modification. Without one, the original TP stays. A broker rejection leaves the existing SL/TP in place; the durable intent remains pending for reconciliation. No fixed-distance trailing or forced break-even is applied by this profile.

This gives a strong trend more room, but can surrender more profit before a swing confirms. Banking the first partial does not guarantee that the whole trade finishes profitable. Fees and slippage can also make a price-level break-even stop a net loss.

## Data and execution

M15 bars are assembled from three unique, completed M5 bars. Forming M5/M15 bars are excluded, including warmup-history tails. At least 35 valid completed M15 bars are needed for ATR context. Context more than 30 minutes behind the tick is rejected. Missing context leaves current protection intact and does not fall back to the legacy ratchet.

Candle collection and structural management continue while PAUSED or EMERGENCY; entry generation remains ACTIVE-only. Emergency and configured time exits retain precedence. Bad M15 data does not suppress those exits or pending-intent reconciliation.

The profile and its settings are stored in SQLite per ticket. New configured-strategy orders registered after manager startup are eligible; pre-existing, adopted, progressed, or already-managed tickets retain legacy rules. Changing settings or disabling new enrollment does not change a persisted structural trade. Restarts recover that profile and its pending intent.

Partial requests store a target remaining volume before dispatch. Retries cannot recalculate a larger close because volatility changed. Local stages advance only after broker position snapshots confirm protection and volume. Requires the existing gateway management protocol 2 (`CLOSE_TO_VOLUME`). Server-side stop/freeze restrictions and execution latency still require broker/demo validation.

## Evaluation and configuration

The example is not automatically loaded and defaults to `enabled: false`. Merge its `structure` section under the existing `trade_management` configuration when conducting a demo evaluation; do not replace other management settings. Strategy names are exact names; defaults are SilverBullet and Gyroscope. Other strategies need separate validation, especially calendar/session exits. No symbol names, pip assumptions, or asset-specific price distances are built into this policy; valid broker tick/volume specifications and history are required.

Run the reproducible exit-only diagnostic:

```sh
.venv/bin/python scripts/structure_exit_study.py --quick --out data/research/structure-demo
```

Omit `--quick` for complete local M5 files. Each destination must be new. This uses the legacy H1 SilverBullet collector to isolate exits; it does not validate every current strategy or broker instrument. The initial three-instrument sample is small and mixed, so the new model is not approved as a universal profitability improvement.
