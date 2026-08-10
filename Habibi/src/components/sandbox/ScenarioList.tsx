import { useState } from "react";
import { Search } from "lucide-react";
import type { Difficulty, Scenario } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const DIFF_COLOR: Record<Difficulty, LozengeTone> = {
  easy: "success",
  medium: "warning",
  hard: "danger",
};

type Props = {
  scenarios: Scenario[];
  activeId: string;
  onSelect: (id: string) => void;
};

export function ScenarioList({ scenarios, activeId, onSelect }: Props) {
  const [q, setQ] = useState("");
  const filtered = scenarios.filter(
    (s) =>
      !q ||
      s.title.toLowerCase().includes(q.toLowerCase()) ||
      s.summary.toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <aside className="hidden h-full min-h-0 w-[17.5rem] shrink-0 flex-col border-r border-border bg-surface lg:flex">
      <div className="shrink-0 border-b border-border p-150">
        <div className="text-body-small font-semibold text-text-subtlest">
          Scenarios
        </div>
        <div className="relative mt-075">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search scenarios…"
            className="w-full rounded-medium border border-border bg-surface py-075 pl-400 pr-100 text-body-small focus:outline-none focus:ring-2 focus:ring-border-brand/30"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-100">
        {filtered.length === 0 && (
          <div className="p-150 text-center text-body-small text-text-subtlest">No scenarios.</div>
        )}
        {filtered.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              "mb-050 w-full rounded-medium border p-150 text-left transition",
              activeId === s.id
                ? "border-border-brand bg-background-brand-subtlest/50"
                : "border-transparent hover:border-border hover:bg-surface-sunken",
            )}
          >
            <div className="flex items-start gap-100">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[0.75rem] font-medium text-text">{s.title}</div>
                <div className="mt-025 line-clamp-2 text-body-small text-text-subtlest">{s.summary}</div>
              </div>
              <Lozenge
                tone={DIFF_COLOR[s.difficulty]}
                className="capitalize"
              >
                {s.difficulty}
              </Lozenge>
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
