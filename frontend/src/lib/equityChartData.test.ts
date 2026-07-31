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
    expect(rows).toEqual([{ ts: 100, equity: 90, balance: 80, drawdown: -10 }]);
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
    expect(rows[1]).toEqual({ ts: 500, equity: null, balance: null, drawdown: null });
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
