import type { Persona } from "@/data/sandbox-seed";

type Props = { persona: Persona; scenarioTitle: string };

export function PersonaCard({ persona, scenarioTitle }: Props) {
  const initials = persona.name.split(" ").map((s) => s[0]).slice(0, 2).join("");
  return (
    <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-sunken px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-full bg-brand-primary/10 text-[13px] font-semibold text-brand-primary-dark">
          {initials || "??"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="truncate text-[13px] font-semibold text-text-primary">{persona.name}</div>
            <span className="rounded-full bg-surface-card px-1.5 py-0.5 text-[10px] font-medium capitalize text-text-secondary">
              {persona.mood}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
            <span>•••{persona.phoneLast4}</span>
            <span>{persona.product}</span>
            {persona.dpd > 0 && <span>DPD {persona.dpd}</span>}
            {persona.overdue > 0 && <span>₹{persona.overdue.toLocaleString()} overdue</span>}
            <span>{persona.language}</span>
          </div>
        </div>
        <div className="text-right text-[11px] text-text-muted">
          Speaking as customer<br />
          <span className="text-text-secondary">{scenarioTitle}</span>
        </div>
      </div>
    </div>
  );
}
