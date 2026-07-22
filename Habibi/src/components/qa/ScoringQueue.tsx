import { useMemo, useState } from "react";
import { Search, Bot, User, Users2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { computeTotal, type Rubric, type Scorecard } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";

type Status = "all" | "unscored" | "ai_draft" | "final";

export function ScoringQueue({
  scorecards,
  activeId,
  onSelect,
  rubric,
}: {
  scorecards: Scorecard[];
  activeId: string | null;
  onSelect: (id: string) => void;
  rubric: Rubric;
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<Status>("all");
  const [handler, setHandler] = useState<"all" | "bot" | "human" | "handoff">("all");

  const filtered = useMemo(() => {
    return scorecards.filter((s) => {
      if (status !== "all" && s.status !== status) return false;
      if (handler !== "all" && s.handledBy.kind !== handler) return false;
      if (q) {
        const t = q.toLowerCase();
        if (!s.customerName.toLowerCase().includes(t) && !s.agentId.toLowerCase().includes(t) && !s.disposition.toLowerCase().includes(t)) return false;
      }
      return true;
    });
  }, [scorecards, q, status, handler]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col border-r border-[var(--border-token)] bg-surface-card">
      <div className="shrink-0 space-y-2 border-b border-[var(--border-token)] px-3 py-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search customer, agent, disposition…"
            className="w-full rounded-md border border-[var(--border-token)] bg-surface-app py-1.5 pl-7 pr-2 text-[12px] outline-none focus:border-brand-primary"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          {(["all", "unscored", "ai_draft", "final"] as Status[]).map((s) => (
            <button
              key={s}
              onClick={() => setStatus(s)}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px]",
                status === s ? "border-brand-primary bg-brand-tint text-brand-primary-dark" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {s === "all" ? "All" : s === "ai_draft" ? "AI draft" : s === "final" ? "Final" : "Unscored"}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-[var(--border-token)]" />
          {(["all", "bot", "human", "handoff"] as const).map((h) => (
            <button
              key={h}
              onClick={() => setHandler(h)}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] capitalize",
                handler === h ? "border-brand-primary bg-brand-tint text-brand-primary-dark" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {h}
            </button>
          ))}
        </div>
        <div className="text-[11px] text-text-muted">{filtered.length} calls</div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.map((s) => {
          const total = computeTotal(s, rubric);
          const HandlerIcon = s.handledBy.kind === "bot" ? Bot : s.handledBy.kind === "handoff" ? Users2 : User;
          return (
            <button
              key={s.id}
              onClick={() => onSelect(s.id)}
              className={cn(
                "flex w-full flex-col gap-1 border-b border-[var(--border-token)] px-3 py-2.5 text-left hover:bg-surface-sunken",
                activeId === s.id && "bg-brand-tint hover:bg-brand-tint",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="truncate text-[13px] font-medium text-brand-navy">{s.customerName}</div>
                {s.status === "final" ? <ScoreBand total={total} size="sm" /> : (
                  <span className={cn(
                    "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                    s.status === "unscored" ? "bg-surface-sunken text-text-secondary" : "bg-amber-50 text-amber-700",
                  )}>
                    {s.status === "unscored" ? "Unscored" : "AI draft"}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                <HandlerIcon className="h-3 w-3" />
                <span className="truncate">{s.handledBy.label}</span>
                <span className="text-text-muted">·</span>
                <span className="truncate">{s.disposition}</span>
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="px-4 py-8 text-center text-[12px] text-text-muted">No calls match these filters.</div>
        )}
      </div>
    </div>
  );
}
