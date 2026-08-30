import { cn } from "@/lib/utils";

/** Stable hue palette from Design.md accent tokens — decorative classification only. */
const HUE_DOT: Record<string, string> = {
  lime: "var(--icon-accent-lime)",
  red: "var(--icon-accent-red)",
  orange: "var(--icon-accent-orange)",
  yellow: "var(--icon-accent-yellow)",
  green: "var(--icon-accent-green)",
  teal: "var(--icon-accent-teal)",
  blue: "var(--icon-accent-blue)",
  purple: "var(--icon-accent-purple)",
  magenta: "var(--icon-accent-magenta)",
  gray: "var(--icon-accent-gray)",
};

const HUE_ORDER = Object.keys(HUE_DOT);

/** Deterministic hue from a label so the same product/category always matches. */
export function tagHueFor(label: string): string {
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  return HUE_ORDER[hash % HUE_ORDER.length]!;
}

const PRODUCT_HUE: Record<string, string> = {
  "Personal Loan": "blue",
  "Credit Card": "purple",
  "Auto Loan": "teal",
  "Home Loan": "green",
  "Business Loan": "orange",
};

export function RecordsTag({
  name,
  hue,
  className,
}: {
  name: string;
  hue?: string;
  className?: string;
}) {
  const resolved = hue ?? PRODUCT_HUE[name] ?? tagHueFor(name);
  const color = HUE_DOT[resolved] ?? HUE_DOT.gray;
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-050 whitespace-nowrap rounded-small border border-border bg-surface px-075 py-025 text-body-small text-text",
        className,
      )}
    >
      <span
        className="h-150 w-150 shrink-0 rounded-full"
        style={{ background: color }}
        aria-hidden
      />
      <span className="truncate">{name}</span>
    </span>
  );
}
