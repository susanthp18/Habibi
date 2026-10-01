import { useEffect, useState } from "react";

/** The current time, re-read every ``intervalMs`` -- for countdowns that must
 *  move while the data under them is unchanged. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}
