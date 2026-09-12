import type { ReactNode } from "react";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The bar above a records list: a search box, the screen's own controls, and
 * a reset once anything is set. Six screens declared this shell for
 * themselves; they pass the controls now.
 */
export function FiltersBar({
  search,
  onSearch,
  placeholder,
  activeCount = 0,
  onReset,
  className,
  children,
}: {
  search?: string;
  onSearch?: (value: string) => void;
  placeholder?: string;
  /** How many filters are set; the reset shows when it is above zero. */
  activeCount?: number;
  onReset?: () => void;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex shrink-0 flex-wrap items-center gap-100 rounded-large border border-border bg-surface px-150 py-100",
        className,
      )}
    >
      {onSearch && (
        <div className="relative min-w-[13.75rem] flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <Input
            aria-label="Search"
            value={search ?? ""}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={placeholder}
            size="compact"
            className="pl-400"
          />
        </div>
      )}
      {children}
      {onReset && activeCount > 0 && (
        <Button size="sm" variant="ghost" className="h-400" onClick={onReset}>
          <X className="mr-050 h-3 w-3" /> Reset ({activeCount})
        </Button>
      )}
    </div>
  );
}

/** A labelled run of chips inside the bar. */
export function FilterGroup({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-050">
      {label && <span className="text-body-small text-text-subtlest">{label}</span>}
      {children}
    </div>
  );
}
