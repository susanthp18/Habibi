import type { Rule } from "@/data/routing-seed";

export function RoutingStats({ rules }: { rules: Rule[] }) {
  const active = rules.filter(r => r.enabled).length;
  const total = rules.length;
  const triggers = rules.reduce((s, r) => s + r.triggersLast24h, 0);
  const cards = [
    { label: "Active rules", value: active, sub: `${total - active} disabled` },
    { label: "Total rules", value: total, sub: "in library" },
    { label: "Triggers · 24h", value: triggers.toLocaleString(), sub: "across all rules" },
    { label: "Avg latency", value: "0.31 ms", sub: "per evaluation" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {cards.map(c => (
        <div key={c.label} className="rounded-lg border border-[var(--border-token)] bg-surface-card p-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-text-muted">{c.label}</div>
          <div className="mt-1 text-[22px] font-semibold text-brand-navy">{c.value}</div>
          <div className="text-[11px] text-text-secondary">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
