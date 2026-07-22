import { ENTITY_TYPES, ENTITY_COLORS, DEFAULT_RULES, type PiiEntityType } from "@/data/redaction-seed";
import { cn } from "@/lib/utils";

interface Props {
  active?: Set<PiiEntityType>;
  onToggle?: (t: PiiEntityType) => void;
  compact?: boolean;
}

export function PiiLegend({ active, onToggle, compact }: Props) {
  return (
    <div className={cn("flex flex-wrap gap-1.5", compact && "gap-1")}>
      {ENTITY_TYPES.map((t) => {
        const isActive = !active || active.has(t);
        return (
          <button
            key={t}
            type="button"
            onClick={() => onToggle?.(t)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition-colors",
              isActive
                ? "border-transparent bg-surface-sunken text-text-primary"
                : "border-dashed border-[var(--border-token)] bg-transparent text-text-muted line-through",
              onToggle && "cursor-pointer hover:bg-brand-tint",
            )}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: ENTITY_COLORS[t] }} />
            {DEFAULT_RULES[t].label}
          </button>
        );
      })}
    </div>
  );
}
