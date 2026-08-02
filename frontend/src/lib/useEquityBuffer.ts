import { useEffect, useRef, useState } from "react";
import type { BufferPoint } from "@/components/EquitySparkline";

const MAX_POINTS = 120;
const STORAGE_KEY = "titan.equity.buffer";

/** Restore the last persisted trend so a reload shows recent history, not one point. */
function loadPersisted(): BufferPoint[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((p) => p && typeof p.t === "number" && typeof p.equity === "number")
      .slice(-MAX_POINTS);
  } catch {
    return [];
  }
}

/**
 * Rolling buffer of equity samples for the Overview sparkline. Appends a new
 * point only when `equity` changes to a distinct value (avoids flooding the
 * chart on unrelated re-renders), capped at ~120 points. `t` is a monotonic
 * ref counter — never Date.now()/new Date() — so the chart stays deterministic
 * and testable.
 *
 * The buffer is persisted to localStorage and restored on mount, so a browser
 * reload keeps the recent trend instead of collapsing to a single point.
 */
export function useEquityBuffer(equity: number | undefined): BufferPoint[] {
  const [points, setPoints] = useState<BufferPoint[]>(loadPersisted);
  const counterRef = useRef(points.length ? points[points.length - 1].t : 0);
  const lastRef = useRef<number | undefined>(points.length ? points[points.length - 1].equity : undefined);

  useEffect(() => {
    if (equity === undefined || equity === lastRef.current) return;
    lastRef.current = equity;
    counterRef.current += 1;
    const t = counterRef.current;
    setPoints((prev) => {
      const next = [...prev, { t, equity }];
      return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
    });
  }, [equity]);

  // Persist the trend so a reload restores it (best-effort; ignore quota/private-mode).
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(points));
    } catch {
      /* ignore */
    }
  }, [points]);

  return points;
}
