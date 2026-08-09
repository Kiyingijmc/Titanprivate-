import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useNewsCalendar } from "./useNewsCalendar";
import type { NewsCalendar } from "./types";

const PAYLOAD: NewsCalendar = {
  status: "ok", cache_age_min: 12, horizon_truncated: false,
  events: [{ when_utc: "2026-08-07T12:30:00Z", currency: "USD", importance: "HIGH",
             title: "Non-Farm Employment Change", affects: ["XAUUSD"] }],
};

describe("useNewsCalendar", () => {
  it("does not touch the api while disabled", async () => {
    const getNewsCalendar = vi.fn().mockResolvedValue(PAYLOAD);
    renderHook(() => useNewsCalendar({ getNewsCalendar }, false));
    await new Promise(r => setTimeout(r, 20));
    expect(getNewsCalendar).not.toHaveBeenCalled();
  });

  it("fetches once when enabled", async () => {
    const getNewsCalendar = vi.fn().mockResolvedValue(PAYLOAD);
    const { result } = renderHook(() => useNewsCalendar({ getNewsCalendar }, true));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(getNewsCalendar).toHaveBeenCalledTimes(1);
    expect(result.current.data?.events).toHaveLength(1);
  });

  it("keeps the last good payload when a refresh fails", async () => {
    const getNewsCalendar = vi.fn()
      .mockResolvedValueOnce(PAYLOAD)
      .mockRejectedValue({ status: 500, kind: "error", detail: "boom" });
    const { result } = renderHook(() =>
      useNewsCalendar({ getNewsCalendar }, true, { pollMs: 10 }));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    // An empty calendar reads as "quiet week" — a lie. Keep the last good one.
    expect(result.current.data?.events).toHaveLength(1);
  });
});
