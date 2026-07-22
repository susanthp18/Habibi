import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles, Plus } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/upsell/MetricsStrip";
import { FiltersBar } from "@/components/upsell/FiltersBar";
import { ViewToggle, type UpsellView } from "@/components/upsell/ViewToggle";
import { LeadBoard } from "@/components/upsell/LeadBoard";
import { LeadTable } from "@/components/upsell/LeadTable";
import { LeadSheet } from "@/components/upsell/LeadSheet";
import { NewLeadSheet } from "@/components/upsell/NewLeadSheet";
import {
  STAGE_LABELS,
  computeMetrics,
  defaultFilters,
  filterLeads,
  listOwners,
  type Filters,
  type LeadStage,
} from "@/data/upsell-seed";
import { patchLead, useLeads } from "@/api/upsell";

export const Route = createFileRoute("/upsell")({
  head: () => ({
    meta: [
      { title: "Upsell & Leads Manager — Collections Agent" },
      {
        name: "description",
        content: "Pipeline for eligibility-gated upsells captured by the bot — Interested → Contacted → Qualified → Won/Lost with follow-ups and conversion tracking.",
      },
      { property: "og:title", content: "Upsell & Leads Manager" },
      {
        property: "og:description",
        content: "Manage top-up loan, consolidation, and card-upgrade leads captured mid-call — assign, schedule follow-ups, and close.",
      },
    ],
  }),
  component: UpsellPage,
});

function UpsellPage() {
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [tick, setTick] = useState(0);
  const bump = () => setTick((t) => t + 1);
  const [openId, setOpenId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [view, setView] = useState<UpsellView>("board");
  const queryClient = useQueryClient();

  const { data: seed = [] } = useLeads();

  const filtered = useMemo(() => filterLeads(seed, filters), [seed, filters, tick]);
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const openLead = openId ? seed.find((l) => l.id === openId) ?? null : null;
  const owners = useMemo(() => listOwners(), []);

  const patchFilters = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }));
  const refreshLeads = async () => {
    bump();
    await queryClient.invalidateQueries({ queryKey: ["leads"] });
  };

  const stageMutation = useMutation({
    mutationFn: ({ id, next }: { id: string; next: LeadStage }) => {
      const lead = seed.find((x) => x.id === id);
      if (!lead) throw new Error("Lead not found");
      return patchLead(lead, {
        stage: next,
        wonAmount: next === "won" ? lead.estimatedValue : undefined,
        lossReason: next === "lost" ? "Marked lost from board" : undefined,
      });
    },
    onSuccess: async (_, { next }) => {
      await refreshLeads();
      if (next === "won") toast.success("Marked won");
      else if (next === "lost") toast("Marked lost");
      else toast.success(`Moved to ${STAGE_LABELS[next]}`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Lead update failed"),
  });

  const handleDropStage = (id: string, next: LeadStage) => {
    const l = seed.find((x) => x.id === id);
    if (!l) return;
    if (l.stage === next) return;
    stageMutation.mutate({ id, next });
  };

  const tableRows = useMemo(
    () =>
      [...filtered].sort((a, b) => {
        const pri = { high: 0, normal: 1, low: 2 } as const;
        if (pri[a.priority] !== pri[b.priority]) return pri[a.priority] - pri[b.priority];
        return new Date(b.capturedAt).getTime() - new Date(a.capturedAt).getTime();
      }),
    [filtered],
  );

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col gap-2.5 p-3">
        <header className="shrink-0 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-brand-primary" />
            <div>
              <h1 className="text-[16px] font-semibold text-brand-navy leading-none">Upsell & Leads Manager</h1>
              <p className="text-[11.5px] text-text-secondary">Eligibility-gated leads from voice & chat — pipeline, follow-ups, and conversion.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="text-[11px] text-text-muted">Showing {filtered.length} of {seed.length}</div>
            <Button size="sm" className="h-8 text-[12px]" onClick={() => setShowNew(true)}>
              <Plus className="mr-1 h-3.5 w-3.5" /> New lead
            </Button>
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <FiltersBar filters={filters} onPatch={patchFilters} onReset={() => setFilters(defaultFilters)} owners={owners} />

        <div className="flex shrink-0 items-center gap-2">
          <ViewToggle view={view} onChange={setView} />
        </div>

        {view === "board" ? (
          <LeadBoard leads={filtered} onOpen={(l) => setOpenId(l.id)} onDropStage={handleDropStage} />
        ) : (
          <LeadTable leads={tableRows} onOpen={(l) => setOpenId(l.id)} />
        )}

        {openLead && <LeadSheet lead={openLead} onClose={() => setOpenId(null)} onMutate={refreshLeads} />}
        {showNew && <NewLeadSheet onClose={() => setShowNew(false)} onCreated={refreshLeads} />}
      </div>
    </AppShell>
  );
}
