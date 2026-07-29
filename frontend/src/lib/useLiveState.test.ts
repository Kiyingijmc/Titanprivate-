import { describe, it, expect, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLiveState } from "./useLiveState";

class FakeWS {
  static last: FakeWS | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  readyState = 0;
  constructor(public url: string) { FakeWS.last = this; }
  send(d: string) { this.sent.push(d); }
  close() { this.readyState = 3; this.onclose?.(); }
  open() { this.readyState = 1; this.onopen?.(); }
  message(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
}

describe("useLiveState", () => {
  it("sends token as first frame, seeds snapshot, appends events", async () => {
    const { result } = renderHook(() =>
      useLiveState("sekret", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, pollFallback: false }));
    act(() => { FakeWS.last!.open(); });
    expect(FakeWS.last!.sent[0]).toBe("sekret");         // FIRST frame is the token
    act(() => { FakeWS.last!.message({ type: "state", health: { paused: false }, positions: [] }); });
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    expect(result.current.connected).toBe(true);
    act(() => { FakeWS.last!.message({ type: "event", topic: "IntentBlocked", ts: 1, rule: "opposition" }); });
    await waitFor(() => expect(result.current.events.at(-1)?.topic).toBe("IntentBlocked"));
  });

  it("caps the event buffer at 200", async () => {
    const { result } = renderHook(() =>
      useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, pollFallback: false, maxEvents: 3 }));
    act(() => { FakeWS.last!.open(); });
    act(() => { for (let i = 0; i < 5; i++) FakeWS.last!.message({ type: "event", topic: "T", ts: i }); });
    await waitFor(() => expect(result.current.events.length).toBe(3));
    expect(result.current.events[0].ts).toBe(2);         // oldest dropped
  });

  it("exposes connectionStatus live after WS open + state", async () => {
    const { result } = renderHook(() =>
      useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, pollFallback: false }));
    act(() => { FakeWS.last!.open(); });
    act(() => { FakeWS.last!.message({ type: "state", health: { last_heartbeat_age_s: 3 }, positions: [] }); });
    await waitFor(() => expect(result.current.connectionStatus.status).toBe("live"));
    expect(result.current.connectionStatus.stale).toBe(false);
  });

  it("polls /api/state to refresh the snapshot even while connected, staying live", async () => {
    // The WS pushes `state` ONCE at connect, then only events — so account/positions
    // would freeze if the snapshot poll were gated off while connected. The poll must
    // keep refreshing the snapshot (live positions) without demoting status off "live".
    let positions: Array<{ ticket: number }> = [{ ticket: 1 }];
    const fetchSpy = vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => ({ health: { last_heartbeat_age_s: 1 }, positions }),
    }));
    vi.stubGlobal("fetch", fetchSpy);
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() =>
        useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, base: "", pollFallback: true, pollMs: 1000 }));
      act(() => { FakeWS.last!.open(); });                                         // connected
      act(() => { FakeWS.last!.message({ type: "state", health: { last_heartbeat_age_s: 1 }, positions: [{ ticket: 1 }] }); });
      positions = [{ ticket: 1 }, { ticket: 2 }];                                  // broker opens a 2nd position
      await act(async () => { await vi.advanceTimersByTimeAsync(1100); });         // one poll tick
      expect(fetchSpy).toHaveBeenCalled();                                         // poll DID fire while connected
      expect(result.current.snapshot?.positions.length).toBe(2);                  // snapshot refreshed live
      expect(result.current.connectionStatus.status).toBe("live");               // still live, not degraded
    } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
  });

  it("a failing poll while connected does NOT demote status off live", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: false });
    vi.stubGlobal("fetch", fetchSpy);
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() =>
        useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, base: "", pollFallback: true, pollMs: 1000 }));
      act(() => { FakeWS.last!.open(); });
      act(() => { FakeWS.last!.message({ type: "state", health: { last_heartbeat_age_s: 1 }, positions: [] }); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
      expect(result.current.connectionStatus.status).toBe("live");               // WS up short-circuits; poll result ignored for status
    } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
  });
});
