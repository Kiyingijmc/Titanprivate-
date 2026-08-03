import { useEffect, useRef, useState } from "react";
import type { Api, ApiError } from "./api";
import type { EquitySeries } from "./types";

const DEFAULT_POLL_MS = 30_000;

/** Newest real (non-null, finite-ts) sample in a series, on the SERVER clock. */
function newestServerTs(series: EquitySeries): number | null {
  for (let i = series.points.length - 1; i >= 0; i--) {
    const p = series.points[i];
    if (p !== null && typeof p.ts === "number" && Number.isFinite(p.ts)) return p.ts;
  }
  return null;
}

/**
 * Seconds to ADD to a client epoch-second reading to land on the server clock.
 *
 * The browser clock and the recorder's SQLite timestamps are two independent
 * clocks; the panel joins them on one X axis, so they must be reconciled before
 * any comparison. Left unreconciled, a viewer whose machine is slow finds every
 * live tail point failing the "newer than the last stored sample" test (tail
 * silently never renders, no symptom) and every lookback range disabled; a
 * viewer whose machine is fast plots live points in the future and stretches
 * the `["dataMin","dataMax"]` domain past now, drawing a flat lead-out that
 * reads as recorded data.
 *
 * The estimate is deliberately a LOWER BOUND on the true offset: the newest
 * STORED sample lags real server time by up to `flush_interval_s` plus a
 * bucket. Under-estimating is the safe direction — it can only place the live
 * leading edge slightly early (never in the future) and unlock a wide range
 * slightly late (never disable one that is already legitimately selected).
 */
export function serverClockOffset(series: EquitySeries | null, clientNowS: number): number {
  if (!series) return 0;                       // nothing fetched yet — trust the local clock
  const newest = newestServerTs(series);
  if (newest === null) return 0;               // empty window — no anchor to measure against
  return newest - clientNowS;
}

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
  // Captured at the instant a series LANDS, against the client clock as it read
  // then — not recomputed later from stale data. See `serverClockOffset`.
  const [serverOffset, setServerOffset] = useState(0);
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
        setData(s);
        setError(null);
        const newest = newestServerTs(s);
        if (newest !== null) setServerOffset(newest - Date.now() / 1000);
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

  return { data, loading, error, serverOffset };
}
