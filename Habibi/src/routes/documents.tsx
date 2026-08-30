import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileText, Plus } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { MetricsStrip } from "@/components/documents/MetricsStrip";
import { PipelineStrip } from "@/components/documents/PipelineStrip";
import { FiltersBar } from "@/components/documents/FiltersBar";
import { BulkActionBar } from "@/components/documents/BulkActionBar";
import { RequestsTable } from "@/components/documents/RequestsTable";
import { RequestSheet } from "@/components/documents/RequestSheet";
import { NewRequestSheet } from "@/components/documents/NewRequestSheet";
import {
  computeMetrics,
  defaultFilters,
  filterDocs,
  type DocChannel,
  type DocRequest,
  type DocStatus,
  type Filters,
} from "@/data/documents-seed";
import {
  markFailed,
  markGenerating,
  markSent,
  reassignChannel,
  retryDocument,
  useDocuments,
} from "@/api/documents";
import { humanNames, useStaff } from "@/api/staff";
import { useCustomers } from "@/api/customers";
import { USE_MOCK } from "@/api/config";
import { parseDeepLinkSearch } from "@/lib/workspace-nav";

export const Route = createFileRoute("/documents")({
  validateSearch: parseDeepLinkSearch,
  head: () => ({
    meta: [
      { title: "Document Fulfillment Desk — BigBound AI" },
      {
        name: "description",
        content:
          "Back-office queue for statement, no-dues, foreclosure and other document requests captured by the bot — with templates, channel routing, and delivery audit.",
      },
      { property: "og:title", content: "Document Fulfillment Desk" },
      {
        property: "og:description",
        content:
          "Process bot-captured document requests: generate, deliver via WhatsApp/Email/SMS, and audit fulfillment.",
      },
    ],
  }),
  component: DocumentsPage,
});

function DocumentsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate({ from: Route.fullPath });
  const search = Route.useSearch();
  const { data: items = [] } = useDocuments();
  const { data: staff = [] } = useStaff();
  const { data: liveCustomers = [] } = useCustomers();
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showNew, setShowNew] = useState(false);
  const deepLinkApplied = useRef(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const assignees = useMemo(() => {
    if (!USE_MOCK) return humanNames(staff);
    return Array.from(new Set(items.map((d) => d.assignee))).sort();
  }, [items, staff]);

  const customerOptions = useMemo(
    () =>
      liveCustomers.map((c) => ({
        id: c.id,
        name: c.name,
        accountId: c.accountId,
      })),
    [liveCustomers],
  );

  const filtered = useMemo(() => filterDocs(items, filters), [filters, items]);
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const openDoc = useMemo(() => items.find((d) => d.id === openId) ?? null, [items, openId]);

  const patchFilters = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }));

  const toggleStatus = (s: DocStatus) => {
    const cur = filters.statuses;
    patchFilters({ statuses: cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s] });
  };

  const toggleRow = (id: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };
  const toggleAll = (ids: string[]) => {
    setSelected((prev) => {
      const allOn = ids.every((i) => prev.has(i));
      const n = new Set(prev);
      if (allOn) ids.forEach((i) => n.delete(i));
      else ids.forEach((i) => n.add(i));
      return n;
    });
  };

  const channelMutation = useMutation({
    mutationFn: (v: { doc: DocRequest; channel: DocChannel }) => reassignChannel(v.doc, v.channel),
    onSuccess: () => invalidate(),
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Channel update failed"),
  });

  const retryMutation = useMutation({
    mutationFn: (doc: DocRequest) => retryDocument(doc),
    onSuccess: () => {
      invalidate();
      toast.success("Retry queued");
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : "Retry failed"),
  });

  // Generate → sent (or failed). Live: real PATCH sequence; mock: seed mutators.
  const runGenerate = async (d: DocRequest) => {
    try {
      await markGenerating(d);
      invalidate();
      // Simulated failure is demo theater — only in mock mode. In live mode this
      // would persist a real "failed" status to the DB via markFailed, so gate it off.
      const shouldFail =
        USE_MOCK && d.id.endsWith("7") && d.status !== "failed" && Math.random() < 0.15;
      await new Promise((r) => setTimeout(r, 1600));
      if (shouldFail) {
        await markFailed(d, "Delivery gateway rejected · retrying available");
        toast.error(`Failed · ${d.customerName}`);
      } else {
        await markSent(d);
        toast.success(`Sent · ${d.customerName}`);
      }
      invalidate();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Generate failed");
      invalidate();
    }
  };

  const bulkGenerate = () => {
    const targets = Array.from(selected)
      .map((id) => items.find((d) => d.id === id))
      .filter((d): d is DocRequest => !!d && (d.status === "requested" || d.status === "failed"));
    if (targets.length === 0) {
      toast("Nothing to generate in selection");
      return;
    }
    toast(`Generating ${targets.length} document${targets.length > 1 ? "s" : ""}…`);
    targets.forEach((d, i) => setTimeout(() => void runGenerate(d), i * 250));
    setSelected(new Set());
  };

  const bulkResend = () => {
    const targets = Array.from(selected)
      .map((id) => items.find((d) => d.id === id))
      .filter((d): d is DocRequest => !!d && d.status === "sent");
    if (targets.length === 0) {
      toast("No delivered documents in selection to resend");
      return;
    }
    targets.forEach((d, i) => setTimeout(() => void runGenerate(d), i * 250));
    toast(`Resending ${targets.length}…`);
    setSelected(new Set());
  };

  const bulkChannel = async (c: DocChannel) => {
    const targets = Array.from(selected)
      .map((id) => items.find((d) => d.id === id))
      .filter((d): d is DocRequest => !!d);
    try {
      await Promise.all(targets.map((doc) => channelMutation.mutateAsync({ doc, channel: c })));
      invalidate();
      toast.success(`Channel switched · ${targets.length} row${targets.length > 1 ? "s" : ""}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Bulk channel update failed");
    }
  };

  const handleRetry = (d: DocRequest) => {
    retryMutation.mutate(d);
  };

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
            <FileText className="h-250 w-250 text-text-brand" />
            <div>
              <h1 className="heading-small font-semibold text-text leading-none">
                Document fulfilment desk
              </h1>
              <p className="text-body-small text-text-subtle">
                Bot captures requests, humans fulfil. Generate, deliver, and audit every document.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-100">
            <div className="text-body-small text-text-subtlest">
              Showing {filtered.length} of {items.length}
            </div>
            <Button size="sm" className="h-400 text-body-small" onClick={() => setShowNew(true)}>
              <Plus className="mr-050 h-3.5 w-3.5" /> New request
            </Button>
          </div>
        </header>

        <MetricsStrip m={metrics} />
        <PipelineStrip counts={metrics.counts} active={filters.statuses} onToggle={toggleStatus} />
        <FiltersBar
          filters={filters}
          onPatch={patchFilters}
          onReset={() => setFilters(defaultFilters)}
          assignees={assignees}
        />

        {selected.size > 0 && (
          <BulkActionBar
            count={selected.size}
            onGenerate={bulkGenerate}
            onResend={bulkResend}
            onReassignChannel={(c) => void bulkChannel(c)}
            onClear={() => setSelected(new Set())}
          />
        )}

        <RequestsTable
          rows={filtered}
          selected={selected}
          onToggle={toggleRow}
          onToggleAll={toggleAll}
          onOpen={(d) => setOpenId(d.id)}
          onGenerate={(d) => void runGenerate(d)}
          onRetry={handleRetry}
        />

        {openDoc && (
          <RequestSheet
            d={openDoc}
            onClose={() => setOpenId(null)}
            onGenerate={(d) => void runGenerate(d)}
            onMutate={invalidate}
            assignees={assignees}
          />
        )}
        {showNew && (
          <NewRequestSheet
            onClose={() => setShowNew(false)}
            onCreated={invalidate}
            customers={customerOptions}
          />
        )}
      </div>
    </AppShell>
  );
}
