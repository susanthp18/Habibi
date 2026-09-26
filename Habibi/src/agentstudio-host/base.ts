/**
 * Where AgentStudio lives inside Habibi, and the translation between the
 * engine UI's own paths ("/workflow/12") and Habibi's ("/studio/workflow/12").
 */

export const STUDIO_BASE = "/studio";

/** Fired by `router.refresh()`; pages that fetch on mount re-fetch on it. */
export const STUDIO_REFRESH_EVENT = "agentstudio:refresh";

/** Engine-UI href -> Habibi href. External, hash and already-prefixed links pass through. */
export function toHostPath(href: string): string {
  if (!href.startsWith("/") || href.startsWith("//")) return href;
  if (
    href === STUDIO_BASE ||
    href.startsWith(`${STUDIO_BASE}/`) ||
    href.startsWith(`${STUDIO_BASE}?`)
  ) {
    return href;
  }
  return href === "/" ? STUDIO_BASE : `${STUDIO_BASE}${href}`;
}

/** Habibi pathname -> the engine UI's pathname. */
export function toEnginePath(pathname: string): string {
  if (pathname === STUDIO_BASE) return "/workflow";
  return pathname.startsWith(`${STUDIO_BASE}/`) ? pathname.slice(STUDIO_BASE.length) : pathname;
}
