import { useEffect, useMemo, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { SplitPanes } from "@/components/shared/SplitPanes";
import { useMinWidth } from "@/hooks/use-min-width";
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
import type { Customer } from "@/api/types/customer360";
import type { DisputeType } from "@/api/types/disputes";
import {
  fetchCustomer,
  fetchCustomerInsights,
  useCreateDocumentRequest,
  useLogInteraction,
  useAddCustomerNote,
} from "@/api/customers";
import { QueryState } from "@/components/ui/query-state";
import type { NbaActionKind } from "@/api/types/customer-insights";
import { cn } from "@/lib/utils";
import { useCreatePromise } from "@/api/promises";
import { ApiError } from "@/api/config";
import { useCreateDispute } from "@/api/disputes";
import type { PromiseChannel } from "@/api/types/promises";

const TABS = [
  "overview",
  "ledger",
  "emi",
  "interactions",
  "promises",
  "disputes",
  "documents",
  "notes",
] as const;
type Tab = (typeof TABS)[number];

export const Route = createLazyFileRoute("/_app/customers/$customerId")({
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

function CustomerDetail() {
  const { customer: initial } = Route.useLoaderData();
  const { tab } = Route.useSearch();
  const navigate = useNavigate({ from: "/customers/$customerId" });
  const isLg = useMinWidth(1024);

  // The record lives in the query cache under ["customer", id], so the
  // invalidations other panels already issue (goodwill posted, note added)
  // reach this screen. A detached useState copy made those no-ops: the
  // Overview re-asked the server and the header kept the loader's snapshot.
  const customerQuery = useQuery({
    queryKey: ["customer", initial.id],
    queryFn: async () => (await fetchCustomer(initial.id)) ?? initial,
    initialData: initial,
    staleTime: 30_000,
  });
  const customer: Customer = customerQuery.data ?? initial;
  const [sheet, setSheet] = useState<"ptp" | "dispute" | "statement" | "call" | null>(null);
  const [railOpen, setRailOpen] = useState(false);

  const setTab = (t: Tab) => navigate({ search: { tab: t }, replace: true });

  const insightsQuery = useQuery({
    queryKey: ["customer-insights", customer.id],
    queryFn: () => fetchCustomerInsights(customer.id, customer),
    staleTime: 30_000,
  });

  // Pending is pending; the browser does not derive a placeholder recommendation.
  const insights = insightsQuery.data;

  // The writes live in api/; each invalidates the 360's reads itself. What is
  // left here is what the screen does afterwards: move to the tab that shows
  // the new row, or turn a refusal into the next step.
  const ptpMutation = useCreatePromise();
  const disputeMutation = useCreateDispute();
  const documentMutation = useCreateDocumentRequest(customer);
  const callMutation = useLogInteraction(customer);
  const noteMutation = useAddCustomerNote(customer.id);

  const onNbaAction = (action: NbaActionKind) => {
    if (action === "ptp") setSheet("ptp");
    else if (action === "dispute") setSheet("dispute");
    else if (action === "review") {
      setTab("disputes");
      setRailOpen(false);
    } else if (action === "statement") setSheet("statement");
    else if (action === "call") setSheet("call");
    else if (action === "offer") {
      const leadId =
        insights?.offerPolicy?.leadId ?? insights?.nba.find((i) => i.action === "offer")?.leadId;
      // `leadId ? {id} : {}` produced `{id: string} | {}`, and the route's
      // search type is `{id: string | undefined}` — an absent key and an
      // undefined one are different types even though they serialise the same.
      // `/upsell` already clears the param this way after it consumes it.
      // `?? undefined` because the lead id is nullable at source and the search
      // schema takes `string | undefined`: a null would serialise into the URL.
      void navigate({ to: "/upsell", search: { id: leadId ?? undefined } });
    } else toast.info("Opens Callback Manager — coming soon.");
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
    [insights?.offerPolicy?.leadId],
  );

  const addNote = (text: string) => {
    noteMutation.mutate(text, { onSuccess: () => toast.success("Note added") });
  };

  const submitSheet = (kind: "ptp" | "dispute" | "statement" | "call", payload: unknown) => {
    setSheet(null);
    if (kind === "ptp") {
      const p = payload as { amount: number; date: string; channel: string; notes: string };
      ptpMutation.mutate(
        {
          customerId: customer.id,
          accountId: customer.accountId,
          amount: p.amount,
          promisedDate: new Date(p.date).toISOString(),
          channel: p.channel as PromiseChannel,
          reminder: "queued",
          notes: p.notes,
        },
        {
          onSuccess: () => setTab("promises"),
          onError: (error) => {
            // One open promise per account: the refusal names it, and the
            // board's detail sheet is where it is revised with a reason.
            const detail = error instanceof ApiError ? error.detail : "";
            if (detail.startsWith("promise_already_open:")) {
              const openId = detail.split(":", 2)[1] ?? "";
              toast.error(`This account already has an open promise (${openId}).`, {
                description:
                  "Revise its date or amount with the customer's reason instead of adding a second one.",
                action: {
                  label: "Revise it",
                  onClick: () => void navigate({ to: "/promises", search: { id: openId } }),
                },
              });
              return;
            }
            toast.error(error instanceof Error ? error.message : "Failed to capture PTP");
          },
        },
      );
      return;
    }
    if (kind === "dispute") {
      const p = payload as { type: DisputeType; amount: number; notes: string };
      disputeMutation.mutate(
        { customerId: customer.id, accountId: customer.accountId, ...p },
        { onSuccess: () => setTab("disputes") },
      );
      return;
    }
    if (kind === "statement") {
      const p = payload as { docType: string; delivery: "email" | "whatsapp" };
      documentMutation.mutate(p, {
        onSuccess: () => {
          toast.success(`${p.docType} queued for ${p.delivery}`);
          setTab("documents");
        },
      });
      return;
    }
    callMutation.mutate(payload as { disposition: string; notes: string }, {
      onSuccess: () => {
        toast.success("Call logged");
        setTab("interactions");
      },
    });
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
          {tab === "overview" && (
            <QueryState query={insightsQuery} label="insights">
              {insights && <OverviewTab insights={insights} onNbaAction={onNbaAction} />}
            </QueryState>
          )}
          {tab === "ledger" && <LedgerTab customer={customer} />}
          {tab === "emi" && <EmiTab customer={customer} />}
          {tab === "interactions" && <InteractionsTab customer={customer} />}
          {tab === "promises" && (
            <PromisesTab customer={customer} onCreate={handlers.onCreatePtp} />
          )}
          {tab === "disputes" && (
            <DisputesTab customer={customer} onCreate={handlers.onRaiseDispute} />
          )}
          {tab === "documents" && (
            <DocumentsTab customer={customer} onCreate={handlers.onSendStatement} />
          )}
          {tab === "notes" && <NotesTab notes={customer.notes} onAdd={addNote} />}
        </div>
      </div>
    </div>
  );

  const rail = (
    <QuickActionsRail
      customer={customer}
      handlers={handlers}
      nba={insights?.nba ?? []}
      className="h-full w-full border-l-0"
    />
  );

  return (
    <>
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

      <ActionSheets
        kind={sheet}
        onOpenChange={(open) => !open && setSheet(null)}
        onSubmit={submitSheet}
      />
    </>
  );
}
