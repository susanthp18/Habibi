import { useState } from "react";
import { toast } from "sonner";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  disputes,
  callbacks,
  docRequests,
  brokenPtps,
  type QueueRow,
  type SlaLevel,
} from "@/data/workspace-seed";

type TabKey = "disputes" | "callbacks" | "docs" | "ptps";

const tabs: { key: TabKey; label: string; rows: QueueRow[] }[] = [
  { key: "disputes", label: "Disputes", rows: disputes },
  { key: "callbacks", label: "Callbacks", rows: callbacks },
  { key: "docs", label: "Doc requests", rows: docRequests },
  { key: "ptps", label: "Broken PTPs", rows: brokenPtps },
];

const slaStyles: Record<SlaLevel, string> = {
  ok: "bg-success-bg text-success",
  warn: "bg-warning-bg text-warning",
  breach: "bg-danger-bg text-danger",
};

export function AssignedQueue() {
  const [active, setActive] = useState<TabKey>("disputes");
  const current = tabs.find((t) => t.key === active)!;

  return (
    <section className="rounded-[10px] border border-[var(--border-token)] bg-surface-card shadow-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-5 py-3">
        <div>
          <h2 className="text-[15px] font-semibold text-brand-navy">My assigned queue</h2>
          <p className="text-[12px] text-text-secondary">Items routed to you across channels</p>
        </div>
        <button
          type="button"
          onClick={() => toast("Filters coming soon")}
          className="text-[12px] font-medium text-brand-primary hover:underline"
        >
          Filters
        </button>
      </div>

      <div className="flex gap-1 border-b border-[var(--border-token)] px-3">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActive(t.key)}
            className={cn(
              "relative px-3 py-2.5 text-[13px] font-medium transition-colors",
              active === t.key
                ? "text-brand-primary"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {t.label}
            <span className="ml-1.5 rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
              {t.rows.length}
            </span>
            {active === t.key && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-primary" />
            )}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[13px] tabular">
          <thead>
            <tr className="text-left text-[11px] font-semibold uppercase tracking-[0.4px] text-text-muted">
              <th className="px-5 py-2.5">Customer</th>
              <th className="px-3 py-2.5">Type</th>
              <th className="px-3 py-2.5">Detail</th>
              <th className="px-3 py-2.5 text-right">Amount</th>
              <th className="px-3 py-2.5">SLA</th>
              <th className="px-3 py-2.5">Age</th>
              <th className="px-5 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {current.rows.map((row, i) => (
              <tr
                key={row.id}
                className="animate-fade-up border-t border-[var(--border-token)] transition-colors hover:bg-brand-tint/60"
                style={{ animationDelay: `${i * 30}ms` }}
              >
                <td className="px-5 py-3">
                  <div className="font-semibold text-text-primary">{row.customer}</div>
                  <div className="font-mono text-[11px] text-text-muted">{row.accountId}</div>
                </td>
                <td className="px-3 py-3 text-text-primary">{row.type}</td>
                <td className="px-3 py-3 text-text-secondary">{row.detail}</td>
                <td className="px-3 py-3 text-right font-mono font-semibold text-text-primary">
                  {row.amount ? `₹${row.amount.toLocaleString("en-IN")}` : "—"}
                </td>
                <td className="px-3 py-3">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
                      slaStyles[row.sla],
                    )}
                  >
                    {row.slaLabel}
                  </span>
                </td>
                <td className="px-3 py-3 text-text-secondary">{row.ageHours}h</td>
                <td className="px-5 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => toast(`Opening ${row.id} · ${row.customer}`)}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-white px-2.5 py-1 text-[12px] font-medium text-brand-primary hover:bg-brand-tint"
                  >
                    Open
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
