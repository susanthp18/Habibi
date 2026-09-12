import type { PiiEntityType, RedactionRules } from "@/api/types/redaction";
import { ENTITY_TYPES, ENTITY_COLORS } from "@/lib/redaction";
import { cn } from "@/lib/utils";

interface Props {
  rules: RedactionRules;
  active?: Set<PiiEntityType>;
  onToggle?: (t: PiiEntityType) => void;
  compact?: boolean;
}

export function PiiLegend({ rules, active, onToggle, compact }: Props) {
  return (
    <div className={cn("flex flex-wrap gap-075", compact && "gap-050")}>
      {ENTITY_TYPES.map((t) => {
        const isActive = !active || active.has(t);
        return (
          <button
            key={t}
            type="button"
            onClick={() => onToggle?.(t)}
            className={cn(
              "inline-flex items-center gap-075 rounded-full border px-100 py-025 text-body-small transition-colors",
              isActive
                ? "border-transparent bg-surface-sunken text-text"
                : "border-dashed border-border bg-transparent text-text-subtlest line-through",
              onToggle && "cursor-pointer hover:bg-background-brand-subtlest",
            )}
          >
            <span className="h-100 w-100 rounded-full" style={{ background: ENTITY_COLORS[t] }} />
            {rules[t].label}
          </button>
        );
      })}
    </div>
  );
}
