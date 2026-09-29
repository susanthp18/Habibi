import { useEffect, useLayoutEffect } from "react";

/** Motion is off for `?still` (screenshots, print) and for reduced-motion users. */
export function isStill() {
  return (
    location.search.includes("still") || matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** useLayoutEffect in the browser, useEffect while prerendering. */
export const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
