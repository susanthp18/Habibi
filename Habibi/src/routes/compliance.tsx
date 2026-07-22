import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { Lock, Download } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { ComplianceStatsStrip } from "@/components/compliance/ComplianceStatsStrip";
import { ComplianceFilters } from "@/components/compliance/ComplianceFilters";
import { ViolationTrendChart } from "@/components/compliance/ViolationTrendChart";
import { RuleBreakdown } from "@/components/compliance/RuleBreakdown";
import { ViolationFeed } from "@/components/compliance/ViolationFeed";
import { ViolationSheet } from "@/components/compliance/ViolationSheet";
import {
  violations as seedViolations,
  defaultCompFilters,
  filterViolations,
  type ComplianceFilterState,
  type Violation,
} from "@/data/compliance-seed";

export const Route = createFileRoute("/compliance")({
  head: () => ({
    meta: [
      { title: "Compliance Risk — Collections Agent" },
      {
        name: "description",
        content: "QA workspace surfacing every call where a mandatory disclosure was missed or prohibited language was used, with severity-ranked evidence and resolution workflow.",
      },
      { property: "og:title", content: "Compliance Risk Dashboard" },
      { property: "og:description", content: "Rule-hit feed, trend chart, and resolve/acknowledge workflow for BFSI collections compliance." },
    ],
  }),
  component: CompliancePage,
});

function CompliancePage() {
  const [items, setItems] = useState<Violation[]>(seedViolations);
  const [filters, setFilters] = useState<ComplianceFilterState>(defaultCompFilters);
  const [openId, setOpenId] = useState<string | null>(null);

  const filtered = useMemo(() => filterViolations(items, filters), [items, filters]);
  const openItem = useMemo(() => items.find((v) => v.id === openId) ?? null, [items, openId]);

  const setRule = (ruleId: "all" | string) => setFilters({ ...filters, ruleId });

  const nowIso = () => new Date().toISOString();

  const applyPatch = (id: string, patch: Partial<Violation>, noteAuthor: string, noteText: string) => {
    setItems((prev) =>
      prev.map((v) =>
        v.id === id
          ? {
              ...v,
              ...patch,
              notes: noteText ? [...v.notes, { at: nowIso(), author: noteAuthor, text: noteText }] : v.notes,
            }
          : v,
      ),
    );
  };

  const onAssign = (id: string, assignee = "Compliance Ops", note = "Assigned for review.") => {
    applyPatch(id, { status: "in_review", assignee }, "You", note);
    toast.success("Assigned for review", { description: `${id} → ${assignee}` });
  };
  const onAcknowledge = (id: string, note = "Acknowledged.") => {
    applyPatch(id, { status: "acknowledged" }, "You", note);
    toast.success("Acknowledged", { description: id });
  };
  const onResolve = (id: string, note = "Resolved.") => {
    applyPatch(id, { status: "resolved" }, "You", note);
    toast.success("Marked resolved", { description: id });
  };

  const handleExport = () => {
    toast.success(`Exporting ${filtered.length} violation${filtered.length === 1 ? "" : "s"}`, {
      description: "Compliance report PDF (PII redacted, watermarked) will be ready in ~30 seconds.",
    });
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[18px] font-semibold text-brand-navy">Compliance Risk</h1>
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">
              <Lock className="h-3 w-3" /> Immutable evidence
            </span>
            <button
              onClick={handleExport}
              className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-3 py-1.5 text-[12px] text-brand-primary hover:bg-brand-tint"
            >
              <Download className="h-3.5 w-3.5" /> Export compliance report
            </button>
          </div>
          <p className="text-[12px] text-text-secondary">
            Every rule hit — disclosure misses, prohibited language, consent breaches — with transcript evidence, severity ranking, and resolution workflow.
          </p>
        </header>

        <ComplianceStatsStrip all={items} filtered={filtered} />
        <ComplianceFilters filters={filters} onChange={setFilters} all={items} resultCount={filtered.length} />

        <div className="min-h-0 flex-1 overflow-y-auto bg-surface-app px-5 py-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-4 min-w-0">
              <ViolationTrendChart all={items} />
              <ViolationFeed
                items={filtered}
                onOpen={setOpenId}
                onAssign={(id) => onAssign(id)}
                onAcknowledge={(id) => onAcknowledge(id)}
                onResolve={(id) => onResolve(id)}
              />
            </div>
            <aside className="space-y-4 xl:sticky xl:top-0 xl:self-start">
              <RuleBreakdown all={items} selectedRuleId={filters.ruleId} onSelect={setRule} />
            </aside>
          </div>
        </div>
      </div>

      <ViolationSheet
        v={openItem}
        onClose={() => setOpenId(null)}
        onAssign={onAssign}
        onAcknowledge={onAcknowledge}
        onResolve={onResolve}
      />
    </AppShell>
  );
}
