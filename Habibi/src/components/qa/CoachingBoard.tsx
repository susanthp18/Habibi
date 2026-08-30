import { Plus, Calendar, Link2, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CoachingAction, CoachingStatus } from "@/data/qa-seed";

const COLS: Array<{ key: CoachingStatus; label: string; tint: string }> = [
  {
    key: "assigned",
    label: "Assigned",
    tint: "bg-background-warning-subtler text-text-warning-bolder",
  },
  {
    key: "in_progress",
    label: "In progress",
    tint: "bg-background-brand-subtlest text-text-brand",
  },
  { key: "done", label: "Done", tint: "bg-background-success-subtler text-text-success-bolder" },
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
    <div className="space-y-150">
      <div className="flex items-center justify-between">
        <div className="text-body-small text-text-subtle">
          Assign actions to agents; drag between columns to update status.
        </div>
        <button
          onClick={onNew}
          className="inline-flex items-center gap-050 rounded-medium bg-background-brand-bold px-150 py-050 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed"
        >
          <Plus className="h-3.5 w-3.5" /> New coaching action
        </button>
      </div>
      <div className="grid gap-150 md:grid-cols-3">
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
              className="flex min-h-[18.75rem] flex-col rounded-large border border-border bg-surface"
            >
              <div className="flex items-center justify-between border-b border-border px-150 py-100">
                <div className="flex items-center gap-100">
                  <span
                    className={cn(
                      "rounded-full px-100 py-025 text-body-small font-semibold",
                      col.tint,
                    )}
                  >
                    {col.label}
                  </span>
                  <span className="text-body-small text-text-subtlest">{items.length}</span>
                </div>
              </div>
              <div className="flex-1 space-y-100 p-100">
                {items.map((a) => {
                  const d = daysUntil(a.dueAt);
                  const overdue = d < 0 && col.key !== "done";
                  return (
                    <div
                      key={a.id}
                      draggable
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", a.id)}
                      onClick={() => onOpen(a.id)}
                      className="group cursor-pointer rounded-medium border border-border bg-surface px-150 py-100 hover:border-border-brand"
                    >
                      <div className="flex items-start justify-between gap-100">
                        <div className="text-body-small font-medium text-text">{a.title}</div>
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-subtlest opacity-0 group-hover:opacity-100" />
                      </div>
                      <div className="mt-050 text-body-small text-text-subtle">
                        {a.agentId} · {a.category}
                      </div>
                      <div className="mt-075 flex items-center gap-100 text-body-small">
                        <span
                          className={cn(
                            "inline-flex items-center gap-050",
                            overdue ? "text-text-danger-bolder" : "text-text-subtlest",
                          )}
                        >
                          <Calendar className="h-3 w-3" />{" "}
                          {overdue
                            ? `${Math.abs(d)}d overdue`
                            : d === 0
                              ? "Due today"
                              : `${d}d left`}
                        </span>
                        {a.callId && (
                          <span className="inline-flex items-center gap-050 text-text-subtlest">
                            <Link2 className="h-3 w-3" /> Call
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
                {items.length === 0 && (
                  <div className="p-300 text-center text-body-small text-text-subtlest">
                    Drop cards here.
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
