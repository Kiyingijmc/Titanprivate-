import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useEquitySeries } from "./useEquitySeries";
import type { EquitySeries } from "./types";

const series = (range: string): EquitySeries => ({
  range, tier: "coarse", bucket_s: 300, series: ["equity", "balance", "peak"],
  points: [{ ts: 1000, equity: 10, balance: 9, peak: 11 }],
  coverage: { first_sample_ts: 500, n: 1, series_first_ts: {}, gaps: [] },
});

describe("useEquitySeries", () => {
  it("fetches on mount and exposes the series", async () => {
    const getEquity = vi.fn(async (r: string) => series(r));
    const { result } = renderHook(() => useEquitySeries({ getEquity } as never, "1d", { pollMs: 0 }));
    await waitFor(() => expect(result.current.data?.range).toBe("1d"));
    expect(getEquity).toHaveBeenCalledWith("1d");
    expect(result.current.loading).toBe(false);
  });

  it("refetches when the range changes and drops a stale in-flight response", async () => {
    let resolveFirst: (v: EquitySeries) => void = () => {};
    const getEquity = vi.fn((r: string) =>
      r === "1d" ? new Promise<EquitySeries>((res) => { resolveFirst = res; }) : Promise.resolve(series(r)));
    const { result, rerender } = renderHook(({ r }) => useEquitySeries({ getEquity } as never, r, { pollMs: 0 }),
      { initialProps: { r: "1d" } });
    rerender({ r: "1w" });
    await waitFor(() => expect(result.current.data?.range).toBe("1w"));
    await act(async () => { resolveFirst(series("1d")); });   // stale response lands late
    expect(result.current.data?.range).toBe("1w");            // and must be ignored
  });

  it("surfaces an error without clearing the last good data", async () => {
    const getEquity = vi.fn()
      .mockResolvedValueOnce(series("1d"))
      .mockRejectedValueOnce({ status: 500, kind: "error", detail: "boom" });
    const { result } = renderHook(() => useEquitySeries({ getEquity } as never, "1d", { pollMs: 10 }));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    await waitFor(() => expect(result.current.error).not.toBeNull(), { timeout: 2000 });
    expect(result.current.data?.range).toBe("1d");            // last good series survives
  });
});
