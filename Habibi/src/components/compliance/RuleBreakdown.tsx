import { groupByRule, severityColor, type Violation } from "@/data/compliance-seed";

export function RuleBreakdown({
  all,
  selectedRuleId,
  onSelect,
}: {
  all: Violation[];
  selectedRuleId: "all" | string;
  onSelect: (id: "all" | string) => void;
}) {
  const rows = groupByRule(all).slice(0, 8);
  const max = Math.max(1, ...rows.map((r) => r.count));

  return (
    <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <div>
          <div className="text-[13px] font-semibold text-brand-navy">Top rule hits</div>
          <div className="text-[11px] text-text-muted">Click to filter · open / total</div>
        </div>
        {selectedRuleId !== "all" && (
          <button
            className="text-[11px] text-brand-primary hover:underline"
            onClick={() => onSelect("all")}
          >
            Clear
          </button>
        )}
      </div>
      <ul className="space-y-2">
        {rows.map(({ rule, count, open }) => {
          const pct = (count / max) * 100;
          const active = selectedRuleId === rule.id;
          return (
            <li key={rule.id}>
              <button
                onClick={() => onSelect(active ? "all" : rule.id)}
                className={`w-full rounded-md px-2 py-1.5 text-left transition-colors ${
                  active ? "bg-brand-tint" : "hover:bg-surface-sunken"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[12px] font-medium text-brand-navy">{rule.label}</div>
                    <div className="text-[10px] font-mono text-text-muted">{rule.code}</div>
                  </div>
                  <div className="shrink-0 text-[11px] text-text-secondary">
                    <span className="font-semibold text-brand-navy">{open}</span> / {count}
                  </div>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${pct}%`, background: severityColor(rule.severity) }}
                  />
                </div>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && <li className="text-[12px] text-text-muted">No violations in scope.</li>}
      </ul>
    </div>
  );
}
