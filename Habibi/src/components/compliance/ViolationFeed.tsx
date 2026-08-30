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
      <div className="flex h-full flex-col items-center justify-center gap-100 rounded-medium border border-dashed border-border bg-surface p-500 text-center">
        <ShieldCheck className="h-400 w-400 text-text-success" />
        <div className="text-body font-semibold text-text">No violations match these filters</div>
        <div className="text-body-small text-text-subtlest">
          Compliance is clean for the current scope.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-100">
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
