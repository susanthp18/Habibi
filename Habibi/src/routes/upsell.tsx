import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles, Plus } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/upsell/MetricsStrip";
import { OfferHealthPanel } from "@/components/upsell/OfferHealthPanel";
import { FiltersBar } from "@/components/upsell/FiltersBar";
import { ViewToggle, type UpsellView } from "@/components/upsell/ViewToggle";
import { LeadBoard } from "@/components/upsell/LeadBoard";
import { LeadTable } from "@/components/upsell/LeadTable";
import { LeadSheet } from "@/components/upsell/LeadSheet";
import { NewLeadSheet } from "@/components/upsell/NewLeadSheet";
import {
  STAGE_LABELS,
  defaultFilters,
  listOwners,
  moneyValue,
  type Filters,
  type LeadStage,
} from "@/data/upsell-seed";
import { patchLead, useLeadMetrics, useLeads, type LeadQuery } from "@/api/upsell";
import { USE_MOCK } from "@/api/config";
import { useMe } from "@/api/me";
import { useProducts } from "@/api/products";
import { humanNames, useStaff } from "@/api/staff";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

export const Route = createFileRoute("/upsell")({
  validateSearch: (search: Record<string, unknown>) => {
    const parsed = parseDeepLinkSearch(search);
    return { id: parsed.id };
  },
  head: () => ({
    meta: [
      { title: "Upsell & Leads Manager — BigBound AI" },
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
  const [openId, setOpenId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [view, setView] = useState<UpsellView>("board");
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const deepLinkApplied = useRef(false);

  const { data: me } = useMe();

  // Every filter is resolved server-side. They used to be applied in the
  // browser over one page of `GET /leads` — which pages at 200 — so past that
  // size the board and every KPI above it silently described the 200 most
  // recently captured leads while the header claimed to show everything.
  const query = useMemo<LeadQuery>(
    () => ({
      q: filters.search,
      team: filters.team === "all" ? undefined : filters.team,
      // "My leads" is an owner filter with the owner filled in for you.
      owner: filters.myQueue ? me?.name : filters.owner === "all" ? undefined : filters.owner,
      productId: filters.productId === "all" ? undefined : filters.productId,
      source: filters.source === "all" ? undefined : filters.source,
      priorities: filters.priorities.length ? filters.priorities : undefined,
      sentiments: filters.sentiments.length ? filters.sentiments : undefined,
    }),
    [filters, me?.name],
  );

  const { data: filtered = [] } = useLeads(query);
  const { data: metrics } = useLeadMetrics(query);
  const openLead = openId ? filtered.find((l) => l.id === openId) ?? null : null;
  // Filter rosters come from the DB in live mode. The hardcoded six names only
  // ever matched the seed, so filtering by owner silently matched nothing
  // against real data.
  const { data: staff = [] } = useStaff();
  const { data: catalog = [] } = useProducts();
  const owners = useMemo(
    () => (USE_MOCK ? listOwners() : [...humanNames(staff), "Unassigned"]),
    [staff],
  );

  const patchFilters = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }));
  const refreshLeads = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["leads"] }),
      queryClient.invalidateQueries({ queryKey: ["lead-metrics"] }),
    ]);
  };

  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!search.id) return;
    deepLinkApplied.current = true;
    // Filtering is server-side now, so a lead arriving by deep link — from
    // Handoff or Customer 360 — would not be in the response at all if a
    // filter excluded it. "Open this lead" outranks whatever was filtered.
    setFilters(defaultFilters);
    setOpenId(search.id);
    void navigate({ search: { id: undefined }, replace: true });
  }, [search.id, navigate]);

  const stageMutation = useMutation({
    mutationFn: ({ id, next }: { id: string; next: LeadStage }) => {
      const lead = filtered.find((x) => x.id === id);
      if (!lead) throw new Error("Lead not found");
      return patchLead(lead, {
        stage: next,
        wonAmount: next === "won" ? moneyValue(lead.estimatedValue) : undefined,
      });
    },
    onSuccess: async (_, { next }) => {
      await refreshLeads();
      if (next === "won") toast.success("Marked won");
      else toast.success(`Moved to ${STAGE_LABELS[next]}`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Lead update failed"),
  });

  const handleDropStage = (id: string, next: LeadStage) => {
    const l = filtered.find((x) => x.id === id);
    if (!l) return;
    if (l.stage === next) return;
    // Dropping onto Lost used to write the literal string "Marked lost from
    // board" as the loss reason — which then showed up in the loss-reason
    // breakdown as if it were analysis. A loss needs a real reason, so the
    // drawer opens and asks for one.
    if (next === "lost") {
      setOpenId(id);
      toast("Add a reason to mark this lost");
      return;
    }
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
      {/* overflow-y-auto, not hidden: the board is `flex-1` on a zero basis, so
          it carries no shrink weight and absorbs none of the overflow when the
          chrome above it grows. Adding the offer-engine panel pushed the total
          past the viewport and the board collapsed to its header strip. The
          min-height below is the floor; past it the page scrolls. */}
      <div className="flex h-full min-h-0 flex-col gap-150 overflow-y-auto p-150">
        <header className="shrink-0 flex items-center justify-between gap-100">
          <div className="flex items-center gap-100">
            <Sparkles className="h-250 w-250 text-text-brand" />
            <div>
              <h1 className="text-[1rem] font-semibold text-text leading-none">Upsell & leads manager</h1>
              <p className="text-body-small text-text-subtle">Eligibility-gated leads from voice & chat — pipeline, follow-ups, and conversion.</p>
            </div>
          </div>
          <div className="flex items-center gap-100">
            {/* Rows on screen against rows that match — the second number is
                a COUNT over the whole book, so a filtered view that exceeds
                the page size now says so instead of implying it is complete. */}
            <div className="text-body-small text-text-subtlest">
              Showing {filtered.length} of {metrics?.total ?? filtered.length}
            </div>
            <Button size="sm" className="h-400 text-body-small" onClick={() => setShowNew(true)}>
              <Plus className="mr-050 h-3.5 w-3.5" /> New lead
            </Button>
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <OfferHealthPanel />
        <FiltersBar
          filters={filters}
          onPatch={patchFilters}
          onReset={() => setFilters(defaultFilters)}
          owners={owners}
          products={catalog}
        />

        <div className="flex shrink-0 items-center gap-100">
          <ViewToggle view={view} onChange={setView} />
        </div>

        <div className="flex min-h-[24rem] flex-1 flex-col">
          {view === "board" ? (
            <LeadBoard leads={filtered} onOpen={(l) => setOpenId(l.id)} onDropStage={handleDropStage} />
          ) : (
            <LeadTable leads={tableRows} onOpen={(l) => setOpenId(l.id)} />
          )}
        </div>

        {openLead && <LeadSheet lead={openLead} onClose={() => setOpenId(null)} onMutate={refreshLeads} />}
        {showNew && <NewLeadSheet onClose={() => setShowNew(false)} onCreated={refreshLeads} />}
      </div>
    </AppShell>
  );
}
