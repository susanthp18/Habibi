import { useMemo, useState } from "react";
import { Search, Bot, User, Users2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { computeTotal, type Rubric, type Scorecard } from "@/data/qa-seed";
import { ScoreBand } from "./ScoreBand";
import { Lozenge } from "@/components/ui/lozenge";

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
    <div className="flex h-full min-h-0 w-full flex-col border-r border-border bg-surface">
      <div className="shrink-0 space-y-100 border-b border-border px-150 py-150">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search customer, agent, disposition…"
            className="w-full rounded-medium border border-border bg-surface py-075 pl-400 pr-100 text-body-small outline-none focus:border-border-brand"
          />
        </div>
        <div className="flex flex-wrap gap-050">
          {(["all", "unscored", "ai_draft", "final"] as Status[]).map((s) => (
            <button
              key={s}
              onClick={() => setStatus(s)}
              className={cn(
                "rounded-full border px-100 py-025 text-body-small",
                status === s ? "border-border-brand bg-background-brand-subtlest text-text-brand" : "border-border text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {s === "all" ? "All" : s === "ai_draft" ? "AI draft" : s === "final" ? "Final" : "Unscored"}
            </button>
          ))}
          <span className="mx-050 h-4 w-px bg-border" />
          {(["all", "bot", "human", "handoff"] as const).map((h) => (
            <button
              key={h}
              onClick={() => setHandler(h)}
              className={cn(
                "rounded-full border px-100 py-025 text-body-small capitalize",
                handler === h ? "border-border-brand bg-background-brand-subtlest text-text-brand" : "border-border text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {h}
            </button>
          ))}
        </div>
        <div className="text-body-small text-text-subtlest">{filtered.length} calls</div>
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
                "flex w-full flex-col gap-050 border-b border-border px-150 py-150 text-left hover:bg-surface-sunken",
                activeId === s.id && "bg-background-brand-subtlest hover:bg-background-brand-subtlest",
              )}
            >
              <div className="flex items-center justify-between gap-100">
                <div className="truncate text-body font-medium text-text">{s.customerName}</div>
                {s.status === "final" ? <ScoreBand total={total} size="sm" /> : (
                  <Lozenge tone={s.status === "unscored" ? "neutral" : "warning"}>
                    {s.status === "unscored" ? "Unscored" : "AI draft"}
                  </Lozenge>
                )}
              </div>
              <div className="flex items-center gap-075 text-body-small text-text-subtle">
                <HandlerIcon className="h-3 w-3" />
                <span className="truncate">{s.handledBy.label}</span>
                <span className="text-text-subtlest">·</span>
                <span className="truncate">{s.disposition}</span>
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="px-200 py-400 text-center text-body-small text-text-subtlest">No calls match these filters.</div>
        )}
      </div>
    </div>
  );
}
