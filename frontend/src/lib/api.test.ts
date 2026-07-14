import { describe, it, expect, vi } from "vitest";
import { createApi, ApiError } from "./api";

function fakeFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300, status,
    json: async () => body, text: async () => JSON.stringify(body),
  });
}

describe("api client", () => {
  it("sends bearer token and returns json", async () => {
    const f = fakeFetch(200, { health: {}, positions: [] });
    const api = createApi(() => "tok", { fetchImpl: f as unknown as typeof fetch });
    const snap = await api.getState();
    expect(snap).toHaveProperty("positions");
    const [, init] = f.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("maps 401/429/403/422 to typed ApiError", async () => {
    for (const [status, kind] of [[401, "unauthorized"], [429, "throttled"], [403, "readOnly"], [422, "validation"]] as const) {
      const api = createApi(() => "tok", { fetchImpl: fakeFetch(status, { detail: "x" }) as unknown as typeof fetch });
      await expect(api.getState()).rejects.toMatchObject({ status, kind } satisfies Partial<ApiError>);
    }
  });

  it("postCommand posts json body", async () => {
    const f = fakeFetch(200, { status: "ok", result: "PAUSED" });
    const api = createApi(() => "tok", { fetchImpl: f as unknown as typeof fetch });
    const r = await api.postCommand({ command: "pause" });
    expect(r.result).toBe("PAUSED");
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/api/command");
    expect(init.method).toBe("POST");
  });
});
