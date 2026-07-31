import type { EquityPoint, EquitySeries } from "./types";

export interface ChartRow {
  ts: number;
  equity: number | null;
  balance: number | null;
  drawdown: number | null;
}

function nextRealTs(points: (EquityPoint | null)[], from: number): number | null {
  for (let i = from; i < points.length; i++) {
    const p = points[i];
    if (p !== null) return p.ts;
  }
  return null;
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
 *
 * If a null has no matching gap entry (a malformed/short `coverage.gaps` from
 * the backend), we never fall back to `ts: 0` or to reusing the previous row's
 * `ts` — either would land on or near the Unix epoch, or duplicate an x
 * position on top of a real point, and since the chart's X domain is
 * `["dataMin","dataMax"]` over these exact values, either would silently
 * crater the visible time range. Instead we interpolate between the nearest
 * real point before and after it; if there isn't a real point on both sides
 * (e.g. a trailing null with nothing after it), we drop the row rather than
 * guess a position.
 */
export function toChartRows(series: EquitySeries): ChartRow[] {
  const rows: ChartRow[] = [];
  const points = series.points;
  let gapIdx = 0;
  let lastRealTs: number | null = null;

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (p === null) {
      const gap = series.coverage.gaps[gapIdx++];
      let ts: number;
      if (gap) {
        ts = (gap[0] + gap[1]) / 2;
      } else {
        const next = nextRealTs(points, i + 1);
        if (lastRealTs === null || next === null) {
          continue; // no gap entry and no real points on both sides — drop it
        }
        ts = (lastRealTs + next) / 2;
      }
      rows.push({ ts, equity: null, balance: null, drawdown: null });
      continue;
    }
    const peak = typeof p.peak === "number" ? p.peak : p.equity;
    rows.push({ ts: p.ts, equity: p.equity, balance: p.balance, drawdown: p.equity - peak });
    lastRealTs = p.ts;
  }
  return rows;
}
