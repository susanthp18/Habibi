/**
 * `next/navigation` for the ported AgentStudio screens, on TanStack Router.
 * Paths the screens use ("/workflow/12") are mapped under STUDIO_BASE.
 */
import {
  useLocation,
  useNavigate,
  useParams as useRouterParams,
  useRouter as useTanstackRouter,
} from "@tanstack/react-router";
import { useMemo } from "react";

import { STUDIO_REFRESH_EVENT, toEnginePath, toHostPath } from "../base";

export interface AppRouter {
  push: (href: string, options?: { scroll?: boolean }) => void;
  replace: (href: string, options?: { scroll?: boolean }) => void;
  back: () => void;
  forward: () => void;
  refresh: () => void;
  prefetch: (href: string) => void;
}

export function useRouter(): AppRouter {
  const navigate = useNavigate();
  const router = useTanstackRouter();
  return useMemo(
    () => ({
      push: (href) => void navigate({ href: toHostPath(href) }),
      replace: (href) => void navigate({ href: toHostPath(href), replace: true }),
      back: () => window.history.back(),
      forward: () => window.history.forward(),
      refresh: () => {
        window.dispatchEvent(new Event(STUDIO_REFRESH_EVENT));
        void router.invalidate();
      },
      prefetch: () => {},
    }),
    [navigate, router],
  );
}

export function usePathname(): string {
  return toEnginePath(useLocation({ select: (l) => l.pathname }));
}

export function useSearchParams(): URLSearchParams {
  const searchStr = useLocation({ select: (l) => l.searchStr });
  return useMemo(() => new URLSearchParams(searchStr), [searchStr]);
}

export function useParams<T extends Record<string, string> = Record<string, string>>(): T {
  // Next's useParams is untyped per route; so is this one.
  const read = useRouterParams as unknown as (opts: { strict: false }) => Record<string, string>;
  return read({ strict: false }) as T;
}

/** Server-only in Next; the ported screens never reach it. */
export function redirect(href: string): never {
  window.location.assign(toHostPath(href));
  throw new Error(`redirect to ${href}`);
}

export function notFound(): never {
  throw new Error("not found");
}
