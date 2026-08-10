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
    <div className="rounded-medium border border-border bg-surface p-150">
      <div className="mb-100 flex items-baseline justify-between">
        <div>
          <div className="text-body font-semibold text-text">Top rule hits</div>
          <div className="text-body-small text-text-subtlest">Click to filter · open / total</div>
        </div>
        {selectedRuleId !== "all" && (
          <button
            className="text-body-small text-text-brand hover:underline"
            onClick={() => onSelect("all")}
          >
            Clear
          </button>
        )}
      </div>
      <ul className="space-y-100">
        {rows.map(({ rule, count, open }) => {
          const pct = (count / max) * 100;
          const active = selectedRuleId === rule.id;
          return (
            <li key={rule.id}>
              <button
                onClick={() => onSelect(active ? "all" : rule.id)}
                className={`w-full rounded-medium px-100 py-075 text-left transition-colors ${
                  active ? "bg-background-brand-subtlest" : "hover:bg-surface-sunken"
                }`}
              >
                <div className="flex items-baseline justify-between gap-100">
                  <div className="min-w-0">
                    <div className="truncate text-body-small font-medium text-text">{rule.label}</div>
                    <div className="text-body-small font-mono text-text-subtlest">{rule.code}</div>
                  </div>
                  <div className="shrink-0 text-body-small text-text-subtle">
                    <span className="font-semibold text-text">{open}</span> / {count}
                  </div>
                </div>
                <div className="mt-050 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${pct}%`, background: severityColor(rule.severity) }}
                  />
                </div>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && <li className="text-body-small text-text-subtlest">No violations in scope.</li>}
      </ul>
    </div>
  );
}
