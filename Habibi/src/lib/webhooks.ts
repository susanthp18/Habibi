import type { Delivery, EventCategory, EventDef } from "@/api/types/webhooks";

/** Categories in catalogue order, each once. */
export function eventCategories(catalog: EventDef[]): EventCategory[] {
  return Array.from(new Set(catalog.map((e) => e.category)));
}

/** What a receiver sees; the value is computed server-side over the raw body. */
export const SIGNATURE_HEADER_EXAMPLE =
  "X-Coll-Signature: t=<unix seconds>, v1=<hex HMAC-SHA256 of `<t>.<raw body>`>";

export function successRate(list: Delivery[]): number {
  if (!list.length) return 100;
  const ok = list.filter((d) => d.status === "success").length;
  return Math.round((ok / list.length) * 100);
}

export function within(list: Delivery[], hours: number): Delivery[] {
  const cutoff = Date.now() - hours * 3_600_000;
  return list.filter((d) => d.at >= cutoff);
}

export function fmtRel(ts: number): string {
  const diff = Date.now() - ts;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}
