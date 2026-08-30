import type { Rule } from "@/data/routing-seed";

export function RoutingStats({ rules }: { rules: Rule[] }) {
  const active = rules.filter((r) => r.enabled).length;
  const total = rules.length;
  const triggers = rules.reduce((s, r) => s + r.triggersLast24h, 0);
  const cards = [
    { label: "Active rules", value: active, sub: `${total - active} disabled` },
    { label: "Total rules", value: total, sub: "in library" },
    { label: "Triggers · 24h", value: triggers.toLocaleString(), sub: "across all rules" },
    { label: "Avg latency", value: "0.31 ms", sub: "per evaluation" },
  ];
  return (
    <div className="grid grid-cols-2 gap-150 md:grid-cols-4">
      {cards.map((c) => (
        <div key={c.label} className="rounded-large border border-border bg-surface p-150">
          <div className="text-body-small font-medium text-text-subtlest">{c.label}</div>
          <div className="mt-050 heading-large font-semibold text-text">{c.value}</div>
          <div className="text-body-small text-text-subtle">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
