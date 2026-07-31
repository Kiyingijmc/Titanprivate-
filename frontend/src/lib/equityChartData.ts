import type { EquitySeries } from "./types";

export interface ChartRow {
  ts: number;
  equity: number | null;
  balance: number | null;
  drawdown: number | null;
}

/**
 * Flattens an API series into Recharts rows.
 *
 * A `null` point from the API is a real data gap. It becomes a row whose values
 * are all `null`, positioned at the midpoint of the corresponding reported gap,
 * so Recharts breaks the line there instead of drawing straight across it. The
 * nth null pairs with the nth entry of `coverage.gaps` — the backend emits them
 * in the same order. A bridged gap would claim the account was flat and healthy
 * through an outage; there was a real ~9-hour one on 2026-07-29.
 */
export function toChartRows(series: EquitySeries): ChartRow[] {
  const rows: ChartRow[] = [];
  let gapIdx = 0;
  for (const p of series.points) {
    if (p === null) {
      const gap = series.coverage.gaps[gapIdx++];
      const ts = gap ? (gap[0] + gap[1]) / 2 : (rows[rows.length - 1]?.ts ?? 0);
      rows.push({ ts, equity: null, balance: null, drawdown: null });
      continue;
    }
    const peak = typeof p.peak === "number" ? p.peak : p.equity;
    rows.push({ ts: p.ts, equity: p.equity, balance: p.balance, drawdown: p.equity - peak });
  }
  return rows;
}
