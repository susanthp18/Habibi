/** `next-themes` for the ported screens: Habibi's own light/dark switch. */
import { setTheme as setHostTheme, useTheme as useHostTheme, type ColorTheme } from "@/lib/theme";

export function useTheme() {
  const theme = useHostTheme();
  return {
    theme,
    resolvedTheme: theme,
    systemTheme: theme,
    themes: ["light", "dark"],
    setTheme: (next: string) => setHostTheme(next === "dark" ? "dark" : "light"),
  };
}
