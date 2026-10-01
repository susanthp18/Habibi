import { useEffect, useState } from "react";

/** ``value`` once it has stopped changing for ``ms`` -- for server searches
 *  that should run when the operator pauses typing, not on every key. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return settled;
}
