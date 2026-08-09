import { useEffect, useRef, useState } from "react";
import type { Api, ApiError } from "./api";
import type { NewsCalendar } from "./types";

const DEFAULT_POLL_MS = 60_000;

/**
 * The expanded calendar's data source.
 *
 * Gated on `enabled` so a CLOSED dialog never polls — this endpoint exists
 * precisely to keep calendar bytes off the 2s hot path, and a background poll
 * for an invisible surface would give some of that back.
 *
 * 60s, not 2s: the underlying feed refreshes hourly (news.refresh_interval_min).
 * A failed refresh keeps the last good payload, because a blank table reads as
 * "no events scheduled" — the one thing an economic calendar must never imply
 * by accident.
 */
export function useNewsCalendar(
  api: Pick<Api, "getNewsCalendar">,
  enabled: boolean,
  opts: { pollMs?: number } = {},
) {
  const pollMs = opts.pollMs ?? DEFAULT_POLL_MS;
  const [data, setData] = useState<NewsCalendar | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // Read through a ref (updated every render, NOT in the dep array) so an
  // inline `api` literal from the caller cannot restart the poll every render.
  const apiRef = useRef(api);
  apiRef.current = api;

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setLoading(true);

    const load = async () => {
      try {
        const next = await apiRef.current.getNewsCalendar();
        if (!alive) return;
        setData(next);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e as ApiError);        // keep the last good `data`
      } finally {
        if (alive) setLoading(false);
      }
    };

    void load();
    if (pollMs <= 0) return () => { alive = false; };
    const id = setInterval(() => { void load(); }, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [enabled, pollMs]);

  return { data, loading, error };
}
