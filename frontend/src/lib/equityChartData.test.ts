import { describe, it, expect } from "vitest";
import { toChartRows } from "./equityChartData";
import type { EquitySeries } from "./types";

const base = (over: Partial<EquitySeries>): EquitySeries => ({
  range: "1d", tier: "coarse", bucket_s: 300, series: ["equity", "balance", "peak"],
  points: [], coverage: { first_sample_ts: 0, n: 0, series_first_ts: {}, gaps: [] }, ...over,
});

describe("toChartRows", () => {
  it("maps points and derives drawdown as equity minus peak", () => {
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80, peak: 100 } as never],
    }));
    expect(rows).toEqual([{ ts: 100, equity: 90, balance: 80, drawdown: -10, peak: 100 }]);
  });

  it("turns a null point into a null-valued row at the gap midpoint, so the line BREAKS", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 10, balance: 9, peak: 10 } as never,
        null,
        { ts: 900, equity: 12, balance: 9, peak: 12 } as never,
      ],
      coverage: { first_sample_ts: 100, n: 2, series_first_ts: {}, gaps: [[100, 900]] },
    }));
    expect(rows).toHaveLength(3);
    expect(rows[1]).toEqual({ ts: 500, equity: null, balance: null, drawdown: null, peak: null });
  });

  it("pairs the nth null with the nth reported gap", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 0, equity: 1, balance: 1, peak: 1 } as never, null,
        { ts: 400, equity: 1, balance: 1, peak: 1 } as never, null,
        { ts: 1000, equity: 1, balance: 1, peak: 1 } as never,
      ],
      coverage: { first_sample_ts: 0, n: 3, series_first_ts: {}, gaps: [[0, 400], [400, 1000]] },
    }));
    expect(rows[1].ts).toBe(200);
    expect(rows[3].ts).toBe(700);
  });

  it("interpolates a null with no matching gap entry from its real neighbours, never ts:0", () => {
    // two nulls, only one reported gap — the second null has nothing to pair with
    const rows = toChartRows(base({
      points: [
        { ts: 5_000_100, equity: 1, balance: 1, peak: 1 } as never,
        null,
        { ts: 5_000_200, equity: 1, balance: 1, peak: 1 } as never,
        null,
        { ts: 5_000_300, equity: 1, balance: 1, peak: 1 } as never,
      ],
      coverage: { first_sample_ts: 5_000_100, n: 3, series_first_ts: {}, gaps: [[5_000_100, 5_000_200]] },
    }));
    expect(rows).toHaveLength(5);
    expect(rows[1].ts).toBe(5_000_150); // paired with the reported gap
    expect(rows[3].ts).toBe(5_000_250); // no gap entry — midpoint of its real neighbours
    expect(rows.some((r) => r.ts === 0)).toBe(false);
  });

  it("drops a trailing null that has no matching gap and no following real point", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 5_000_100, equity: 1, balance: 1, peak: 1 } as never,
        null,
        { ts: 5_000_200, equity: 1, balance: 1, peak: 1 } as never,
        null, // trailing — no gap entry, nothing real after it
      ],
      coverage: { first_sample_ts: 5_000_100, n: 2, series_first_ts: {}, gaps: [[5_000_100, 5_000_200]] },
    }));
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.ts)).toEqual([5_000_100, 5_000_150, 5_000_200]);
  });
});

describe("toChartRows — non-finite defence", () => {
  // ---- M7 ----
  it("emits a NULL drawdown when equity is null but peak is numeric, not a fabricated extreme", () => {
    // `null - 10000` is -10000 in JS. One such row would set the drawdown axis
    // floor by itself and squash every real drawdown in the window into an
    // invisible sliver — re-opening a Critical that was already fixed once.
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 10000, balance: 9990, peak: 10000 } as never,
        { ts: 200, equity: null, balance: null, peak: 10000 } as never,
        { ts: 300, equity: 9950, balance: 9990, peak: 10000 } as never,
      ],
    }));
    expect(rows[1].drawdown).toBeNull();
    expect(rows[1].equity).toBeNull();
    // the surviving real drawdowns still set the axis, and none is fabricated
    const dds = rows.map((r) => r.drawdown).filter((v): v is number => v !== null);
    expect(Math.min(...dds)).toBe(-50);
  });

  it("emits a null drawdown when equity is present but peak is absent-or-corrupt", () => {
    // peak absent -> peak falls back to equity -> drawdown 0 (truthful: no
    // recorded high to be down from). peak NaN must NOT become NaN drawdown.
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 10000, balance: 9990 } as never,
        { ts: 200, equity: 9900, balance: 9990, peak: NaN } as never,
      ],
    }));
    expect(rows[0].drawdown).toBe(0);
    expect(rows[1].drawdown).toBe(0);   // NaN peak falls back to equity, never NaN
    expect(rows.every((r) => !Number.isNaN(r.drawdown as number))).toBe(true);
  });

  // ---- I4 ----
  it("maps an ABSENT series key to null rather than letting `undefined` through", () => {
    // A registry change that drops `balance` yields points with no such key.
    // `undefined` passes a `!== null` filter and turns Math.min into NaN.
    const rows = toChartRows(base({
      series: ["equity"],
      points: [{ ts: 100, equity: 10000 } as never, { ts: 200, equity: 10050 } as never],
    }));
    expect(rows).toEqual([
      { ts: 100, equity: 10000, balance: null, drawdown: 0, peak: null },
      { ts: 200, equity: 10050, balance: null, drawdown: 0, peak: null },
    ]);
    rows.forEach((r) => expect(r.balance).not.toBeUndefined());
  });

  it("drops a point whose ts is not finite instead of cratering the x domain", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 10000, balance: 9990, peak: 10000 } as never,
        { ts: NaN, equity: 10010, balance: 9990, peak: 10010 } as never,
        { ts: 300, equity: 10020, balance: 9990, peak: 10020 } as never,
      ],
    }));
    expect(rows.map((r) => r.ts)).toEqual([100, 300]);
  });
});

describe("peak on ChartRow (B1 spec §5)", () => {
  it("carries a reported peak through as a real number", () => {
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80, peak: 120 } as never],
    }));
    expect(rows[0].peak).toBe(120);
  });

  it("leaves peak null when the backend omitted it, instead of echoing equity", () => {
    // The `?? equity` fallback may keep drawdown at 0, but peak itself must stay
    // null — otherwise the high-water line is drawn on top of the equity line
    // and reads as a real, flat high-water mark that was never recorded.
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80 } as never],
    }));
    expect(rows[0].peak).toBeNull();
    expect(rows[0].drawdown).toBe(0);
  });

  it("leaves peak null on a declared gap row", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 90, balance: 80, peak: 120 } as never,
        null as never,
        { ts: 300, equity: 90, balance: 80, peak: 120 } as never,
      ],
      coverage: { first_sample_ts: 100, n: 2, series_first_ts: {}, gaps: [[100, 300]] as [number, number][] },
    }));
    const gapRow = rows.find((r) => r.equity === null);
    expect(gapRow).toBeDefined();
    expect(gapRow!.peak).toBeNull();
  });

  it("leaves peak null when the reported value is not finite", () => {
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80, peak: Number.NaN } as never],
    }));
    expect(rows[0].peak).toBeNull();
  });
});
