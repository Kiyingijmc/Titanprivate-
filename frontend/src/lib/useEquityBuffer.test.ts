import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useEquityBuffer } from "./useEquityBuffer";

describe("useEquityBuffer", () => {
  beforeEach(() => localStorage.clear());

  it("appends only on distinct equity values", () => {
    const { result, rerender } = renderHook(({ e }) => useEquityBuffer(e), {
      initialProps: { e: 100 as number | undefined },
    });
    expect(result.current).toHaveLength(1);
    rerender({ e: 100 }); // same value → no append
    expect(result.current).toHaveLength(1);
    rerender({ e: 101 }); // distinct → append
    expect(result.current).toHaveLength(2);
  });

  it("restores the persisted trend on a fresh mount (survives a reload)", () => {
    const first = renderHook(({ e }) => useEquityBuffer(e), {
      initialProps: { e: 100 as number | undefined },
    });
    first.rerender({ e: 101 });
    first.rerender({ e: 102 });
    first.unmount();

    const second = renderHook(() => useEquityBuffer(undefined));
    expect(second.result.current.length).toBeGreaterThanOrEqual(3);
    expect(second.result.current.at(-1)?.equity).toBe(102);
  });
});
