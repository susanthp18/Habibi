/**
 * The display formatters every screen shares: money in the deployment's
 * currency, dates in the tenant's zone, relative times, mm:ss durations. One
 * owner -- these used to live in the mock seed files and were copied into
 * components (three `fmtMoney`, four `fmtDate`, two `formatDuration`).
 */

/**
 * The deployment's currency: Vietnamese đồng, written the vi-VN way
 * ("45.000 ₫"). It was Indian rupees until the Vietnam deployment
 * (2026-10-08); stored amounts were not converted, only their rendering.
 * Mirrors backend/money_inr.py::CURRENCY. Change one, change both.
 */
export const CURRENCY = "VND";
export const CURRENCY_SYMBOL = "₫";
const MONEY_LOCALE = "vi-VN";
const money = new Intl.NumberFormat(MONEY_LOCALE, { style: "currency", currency: CURRENCY });
const moneyCompact = new Intl.NumberFormat(MONEY_LOCALE, {
  style: "currency",
  currency: CURRENCY,
  notation: "compact",
  maximumFractionDigits: 1,
});
/** What Intl puts between a number and its symbol: a no-break space. */
const NBSP = "\u00a0";

export function fmtMoney(n: number | null | undefined) {
  const value = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return money.format(value);
}

/** A plain number in the money locale's grouping ("1.234.567"), for inputs and
 * axis labels that carry the symbol separately. */
export function fmtMoneyNumber(n: number): string {
  return Math.round(n).toLocaleString(MONEY_LOCALE);
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
  return money.format(Math.round(n));
}

/**
 * Below this, a nonzero value cannot be shown to four decimals and is floored
 * to a "smaller than" reading rather than to a plausible-looking zero.
 */
const COMPACT_EPSILON = 0.0001;

/** Fixed decimals with the vi-VN decimal comma, and the symbol. */
function fixedMoney(n: number, digits: number): string {
  return `${n.toFixed(digits).replace(".", ",")}${NBSP}${CURRENCY_SYMBOL}`;
}

/**
 * Compact money. The canonical ladder, shared with the backend.
 *
 * ```
 * 0                 -> "0 ₫"
 * 0 < n < 0.0001    -> "<0,0001 ₫"
 * 0.0001 <= n < 1   -> "0,0040 ₫"   (4 dp)
 * 1 <= n < 1_000    -> "12,50 ₫"    (2 dp)
 * n >= 1_000        -> "1,5 N ₫", "12,3 Tr ₫", "4,5 T ₫" (vi-VN compact)
 * negative          -> "-" + the same
 * ```
 *
 * (Every space is a no-break space, as Intl prints it.)
 *
 * Mirrors backend/money_inr.py::inr_compact exactly. Change one, change both:
 * they are read side by side on the billing screen, where a Python value
 * labels a chart whose axis the TypeScript value labels.
 */
export function inrCompact(n: number): string {
  if (n < 0) return `-${inrCompact(-n)}`;
  if (n >= 1_000) return moneyCompact.format(n);
  if (n >= 1) return fixedMoney(n, 2);
  if (n >= COMPACT_EPSILON) return fixedMoney(n, 4);
  // Real spend, too small to render. Saying so beats rounding it away — a
  // metered call that cost a fraction of a đồng is not a free call.
  if (n > 0) return `<${fixedMoney(COMPACT_EPSILON, 4)}`;
  return `0${NBSP}${CURRENCY_SYMBOL}`;
}

export function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
