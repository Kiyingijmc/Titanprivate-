import { useEffect, useRef, useState } from "react";
import type { EquityPoint } from "@/components/EquitySparkline";

const MAX_POINTS = 120;

/**
 * Rolling buffer of equity samples for the Overview sparkline. Appends a new
 * point only when `equity` changes to a distinct value (avoids flooding the
 * chart on unrelated re-renders), capped at ~120 points. `x` is a monotonic
 * ref counter — never Date.now()/new Date() — so the chart stays deterministic
 * and testable.
 */
export function useEquityBuffer(equity: number | undefined): EquityPoint[] {
  const [points, setPoints] = useState<EquityPoint[]>([]);
  const counterRef = useRef(0);
  const lastRef = useRef<number | undefined>(undefined);

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

  return points;
}
