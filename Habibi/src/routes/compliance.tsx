import { useEffect, useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Lock, Download } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { ComplianceStatsStrip } from "@/components/compliance/ComplianceStatsStrip";
import { ComplianceFilters } from "@/components/compliance/ComplianceFilters";
import { ViolationTrendChart } from "@/components/compliance/ViolationTrendChart";
import { RuleBreakdown } from "@/components/compliance/RuleBreakdown";
import { RuleCoverageCard } from "@/components/compliance/RuleCoverageCard";
import { ViolationFeed } from "@/components/compliance/ViolationFeed";
import { ViolationSheet } from "@/components/compliance/ViolationSheet";
import {
  defaultCompFilters,
  filterViolations,
  type ComplianceFilterState,
  type Violation,
} from "@/data/compliance-seed";
import { Lozenge } from "@/components/ui/lozenge";
import {
  acknowledgeViolation,
  assignViolation,
  resolveViolation,
  useViolations,
} from "@/api/compliance";
import { currentActor } from "@/api/me";
import { humanNames, useStaff } from "@/api/staff";
import { apiGet, USE_MOCK } from "@/api/config";

export const Route = createFileRoute("/compliance")({
  validateSearch: (search: Record<string, unknown>): { callId?: string } => ({
    callId: typeof search.callId === "string" ? search.callId : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Compliance Risk — BigBound AI" },
      {
        name: "description",
        content:
          "QA workspace surfacing every call where a mandatory disclosure was missed or prohibited language was used, with severity-ranked evidence and resolution workflow.",
      },
      { property: "og:title", content: "Compliance Risk Dashboard" },
      {
        property: "og:description",
        content:
          "Rule-hit feed, trend chart, and resolve/acknowledge workflow for BFSI collections compliance.",
      },
    ],
  }),
  component: CompliancePage,
});

function CompliancePage() {
  const queryClient = useQueryClient();
  const { callId } = Route.useSearch();
  const { data: items = [] } = useViolations();
  const { data: staff = [] } = useStaff();
  const [filters, setFilters] = useState<ComplianceFilterState>(defaultCompFilters);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (!callId || !items.length) return;
    const hit = items.find((v) => v.callId === callId);
    if (hit) setOpenId(hit.id);
  }, [callId, items]);

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
      description:
        "Compliance report PDF (PII redacted, watermarked) will be ready in ~30 seconds.",
    });
  };

  const handlePolicyExport = async (fmt: "opa" | "cedar") => {
    try {
      const bundle = await apiGet<{ format: string; text: string }>(
        `/compliance/policy-export?fmt=${fmt}`,
      );
      const blob = new Blob([bundle.text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fmt === "cedar" ? "policy.cedar" : "policy.rego";
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Downloaded ${fmt.toUpperCase()} projection — live veto remains Python`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Policy export failed");
    }
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
          <div className="flex flex-wrap items-center gap-100">
            <h1 className="heading-medium font-semibold text-text">Compliance risk</h1>
            <Lozenge tone="neutral">
              <Lock className="h-3 w-3" /> Immutable evidence
            </Lozenge>
            <button
              onClick={handleExport}
              className="ml-auto inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest"
            >
              <Download className="h-3.5 w-3.5" /> Export compliance report
            </button>
            {!USE_MOCK ? (
              <>
                <button
                  onClick={() => void handlePolicyExport("opa")}
                  className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
                >
                  OPA bundle
                </button>
                <button
                  onClick={() => void handlePolicyExport("cedar")}
                  className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
                >
                  Cedar
                </button>
              </>
            ) : null}
          </div>
          <p className="text-body-small text-text-subtle">
            Every rule hit — disclosure misses, prohibited language, consent breaches — with
            transcript evidence, severity ranking, and resolution workflow. Policy export is a
            projection of live Python. This card cannot disable DND.
          </p>
        </header>

        <ComplianceStatsStrip all={items} filtered={filtered} />
        <ComplianceFilters
          filters={filters}
          onChange={setFilters}
          all={items}
          resultCount={filtered.length}
        />

        <div className="min-h-0 flex-1 overflow-y-auto bg-surface px-250 py-200">
          <div className="grid gap-200 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-200 min-w-0">
              {/* ChartCard is `h-full` by design — it is built for a fixed-height
                  dashboard tile and every other caller wraps it in one. Stacked
                  straight into this stretched grid item it resolved to the full
                  column height, so the chart claimed the whole left column and
                  pushed the violation feed below the scroll area: the page
                  reported "3 violations" over an empty panel. The <aside> was
                  unaffected only because `self-start` keeps it auto-height. */}
              <div className="h-[15rem]">
                <ViolationTrendChart all={items} />
              </div>
              <ViolationFeed
                items={filtered}
                onOpen={setOpenId}
                onAssign={(id) => void onAssign(id)}
                onAcknowledge={(id) => onAcknowledge(id)}
                onResolve={(id) => onResolve(id, "Resolved after review.")}
              />
            </div>
            <aside className="space-y-200 xl:sticky xl:top-0 xl:self-start">
              <RuleBreakdown all={items} selectedRuleId={filters.ruleId} onSelect={setRule} />
              <RuleCoverageCard selectedRuleId={filters.ruleId} onSelect={setRule} />
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
