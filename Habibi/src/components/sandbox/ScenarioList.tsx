import { useState } from "react";
import { Search } from "lucide-react";
import { SCENARIOS, type Difficulty } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";

const DIFF_COLOR: Record<Difficulty, string> = {
  easy: "bg-emerald-50 text-emerald-700",
  medium: "bg-amber-50 text-amber-700",
  hard: "bg-red-50 text-red-700",
};

type Props = {
  activeId: string;
  onSelect: (id: string) => void;
};

export function ScenarioList({ activeId, onSelect }: Props) {
  const [q, setQ] = useState("");
  const filtered = SCENARIOS.filter((s) =>
    !q || s.title.toLowerCase().includes(q.toLowerCase()) || s.summary.toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <aside className="hidden h-full min-h-0 w-[280px] shrink-0 flex-col border-r border-[var(--border-token)] bg-surface-card lg:flex">
      <div className="shrink-0 border-b border-[var(--border-token)] p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Scenarios</div>
        <div className="relative mt-1.5">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search scenarios…"
            className="w-full rounded-md border border-[var(--border-token)] bg-surface-card py-1.5 pl-7 pr-2 text-[12.5px] focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {filtered.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              "mb-1 w-full rounded-md border p-2.5 text-left transition",
              activeId === s.id
                ? "border-brand-primary bg-brand-tint/50"
                : "border-transparent hover:border-[var(--border-token)] hover:bg-surface-sunken",
            )}
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] font-medium text-text-primary">{s.title}</div>
                <div className="mt-0.5 line-clamp-2 text-[11px] text-text-muted">{s.summary}</div>
              </div>
              <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-medium capitalize", DIFF_COLOR[s.difficulty])}>
                {s.difficulty}
              </span>
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
