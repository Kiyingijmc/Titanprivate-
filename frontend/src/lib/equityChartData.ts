import type { EquityPoint, EquitySeries } from "./types";

export interface ChartRow {
  ts: number;
  equity: number | null;
  balance: number | null;
  drawdown: number | null;
  /** High-water mark as REPORTED. Null when the backend omitted it — never
   *  echoes equity, or the high-water line becomes a fabricated flat staircase
   *  sitting exactly on the equity curve. */
  peak: number | null;
}

/**
 * The single admission gate for a number entering the chart.
 *
 * `null` from the API is a declared gap; `undefined` is an ABSENT series key
 * (see `EquityPoint`) and `NaN`/`Infinity` are corrupt. All three must become
 * `null` here rather than being passed through, because every downstream
 * consumer treats "not null" as "safe to do arithmetic with" — and a single
 * `undefined` reaching `Math.min(...)` yields `NaN`, which Recharts renders as
 * an empty chart with no error.
 */
export function finiteOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function nextRealTs(points: (EquityPoint | null)[], from: number): number | null {
  for (let i = from; i < points.length; i++) {
    const p = points[i];
    if (p !== null && finiteOrNull(p.ts) !== null) return p.ts;
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
 *
 * Every emitted value passes `finiteOrNull` first. In particular `drawdown` is
 * computed ONLY when equity and peak are BOTH finite: `null - 10000` coerces to
 * `-10000` in JS, so a bucket that is null for equity but numeric for peak would
 * otherwise fabricate a full-equity drawdown, set the drawdown axis floor by
 * itself, and squash every real drawdown in the window into an invisible sliver
 * — the same Critical the dedicated drawdown axis already fixed once, arriving
 * through a different door.
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
      rows.push({ ts, equity: null, balance: null, drawdown: null, peak: null });
      continue;
    }
    const ts = finiteOrNull(p.ts);
    if (ts === null) continue;   // an unplottable x would crater the dataMin/dataMax domain
    const equity = finiteOrNull(p.equity);
    const balance = finiteOrNull(p.balance);
    const reportedPeak = finiteOrNull(p.peak);
    // `?? equity` keeps drawdown at 0 when peak was not reported; the reported
    // value alone is what leaves this function as `peak`.
    const peakForDrawdown = reportedPeak ?? equity;
    const drawdown = equity !== null && peakForDrawdown !== null ? equity - peakForDrawdown : null;
    rows.push({ ts, equity, balance, drawdown, peak: reportedPeak });
    lastRealTs = ts;
  }
  return rows;
}
