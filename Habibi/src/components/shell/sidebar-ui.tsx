import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

const STORAGE_KEY = "bigbond.sidebar.collapsed";

type SidebarUiContextValue = {
  collapsed: boolean;
  setCollapsed: (next: boolean) => void;
  toggle: () => void;
};

const SidebarUiContext = createContext<SidebarUiContextValue | null>(null);

function readCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(next: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    /* ignore */
  }
}

/** Clear stuck collapse flag (call from error boundaries / recovery). */
export function clearSidebarCollapsedPreference() {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* ignore */
  }
}

export function SidebarUiProvider({ children }: { children: ReactNode }) {
  // Always start expanded on first paint (SSR + hydration-safe). Restore preference after mount.
  const [collapsed, setCollapsedState] = useState(false);

  useEffect(() => {
    setCollapsedState(readCollapsed());
  }, []);

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next);
    writeCollapsed(next);
  }, []);

  const toggle = useCallback(() => {
    setCollapsedState((prev) => {
      const next = !prev;
      writeCollapsed(next);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ collapsed, setCollapsed, toggle }),
    [collapsed, setCollapsed, toggle],
  );

  return <SidebarUiContext.Provider value={value}>{children}</SidebarUiContext.Provider>;
}

export function useSidebarUi(): SidebarUiContextValue {
  const ctx = useContext(SidebarUiContext);
  // Never throw — a missing provider used to white-screen the whole app.
  if (!ctx) {
    return {
      collapsed: false,
      setCollapsed: () => undefined,
      toggle: () => undefined,
    };
  }
  return ctx;
}
