import { Plus, Calendar, Link2, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CoachingAction, CoachingStatus } from "@/data/qa-seed";

const COLS: Array<{ key: CoachingStatus; label: string; tint: string }> = [
  { key: "assigned", label: "Assigned", tint: "bg-amber-50 text-amber-800" },
  { key: "in_progress", label: "In Progress", tint: "bg-brand-tint text-brand-primary-dark" },
  { key: "done", label: "Done", tint: "bg-emerald-50 text-emerald-800" },
];

function daysUntil(iso: string) {
  const d = Math.round((new Date(iso).getTime() - Date.now()) / 86400_000);
  return d;
}

export function CoachingBoard({
  actions,
  onMove,
  onNew,
  onOpen,
}: {
  actions: CoachingAction[];
  onMove: (id: string, status: CoachingStatus) => void;
  onNew: () => void;
  onOpen: (id: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[12px] text-text-secondary">Assign actions to agents; drag between columns to update status.</div>
        <button
          onClick={onNew}
          className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-2.5 py-1 text-[12px] font-medium text-white hover:bg-brand-primary-dark"
        >
          <Plus className="h-3.5 w-3.5" /> New coaching action
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {COLS.map((col) => {
          const items = actions.filter((a) => a.status === col.key);
          return (
            <div
              key={col.key}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                const id = e.dataTransfer.getData("text/plain");
                if (id) onMove(id, col.key);
              }}
              className="flex min-h-[300px] flex-col rounded-lg border border-[var(--border-token)] bg-surface-card"
            >
              <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", col.tint)}>{col.label}</span>
                  <span className="text-[11px] text-text-muted">{items.length}</span>
                </div>
              </div>
              <div className="flex-1 space-y-2 p-2">
                {items.map((a) => {
                  const d = daysUntil(a.dueAt);
                  const overdue = d < 0 && col.key !== "done";
                  return (
                    <div
                      key={a.id}
                      draggable
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", a.id)}
                      onClick={() => onOpen(a.id)}
                      className="group cursor-pointer rounded-md border border-[var(--border-token)] bg-surface-card px-2.5 py-2 shadow-sm hover:border-brand-primary"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-[12.5px] font-medium text-brand-navy">{a.title}</div>
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-muted opacity-0 group-hover:opacity-100" />
                      </div>
                      <div className="mt-1 text-[11px] text-text-secondary">{a.agentId} · {a.category}</div>
                      <div className="mt-1.5 flex items-center gap-2 text-[11px]">
                        <span className={cn("inline-flex items-center gap-1", overdue ? "text-red-700" : "text-text-muted")}>
                          <Calendar className="h-3 w-3" /> {overdue ? `${Math.abs(d)}d overdue` : d === 0 ? "Due today" : `${d}d left`}
                        </span>
                        {a.callId && (
                          <span className="inline-flex items-center gap-1 text-text-muted">
                            <Link2 className="h-3 w-3" /> Call
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
                {items.length === 0 && (
                  <div className="p-6 text-center text-[11px] text-text-muted">Drop cards here.</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
