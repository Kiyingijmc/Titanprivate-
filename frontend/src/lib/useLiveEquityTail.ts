import { useEffect, useRef, useState } from "react";

const MAX_POINTS = 300;

/** One live sample. `ts` is a REAL UTC epoch second (`Date.now() / 1000`) —
 * unlike `useEquityBuffer`'s synthetic monotonic counter, that is the whole
 * point here: these points get stitched onto the end of a fetched
 * `EquitySeries`, whose x-axis is real epoch seconds, so a fake x-value would
 * misplace them on the shared axis. */
export interface LiveEquityPoint {
  ts: number;
  equity: number;
}

/**
 * Leading-edge tail of live equity samples, for extending a fetched (polled,
 * up to `flush_interval_s` stale — currently 60s server-side) `EquitySeries`
 * so the fine-tier ranges keep feeling live between poll ticks, without
 * re-fetching. This is a DIFFERENT concern from `useEquityBuffer` (the
 * legacy WS-only sparkline path, whose `t` counter and its own tests this
 * hook must not disturb) — kept as a separate, smaller hook rather than
 * folded into it.
 *
 * Appends only when `equity` changes to a distinct value, bounded to a few
 * hundred points (far more than the gap between poll ticks will ever need),
 * and never persists — this is a short-lived UI buffer, not durable history.
 * Like its neighbour, it never throws: an `undefined` equity (no snapshot
 * yet) is simply a no-op.
 */
export function useLiveEquityTail(equity: number | undefined): LiveEquityPoint[] {
  const [points, setPoints] = useState<LiveEquityPoint[]>([]);
  const lastRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (equity === undefined || equity === lastRef.current) return;
    lastRef.current = equity;
    const ts = Date.now() / 1000;
    setPoints((prev) => {
      const next = [...prev, { ts, equity }];
      return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
    });
  }, [equity]);

  return points;
}
