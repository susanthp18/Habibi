import { useMemo, useState } from "react";
import { createLazyFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { CustomerHeader } from "@/components/customer360/CustomerHeader";
import { QuickActionsRail } from "@/components/customer360/QuickActionsRail";
import { LedgerTab } from "@/components/customer360/LedgerTab";
import { EmiTab } from "@/components/customer360/EmiTab";
import { InteractionsTab } from "@/components/customer360/InteractionsTab";
import { PromisesTab } from "@/components/customer360/PromisesTab";
import { DisputesTab } from "@/components/customer360/DisputesTab";
import { DocumentsTab } from "@/components/customer360/DocumentsTab";
import { NotesTab } from "@/components/customer360/NotesTab";
import { ActionSheets } from "@/components/customer360/ActionSheets";
import { type Customer, type CustomerNote, type Promise as PtpPromise, type Dispute, type DocumentRequest, type Interaction } from "@/data/customer360-seed";
import type { DisputeType } from "@/data/disputes-seed";
import { createDispute, createDocumentRequest, createPromise, fetchCustomer, logInteraction } from "@/api/customers";
import { cn } from "@/lib/utils";

const TABS = ["ledger", "emi", "interactions", "promises", "disputes", "documents", "notes"] as const;
type Tab = (typeof TABS)[number];

export const Route = createLazyFileRoute("/customers/$customerId")({
  component: CustomerDetail,
});

const TAB_LABELS: Record<Tab, string> = {
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
    case "interactions": return customer.interactions.length;
    case "promises": return customer.promises.length;
    case "disputes": return customer.disputes.length;
    case "documents": return customer.documents.length;
    case "notes": return customer.notes.length;
    default: return undefined;
  }
}

function CustomerDetail() {
  const { customer: initial } = Route.useLoaderData();
  const { tab } = Route.useSearch();
  const navigate = useNavigate({ from: "/customers/$customerId" });
  const queryClient = useQueryClient();

  const [customer, setCustomer] = useState<Customer>(initial);
  const [sheet, setSheet] = useState<"ptp" | "dispute" | "statement" | "call" | null>(null);

  const setTab = (t: Tab) => navigate({ search: { tab: t }, replace: true });

  const refreshCustomer = async () => {
    await queryClient.invalidateQueries({ queryKey: ["customers"] });
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

  const handlers = useMemo(
    () => ({
      onCreatePtp: () => setSheet("ptp"),
      onRaiseDispute: () => setSheet("dispute"),
      onSendStatement: () => setSheet("statement"),
      onLogCall: () => setSheet("call"),
    }),
    [],
  );

  const addNote = (text: string) => {
    const note: CustomerNote = { id: `n-${Date.now()}`, author: "You", at: new Date().toISOString(), text };
    setCustomer((c) => ({ ...c, notes: [note, ...c.notes] }));
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
    if (kind === "call") {
      callMutation.mutate(payload as { disposition: string; notes: string });
      return;
    }
    if (kind === "ptp") {
      const p = payload as { amount: number; date: string; channel: string; notes: string };
      const ptp: PtpPromise = {
        id: `p-${Date.now()}`,
        amount: p.amount,
        promisedDate: new Date(p.date).toISOString(),
        createdAt: new Date().toISOString(),
        channel: p.channel as PtpPromise["channel"],
        handler: "You",
        status: "upcoming",
        reminderStatus: "queued",
      };
      setCustomer((c) => ({ ...c, promises: [ptp, ...c.promises] }));
      toast.success(`PTP for ₹${p.amount.toLocaleString("en-IN")} captured`);
      setTab("promises");
    }
    if (kind === "dispute") {
      const d = payload as { type: string; amount: number; notes: string };
      const disp: Dispute = {
        id: `D-${Math.floor(1000 + Math.random() * 9000)}`,
        type: d.type,
        amount: d.amount,
        transcriptSnippet: d.notes ? `"${d.notes}"` : "(no snippet)",
        status: "new",
        slaLabel: "24h left",
        filedAt: new Date().toISOString(),
        assignee: "You",
      };
      setCustomer((c) => ({ ...c, disputes: [disp, ...c.disputes] }));
      toast.success("Dispute filed");
      setTab("disputes");
    }
    if (kind === "statement") {
      const s = payload as { docType: string; delivery: "email" | "whatsapp" };
      const doc: DocumentRequest = {
        id: `doc-${Date.now()}`,
        type: s.docType,
        requestedVia: "voice",
        requestedAt: new Date().toISOString(),
        deliveryChannel: s.delivery,
        status: "generating",
      };
      setCustomer((c) => ({ ...c, documents: [doc, ...c.documents] }));
      toast.success(`${s.docType} queued for ${s.delivery}`);
      setTab("documents");
    }
    if (kind === "call") {
      const p = payload as { disposition: string; notes: string };
      const interaction: Interaction = {
        id: `i-${Date.now()}`,
        channel: "voice",
        handler: { kind: "human", name: "You" },
        startedAt: new Date().toISOString(),
        duration: "3m 20s",
        disposition: p.disposition,
        sentiment: "neutral",
        sentimentDelta: "flat",
        summary: p.notes || "Logged call — no notes.",
        intents: { queryResolved: p.disposition === "Query resolved", ptpCaptured: p.disposition === "PTP captured" },
      };
      setCustomer((c) => ({ ...c, interactions: [interaction, ...c.interactions] }));
      toast.success("Call logged");
      setTab("interactions");
    }
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0">
        <div className="flex min-w-0 flex-1 flex-col">
          <CustomerHeader customer={customer} />

          {/* Tabs */}
          <div className="flex items-center gap-0 overflow-x-auto border-b border-border bg-surface-card px-4">
            {TABS.map((t) => {
              const count = tabCount(customer, t);
              return (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium",
                    tab === t ? "border-brand-primary text-brand-primary" : "border-transparent text-text-secondary hover:text-brand-navy",
                  )}
                >
                  {TAB_LABELS[t]}
                  {count !== undefined && (
                    <span className="ml-1.5 rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] text-text-secondary">{count}</span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="p-6">
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

        <QuickActionsRail customer={customer} handlers={handlers} />
      </div>

      <ActionSheets kind={sheet} onOpenChange={(open) => !open && setSheet(null)} onSubmit={submitSheet} />
    </AppShell>
  );
}
