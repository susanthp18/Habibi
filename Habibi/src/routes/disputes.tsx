import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertOctagon } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { MetricsStrip } from "@/components/disputes/MetricsStrip";
import { FiltersBar } from "@/components/disputes/FiltersBar";
import { DisputeBoard } from "@/components/disputes/DisputeBoard";
import { DisputeSheet } from "@/components/disputes/DisputeSheet";
import {
  CURRENT_AGENT,
  computeMetrics,
  defaultFilters,
  filterDisputes,
  STATUS_LABELS,
  type Dispute,
  type Filters,
} from "@/data/disputes-seed";
import {
  assignDispute,
  moveDispute,
  useDisputes,
} from "@/api/disputes";
import { humanNames, useStaff } from "@/api/staff";
import { useMe } from "@/api/me";
import { USE_MOCK } from "@/api/config";

export const Route = createFileRoute("/disputes")({
  head: () => ({
    meta: [
      { title: "Disputes & Exceptions Queue — Collections Agent" },
      {
        name: "description",
        content:
          "Triage disputes captured by the bot — paid-already, wrong amount, fee waivers, fraud — with SLA-aware Kanban, evidence, and CRM writeback.",
      },
      { property: "og:title", content: "Disputes & Exceptions Queue" },
      {
        property: "og:description",
        content: "Kanban of bot-captured disputes with SLA timers, assignment, evidence, and resolution.",
      },
    ],
  }),
  component: DisputesPage,
});

function DisputesPage() {
  const queryClient = useQueryClient();
  const { data: disputesData = [] } = useDisputes();
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [openId, setOpenId] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["disputes"] });
  };

  // Live mode: real people from the /staff roster. Mock: derive from seed rows.
  const { data: staff = [] } = useStaff();
  const { data: me } = useMe();
  const assignees = useMemo(() => {
    if (!USE_MOCK) return humanNames(staff);
    return Array.from(new Set(disputesData.map((d) => d.assignee))).sort();
  }, [disputesData, staff]);

  const filtered = useMemo(() => filterDisputes(disputesData, filters), [filters, disputesData]);
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);

  // Derive the open sheet from fetched data so it stays fresh after invalidation.
  const openDispute = openId ? disputesData.find((d) => d.id === openId) ?? null : null;

  const patchFilters = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }));

  const moveMutation = useMutation({
    mutationFn: (v: { d: Dispute; status: Dispute["status"] }) => moveDispute(v.d, v.status),
    onSuccess: (_r, v) => {
      invalidate();
      toast.success(`${v.d.customerName} → ${STATUS_LABELS[v.status]}`);
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Move failed"),
  });

  const assignMutation = useMutation({
    mutationFn: (v: { d: Dispute; assignee: string }) => assignDispute(v.d, v.assignee),
    onSuccess: (_r, v) => {
      invalidate();
      toast.success(`Assigned to ${v.assignee} · ${v.d.id}`);
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Assign failed"),
  });

  const handleDrop = (id: string, status: Dispute["status"]) => {
    const d = disputesData.find((x) => x.id === id);
    if (!d || d.status === status) return;
    moveMutation.mutate({ d, status });
  };

  // "Assign to me" must mean the real acting user, not a seed constant —
  // otherwise the assignment disagrees with the actor recorded on the write.
  const handleAssignMe = (d: Dispute) => {
    assignMutation.mutate({ d, assignee: me?.name ?? CURRENT_AGENT });
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col gap-3 p-3">
        <header className="shrink-0 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertOctagon className="h-5 w-5 text-brand-primary" />
            <div>
              <h1 className="text-[16px] font-semibold text-brand-navy leading-none">Disputes & Exceptions</h1>
              <p className="text-[11.5px] text-text-secondary">
                Bot captures, humans resolve. Drag between columns to progress a dispute.
              </p>
            </div>
          </div>
          <div className="text-[11px] text-text-muted">
            Showing {filtered.length} of {disputesData.length}
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <FiltersBar filters={filters} onPatch={patchFilters} onReset={() => setFilters(defaultFilters)} assignees={assignees} />

        <DisputeBoard
          disputes={filtered}
          counts={metrics.counts}
          subtotals={metrics.subtotals}
          onOpen={(d) => setOpenId(d.id)}
          onAssignMe={handleAssignMe}
          onDropStatus={handleDrop}
        />

        {openDispute && (
          <DisputeSheet
            dispute={openDispute}
            onClose={() => setOpenId(null)}
            onMutate={invalidate}
            assignees={assignees}
          />
        )}
      </div>
    </AppShell>
  );
}
