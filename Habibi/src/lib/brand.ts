/** Product branding — used by shell chrome and document titles. */
export const BRAND = {
  name: "PayInt",
  shortName: "PayInt",
  tagline: "Collections workspace",
  /**
   * The tenant strip under the wordmark. Defaults to a neutral demo tenant so
   * screenshots and any public build never carry a real institution's name.
   * Set VITE_TENANT_LINE in .env.local to dress the app for a specific demo.
   */
  tenantLine:
    (import.meta.env.VITE_TENANT_LINE as string | undefined)?.trim() || "Beeonix · Bigtapp",
  titleSuffix: "PayInt",
} as const;
