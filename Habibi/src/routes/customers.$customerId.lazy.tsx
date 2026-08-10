import { useEffect, useMemo, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { SplitPanes } from "@/components/inbox/SplitPanes";
import { CustomerHeader } from "@/components/customer360/CustomerHeader";
import { QuickActionsRail } from "@/components/customer360/QuickActionsRail";
import { OverviewTab } from "@/components/customer360/OverviewTab";
import { LedgerTab } from "@/components/customer360/LedgerTab";
import { EmiTab } from "@/components/customer360/EmiTab";
import { InteractionsTab } from "@/components/customer360/InteractionsTab";
import { PromisesTab } from "@/components/customer360/PromisesTab";
import { DisputesTab } from "@/components/customer360/DisputesTab";
import { DocumentsTab } from "@/components/customer360/DocumentsTab";
import { NotesTab } from "@/components/customer360/NotesTab";
import { ActionSheets } from "@/components/customer360/ActionSheets";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { type Customer } from "@/data/customer360-seed";
import type { DisputeType } from "@/data/disputes-seed";
import {
  addCustomerNote,
  createDispute,
  createDocumentRequest,
  createPromise,
  fetchCustomer,
  fetchCustomerInsights,
  logInteraction,
} from "@/api/customers";
import { deriveCustomerInsights, type NbaActionKind } from "@/lib/customerInsights";
import { cn } from "@/lib/utils";

const TABS = ["overview", "ledger", "emi", "interactions", "promises", "disputes", "documents", "notes"] as const;
type Tab = (typeof TABS)[number];

export const Route = createLazyFileRoute("/customers/$customerId")({
  component: CustomerDetail,
});

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  ledger: "Ledger",
  emi: "EMI schedule",
  interactions: "Interactions",
  promises: "Promises",
  disputes: "Disputes",
  documents: "Documents",
  notes: "Notes",
};

function tabCount(customer: Customer, tab: Tab): number | undefined {
  switch (tab) {
    case "interactions":
      return customer.interactions.length;
    case "promises":
      return customer.promises.length;
    case "disputes":
      return customer.disputes.length;
    case "documents":
      return customer.documents.length;
    case "notes":
      return customer.notes.length;
    default:
      return undefined;
  }
}

function useIsLg() {
  const [lg, setLg] = useState(() => (typeof window !== "undefined" ? window.matchMedia("(min-width: 1024px)").matches : true));
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const onChange = () => setLg(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return lg;
}

function CustomerDetail() {
  const { customer: initial } = Route.useLoaderData();
  const { tab } = Route.useSearch();
  const navigate = useNavigate({ from: "/customers/$customerId" });
  const queryClient = useQueryClient();
  const isLg = useIsLg();

  const [customer, setCustomer] = useState<Customer>(initial);
  const [sheet, setSheet] = useState<"ptp" | "dispute" | "statement" | "call" | null>(null);
  const [railOpen, setRailOpen] = useState(false);

  useEffect(() => {
    setCustomer(initial);
  }, [initial]);

  const setTab = (t: Tab) => navigate({ search: { tab: t }, replace: true });

  const insightsQuery = useQuery({
    queryKey: ["customer-insights", customer.id],
    queryFn: () => fetchCustomerInsights(customer.id, customer),
    staleTime: 30_000,
  });

  const insights = insightsQuery.data ?? deriveCustomerInsights(customer);

  const refreshCustomer = async () => {
    await queryClient.invalidateQueries({ queryKey: ["customers"] });
    await queryClient.invalidateQueries({ queryKey: ["customer-insights", customer.id] });
    const fresh = await fetchCustomer(customer.id);
    if (fresh) setCustomer(fresh);
  };

  const ptpMutation = useMutation({
    mutationFn: (payload: { amount: number; date: string; channel: string; notes: string }) => createPromise(customer, payload),
    onSuccess: async () => {
      await refreshCustomer();
      toast.success("PTP captured");
      setTab("promises");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Failed to capture PTP"),
  });

  const disputeMutation = useMutation({
    mutationFn: (payload: { type: DisputeType; amount: number; notes: string }) => createDispute(customer, payload),
    onSuccess: async () => {
      await refreshCustomer();
      toast.success("Dispute filed");
      setTab("disputes");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Failed to file dispute"),
  });

  const documentMutation = useMutation({
    mutationFn: (payload: { docType: string; delivery: "email" | "whatsapp" }) => createDocumentRequest(customer, payload),
    onSuccess: async (_, payload) => {
      await refreshCustomer();
      toast.success(`${payload.docType} queued for ${payload.delivery}`);
      setTab("documents");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Failed to request document"),
  });

  const callMutation = useMutation({
    mutationFn: (payload: { disposition: string; notes: string }) => logInteraction(customer, payload),
    onSuccess: async () => {
      await refreshCustomer();
      toast.success("Call logged");
      setTab("interactions");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Failed to log call"),
  });

  const noteMutation = useMutation({
    mutationFn: (text: string) => addCustomerNote(customer.id, text),
    onSuccess: async (note) => {
      if (note) {
        setCustomer((c) => ({ ...c, notes: [note, ...c.notes] }));
      } else {
        await refreshCustomer();
      }
      toast.success("Note added");
      await queryClient.invalidateQueries({ queryKey: ["customer-insights", customer.id] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Failed to save note"),
  });

  const onNbaAction = (action: NbaActionKind) => {
    if (action === "ptp") setSheet("ptp");
    else if (action === "dispute") setSheet("dispute");
    else if (action === "review") {
      setTab("disputes");
      setRailOpen(false);
    } else if (action === "statement") setSheet("statement");
    else if (action === "call") setSheet("call");
    else toast.info("Opens Callback Manager — coming soon.");
  };

  const handlers = useMemo(
    () => ({
      onCreatePtp: () => setSheet("ptp"),
      onRaiseDispute: () => setSheet("dispute"),
      onSendStatement: () => setSheet("statement"),
      onLogCall: () => setSheet("call"),
      onNbaAction,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const addNote = (text: string) => {
    noteMutation.mutate(text);
  };

  const submitSheet = (kind: "ptp" | "dispute" | "statement" | "call", payload: unknown) => {
    setSheet(null);
    if (kind === "ptp") {
      ptpMutation.mutate(payload as { amount: number; date: string; channel: string; notes: string });
      return;
    }
    if (kind === "dispute") {
      disputeMutation.mutate(payload as { type: DisputeType; amount: number; notes: string });
      return;
    }
    if (kind === "statement") {
      documentMutation.mutate(payload as { docType: string; delivery: "email" | "whatsapp" });
      return;
    }
    callMutation.mutate(payload as { disposition: string; notes: string });
  };

  const mainPane = (
    <div className="flex h-full min-h-0 flex-col">
      <CustomerHeader customer={customer} onOpenRail={() => setRailOpen(true)} />

      <div className="flex items-center gap-0 overflow-x-auto border-b border-border bg-surface px-200">
        {TABS.map((t) => {
          const count = tabCount(customer, t);
          return (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "shrink-0 border-b-2 px-150 py-150 text-sm font-medium",
                tab === t
                  ? "border-border-brand text-text-brand"
                  : "border-transparent text-text-subtle hover:text-text",
              )}
            >
              {TAB_LABELS[t]}
              {count !== undefined && (
                <span className="ml-075 rounded-medium bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="p-200 sm:p-300">
          {tab === "overview" && <OverviewTab insights={insights} onNbaAction={onNbaAction} />}
          {tab === "ledger" && <LedgerTab customer={customer} />}
          {tab === "emi" && <EmiTab customer={customer} />}
          {tab === "interactions" && <InteractionsTab customer={customer} />}
          {tab === "promises" && <PromisesTab customer={customer} onCreate={handlers.onCreatePtp} />}
          {tab === "disputes" && <DisputesTab customer={customer} onCreate={handlers.onRaiseDispute} />}
          {tab === "documents" && <DocumentsTab customer={customer} onCreate={handlers.onSendStatement} />}
          {tab === "notes" && <NotesTab notes={customer.notes} onAdd={addNote} />}
        </div>
      </div>
    </div>
  );

  const rail = <QuickActionsRail customer={customer} handlers={handlers} nba={insights.nba} className="h-full w-full border-l-0" />;

  return (
    <AppShell>
      <div className="h-full min-h-0">
        {isLg ? (
          <SplitPanes storageKey="c360-split" defaultWidths={[72, 28]} minWidthsPx={[480, 280]}>
            {mainPane}
            {rail}
          </SplitPanes>
        ) : (
          mainPane
        )}
      </div>

      <Sheet open={railOpen} onOpenChange={setRailOpen}>
        <SheetContent side="right" className="w-full max-w-sm p-0 sm:max-w-sm">
          <SheetHeader className="sr-only">
            <SheetTitle>Customer context</SheetTitle>
          </SheetHeader>
          {rail}
        </SheetContent>
      </Sheet>

      <ActionSheets kind={sheet} onOpenChange={(open) => !open && setSheet(null)} onSubmit={submitSheet} />
    </AppShell>
  );
}
