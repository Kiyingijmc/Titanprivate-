import { useEffect, useState } from "react";

/**
 * Returns the current time, ticking on an interval. The one place in the
 * app that reads real wall-clock time — components take `now` as a prop so
 * tests can inject a fixed instant instead of depending on this hook.
 */
export function useNow(intervalMs = 1000): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return now;
}
