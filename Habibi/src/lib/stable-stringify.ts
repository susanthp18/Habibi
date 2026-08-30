/**
 * Key-order-independent JSON identity.
 *
 * Every place this app asks "did this object change?" or "have I already asked
 * the server about this payload?" answers by serialising it, and plain
 * `JSON.stringify` answers by key order. That is not a theoretical hazard here:
 *
 * - The Prompt Studio autosave fingerprint compared locally-seeded state
 *   (`DEFAULT_VOICE`, which omits `style`/`params`) against a server-shaped row
 *   (Pydantic emits every field, in field order). The first save stored a
 *   server-shaped baseline while local state kept the seed shape, so `dirty`
 *   recomputed true immediately after "Draft saved" — a permanent unsaved chip
 *   and a PATCH that re-triggers itself.
 * - PublishDialog would call a card "changed" because a spread rebuilt it in a
 *   different key order, and a changed-flag that cries wolf is one nobody reads.
 *
 * `undefined` values are dropped rather than serialised, so an explicitly-unset
 * key and an absent key are the same object — which is what the backend does
 * with them too.
 */
export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(",")}}`;
}
