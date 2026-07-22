import { ShieldCheck } from "lucide-react";
import { ViolationCard } from "./ViolationCard";
import type { Violation } from "@/data/compliance-seed";

export function ViolationFeed({
  items,
  onOpen,
  onAssign,
  onAcknowledge,
  onResolve,
}: {
  items: Violation[];
  onOpen: (id: string) => void;
  onAssign: (id: string) => void;
  onAcknowledge: (id: string) => void;
  onResolve: (id: string) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 rounded-md border border-dashed border-[var(--border-token)] bg-surface-card p-10 text-center">
        <ShieldCheck className="h-8 w-8 text-[color:var(--sentiment-positive)]" />
        <div className="text-[14px] font-semibold text-brand-navy">No violations match these filters</div>
        <div className="text-[12px] text-text-muted">Compliance is clean for the current scope.</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((v) => (
        <ViolationCard
          key={v.id}
          v={v}
          onOpen={() => onOpen(v.id)}
          onAssign={() => onAssign(v.id)}
          onAcknowledge={() => onAcknowledge(v.id)}
          onResolve={() => onResolve(v.id)}
        />
      ))}
    </div>
  );
}
