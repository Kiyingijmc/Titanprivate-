import { useEffect, useRef, useState } from "react";
import type { Api, ApiError } from "./api";
import type { EquitySeries } from "./types";

const DEFAULT_POLL_MS = 30_000;

/**
 * Fetches one lookback range and keeps it fresh on a slow poll.
 *
 * Two deliberate behaviours: a response for a range the user has already moved
 * away from is DISCARDED (a slow 1y query must not overwrite the 15m the user
 * is now looking at), and a failed refresh leaves the last good series on
 * screen rather than blanking the panel — an empty chart reads as "flat", which
 * is a lie the rest of this codebase is careful not to tell.
 */
export function useEquitySeries(api: Pick<Api, "getEquity">, range: string,
                                opts: { pollMs?: number } = {}) {
  const pollMs = opts.pollMs ?? DEFAULT_POLL_MS;
  const [data, setData] = useState<EquitySeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const wanted = useRef(range);
  // `api` is commonly a fresh object identity per caller render (e.g. an inline
  // literal). Reading it through a ref — updated every render, but NOT in the
  // effect's dependency array — means the fetch effect only re-runs when
  // `range`/`pollMs` actually change, never merely because the caller re-rendered.
  const apiRef = useRef(api);
  apiRef.current = api;

  useEffect(() => {
    wanted.current = range;
    let alive = true;
    setLoading(true);

    const load = async () => {
      try {
        const s = await apiRef.current.getEquity(range);
        if (!alive || wanted.current !== range) return;   // stale range — drop it
        if (s == null) return;                            // no payload — leave prior state alone
        setData(s);
        setError(null);
      } catch (e) {
        if (!alive || wanted.current !== range) return;
        setError(e as ApiError);                          // keep last good `data`
      } finally {
        if (alive && wanted.current === range) setLoading(false);
      }
    };

    void load();
    if (pollMs <= 0) return () => { alive = false; };
    const id = setInterval(() => { void load(); }, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [range, pollMs]);

  return { data, loading, error };
}
