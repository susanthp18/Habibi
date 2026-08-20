import { useSyncExternalStore } from "react";

export type ColorTheme = "light" | "dark";

const STORAGE_KEY = "theme";
const listeners = new Set<() => void>();

function readDom(): ColorTheme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function getTheme(): ColorTheme {
  return readDom();
}

export function getServerTheme(): ColorTheme {
  return "light";
}

export function subscribeTheme(onStoreChange: () => void) {
  listeners.add(onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
  };
}

export function setTheme(next: ColorTheme) {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", next === "dark");
  }
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore quota / private mode */
  }
  listeners.forEach((fn) => fn());
}

export function toggleTheme() {
  setTheme(getTheme() === "dark" ? "light" : "dark");
}

export function useTheme() {
  return useSyncExternalStore(subscribeTheme, getTheme, getServerTheme);
}
