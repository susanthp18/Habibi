import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
  defaultCompFilters,
  filterViolations,
  type ComplianceFilterState,
  type Violation,
} from "@/data/compliance-seed";
import {
  acknowledgeViolation,
  assignViolation,
  resolveViolation,
  useViolations,
} from "@/api/compliance";
import { currentActor } from "@/api/me";
import { humanNames, useStaff } from "@/api/staff";
import { USE_MOCK } from "@/api/config";

export const Route = createFileRoute("/compliance")({
  head: () => ({
    meta: [
      { title: "Compliance Risk — Collections Agent" },
      {
        name: "description",
        content:
          "QA workspace surfacing every call where a mandatory disclosure was missed or prohibited language was used, with severity-ranked evidence and resolution workflow.",
      },
      { property: "og:title", content: "Compliance Risk Dashboard" },
      {
        property: "og:description",
        content: "Rule-hit feed, trend chart, and resolve/acknowledge workflow for BFSI collections compliance.",
      },
    ],
  }),
  component: CompliancePage,
});

function CompliancePage() {
  const queryClient = useQueryClient();
  const { data: items = [] } = useViolations();
  const { data: staff = [] } = useStaff();
  const [filters, setFilters] = useState<ComplianceFilterState>(defaultCompFilters);
  const [openId, setOpenId] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["violations"] });
  };

  const assignees = useMemo(() => {
    if (!USE_MOCK) return humanNames(staff);
    // Mock: prefer real staff names; fall back to names already on seed rows.
    const fromStaff = humanNames(staff);
    if (fromStaff.length) return fromStaff;
    return Array.from(new Set(items.map((v) => v.assignee).filter(Boolean) as string[])).sort();
  }, [items, staff]);

  const filtered = useMemo(() => filterViolations(items, filters), [items, filters]);
  const openItem = useMemo(() => items.find((v) => v.id === openId) ?? null, [items, openId]);

  const setRule = (ruleId: "all" | string) => setFilters({ ...filters, ruleId });

  const assignMutation = useMutation({
    mutationFn: (v: { item: Violation; assignee: string; note: string }) =>
      assignViolation(v.item, v.assignee, v.note),
    onSuccess: (_d, vars) => {
      invalidate();
      toast.success("Assigned for review", { description: `${vars.item.id} → ${vars.assignee}` });
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Assign failed"),
  });

  const acknowledgeMutation = useMutation({
    mutationFn: (v: { item: Violation; note: string }) => acknowledgeViolation(v.item, v.note),
    onSuccess: (_d, vars) => {
      invalidate();
      toast.success("Acknowledged", { description: vars.item.id });
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Acknowledge failed"),
  });

  const resolveMutation = useMutation({
    mutationFn: (v: { item: Violation; note: string }) => resolveViolation(v.item, v.note),
    onSuccess: (_d, vars) => {
      invalidate();
      toast.success("Marked resolved", { description: vars.item.id });
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Resolve failed"),
  });

  const onAssign = async (id: string, assignee?: string, note = "Assigned for review.") => {
    const item = items.find((v) => v.id === id);
    if (!item) return;
    let target = assignee;
    if (!target) {
      // Quick-assign from the feed card → acting user (never a hardcoded roster name).
      const me = await currentActor();
      target = me.name;
    }
    assignMutation.mutate({ item, assignee: target, note });
  };

  const onAcknowledge = (id: string, note = "Acknowledged.") => {
    const item = items.find((v) => v.id === id);
    if (!item) return;
    acknowledgeMutation.mutate({ item, note });
  };

  const onResolve = (id: string, note: string) => {
    const item = items.find((v) => v.id === id);
    if (!item) return;
    resolveMutation.mutate({ item, note });
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
                onAssign={(id) => void onAssign(id)}
                onAcknowledge={(id) => onAcknowledge(id)}
                onResolve={(id) => onResolve(id, "Resolved after review.")}
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
        assignees={assignees}
      />
    </AppShell>
  );
}
