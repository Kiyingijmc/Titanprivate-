import type { Snapshot, FeedEvent, SettingRow, RegistryRow, CommandResult, SettingsPatchResult, HistoryRow, EquitySeries } from "./types";

export interface ApiError { status: number; kind: "unauthorized" | "throttled" | "readOnly" | "validation" | "error"; detail: string; }
function kindFor(status: number): ApiError["kind"] {
  return status === 401 ? "unauthorized" : status === 429 ? "throttled"
    : status === 403 ? "readOnly" : status === 422 ? "validation" : "error";
}

interface Opts { fetchImpl?: typeof fetch; base?: string; }

export function createApi(getToken: () => string, opts: Opts = {}) {
  const f = opts.fetchImpl ?? fetch;
  const base = opts.base ?? "";
  async function req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await f(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}`, ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json())?.detail ?? detail; } catch { /* ignore */ }
      const err: ApiError = { status: res.status, kind: kindFor(res.status), detail };
      throw err;
    }
    return (await res.json()) as T;
  }
  return {
    getState: () => req<Snapshot>("/api/state"),
    getEvents: (limit = 200) => req<{ events: FeedEvent[] }>(`/api/events?limit=${limit}`).then(r => r.events),
    getHistory: (limit = 50) => req<{ history: HistoryRow[] }>(`/api/history?limit=${limit}`).then(r => r.history),
    getEquity: (range: string) => req<EquitySeries>(`/api/equity?range=${encodeURIComponent(range)}`),
    getSettings: () => req<{ settings: SettingRow[] }>("/api/settings").then(r => r.settings),
    getRegistry: () => req<{ registry: RegistryRow[] }>("/api/registry").then(r => r.registry),
    postCommand: (body: Record<string, unknown>) => req<CommandResult>("/api/command", { method: "POST", body: JSON.stringify(body) }),
    patchSetting: (key: string, value: unknown) => req<SettingsPatchResult>("/api/settings", { method: "PATCH", body: JSON.stringify({ key, value }) }),
    registryAction: (sid: string, action: string, body: Record<string, unknown> = {}) =>
      req<CommandResult>(`/api/registry/${encodeURIComponent(sid)}/${action}`, { method: "POST", body: JSON.stringify(body) }),
  };
}
export type Api = ReturnType<typeof createApi>;
