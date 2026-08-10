import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/*
 * The Design.md type scale is declared in styles.css as custom `@utility` classes whose
 * names sit inside namespaces Tailwind already owns: `text-body-small` looks exactly like
 * a `text-<color>` utility, and `border-width-default` like `border-<color>`. Stock
 * tailwind-merge therefore files them in the *colour* conflict groups, decides they clash
 * with the real colour class beside them, and deletes whichever came first — so
 * `cn("text-body-small", "text-text-brand")` shipped the colour alone and the element fell
 * back to the inherited 16px. Chips rendered ~33% oversized wherever they were composed
 * through cn(), and at the correct 12px wherever the className happened to be a plain
 * string literal, which is what made type sizes look inconsistent between screens.
 *
 * Registering the presets explicitly is what stops the deletion. Everything that sets a
 * font-size shares one group so the presets also override *each other*: styles.css states
 * each token bundles size + weight + line-height and must never be split, so
 * cn("text-body", "heading-small") has to resolve to one winner, not a half-merged pair.
 */
const TYPE_PRESETS = [
  "text-body",
  "text-body-small",
  "text-body-large",
  "text-code",
  "heading-xxsmall",
  "heading-xsmall",
  "heading-small",
  "heading-medium",
  "heading-large",
  "heading-xlarge",
  "heading-xxlarge",
  "metric-small",
  "metric-medium",
  "metric-large",
];

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": TYPE_PRESETS,
      // 653, the Atlassian variable-font bold — not Tailwind's font-bold (700). Without
      // this it is read as a font-*family* and any `font-mono` beside it wins.
      "font-weight": ["font-weight-bold-token"],
      "border-w": ["border-width-default", "border-width-focused", "border-width-selected"],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Safe date label for KB timestamps that may be empty / invalid. */
export function formatKbDate(
  value: string | null | undefined,
  opts: Intl.DateTimeFormatOptions = { day: "2-digit", month: "short", year: "2-digit" },
): string {
  const raw = (value || "").trim();
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  // Pinned locale, matching formatDateTime: `undefined` follows the browser,
  // so the same timestamp rendered differently per user (and differently
  // between SSR and CSR).
  return d.toLocaleDateString("en-IN", opts);
}

export function formatKbDateTime(value: string | null | undefined): string {
  const raw = (value || "").trim();
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
