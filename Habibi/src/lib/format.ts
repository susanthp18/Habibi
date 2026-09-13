/**
 * The display formatters every screen shares: rupees with Indian grouping,
 * dates in the tenant's zone, relative times, mm:ss durations. One owner --
 * these used to live in the mock seed files and were copied into components
 * (three `fmtMoney`, four `fmtDate`, two `formatDuration`).
 */

export function fmtMoney(n: number | null | undefined) {
  const value = typeof n === "number" && Number.isFinite(n) ? n : 0;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  return `${sign}₹${abs.toLocaleString("en-IN")}`;
}

export function fmtDate(iso: string | null | undefined, opts?: Intl.DateTimeFormatOptions) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    ...(opts ?? { month: "short", day: "numeric", year: "numeric" }),
  });
}

/** `13 Sep 26` -- the compact date the tables use. */
export function fmtShortDate(iso: string | null | undefined, opts?: Intl.DateTimeFormatOptions) {
  return fmtDate(iso, opts ?? { day: "2-digit", month: "short", year: "2-digit" });
}

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function fmtRelative(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  const days = Math.floor(diff / 86400);
  if (days < 7) return `${days}d ago`;
  return fmtDate(iso, { month: "short", day: "numeric" });
}

export function inr(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

/**
 * Below this, a nonzero value cannot be shown to four decimals and is floored
 * to a "smaller than" reading rather than to a plausible-looking zero.
 */
const COMPACT_EPSILON = 0.0001;

/**
 * Compact Indian money. The canonical ladder, shared with the backend.
 *
 * ```
 * 0                     -> "₹0"
 * 0 < n < 0.0001        -> "<₹0.0001"
 * 0.0001 <= n < 1       -> "₹0.0040"     (4 dp)
 * 1 <= n < 1_000        -> "₹12.50"      (2 dp)
 * 1_000 <= n < 1_00_000 -> "₹1.5k"       (lowercase k, no space)
 * 1_00_000 <= n < 1cr   -> "₹12.3L"
 * n >= 1_00_00_000      -> "₹4.5Cr"
 * negative              -> "-" + the same
 * ```
 *
 * One decimal on every magnitude suffix, so the three read as one ladder
 * rather than three conventions. This used to print "₹12.35L" beside "₹1.5k"
 * — two and one decimals in the same column — and to space the Cr and L
 * suffixes but not the k.
 *
 * Mirrors backend/money_inr.py::inr_compact exactly. Change one, change both:
 * they are read side by side on the billing screen, where a Python value
 * labels a chart whose axis the TypeScript value labels.
 */
export function inrCompact(n: number): string {
  if (n < 0) return `-${inrCompact(-n)}`;
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}k`;
  if (n >= 1) return `₹${n.toFixed(2)}`;
  if (n >= COMPACT_EPSILON) return `₹${n.toFixed(4)}`;
  // Real spend, too small to render. Saying so beats rounding it away — a
  // metered call that cost a fraction of a paisa is not a free call.
  if (n > 0) return `<₹${COMPACT_EPSILON.toFixed(4)}`;
  return "₹0";
}

export function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
