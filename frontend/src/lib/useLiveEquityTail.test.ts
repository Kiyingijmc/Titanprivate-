import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLiveEquityTail } from "./useLiveEquityTail";

describe("useLiveEquityTail", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T00:00:00Z")); // epoch seconds = 1785542400
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("appends only on distinct equity values, stamped with a CLIENT epoch-second clientTs", () => {
    const { result, rerender } = renderHook(({ e }) => useLiveEquityTail(e), {
      initialProps: { e: 100 as number | undefined },
    });
    expect(result.current).toHaveLength(1);
    expect(result.current[0]).toEqual({ clientTs: 1785542400, equity: 100 });

    rerender({ e: 100 }); // same value → no append
    expect(result.current).toHaveLength(1);

    vi.setSystemTime(new Date("2026-08-01T00:00:05Z"));
    rerender({ e: 101 }); // distinct → append, with the new ts
    expect(result.current).toHaveLength(2);
    expect(result.current[1]).toEqual({ clientTs: 1785542405, equity: 101 });
  });

  it("is a no-op while equity is undefined", () => {
    const { result, rerender } = renderHook(({ e }) => useLiveEquityTail(e), {
      initialProps: { e: undefined as number | undefined },
    });
    expect(result.current).toHaveLength(0);
    rerender({ e: undefined });
    expect(result.current).toHaveLength(0);
  });

  it("bounds the buffer instead of growing unboundedly", () => {
    const { result, rerender } = renderHook(({ e }) => useLiveEquityTail(e), {
      initialProps: { e: 0 },
    });
    for (let i = 1; i <= 400; i++) {
      vi.setSystemTime(new Date(1785715200_000 + i * 1000));
      rerender({ e: i });
    }
    expect(result.current.length).toBeLessThanOrEqual(300);
    expect(result.current.at(-1)?.equity).toBe(400);
  });
});
