import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertOctagon, Plus } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/disputes/MetricsStrip";
import { FiltersBar } from "@/components/disputes/FiltersBar";
import { DisputeBoard } from "@/components/disputes/DisputeBoard";
import { DisputeSheet } from "@/components/disputes/DisputeSheet";
import { NewDisputeSheet } from "@/components/disputes/NewDisputeSheet";
import {
  CURRENT_AGENT,
  computeMetrics,
  defaultFilters,
  filterDisputes,
  STATUS_LABELS,
  type Dispute,
  type Filters,
} from "@/data/disputes-seed";
import { assignDispute, moveDispute, useDisputes } from "@/api/disputes";
import { humanNames, useStaff } from "@/api/staff";
import { useMe } from "@/api/me";
import { useCustomers } from "@/api/customers";
import { USE_MOCK } from "@/api/config";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

export const Route = createFileRoute("/disputes")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Disputes & Exceptions Queue — BigBound AI" },
      {
        name: "description",
        content:
          "Triage disputes captured by the bot — paid-already, wrong amount, fee waivers, fraud — with SLA-aware Kanban, evidence, and CRM writeback.",
      },
      { property: "og:title", content: "Disputes & Exceptions Queue" },
      {
        property: "og:description",
        content:
          "Kanban of bot-captured disputes with SLA timers, assignment, evidence, and resolution.",
      },
    ],
  }),
  component: DisputesPage,
});

function DisputesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const { data: disputesData = [] } = useDisputes();
  const { data: liveCustomers = [] } = useCustomers();
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const deepLinkApplied = useRef(false);

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
  const openDispute = openId ? (disputesData.find((d) => d.id === openId) ?? null) : null;

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

  const customerOptions = useMemo(
    () =>
      liveCustomers.map((c) => ({
        id: c.id,
        name: c.name,
        accountId: c.accountId,
      })),
    [liveCustomers],
  );

  // Workspace / ⌘K deep-link: open sheet or new-dispute form once, then clear search.
  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!search.id && !search.new) return;
    deepLinkApplied.current = true;
    if (search.id) setOpenId(search.id);
    if (search.new) setShowNew(true);
    void navigate({ search: {}, replace: true });
  }, [search.id, search.new, navigate]);

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col gap-150 p-150">
        <header className="shrink-0 flex items-center justify-between">
          <div className="flex items-center gap-100">
            <AlertOctagon className="h-250 w-250 text-text-brand" />
            <div>
              <h1 className="heading-small font-semibold text-text leading-none">
                Disputes & exceptions
              </h1>
              <p className="text-body-small text-text-subtle">
                Bot captures, humans resolve. Drag between columns to progress a dispute.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-100">
            <div className="text-body-small text-text-subtlest">
              Showing {filtered.length} of {disputesData.length}
            </div>
            <Button size="sm" className="h-400 text-body-small" onClick={() => setShowNew(true)}>
              <Plus className="mr-050 h-3.5 w-3.5" /> Raise dispute
            </Button>
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <FiltersBar
          filters={filters}
          onPatch={patchFilters}
          onReset={() => setFilters(defaultFilters)}
          assignees={assignees}
        />

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
        {showNew && (
          <NewDisputeSheet
            onClose={() => setShowNew(false)}
            onCreated={invalidate}
            customers={customerOptions}
          />
        )}
      </div>
    </AppShell>
  );
}
